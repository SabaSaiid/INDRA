"""Deterministic, project-authored duplicate-pair development data."""

from app.ml.data.synthetic_duplicates.generator import (
    DEFAULT_CREATION_TIMESTAMP,
    DEFAULT_DATASET_ID,
    DEFAULT_DATASET_VERSION,
    DEFAULT_SEED,
    DEFAULT_TOTAL_PAIRS,
    DUPLICATE_SCENARIOS,
    GENERATOR_VERSION,
    HARD_NEGATIVE_SCENARIOS,
    SyntheticDuplicateArtifacts,
    SyntheticDuplicateGeneratorConfig,
    generate_pair_records,
    register_synthetic_duplicate_dataset,
    write_synthetic_duplicate_dataset,
)

__all__ = [
    "DEFAULT_CREATION_TIMESTAMP",
    "DEFAULT_DATASET_ID",
    "DEFAULT_DATASET_VERSION",
    "DEFAULT_SEED",
    "DEFAULT_TOTAL_PAIRS",
    "DUPLICATE_SCENARIOS",
    "GENERATOR_VERSION",
    "HARD_NEGATIVE_SCENARIOS",
    "SyntheticDuplicateArtifacts",
    "SyntheticDuplicateGeneratorConfig",
    "generate_pair_records",
    "register_synthetic_duplicate_dataset",
    "write_synthetic_duplicate_dataset",
]
