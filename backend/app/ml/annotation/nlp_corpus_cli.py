"""Local-only CLI for Phase 16 NLP corpus enrollment and queue creation.

No model, embedding, API, or network client is imported by this module.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from app.ml.config import local_only_path
from app.ml.data.nlp_annotations import NLPAdjudicationStore, NLPAnnotationStore
from app.ml.data.nlp_corpus import (
    NLPAnnotationQueueStatus,
    NLPAnnotationQueueStatusStore,
    NLPQueueSamplingStrategy,
    create_queue_status_event,
    enroll_local_nlp_corpus,
    load_enrolled_nlp_corpus,
    load_nlp_annotation_queue,
    raw_nlp_reports_to_annotation_sources,
    write_nlp_annotation_queue,
)
from app.ml.data.nlp_dataset import release_nlp_annotation_dataset
from app.ml.data.registry import DEFAULT_DATASET_REGISTRY_PATH, DatasetProvenance


def _aware_timestamp(value: str) -> datetime:
    candidate = value.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed


def _load_json_object(path: Path, description: str) -> dict[str, Any]:
    selected = local_only_path(path, description=description)
    payload = json.loads(selected.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(payload, dict):
        raise TypeError(f"{description} must contain a JSON object")
    return payload


def _load_report_ids(path: Path | None) -> list[str]:
    if path is None:
        return []
    selected = local_only_path(path, description="NLP review-priority paths")
    text = selected.read_text(encoding="utf-8", errors="strict")
    if selected.suffix.casefold() == ".json":
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = payload.get("report_ids")
        if not isinstance(payload, list) or not all(
            isinstance(item, str) and item.strip() for item in payload
        ):
            raise ValueError(
                "review-priority JSON must be a string list or contain report_ids"
            )
        return [item.strip() for item in payload]
    return [line.strip() for line in text.splitlines() if line.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local INDRA NLP corpus enrollment and annotation queue"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    enroll = commands.add_parser(
        "enroll",
        help="discover, normalize, register provenance, and validate a local corpus",
    )
    enroll.add_argument("--source", type=Path, required=True)
    enroll.add_argument("--dataset-id", required=True)
    enroll.add_argument("--dataset-version", required=True)
    enroll.add_argument("--source-description", required=True)
    enroll.add_argument(
        "--provenance",
        choices=[item.value for item in DatasetProvenance],
        required=True,
    )
    enroll.add_argument("--output-directory", type=Path, required=True)
    enroll.add_argument("--creation-timestamp", type=_aware_timestamp)

    queue = commands.add_parser(
        "queue",
        help="create a deterministic, full-population, label-free priority queue",
    )
    queue.add_argument("--enrollment-directory", type=Path, required=True)
    queue.add_argument("--output-directory", type=Path, required=True)
    queue.add_argument(
        "--strategy",
        choices=[item.value for item in NLPQueueSamplingStrategy],
        required=True,
    )
    queue.add_argument("--seed", type=int, default=42)
    queue.add_argument("--priority-count", type=int)
    queue.add_argument(
        "--review-report-ids",
        type=Path,
        help=(
            "explicit local IDs for UNCERTAINTY_REVIEW or MODEL_ERROR_REVIEW; "
            "the file is never treated as ground truth"
        ),
    )
    queue.add_argument("--creation-timestamp", type=_aware_timestamp)

    status = commands.add_parser(
        "queue-status",
        help="append a label-free annotation workflow status event",
    )
    status.add_argument("--queue", type=Path, required=True)
    status.add_argument("--events", type=Path, required=True)
    status.add_argument("--report-id", required=True)
    status.add_argument(
        "--status",
        choices=[
            item.value
            for item in NLPAnnotationQueueStatus
            if item is not NLPAnnotationQueueStatus.UNANNOTATED
        ],
        required=True,
    )
    status.add_argument("--actor-id", required=True)
    status.add_argument("--reason", required=True)
    status.add_argument("--annotation-reference")
    status.add_argument("--adjudication-id")
    status.add_argument("--released-dataset-version")
    status.add_argument("--timestamp", type=_aware_timestamp)

    release = commands.add_parser(
        "release",
        help=(
            "release explicitly adjudicated rows and register them as CANDIDATE_DATA"
        ),
    )
    release.add_argument("--enrollment-directory", type=Path, required=True)
    release.add_argument("--annotations", type=Path, required=True)
    release.add_argument("--adjudications", type=Path, required=True)
    release.add_argument("--split-assignments", type=Path, required=True)
    release.add_argument("--dataset-id")
    release.add_argument("--dataset-version")
    release.add_argument("--output-directory", type=Path, required=True)
    release.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_DATASET_REGISTRY_PATH,
    )
    release.add_argument("--license-or-usage-note", required=True)
    release.add_argument("--independent-test-dataset-id", action="append", default=[])
    release.add_argument("--creation-timestamp", type=_aware_timestamp)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "enroll":
        result = enroll_local_nlp_corpus(
            args.source,
            dataset_id=args.dataset_id,
            dataset_version=args.dataset_version,
            source_description=args.source_description,
            provenance_classification=DatasetProvenance(args.provenance),
            output_directory=args.output_directory,
            creation_timestamp=args.creation_timestamp,
        )
        print(f"enrollment_directory={result.enrollment_directory}")
        print(f"validation_report={result.validation_report_path}")
        print(f"validation_status={result.validation_report.status.value}")
        print(f"annotation_readiness={result.enrollment_manifest.annotation_readiness}")
        return 0 if result.validation_report.valid else 2
    if args.command == "queue":
        corpus = load_enrolled_nlp_corpus(args.enrollment_directory)
        result = write_nlp_annotation_queue(
            corpus,
            output_directory=args.output_directory,
            sampling_strategy=NLPQueueSamplingStrategy(args.strategy),
            seed=args.seed,
            priority_count=args.priority_count,
            review_report_ids=_load_report_ids(args.review_report_ids),
            created_at=args.creation_timestamp,
        )
        print(f"queue_path={result.queue_path}")
        print(f"queue_report={result.report_path}")
        print(f"total_reports={result.report.total_reports}")
        print("automatic_labels=NONE")
        return 0
    if args.command == "queue-status":
        queue = load_nlp_annotation_queue(args.queue)
        store = NLPAnnotationQueueStatusStore(args.events)
        event = create_queue_status_event(
            queue,
            store.load(),
            report_id=args.report_id,
            annotation_status=NLPAnnotationQueueStatus(args.status),
            actor_id=args.actor_id,
            reason=args.reason,
            timestamp=args.timestamp,
            annotation_reference=args.annotation_reference,
            adjudication_id=args.adjudication_id,
            released_dataset_version=args.released_dataset_version,
        )
        store.append(queue, event)
        print(f"queue_status_event={event.event_id}")
        print(f"annotation_status={event.annotation_status.value}")
        return 0
    if args.command == "release":
        corpus = load_enrolled_nlp_corpus(args.enrollment_directory)
        split_assignments = _load_json_object(
            args.split_assignments,
            "NLP split assignment paths",
        )
        dataset_id = args.dataset_id or corpus.source_manifest.dataset_id
        dataset_version = args.dataset_version or corpus.source_manifest.dataset_version
        release = release_nlp_annotation_dataset(
            raw_nlp_reports_to_annotation_sources(corpus.reports),
            NLPAnnotationStore(args.annotations).load(),
            NLPAdjudicationStore(args.adjudications).load(),
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            output_directory=args.output_directory,
            registry_path=args.registry,
            split_assignments_by_group=split_assignments,
            independent_test_dataset_ids=args.independent_test_dataset_id,
            provenance=corpus.source_manifest.provenance_classification,
            source_description=corpus.source_manifest.source_description,
            license_or_usage_note=args.license_or_usage_note,
            creation_timestamp=args.creation_timestamp,
            source_manifest_path=corpus.source_manifest_path,
            source_manifest_hash=corpus.enrollment_manifest.source_manifest_hash,
        )
        print(f"dataset_path={release.dataset_path}")
        print(f"manifest_path={release.manifest_path}")
        print(f"dataset_hash={release.manifest.dataset_hash}")
        print(f"source_manifest_hash={release.manifest.source_manifest_hash}")
        print("registry_classification=CANDIDATE_DATA")
        print("registry_status=DISCOVERED_REQUIRES_VALIDATION_AND_EXPLICIT_APPROVAL")
        return 0
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
