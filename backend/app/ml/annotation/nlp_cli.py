"""Local CLI for blind NLP annotation, sampling, QC, and adjudication."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from app.ml.config import NLPClassifierConfig, local_only_path
from app.ml.contracts import TextPrediction
from app.ml.data.nlp_annotations import (
    MODEL_SUGGESTION_BANNER,
    PROTECTED_V2_ARTIFACT_PATH,
    NLPAdjudicationStore,
    NLPAnnotationState,
    NLPAnnotationStore,
    NLPAnnotationView,
    NLPEventLabel,
    NLPHumanAnnotation,
    NLPLanguage,
    NLPReviewQueue,
    NLPSamplingStrategy,
    NLPSourceReport,
    adjudicate_nlp_case,
    assert_protected_nlp_assets_immutable,
    build_nlp_adjudication_case,
    build_nlp_annotation_view,
    create_nlp_human_annotation,
    load_nlp_source_reports,
    sample_nlp_review_queue,
    validate_nlp_annotation_quality,
    write_nlp_annotation_quality_report,
)
from app.ml.data.nlp_dataset import (
    build_nlp_grouping_plan,
    group_nlp_records,
    release_nlp_annotation_dataset,
    resolve_nlp_adjudications,
)
from app.ml.data.registry import (
    DEFAULT_DATASET_REGISTRY_PATH,
    DatasetProvenance,
)

PredictionProvider = Callable[[str], TextPrediction]


def format_nlp_report_for_review(
    report: NLPSourceReport,
    view: NLPAnnotationView,
) -> str:
    """Render exact text and keep optional model output visibly non-authoritative."""

    if view.report_id != report.report_id or view.text != report.text:
        raise ValueError("annotation view does not match source report")
    lines = [
        f"REPORT FOR HUMAN REVIEW: {report.report_id}",
        f"BLIND_ANNOTATION = {str(view.blind_annotation).upper()}",
        "ORIGINAL TEXT (PRESERVED EXACTLY):",
        view.text,
        "SOURCE METADATA: "
        + json.dumps(
            report.source_metadata_if_available,
            ensure_ascii=False,
            sort_keys=True,
        ),
        "LANGUAGE HINT (NOT A LABEL): "
        + (report.language_hint.value if report.language_hint else "NONE"),
        f"EVENT ID IF KNOWN: {report.event_id_if_known or 'NONE'}",
        f"INCIDENT ID IF KNOWN: {report.incident_id_if_known or 'NONE'}",
        f"SOURCE REPORT FAMILY: {report.source_report_family or 'NONE'}",
    ]
    if view.model_suggestion is not None:
        lines.extend(
            [
                MODEL_SUGGESTION_BANNER,
                f"suggested_label: {view.model_suggestion.label.value}",
                f"model_confidence: {view.model_suggestion.confidence:.6f}",
                f"model_version: {view.model_suggestion.model_version}",
                "The human must independently enter a label or UNCERTAIN.",
            ]
        )
    return "\n".join(lines)


def _parse_human_label(value: str) -> tuple[NLPAnnotationState, NLPEventLabel | None]:
    normalized = value.strip().upper().replace(" ", "_")
    aliases: dict[str, NLPEventLabel] = {
        "UF": NLPEventLabel.URBAN_FLOOD,
        "URBAN_FLOOD": NLPEventLabel.URBAN_FLOOD,
        "RB": NLPEventLabel.RIVER_BREACH,
        "RIVER_BREACH": NLPEventLabel.RIVER_BREACH,
        "CB": NLPEventLabel.CLOUDBURST,
        "CLOUDBURST": NLPEventLabel.CLOUDBURST,
        "CI": NLPEventLabel.CYCLONE_INUNDATION,
        "CYCLONE_INUNDATION": NLPEventLabel.CYCLONE_INUNDATION,
        "NR": NLPEventLabel.NOT_RELEVANT,
        "NOT_RELEVANT": NLPEventLabel.NOT_RELEVANT,
    }
    if normalized in {"U", "UNCERTAIN"}:
        return NLPAnnotationState.UNCERTAIN, None
    if normalized not in aliases:
        raise ValueError(
            "label must be UF, RB, CB, CI, NR, or U (UNCERTAIN)"
        )
    return NLPAnnotationState.LABELED, aliases[normalized]


def _parse_language(value: str) -> NLPLanguage:
    aliases = {
        "EN": NLPLanguage.ENGLISH,
        "ENGLISH": NLPLanguage.ENGLISH,
        "HI": NLPLanguage.HINDI,
        "HINDI": NLPLanguage.HINDI,
        "HINGLISH": NLPLanguage.HINGLISH,
        "OTHER": NLPLanguage.OTHER,
        "UNKNOWN": NLPLanguage.UNKNOWN,
    }
    normalized = value.strip().upper()
    if normalized not in aliases:
        raise ValueError("language must be en, hi, hinglish, other, or unknown")
    return aliases[normalized]


def run_nlp_annotation_cli(
    reports: Sequence[NLPSourceReport],
    store: NLPAnnotationStore,
    *,
    annotator_id: str,
    blind_annotation: bool = True,
    prediction_provider: PredictionProvider | None = None,
    report_ids: Sequence[str] | None = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> list[NLPHumanAnnotation]:
    """Collect only explicit human input and append immutable annotations."""

    if not annotator_id.strip():
        raise ValueError("annotator_id is required")
    if not blind_annotation and prediction_provider is None:
        raise ValueError(
            "model-assisted mode requires an explicit local prediction provider"
        )
    protected_index = assert_protected_nlp_assets_immutable()
    report_by_id = {item.report_id: item for item in reports}
    if len(report_by_id) != len(reports):
        raise ValueError("source report IDs must be unique")
    if report_ids is None:
        ordered = list(reports)
    else:
        unknown = sorted(set(report_ids) - set(report_by_id))
        if unknown:
            raise ValueError(f"review queue contains unknown reports: {unknown}")
        ordered = [report_by_id[report_id] for report_id in report_ids]

    existing = {
        (item.report_id, item.annotator_id) for item in store.load()
    }
    created: list[NLPHumanAnnotation] = []
    for report in ordered:
        key = (report.report_id, annotator_id.strip())
        if key in existing:
            continue
        prediction = (
            None
            if blind_annotation
            else prediction_provider(report.text)  # type: ignore[misc]
        )
        view = build_nlp_annotation_view(
            report,
            prediction,
            blind_annotation=blind_annotation,
        )
        output_fn(format_nlp_report_for_review(report, view))
        output_fn(
            "[UF URBAN_FLOOD] [RB RIVER_BREACH] [CB CLOUDBURST] "
            "[CI CYCLONE_INUNDATION] [NR NOT_RELEVANT] [U UNCERTAIN]"
        )
        state, label = _parse_human_label(input_fn("human label: "))
        language = _parse_language(
            input_fn("language [en/hi/hinglish/other/unknown]: ")
        )
        reason = input_fn("human reason: ").strip()
        if not reason:
            raise ValueError("human annotation reason is required")
        try:
            confidence = float(input_fn("human confidence [0.0-1.0]: ").strip())
        except ValueError as error:
            raise ValueError("human confidence must be numeric") from error
        annotation = create_nlp_human_annotation(
            report,
            state=state,
            label=label,
            annotator_id=annotator_id,
            reason=reason,
            confidence=confidence,
            language=language,
            timestamp=now_fn(),
            view=view,
            protected_index=protected_index,
        )
        store.append(annotation)
        existing.add(key)
        created.append(annotation)
    return created


def run_nlp_adjudication_cli(
    annotations: Sequence[NLPHumanAnnotation],
    store: NLPAdjudicationStore,
    *,
    adjudicator_id: str,
    report_ids: Sequence[str] | None = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
):
    """Create explicit human decisions; agreement is never auto-accepted."""

    if not adjudicator_id.strip():
        raise ValueError("adjudicator_id is required")
    by_report: defaultdict[str, list[NLPHumanAnnotation]] = defaultdict(list)
    for annotation in annotations:
        by_report[annotation.report_id].append(annotation)
    selected_ids = list(report_ids) if report_ids is not None else sorted(by_report)
    unknown = sorted(set(selected_ids) - set(by_report))
    if unknown:
        raise ValueError(f"adjudication queue contains unknown reports: {unknown}")
    existing_reports = {item.report_id for item in store.load()}
    created = []
    for report_id in selected_ids:
        if report_id in existing_reports:
            continue
        case = build_nlp_adjudication_case(by_report[report_id])
        output_fn(f"REPORT FOR EXPLICIT ADJUDICATION: {report_id}")
        output_fn(case.annotations[0].text)
        for item in case.annotations:
            human_value = item.label.value if item.label is not None else "UNCERTAIN"
            output_fn(
                f"{item.annotation_id}: annotator={item.annotator_id}, "
                f"judgment={human_value}, reason={item.reason}"
            )
        output_fn(
            "Agreement is evidence only; an adjudicator decision is still required."
        )
        final_state, final_label = _parse_human_label(
            input_fn("final human label: ")
        )
        reason = input_fn("adjudication reason: ").strip()
        if not reason:
            raise ValueError("adjudication reason is required")
        resolved = adjudicate_nlp_case(
            case,
            final_state=final_state,
            final_label=final_label,
            adjudicator_id=adjudicator_id,
            reason=reason,
            timestamp=now_fn(),
        )
        if resolved.decision is None:  # defensive; adjudicate_nlp_case always sets it
            raise RuntimeError("explicit adjudication did not produce a decision")
        store.append(resolved.decision)
        existing_reports.add(report_id)
        created.append(resolved.decision)
    return created


def load_frozen_v2_prediction_provider() -> PredictionProvider:
    """Load frozen v2 only after explicit assisted-mode opt-in."""

    assert_protected_nlp_assets_immutable()
    from app.ml.components.nlp_classifier import NLPClassifier, load_nlp_artifact

    artifact = load_nlp_artifact(PROTECTED_V2_ARTIFACT_PATH)
    if artifact.model_status != "DEVELOPMENT_ONLY_FROZEN":
        raise ValueError("model assistance requires the frozen development v2 artifact")
    config = NLPClassifierConfig(
        model_version=artifact.model_version,
        feature_version=artifact.feature_version,
        preprocessing_version=artifact.preprocessing_version,
        artifact_path=PROTECTED_V2_ARTIFACT_PATH,
        metrics_path=PROTECTED_V2_ARTIFACT_PATH.with_suffix(".metrics.json"),
        char_ngram_range=tuple(artifact.char_space.ngram_range),
        word_ngram_range=tuple(artifact.word_space.ngram_range),
        regularization_grid=(artifact.classifier.regularization_c,),
        regularization_c=artifact.classifier.regularization_c,
        max_iterations=artifact.classifier.max_iterations,
        random_state=artifact.classifier.random_state,
    )
    classifier = NLPClassifier(config)
    return classifier.predict


def _load_queue(path: Path | None) -> list[str] | None:
    if path is None:
        return None
    selected = local_only_path(path, description="NLP review queue paths")
    payload = json.loads(selected.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("queue_version") == (
        "nlp-annotation-queue-v1"
    ):
        from app.ml.data.nlp_corpus import NLPAnnotationQueue

        queue = NLPAnnotationQueue.model_validate(payload)
        return [item.report_id for item in queue.items]
    return list(NLPReviewQueue.model_validate(payload).report_ids)


def _write_queue(path: Path, queue: NLPReviewQueue) -> None:
    selected = local_only_path(path, description="NLP review queue paths")
    if selected.exists():
        raise FileExistsError("review queue output already exists")
    selected.parent.mkdir(parents=True, exist_ok=True)
    selected.write_text(
        queue.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local INDRA human NLP annotation workflow"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    annotate = commands.add_parser("annotate", help="append human annotations")
    annotate.add_argument("--reports", type=Path, required=True)
    annotate.add_argument("--annotations", type=Path, required=True)
    annotate.add_argument("--annotator-id", required=True)
    annotate.add_argument("--queue", type=Path)
    annotate.add_argument(
        "--model-assistance",
        action="store_true",
        help=(
            "explicitly show frozen v2 output as MODEL SUGGESTION — NOT GROUND TRUTH; "
            "default is blind"
        ),
    )

    adjudicate = commands.add_parser(
        "adjudicate",
        help="append explicit human adjudication decisions",
    )
    adjudicate.add_argument("--annotations", type=Path, required=True)
    adjudicate.add_argument("--adjudications", type=Path, required=True)
    adjudicate.add_argument("--adjudicator-id", required=True)
    adjudicate.add_argument("--report-id", action="append")

    quality = commands.add_parser("quality", help="write annotation QC report")
    quality.add_argument("--reports", type=Path, required=True)
    quality.add_argument("--annotations", type=Path, required=True)
    quality.add_argument("--adjudications", type=Path, required=True)
    quality.add_argument("--output", type=Path, required=True)
    quality.add_argument("--minimum-repeated-reports", type=int, default=2)

    sample = commands.add_parser("sample", help="write deterministic review queue")
    sample.add_argument("--reports", type=Path, required=True)
    sample.add_argument("--annotations", type=Path, required=True)
    sample.add_argument(
        "--strategy",
        choices=[item.value for item in NLPSamplingStrategy],
        required=True,
    )
    sample.add_argument("--count", type=int, required=True)
    sample.add_argument("--seed", type=int, default=42)
    sample.add_argument("--confusion-actual", choices=[item.value for item in NLPEventLabel])
    sample.add_argument("--confusion-predicted", choices=[item.value for item in NLPEventLabel])
    sample.add_argument("--output", type=Path, required=True)

    plan = commands.add_parser(
        "plan-splits",
        help="write grouped records with blank splits for explicit human assignment",
    )
    plan.add_argument("--reports", type=Path, required=True)
    plan.add_argument("--annotations", type=Path, required=True)
    plan.add_argument("--adjudications", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)

    release = commands.add_parser(
        "release",
        help="write and register an immutable human-adjudicated candidate version",
    )
    release.add_argument("--reports", type=Path, required=True)
    release.add_argument("--annotations", type=Path, required=True)
    release.add_argument("--adjudications", type=Path, required=True)
    release.add_argument("--split-assignments", type=Path, required=True)
    release.add_argument("--dataset-id", required=True)
    release.add_argument("--dataset-version", required=True)
    release.add_argument("--output-directory", type=Path, required=True)
    release.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_DATASET_REGISTRY_PATH,
    )
    release.add_argument(
        "--provenance",
        choices=[
            item.value
            for item in DatasetProvenance
            if item is not DatasetProvenance.PROVENANCE_UNKNOWN
        ],
        required=True,
    )
    release.add_argument("--source-description", required=True)
    release.add_argument("--license-or-usage-note", required=True)
    release.add_argument("--independent-test-dataset-id", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "annotate":
        reports = load_nlp_source_reports(args.reports)
        provider = (
            load_frozen_v2_prediction_provider()
            if args.model_assistance
            else None
        )
        created = run_nlp_annotation_cli(
            reports,
            NLPAnnotationStore(args.annotations),
            annotator_id=args.annotator_id,
            blind_annotation=not args.model_assistance,
            prediction_provider=provider,
            report_ids=_load_queue(args.queue),
        )
        print(f"appended_annotations={len(created)}")
        return 0
    if args.command == "adjudicate":
        created = run_nlp_adjudication_cli(
            NLPAnnotationStore(args.annotations).load(),
            NLPAdjudicationStore(args.adjudications),
            adjudicator_id=args.adjudicator_id,
            report_ids=args.report_id,
        )
        print(f"appended_adjudications={len(created)}")
        return 0
    if args.command == "quality":
        report = validate_nlp_annotation_quality(
            NLPAnnotationStore(args.annotations).load(),
            load_nlp_source_reports(args.reports),
            adjudications=NLPAdjudicationStore(args.adjudications).load(),
            minimum_repeated_reports=args.minimum_repeated_reports,
        )
        write_nlp_annotation_quality_report(args.output, report)
        print(f"quality_status={'VALID' if report.valid else 'INVALID'}")
        return 0 if report.valid else 2
    if args.command == "sample":
        confusion_pair = None
        if args.confusion_actual or args.confusion_predicted:
            if not (args.confusion_actual and args.confusion_predicted):
                raise ValueError(
                    "confusion sampling requires both actual and predicted labels"
                )
            confusion_pair = (
                NLPEventLabel(args.confusion_actual),
                NLPEventLabel(args.confusion_predicted),
            )
        queue = sample_nlp_review_queue(
            load_nlp_source_reports(args.reports),
            NLPAnnotationStore(args.annotations).load(),
            strategy=NLPSamplingStrategy(args.strategy),
            count=args.count,
            seed=args.seed,
            confusion_pair=confusion_pair,
        )
        _write_queue(args.output, queue)
        print(f"queued_reports={len(queue.report_ids)}")
        return 0
    if args.command == "plan-splits":
        selected = local_only_path(
            args.output,
            description="NLP grouping plan paths",
        )
        if selected.exists():
            raise FileExistsError("grouping plan output already exists")
        selected.parent.mkdir(parents=True, exist_ok=True)
        resolution = resolve_nlp_adjudications(
            load_nlp_source_reports(args.reports),
            NLPAnnotationStore(args.annotations).load(),
            NLPAdjudicationStore(args.adjudications).load(),
        )
        plan = build_nlp_grouping_plan(group_nlp_records(resolution.records))
        selected.write_text(
            plan.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"groups_requiring_explicit_split={len(plan.entries)}")
        return 0
    if args.command == "release":
        split_path = local_only_path(
            args.split_assignments,
            description="NLP split assignment paths",
        )
        split_assignments = json.loads(split_path.read_text(encoding="utf-8"))
        if not isinstance(split_assignments, dict):
            raise ValueError("split assignments must be a JSON object")
        result = release_nlp_annotation_dataset(
            load_nlp_source_reports(args.reports),
            NLPAnnotationStore(args.annotations).load(),
            NLPAdjudicationStore(args.adjudications).load(),
            dataset_id=args.dataset_id,
            dataset_version=args.dataset_version,
            output_directory=args.output_directory,
            registry_path=args.registry,
            split_assignments_by_group=split_assignments,
            independent_test_dataset_ids=args.independent_test_dataset_id,
            provenance=DatasetProvenance(args.provenance),
            source_description=args.source_description,
            license_or_usage_note=args.license_or_usage_note,
        )
        print(f"dataset_path={result.dataset_path}")
        print(f"manifest_path={result.manifest_path}")
        print("registry_status=DISCOVERED_CANDIDATE_REQUIRES_VALIDATION_AND_APPROVAL")
        return 0
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "build_parser",
    "format_nlp_report_for_review",
    "load_frozen_v2_prediction_provider",
    "main",
    "run_nlp_adjudication_cli",
    "run_nlp_annotation_cli",
]
