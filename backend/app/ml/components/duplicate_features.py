"""Frozen, JSON-serializable TF-IDF feature state for duplicate matching."""

from __future__ import annotations

import hashlib
import math
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.config import DuplicateMatchingConfig, authorize_manifest_artifact


AnalyzerName = Literal["char", "word"]


class FrozenTfidfSpace(BaseModel):
    """Vocabulary and IDF statistics required for inference-only transforms."""

    model_config = ConfigDict(extra="forbid")

    analyzer: AnalyzerName
    ngram_range: tuple[int, int]
    vocabulary: dict[str, int]
    idf: list[float]
    vectorizer_config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_fitted_state(self) -> "FrozenTfidfSpace":
        minimum, maximum = self.ngram_range
        if minimum <= 0 or maximum < minimum:
            raise ValueError("TF-IDF ngram_range must be positive and ascending")
        if not self.vocabulary:
            raise ValueError("TF-IDF vocabulary cannot be empty")
        expected_indexes = list(range(len(self.vocabulary)))
        if sorted(self.vocabulary.values()) != expected_indexes:
            raise ValueError("TF-IDF vocabulary indexes must be unique and contiguous")
        if len(self.idf) != len(self.vocabulary):
            raise ValueError("TF-IDF IDF length must match the vocabulary")
        if any(not math.isfinite(value) or value <= 0.0 for value in self.idf):
            raise ValueError("TF-IDF IDF values must be finite and positive")
        return self

    def transform(self, text: str) -> dict[int, float]:
        terms = _terms(text, self.analyzer, self.ngram_range)
        counts = Counter(term for term in terms if term in self.vocabulary)
        values: dict[int, float] = {}
        for term, count in counts.items():
            index = self.vocabulary[term]
            values[index] = (1.0 + math.log(float(count))) * self.idf[index]
        norm = math.sqrt(sum(value * value for value in values.values()))
        if norm == 0.0:
            return {}
        return {index: value / norm for index, value in values.items()}


class DuplicateFeatureState(BaseModel):
    """Versioned frozen feature state with development-corpus provenance."""

    model_config = ConfigDict(extra="forbid")

    state_version: str = Field(min_length=1)
    feature_version: str = Field(min_length=1)
    preprocessing_version: str = Field(min_length=1)
    corpus_identifier: str = Field(min_length=1)
    corpus_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    creation_timestamp: datetime
    library_version: str = Field(min_length=1)
    development_only: Literal[True] = True
    char_space: FrozenTfidfSpace
    word_space: FrozenTfidfSpace

    @model_validator(mode="after")
    def validate_spaces(self) -> "DuplicateFeatureState":
        if self.creation_timestamp.tzinfo is None:
            raise ValueError("feature-state creation_timestamp must include a timezone")
        if self.char_space.analyzer != "char":
            raise ValueError("char_space must use the character analyzer")
        if self.word_space.analyzer != "word":
            raise ValueError("word_space must use the word analyzer")
        return self


def normalize_text(text: str) -> str:
    """Normalize text without transliterating or discarding Unicode scripts."""

    if not text:
        return ""
    punctuation_translation = str.maketrans(
        {
            "–": "-",
            "—": "-",
            "−": "-",
            "“": '"',
            "”": '"',
            "‘": "'",
            "’": "'",
        }
    )
    normalized = unicodedata.normalize("NFKC", text).translate(punctuation_translation)
    normalized = "".join(
        " " if unicodedata.category(char).startswith("P") else char
        for char in normalized
    )
    normalized = re.sub(r"([A-Za-z0-9])\1{2,}", r"\1\1", normalized)
    return re.sub(r"\s+", " ", normalized.casefold()).strip()


