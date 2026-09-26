"""Local-only dataset registry and readiness commands."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.ml.config import local_only_path
from app.ml.data.dataset_validation import (
    materialize_explicit_splits,
    validate_dataset_record,
    validate_registered_dataset,
)
from app.ml.data.registry import (
    DEFAULT_DATASET_REGISTRY_PATH,
    AnomalyDataRole,
    DatasetClassification,
    DatasetComponent,
    DatasetFormat,
    DatasetProvenance,
    DatasetRegistry,
    DatasetRegistryRecord,
    DatasetStatus,
    DatasetUse,
    approve_dataset,
    find_dataset,
    hash_dataset_path,
    load_bound_validation_report,
    load_dataset_registry,
    register_dataset,
    safe_extract_local_zip,
    save_dataset_registry,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed


def _ensure_registry(path: Path) -> None:
    if path.exists():
        return
    save_dataset_registry(
        DatasetRegistry(
            last_modified_at=datetime.now(timezone.utc),
            entries=[],
        ),
        path,
    )


def _infer_format(path: Path) -> DatasetFormat:
    if path.is_dir():
        return DatasetFormat.DIRECTORY
    suffix = path.suffix.casefold()
    mapping = {
        ".csv": DatasetFormat.CSV,
        ".json": DatasetFormat.JSON,
        ".jsonl": DatasetFormat.JSONL,
        ".parquet": DatasetFormat.PARQUET,
        ".jpg": DatasetFormat.JPEG,
        ".jpeg": DatasetFormat.JPEG,
        ".png": DatasetFormat.PNG,
        ".zip": DatasetFormat.ZIP,
    }
    if suffix not in mapping:
        raise ValueError(
            f"cannot infer dataset format from suffix: {suffix or '<none>'}"
        )
    return mapping[suffix]


def _stored_path(path: Path, registry_path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(registry_path.resolve().parent).as_posix()
    except ValueError:
        return str(resolved)


def _print(payload) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _record_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "discover-dataset",
        help="Register local bytes without inferring approval",
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument(
        "--component", required=True, choices=[item.value for item in DatasetComponent]
    )
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--format", choices=[item.value for item in DatasetFormat])
    parser.add_argument("--schema-version", required=True)
    parser.add_argument("--label-schema-version", required=True)
    parser.add_argument("--creation-timestamp")
    parser.add_argument("--source-description", required=True)
    parser.add_argument(
        "--provenance",
        required=True,
        choices=[item.value for item in DatasetProvenance],
    )
    parser.add_argument("--license-or-usage-note", required=True)
    parser.add_argument("--grouping-field")
    parser.add_argument("--time-field")
    parser.add_argument("--split-field", default="split")
    parser.add_argument(
        "--classification",
        default=DatasetClassification.CANDIDATE_DATA.value,
        choices=[item.value for item in DatasetClassification],
    )
    parser.add_argument("--human-adjudicated", action="store_true")
    parser.add_argument("--label-source", default="UNSPECIFIED")
    parser.add_argument(
        "--anomaly-data-role",
        choices=[item.value for item in AnomalyDataRole],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="INDRA local dataset readiness commands (no network access)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _record_parser(subparsers)

    validate = subparsers.add_parser("validate-dataset")
    validate.add_argument(
        "--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH
    )
    validate.add_argument("--dataset-id", required=True)
    validate.add_argument("--dataset-version")
    validate.add_argument("--report", type=Path)

    hash_parser = subparsers.add_parser("hash-dataset")
    hash_parser.add_argument("path", type=Path)

    report = subparsers.add_parser("report-dataset")
    report.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    report.add_argument("--dataset-id", required=True)
    report.add_argument("--dataset-version")

    approve = subparsers.add_parser("approve-dataset")
    approve.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    approve.add_argument("--dataset-id", required=True)
    approve.add_argument("--dataset-version")
    approve.add_argument(
        "--use", required=True, choices=[item.value for item in DatasetUse]
    )
    approve.add_argument("--approver-id", required=True)
    approve.add_argument("--approval-note", required=True)

    split = subparsers.add_parser("split-dataset")
    split.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    split.add_argument("--dataset-id", required=True)
    split.add_argument("--dataset-version")
    split.add_argument("--output-directory", type=Path, required=True)

    leakage = subparsers.add_parser("verify-leakage")
    leakage.add_argument("--registry", type=Path, default=DEFAULT_DATASET_REGISTRY_PATH)
    leakage.add_argument("--dataset-id", required=True)
    leakage.add_argument("--dataset-version")

    extract = subparsers.add_parser("extract-local-archive")
    extract.add_argument("archive", type=Path)
    extract.add_argument("destination", type=Path)
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "hash-dataset":
        _print(hash_dataset_path(args.path))
        return 0
    if args.command == "extract-local-archive":
        paths = safe_extract_local_zip(args.archive, args.destination)
        _print({"extracted": [str(path) for path in paths]})
        return 0

    registry_path = local_only_path(args.registry, description="dataset registries")
    if args.command == "discover-dataset":
        _ensure_registry(registry_path)
        dataset_path = local_only_path(args.path, description="dataset paths").resolve()
        hashed = hash_dataset_path(dataset_path)
        record = DatasetRegistryRecord(
            dataset_id=args.dataset_id,
            dataset_version=args.dataset_version,
            component=DatasetComponent(args.component),
            local_path=_stored_path(dataset_path, registry_path),
            format=DatasetFormat(args.format)
            if args.format
            else _infer_format(dataset_path),
            content_sha256=hashed.content_sha256,
            schema_version=args.schema_version,
            label_schema_version=args.label_schema_version,
            creation_timestamp=_timestamp(args.creation_timestamp),
            source_description=args.source_description,
            provenance=DatasetProvenance(args.provenance),
            license_or_usage_note=args.license_or_usage_note,
            grouping_field=args.grouping_field,
            time_field=args.time_field,
            split_field=args.split_field,
            label_count=0,
            row_or_image_count=0,
            status=DatasetStatus.DISCOVERED,
            data_classification=DatasetClassification(args.classification),
            human_adjudicated=args.human_adjudicated,
            label_source=args.label_source,
            anomaly_data_role=(
                AnomalyDataRole(args.anomaly_data_role)
                if args.anomaly_data_role
                else None
            ),
        )
        updated = register_dataset(record, registry_path=registry_path)
        _print(find_dataset(updated, record.dataset_id, record.dataset_version))
        return 0
    if args.command == "validate-dataset":
        _print(
            validate_registered_dataset(
                args.dataset_id,
                registry_path=registry_path,
                dataset_version=args.dataset_version,
                report_path=args.report,
            )
        )
        return 0
    if args.command == "report-dataset":
        registry = load_dataset_registry(registry_path)
        record = find_dataset(registry, args.dataset_id, args.dataset_version)
        payload = {"registry_record": record.model_dump(mode="json")}
        if record.validation_report_path:
            payload["validation_report"] = load_bound_validation_report(
                record,
                registry_path,
            ).model_dump(mode="json")
        _print(payload)
        return 0
    if args.command == "approve-dataset":
        _print(
            approve_dataset(
                args.dataset_id,
                DatasetUse(args.use),
                approver_id=args.approver_id,
                approval_note=args.approval_note,
                registry_path=registry_path,
                dataset_version=args.dataset_version,
            )
        )
        return 0
    if args.command == "split-dataset":
        outputs = materialize_explicit_splits(
            args.dataset_id,
            args.output_directory,
            registry_path=registry_path,
            dataset_version=args.dataset_version,
        )
        _print({name: str(path) for name, path in outputs.items()})
        return 0
    if args.command == "verify-leakage":
        registry = load_dataset_registry(registry_path)
        record = find_dataset(registry, args.dataset_id, args.dataset_version)
        _print(
            validate_dataset_record(
                record,
                registry_path=registry_path,
            ).leakage
        )
        return 0
    raise ValueError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except Exception as error:  # noqa: BLE001 - CLI must return structured local failures
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