def _terms(text: str, analyzer: AnalyzerName, ngram_range: tuple[int, int]) -> list[str]:
    normalized = normalize_text(text)
    minimum, maximum = ngram_range
    if analyzer == "word":
        tokens = re.findall(r"(?u)\b\w+\b", normalized)
        terms: list[str] = []
        for size in range(minimum, maximum + 1):
            terms.extend(
                " ".join(tokens[index : index + size])
                for index in range(0, len(tokens) - size + 1)
            )
        return terms

    return [
        normalized[index : index + size]
        for size in range(minimum, maximum + 1)
        for index in range(0, max(0, len(normalized) - size + 1))
    ]


def _fit_space(
    texts: Sequence[str],
    *,
    analyzer: AnalyzerName,
    ngram_range: tuple[int, int],
) -> FrozenTfidfSpace:
    document_frequency: Counter[str] = Counter()
    document_count = 0
    for text in texts:
        document_frequency.update(set(_terms(text, analyzer, ngram_range)))
        document_count += 1
    vocabulary = {
        term: index for index, term in enumerate(sorted(document_frequency))
    }
    document_count = max(1, document_count)
    idf = [
        math.log((1.0 + document_count) / (1.0 + document_frequency[term])) + 1.0
        for term in sorted(vocabulary)
    ]
    return FrozenTfidfSpace(
        analyzer=analyzer,
        ngram_range=ngram_range,
        vocabulary=vocabulary,
        idf=idf,
        vectorizer_config={
            "sublinear_tf": True,
            "norm": "l2",
            "lowercase": False,
            "local_only": True,
        },
    )


def fit_feature_state(
    corpus: Sequence[str],
    *,
    corpus_identifier: str,
    corpus_sha256: str,
    config: DuplicateMatchingConfig,
    state_version: str = "duplicate-feature-state-v1",
    creation_timestamp: datetime | None = None,
    library_version: str | None = None,
) -> DuplicateFeatureState:
    """Fit feature statistics once from an explicitly supplied local corpus."""

    if not corpus:
        raise ValueError("feature corpus must contain at least one text")
    if len(corpus_sha256) != 64:
        raise ValueError("corpus_sha256 must be a SHA-256 hex digest")
    normalized = [normalize_text(text) for text in corpus]
    return DuplicateFeatureState(
        state_version=state_version,
        feature_version=config.feature_version,
        preprocessing_version=config.preprocessing_version,
        corpus_identifier=corpus_identifier,
        corpus_sha256=corpus_sha256.lower(),
        creation_timestamp=creation_timestamp or datetime.now(timezone.utc),
        library_version=library_version or f"python={sys.version_info.major}.{sys.version_info.minor}",
        development_only=True,
        char_space=_fit_space(
            normalized,
            analyzer="char",
            ngram_range=config.char_ngram_range,
        ),
        word_space=_fit_space(
            normalized,
            analyzer="word",
            ngram_range=config.word_ngram_range,
        ),
    )


def load_feature_state(path, *, manifest_path=None) -> DuplicateFeatureState:
    """Load a hash-authorized local JSON feature state from the shared manifest."""

    state_path, metadata = authorize_manifest_artifact(
        path,
        intended_component="duplicate_matcher",
        manifest_path=manifest_path,
        allowed_suffixes={".json"},
    )
    state = DuplicateFeatureState.model_validate_json(
        state_path.read_text(encoding="utf-8")
    )
    checks = {
        "state version": state.state_version == metadata.artifact_version,
        "corpus hash": state.corpus_sha256.casefold()
        == metadata.training_dataset_hash.casefold(),
        "feature version": state.feature_version == metadata.feature_version,
        "preprocessing version": state.preprocessing_version
        == metadata.preprocessing_version,
        "creation timestamp": state.creation_timestamp
        == metadata.training_timestamp,
        "deterministic no-RNG marker": metadata.random_seed == 0,
        "library versions": all(
            f"{name}={version}" in state.library_version
            for name, version in metadata.framework_versions.items()
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(
            "duplicate feature-state provenance mismatch: " + ", ".join(failed)
        )
    return state


def feature_state_sha256(state: DuplicateFeatureState) -> str:
    payload = state.model_dump_json().encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
