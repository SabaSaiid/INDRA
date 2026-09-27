from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ml.annotation.nlp_cli import (
    format_nlp_report_for_review,
    run_nlp_adjudication_cli,
    run_nlp_annotation_cli,
)
from app.ml.components.nlp_classifier import load_nlp_artifact
from app.ml.contracts import PredictionStatus, TextPrediction
from app.ml.data.dataset_validation import (
    CheckStatus,
    validate_dataset_record,
    validate_registered_dataset,
)
from app.ml.data.loaders import load_csv
from app.ml.data.nlp_annotations import (
    MODEL_SUGGESTION_BANNER,
    PROTECTED_REPORTS_PATH,
    PROTECTED_V1_ARTIFACT_PATH,
    PROTECTED_V2_ARTIFACT_PATH,
    NLPAdjudicationStore,
    NLPAnnotationQualityReport,
    NLPAnnotationState,
    NLPAnnotationStore,
    NLPEventLabel,
    NLPHumanAnnotation,
    NLPLanguage,
    NLPSamplingStrategy,
    NLPSourceReport,
    adjudicate_nlp_case,
    assert_protected_nlp_assets_immutable,
    build_nlp_adjudication_case,
    build_nlp_annotation_view,
    create_nlp_human_annotation,
    exact_text_sha256,
    sample_nlp_review_queue,
    validate_nlp_annotation_quality,
)
from app.ml.data.nlp_dataset import (
    HUMAN_LABEL_SOURCE,
    NLP_DATASET_SCHEMA_VERSION,
    NLPDatasetRecord,
    NLPDatasetSplit,
    build_nlp_grouping_plan,
    group_nlp_records,
    materialize_nlp_dataset_records,
    release_nlp_annotation_dataset,
    resolve_nlp_adjudications,
    validate_nlp_dataset_leakage,
)
from app.ml.data.registry import (
    DatasetApprovalError,
    DatasetProvenance,
    DatasetRegistry,
    DatasetStatus,
    DatasetUse,
    approve_dataset,
    find_dataset,
    load_dataset_registry,
    save_dataset_registry,
)
from app.ml.data.schemas import DatasetSplit
from app.ml.training.train_nlp_classifier import EXPECTED_CLASSES

FIXED_TIME = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def phase15_workspace():
    root = Path(__file__).resolve().parents[3] / ".phase15-test-tmp"
    case = (root / f"case-{uuid4().hex}").resolve()
    case.mkdir(parents=True, exist_ok=False)
    try:
        yield case
    finally:
        if case.is_relative_to(root.resolve()):
            shutil.rmtree(case)
        if root.exists() and not any(root.iterdir()):
            root.rmdir()


@pytest.fixture(scope="module")
def protected_index():
    return assert_protected_nlp_assets_immutable()


def _report(
    report_id: str,
    text: str,
    *,
    language: NLPLanguage | None = None,
    event_id: str | None = None,
    incident_id: str | None = None,
    family: str | None = None,
    source_dataset_id: str | None = "phase15-local-source",
) -> NLPSourceReport:
    return NLPSourceReport(
        report_id=report_id,
        text=text,
        source_metadata_if_available={"fixture": "PHASE15_LOCAL_ONLY"},
        language_hint=language,
        event_id_if_known=event_id,
        incident_id_if_known=incident_id,
        source_report_family=family,
        source_dataset_id=source_dataset_id,
    )


def _annotation(
    report: NLPSourceReport,
    annotator: str,
    *,
    label: NLPEventLabel | None,
    state: NLPAnnotationState = NLPAnnotationState.LABELED,
    language: NLPLanguage = NLPLanguage.ENGLISH,
    annotation_id: str | None = None,
    view=None,
    protected_index=None,
) -> NLPHumanAnnotation:
    return create_nlp_human_annotation(
        report,
        state=state,
        label=label,
        annotator_id=annotator,
        reason=f"Independent human review by {annotator}",
        confidence=0.8,
        language=language,
        timestamp=FIXED_TIME,
        annotation_id=annotation_id,
        view=view,
        protected_index=protected_index,
    )


def _decision(
    annotations: list[NLPHumanAnnotation],
    *,
    label: NLPEventLabel | None,
    state: NLPAnnotationState = NLPAnnotationState.LABELED,
    suffix: str,
):
    resolved = adjudicate_nlp_case(
        build_nlp_adjudication_case(annotations),
        final_state=state,
        final_label=label,
        adjudicator_id="phase15-adjudicator",
        reason="Explicit independent adjudication of the source annotations.",
        timestamp=FIXED_TIME,
        adjudication_id=f"adjudication-{suffix}",
    )
    assert resolved.decision is not None
    return resolved.decision


def _empty_registry(workspace: Path) -> Path:
    path = workspace / "registry" / "datasets.json"
    save_dataset_registry(
        DatasetRegistry(last_modified_at=FIXED_TIME),
        path,
        modified_at=FIXED_TIME,
    )
    return path


def _release_inputs(protected_index):
    specifications = (
        (
            "p15-01",
            "Municipal drainage failed beside Lotus Market and water entered shops.",
            NLPEventLabel.URBAN_FLOOD,
            NLPLanguage.ENGLISH,
            "train",
        ),
        (
            "p15-02",
            "वार्ड बाईस में नालियां जाम होने से गलियों में पानी भर गया।",
            NLPEventLabel.URBAN_FLOOD,
            NLPLanguage.HINDI,
            "train",
        ),
        (
            "p15-03",
            "The Bhagirathi embankment opened near Sona village before sunrise.",
            NLPEventLabel.RIVER_BREACH,
            NLPLanguage.ENGLISH,
            "train",
        ),
        (
            "p15-04",
            "नदी का तटबंध टूटने से उत्तरी खेतों में तेज बहाव पहुंचा।",
            NLPEventLabel.RIVER_BREACH,
            NLPLanguage.HINDI,
            "train",
        ),
        (
            "p15-05",
            "Stormwater from blocked culverts flooded the old bus terminal.",
            NLPEventLabel.URBAN_FLOOD,
            NLPLanguage.ENGLISH,
            "validation",
        ),
        (
            "p15-06",
            "पूर्वी गांव के पास नदी का बांध कट गया और खेत डूब गए।",
            NLPEventLabel.RIVER_BREACH,
            NLPLanguage.HINDI,
            "validation",
        ),
        (
            "p15-07",
            "Residential lanes around Cedar Square flooded after drains backed up.",
            NLPEventLabel.URBAN_FLOOD,
            NLPLanguage.ENGLISH,
            "test",
        ),
        (
            "p15-08",
            "स्वतंत्र सर्वे में नदी किनारे नया तटबंध टूटने की पुष्टि हुई।",
            NLPEventLabel.RIVER_BREACH,
            NLPLanguage.HINDI,
            "test",
        ),
    )
    reports: list[NLPSourceReport] = []
    annotations: list[NLPHumanAnnotation] = []
    decisions = []
    split_by_report: dict[str, str] = {}
    for report_id, text, label, language, split in specifications:
        source_id = (
            "phase15-independent-real-test-v1"
            if split == "test"
            else "phase15-real-development-v1"
        )
        report = _report(
            report_id,
            text,
            language=language,
            event_id=f"event-{report_id}",
            family=f"family-{report_id}",
            source_dataset_id=source_id,
        )
        annotation = _annotation(
            report,
            "annotator-a" if language is NLPLanguage.ENGLISH else "annotator-b",
            label=label,
            language=language,
            annotation_id=f"annotation-{report_id}",
            protected_index=protected_index,
        )
        reports.append(report)
        annotations.append(annotation)
        decisions.append(_decision([annotation], label=label, suffix=report_id))
        split_by_report[report_id] = split
    grouping = group_nlp_records(
        resolve_nlp_adjudications(
            reports,
            annotations,
            decisions,
            protected_index=protected_index,
        ).records
    )
    assignments = {
        record.split_assignment_key: split_by_report[record.report_id]
        for record in grouping.records
    }
    return reports, annotations, decisions, assignments


def test_taxonomy_matches_repository_and_frozen_v2_artifact():
    artifact = load_nlp_artifact(PROTECTED_V2_ARTIFACT_PATH)
    taxonomy = {item.value for item in NLPEventLabel}

    assert taxonomy == EXPECTED_CLASSES
    assert taxonomy == set(artifact.classes)
    assert taxonomy == {
        "URBAN_FLOOD",
        "RIVER_BREACH",
        "CLOUDBURST",
        "CYCLONE_INUNDATION",
        "NOT_RELEVANT",
    }


def test_committed_quality_report_is_honest_zero_data_evidence():
    path = (
        Path(__file__).resolve().parents[4]
        / "data"
        / "labelled"
        / "nlp"
        / "annotation_quality_report.json"
    )
    report = NLPAnnotationQualityReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )

    assert report.valid is True
    assert report.report_count == 0
    assert report.annotation_count == 0
    assert report.annotator_count == 0
    assert report.agreement_status == "DATA_UNAVAILABLE"
    assert report.agreement_rate is None
    assert all(count == 0 for count in report.label_counts.values())
    assert all(count == 0 for count in report.language_counts.values())


def test_annotation_creation_preserves_hindi_and_rejects_bad_hash_or_language(
    protected_index,
):
    text = "मूल रिपोर्ट — सड़क पर पानी भरा है।  spacing जस का तस"
    report = _report("hindi-preserved", text, language=NLPLanguage.HINDI)
    annotation = _annotation(
        report,
        "annotator-hindi",
        label=NLPEventLabel.URBAN_FLOOD,
        language=NLPLanguage.HINDI,
        annotation_id="annotation-hindi",
        protected_index=protected_index,
    )

    assert annotation.text == text
    assert annotation.text_hash == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert annotation.language is NLPLanguage.HINDI
    payload = annotation.model_dump(mode="json")
    payload["text_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="text_hash"):
        NLPHumanAnnotation.model_validate(payload)
    payload = annotation.model_dump(mode="json")
    payload["language"] = "fr"
    with pytest.raises(ValidationError, match="language"):
        NLPHumanAnnotation.model_validate(payload)


def test_schema_and_quality_reject_invalid_class_annotator_and_report_context(
    protected_index,
):
    report = _report("quality-schema", "A unique report for schema validation.")
    annotation = _annotation(
        report,
        "annotator-a",
        label=NLPEventLabel.NOT_RELEVANT,
        annotation_id="quality-schema-a",
        protected_index=protected_index,
    )
    invalid_class = annotation.model_dump(mode="json")
    invalid_class["label"] = "OTHER_HEAVY_RAIN"
    with pytest.raises(ValidationError, match="label"):
        NLPHumanAnnotation.model_validate(invalid_class)
    missing_annotator = annotation.model_dump(mode="json")
    missing_annotator["annotator_id"] = " "
    with pytest.raises(ValidationError, match="annotator"):
        NLPHumanAnnotation.model_validate(missing_annotator)

    missing_report = validate_nlp_annotation_quality(
        [annotation],
        [],
        generated_at=FIXED_TIME,
    )
    assert missing_report.valid is False
    assert "missing report: quality-schema" in missing_report.errors
    duplicate_source = validate_nlp_annotation_quality(
        [annotation],
        [report, report],
        generated_at=FIXED_TIME,
    )
    assert duplicate_source.valid is False
    assert duplicate_source.duplicate_source_report_ids == ["quality-schema"]


def test_append_only_store_supports_multiple_annotators_and_rejects_duplicates(
    phase15_workspace,
    protected_index,
):
    report = _report("append-only", "A unique local drain overflow report.")
    first = _annotation(
        report,
        "annotator-a",
        label=NLPEventLabel.URBAN_FLOOD,
        annotation_id="append-a",
        protected_index=protected_index,
    )
    second = _annotation(
        report,
        "annotator-b",
        label=NLPEventLabel.RIVER_BREACH,
        annotation_id="append-b",
        protected_index=protected_index,
    )
    store = NLPAnnotationStore(phase15_workspace / "annotations.jsonl")
    store.append(first)
    store.append(second)
    before = store.path.read_bytes()

    duplicate = first.model_copy(update={"annotation_id": "append-c"})
    with pytest.raises(ValueError, match="same annotator"):
        store.append(duplicate)
    assert store.path.read_bytes() == before
    assert [item.annotation_id for item in store.load()] == ["append-a", "append-b"]


def test_blind_cli_is_default_and_assisted_cli_never_copies_suggestion(
    phase15_workspace,
):
    blind_report = _report(
        "blind-report",
        "Nali block hai aur gali mein paani bhar gaya.",
        language=NLPLanguage.HINGLISH,
    )
    blind_output: list[str] = []
    blind_responses = iter(
        ["UF", "hinglish", "Drain context is explicit.", "0.85"]
    )
    blind = run_nlp_annotation_cli(
        [blind_report],
        NLPAnnotationStore(phase15_workspace / "blind.jsonl"),
        annotator_id="human-a",
        input_fn=lambda _: next(blind_responses),
        output_fn=blind_output.append,
        now_fn=lambda: FIXED_TIME,
    )[0]
    assert blind.blind_annotation is True
    assert blind.assistance_shown is False
    assert MODEL_SUGGESTION_BANNER not in "\n".join(blind_output)

    assisted_report = _report(
        "assisted-report",
        "A separate city underpass has standing water.",
        language=NLPLanguage.ENGLISH,
    )
    suggestion = TextPrediction(
        status=PredictionStatus.AVAILABLE,
        model_version="nlp-classifier-v2-development",
        feature_version="nlp-features-v2",
        preprocessing_version="nlp-text-normalization-v1",
        label="RIVER_BREACH",
        probabilities={"RIVER_BREACH": 0.8, "URBAN_FLOOD": 0.2},
        confidence=0.8,
    )
    assisted_output: list[str] = []
    assisted_responses = iter(
        ["UF", "en", "Human sees urban drainage, not a river breach.", "0.9"]
    )
    assisted = run_nlp_annotation_cli(
        [assisted_report],
        NLPAnnotationStore(phase15_workspace / "assisted.jsonl"),
        annotator_id="human-b",
        blind_annotation=False,
        prediction_provider=lambda _: suggestion,
        input_fn=lambda _: next(assisted_responses),
        output_fn=assisted_output.append,
        now_fn=lambda: FIXED_TIME,
    )[0]

    assert assisted.label is NLPEventLabel.URBAN_FLOOD
    assert assisted.model_suggestion is not None
    assert assisted.model_suggestion.label is NLPEventLabel.RIVER_BREACH
    assert assisted.model_assistance == "NON_GROUND_TRUTH"
    assert assisted.assistance_shown is True
    assert MODEL_SUGGESTION_BANNER in "\n".join(assisted_output)


def test_disagreement_remains_uncertain_until_explicit_adjudication(
    phase15_workspace,
    protected_index,
):
    report = _report("disagreement", "Water followed a damaged river embankment.")
    first = _annotation(
        report,
        "annotator-a",
        label=NLPEventLabel.RIVER_BREACH,
        annotation_id="disagreement-a",
        protected_index=protected_index,
    )
    second = _annotation(
        report,
        "annotator-b",
        label=NLPEventLabel.URBAN_FLOOD,
        annotation_id="disagreement-b",
        protected_index=protected_index,
    )
    case = build_nlp_adjudication_case([first, second])

    assert case.disagreement is True
    assert case.effective_state is NLPAnnotationState.UNCERTAIN
    assert case.effective_label is None
    responses = iter(["RB", "The embankment failure is the decisive evidence."])
    decisions = run_nlp_adjudication_cli(
        [first, second],
        NLPAdjudicationStore(phase15_workspace / "adjudications.jsonl"),
        adjudicator_id="adjudicator-a",
        input_fn=lambda _: next(responses),
        output_fn=lambda _: None,
        now_fn=lambda: FIXED_TIME,
    )
    assert decisions[0].final_label is NLPEventLabel.RIVER_BREACH
    assert decisions[0].final_state is NLPAnnotationState.LABELED


def test_quality_reports_language_counts_disagreement_and_data_unavailable(
    protected_index,
):
    first_report = _report("quality-1", "A local report about damaged river wall.")
    second_report = _report("quality-2", "शहर की नाली से सड़क पर पानी आया।")
    first_annotations = [
        _annotation(
            first_report,
            "a",
            label=NLPEventLabel.RIVER_BREACH,
            annotation_id="q1-a",
            protected_index=protected_index,
        ),
        _annotation(
            first_report,
            "b",
            label=NLPEventLabel.URBAN_FLOOD,
            annotation_id="q1-b",
            protected_index=protected_index,
        ),
    ]
    second_annotations = [
        _annotation(
            second_report,
            "a",
            label=NLPEventLabel.URBAN_FLOOD,
            language=NLPLanguage.HINDI,
            annotation_id="q2-a",
            protected_index=protected_index,
        ),
        _annotation(
            second_report,
            "b",
            label=NLPEventLabel.URBAN_FLOOD,
            language=NLPLanguage.HINDI,
            annotation_id="q2-b",
            protected_index=protected_index,
        ),
    ]
    unavailable = validate_nlp_annotation_quality(
        first_annotations,
        [first_report],
        minimum_repeated_reports=2,
        generated_at=FIXED_TIME,
    )
    assert unavailable.agreement_status == "DATA_UNAVAILABLE"
    assert unavailable.agreement_rate is None

    decision = _decision(
        first_annotations,
        label=NLPEventLabel.RIVER_BREACH,
        suffix="quality-1",
    )
    quality = validate_nlp_annotation_quality(
        [*first_annotations, *second_annotations],
        [first_report, second_report],
        adjudications=[decision],
        minimum_repeated_reports=2,
        generated_at=FIXED_TIME,
    )
    assert quality.valid is True
    assert quality.report_count == 2
    assert quality.annotation_count == 4
    assert quality.annotator_count == 2
    assert quality.agreement_status == "DATA_AVAILABLE"
    assert quality.agreement_rate == 0.5
    assert quality.disagreement_count == 1
    assert quality.adjudication_count == 1
    assert quality.language_counts[NLPLanguage.ENGLISH.value] == 2
    assert quality.language_counts[NLPLanguage.HINDI.value] == 2


def test_uncertain_state_requires_no_label_and_is_excluded_only_by_decision(
    protected_index,
):
    report = _report("uncertain", "The wording is too vague to identify an event.")
    annotation = _annotation(
        report,
        "annotator-a",
        label=None,
        state=NLPAnnotationState.UNCERTAIN,
        annotation_id="uncertain-a",
        protected_index=protected_index,
    )
    decision = _decision(
        [annotation],
        label=None,
        state=NLPAnnotationState.UNCERTAIN,
        suffix="uncertain",
    )
    result = resolve_nlp_adjudications(
        [report],
        [annotation],
        [decision],
        protected_index=protected_index,
    )
    assert result.records == ()
    assert result.excluded_uncertain_report_ids == ("uncertain",)
    invalid_payload = annotation.model_dump(mode="json")
    invalid_payload["label"] = NLPEventLabel.NOT_RELEVANT.value
    with pytest.raises(ValidationError, match="UNCERTAIN"):
        NLPHumanAnnotation.model_validate(invalid_payload)


def test_sampling_is_deterministic_and_never_generates_labels(protected_index):
    reports = [
        _report("sample-1", "Urban water report one.", language=NLPLanguage.ENGLISH),
        _report("sample-2", "असंबंधित स्थानीय सूचना।", language=NLPLanguage.HINDI),
        _report("sample-3", "Pata nahi kya hua.", language=NLPLanguage.HINGLISH),
        _report("sample-4", "Cyclone water report four.", language=NLPLanguage.ENGLISH),
    ]
    suggestion = TextPrediction(
        status=PredictionStatus.AVAILABLE,
        model_version="nlp-classifier-v2-development",
        label="RIVER_BREACH",
        probabilities={"RIVER_BREACH": 1.0},
        confidence=1.0,
    )
    assisted_view = build_nlp_annotation_view(
        reports[0],
        suggestion,
        blind_annotation=False,
    )
    annotations = [
        _annotation(
            reports[0],
            "a",
            label=NLPEventLabel.URBAN_FLOOD,
            annotation_id="s1-a",
            view=assisted_view,
            protected_index=protected_index,
        ),
        _annotation(
            reports[0],
            "b",
            label=NLPEventLabel.RIVER_BREACH,
            annotation_id="s1-b",
            protected_index=protected_index,
        ),
        _annotation(
            reports[1],
            "a",
            label=NLPEventLabel.NOT_RELEVANT,
            language=NLPLanguage.HINDI,
            annotation_id="s2-a",
            protected_index=protected_index,
        ),
        _annotation(
            reports[2],
            "a",
            label=None,
            state=NLPAnnotationState.UNCERTAIN,
            language=NLPLanguage.HINGLISH,
            annotation_id="s3-a",
            protected_index=protected_index,
        ),
        _annotation(
            reports[3],
            "a",
            label=NLPEventLabel.CYCLONE_INUNDATION,
            annotation_id="s4-a",
            protected_index=protected_index,
        ),
    ]
    first = sample_nlp_review_queue(
        reports,
        annotations,
        strategy=NLPSamplingStrategy.RANDOM,
        count=3,
        seed=73,
    )
    second = sample_nlp_review_queue(
        reports,
        annotations,
        strategy=NLPSamplingStrategy.RANDOM,
        count=3,
        seed=73,
    )
    assert first == second
    assert first.label_generation == "NONE"
    assert first.population_distribution_unchanged is True
    expectations = {
        NLPSamplingStrategy.DISAGREEMENT_REVIEW: "sample-1",
        NLPSamplingStrategy.UNCERTAINTY_REVIEW: "sample-3",
        NLPSamplingStrategy.NOT_RELEVANT_REVIEW: "sample-2",
        NLPSamplingStrategy.HINDI_REVIEW: "sample-2",
        NLPSamplingStrategy.HINGLISH_REVIEW: "sample-3",
    }
    for strategy, report_id in expectations.items():
        queue = sample_nlp_review_queue(
            reports,
            annotations,
            strategy=strategy,
            count=4,
            seed=73,
        )
        assert report_id in queue.report_ids
        assert queue.label_generation == "NONE"
    for strategy in (
        NLPSamplingStrategy.CLASS_BALANCED,
        NLPSamplingStrategy.LANGUAGE_BALANCED,
    ):
        queue = sample_nlp_review_queue(
            reports,
            annotations,
            strategy=strategy,
            count=4,
            seed=73,
        )
        assert queue.report_ids
    confusion = sample_nlp_review_queue(
        reports,
        annotations,
        strategy=NLPSamplingStrategy.CONFUSION_PAIR_REVIEW,
        count=4,
        seed=73,
        confusion_pair=(NLPEventLabel.URBAN_FLOOD, NLPEventLabel.RIVER_BREACH),
    )
    assert confusion.report_ids == ["sample-1"]


def test_connected_grouping_and_leakage_are_fail_closed(protected_index):
    reports = [
        _report("group-1", "First connected report.", event_id="event-a"),
        _report(
            "group-2",
            "Second connected report.",
            event_id="event-a",
            incident_id="incident-b",
        ),
        _report("group-3", "Third connected report.", incident_id="incident-b"),
        _report("group-4", "Ungrouped report with no identifiers.", source_dataset_id=None),
    ]
    annotations = [
        _annotation(
            report,
            "a",
            label=NLPEventLabel.URBAN_FLOOD,
            annotation_id=f"annotation-{report.report_id}",
            protected_index=protected_index,
        )
        for report in reports
    ]
    decisions = [
        _decision(
            [annotation],
            label=NLPEventLabel.URBAN_FLOOD,
            suffix=annotation.report_id,
        )
        for annotation in annotations
    ]
    grouping = group_nlp_records(
        resolve_nlp_adjudications(
            reports,
            annotations,
            decisions,
            protected_index=protected_index,
        ).records
    )
    grouped_ids = {item.report_id: item.group_id for item in grouping.records}
    assert grouped_ids["group-1"] == grouped_ids["group-2"] == grouped_ids["group-3"]
    assert grouped_ids["group-4"] is None
    assert grouping.status == "PARTIAL"
    plan = build_nlp_grouping_plan(grouping)
    assert plan.automatic_split_assignment == "NONE"
    assert all(entry.split is None for entry in plan.entries)

    shared_key = next(
        item.split_assignment_key
        for item in grouping.records
        if item.report_id == "group-1"
    )
    assignments = {
        shared_key: "train",
        "ungrouped-report:group-4": "validation",
    }
    rows = materialize_nlp_dataset_records(
        grouping,
        split_assignments_by_group=assignments,
    )
    report = validate_nlp_dataset_leakage(
        rows,
        protected_index=protected_index,
        generated_at=FIXED_TIME,
    )
    assert report.overall_status == "INSUFFICIENT_EVIDENCE"
    assert report.missing_group_report_ids == ("group-4",)

    leaked = [
        rows[0].model_copy(update={"split": NLPDatasetSplit.TRAIN}),
        rows[1].model_copy(update={"split": NLPDatasetSplit.TEST}),
    ]
    leakage = validate_nlp_dataset_leakage(
        leaked,
        protected_index=protected_index,
        generated_at=FIXED_TIME,
    )
    assert leakage.overall_status == "FAIL"
    assert leakage.group_ids_across_splits


def test_future_test_split_requires_independent_named_source(protected_index):
    report = _report(
        "future-test",
        "An independently collected future report.",
        event_id="future-event",
        source_dataset_id="independent-real-test-v1",
    )
    annotation = _annotation(
        report,
        "a",
        label=NLPEventLabel.NOT_RELEVANT,
        annotation_id="future-test-a",
        protected_index=protected_index,
    )
    grouping = group_nlp_records(
        resolve_nlp_adjudications(
            [report],
            [annotation],
            [_decision([annotation], label=NLPEventLabel.NOT_RELEVANT, suffix="future")],
            protected_index=protected_index,
        ).records
    )
    key = grouping.records[0].split_assignment_key
    with pytest.raises(ValueError, match="independent source dataset"):
        materialize_nlp_dataset_records(
            grouping,
            split_assignments_by_group={key: "test"},
        )
    rows = materialize_nlp_dataset_records(
        grouping,
        split_assignments_by_group={key: "test"},
        independent_test_dataset_ids=["independent-real-test-v1"],
    )
    assert rows[0].split is NLPDatasetSplit.TEST


def test_dataset_version_is_immutable_registered_and_explicitly_approved(
    phase15_workspace,
    protected_index,
):
    reports, annotations, decisions, assignments = _release_inputs(protected_index)
    registry_path = _empty_registry(phase15_workspace)
    release = release_nlp_annotation_dataset(
        reports,
        annotations,
        decisions,
        dataset_id="phase15-human-nlp",
        dataset_version="v1",
        output_directory=phase15_workspace / "released",
        registry_path=registry_path,
        split_assignments_by_group=assignments,
        independent_test_dataset_ids=["phase15-independent-real-test-v1"],
        provenance=DatasetProvenance.USER_SUPPLIED,
        source_description="Locally supplied reports with explicit human adjudication.",
        license_or_usage_note="Authorized for local INDRA development review.",
        creation_timestamp=FIXED_TIME,
    )

    assert release.manifest.dataset_id == "phase15-human-nlp"
    assert release.manifest.dataset_version == "v1"
    assert release.manifest.content_hash == hashlib.sha256(
        release.dataset_path.read_bytes()
    ).hexdigest()
    assert release.manifest.annotation_schema_version == "nlp-human-annotation-v1"
    assert release.manifest.guide_version == "nlp-annotation-guide-v1"
    assert release.manifest.annotator_count == 2
    assert release.manifest.label_counts["URBAN_FLOOD"] == 4
    assert release.manifest.language_counts["hi"] == 4
    assert release.manifest.grouping_status == "COMPLETE"
    assert release.manifest.automatic_label_generation == "NONE"
    assert release.manifest.leakage_status == "PASS"
    registered = find_dataset(
        load_dataset_registry(registry_path),
        "phase15-human-nlp",
        "v1",
    )
    assert registered.status is DatasetStatus.DISCOVERED
    assert registered.human_adjudicated is True
    assert registered.label_source == HUMAN_LABEL_SOURCE
    assert registered.schema_version == NLP_DATASET_SCHEMA_VERSION

    validation = validate_registered_dataset(
        "phase15-human-nlp",
        registry_path=registry_path,
        dataset_version="v1",
        generated_at=FIXED_TIME,
    )
    assert validation.valid is True
    assert validation.leakage.overall_status is CheckStatus.PASS
    assert validation.approval_blockers == {
        "TRAINING": [],
        "VALIDATION": [],
        "TEST": [],
    }
    approved = approve_dataset(
        "phase15-human-nlp",
        DatasetUse.TRAINING,
        approver_id="independent-dataset-reviewer",
        approval_note="Explicit approval of the grouped human-adjudicated training split.",
        registry_path=registry_path,
        dataset_version="v1",
        approved_at=FIXED_TIME,
    )
    assert approved.status is DatasetStatus.APPROVED_TRAINING

    with pytest.raises(FileExistsError, match="immutable"):
        release_nlp_annotation_dataset(
            reports,
            annotations,
            decisions,
            dataset_id="phase15-human-nlp",
            dataset_version="v1",
            output_directory=phase15_workspace / "released",
            registry_path=registry_path,
            split_assignments_by_group=assignments,
            independent_test_dataset_ids=["phase15-independent-real-test-v1"],
            provenance=DatasetProvenance.USER_SUPPLIED,
            source_description="Locally supplied reports.",
            license_or_usage_note="Local use.",
            creation_timestamp=FIXED_TIME,
        )


def test_nlp_approval_gate_rejects_nonhuman_and_generated_label_sources(
    phase15_workspace,
    protected_index,
):
    reports, annotations, decisions, assignments = _release_inputs(protected_index)
    registry_path = _empty_registry(phase15_workspace)
    release = release_nlp_annotation_dataset(
        reports,
        annotations,
        decisions,
        dataset_id="phase15-gate-check",
        dataset_version="v1",
        output_directory=phase15_workspace / "gate-release",
        registry_path=registry_path,
        split_assignments_by_group=assignments,
        independent_test_dataset_ids=["phase15-independent-real-test-v1"],
        provenance=DatasetProvenance.USER_SUPPLIED,
        source_description="Human-reviewed local source.",
        license_or_usage_note="Local test use.",
        creation_timestamp=FIXED_TIME,
    )
    unsafe = release.registry_record.model_copy(
        update={
            "human_adjudicated": False,
            "label_source": "MODEL_GENERATED_RULE_LABELS",
        }
    )
    validation = validate_dataset_record(
        unsafe,
        registry_path=registry_path,
        generated_at=FIXED_TIME,
    )
    assert "HUMAN_ADJUDICATION_REQUIRED" in validation.approval_blockers["TRAINING"]
    assert (
        "MODEL_GENERATED_LABELS_PROHIBITED"
        in validation.approval_blockers["TRAINING"]
    )
    with pytest.raises(DatasetApprovalError):
        approve_dataset(
            "phase15-gate-check",
            DatasetUse.TRAINING,
            approver_id="reviewer",
            approval_note="Cannot approve before validation and explicit review.",
            registry_path=registry_path,
            dataset_version="v1",
        )


@pytest.mark.parametrize(
    ("evidence_name", "expected_error"),
    (
        ("manifest", "MANIFEST_HASH_MISMATCH"),
        ("leakage", "LEAKAGE_REPORT_HASH_MISMATCH"),
    ),
)
def test_approval_rechecks_phase15_evidence_hashes(
    phase15_workspace,
    protected_index,
    evidence_name,
    expected_error,
):
    reports, annotations, decisions, assignments = _release_inputs(protected_index)
    registry_path = _empty_registry(phase15_workspace)
    release = release_nlp_annotation_dataset(
        reports,
        annotations,
        decisions,
        dataset_id=f"phase15-{evidence_name}-binding",
        dataset_version="v1",
        output_directory=phase15_workspace / "evidence-release",
        registry_path=registry_path,
        split_assignments_by_group=assignments,
        independent_test_dataset_ids=["phase15-independent-real-test-v1"],
        provenance=DatasetProvenance.USER_SUPPLIED,
        source_description="Human-reviewed local source.",
        license_or_usage_note="Local test use.",
        creation_timestamp=FIXED_TIME,
    )
    report = validate_registered_dataset(
        release.registry_record.dataset_id,
        registry_path=registry_path,
        dataset_version="v1",
        generated_at=FIXED_TIME,
    )
    assert report.valid is True
    evidence_path = (
        release.manifest_path
        if evidence_name == "manifest"
        else release.leakage_report_path
    )
    evidence_path.write_text(
        evidence_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(DatasetApprovalError, match=expected_error):
        approve_dataset(
            release.registry_record.dataset_id,
            DatasetUse.TRAINING,
            approver_id="reviewer",
            approval_note="Tampered evidence must fail closed.",
            registry_path=registry_path,
            dataset_version="v1",
            approved_at=FIXED_TIME,
        )


def test_sealed_final_test_and_frozen_artifacts_cannot_be_annotation_targets(
    phase15_workspace,
):
    before = assert_protected_nlp_assets_immutable()
    records = load_csv(PROTECTED_REPORTS_PATH)
    protected_record = next(item for item in records if item.split is DatasetSplit.TEST)
    protected_report = _report(
        "must-not-enter-phase15",
        protected_record.text,
        source_dataset_id="forbidden-copy",
    )

    with pytest.raises(ValueError, match="sealed final test"):
        _annotation(
            protected_report,
            "annotator",
            label=NLPEventLabel.URBAN_FLOOD,
            annotation_id="forbidden-annotation",
        )
    with pytest.raises(ValueError, match="protected NLP file"):
        NLPAnnotationStore(PROTECTED_REPORTS_PATH)

    direct_annotation = NLPHumanAnnotation(
        annotation_id="direct-protected-annotation",
        report_id=protected_report.report_id,
        text_hash=exact_text_sha256(protected_report.text),
        text=protected_report.text,
        state=NLPAnnotationState.LABELED,
        label=NLPEventLabel.URBAN_FLOOD,
        annotator_id="annotator",
        annotation_timestamp=FIXED_TIME,
        reason="This direct construction must still be blocked at append.",
        confidence=0.5,
        language=NLPLanguage.ENGLISH,
    )
    store = NLPAnnotationStore(phase15_workspace / "protected-attempt.jsonl")
    with pytest.raises(ValueError, match="sealed final test"):
        store.append(direct_annotation)
    assert not store.path.exists()

    dataset_row = NLPDatasetRecord(
        record_id="protected-dataset-row",
        text=protected_record.text,
        text_hash=exact_text_sha256(protected_record.text),
        event_type=NLPEventLabel.URBAN_FLOOD,
        language=NLPLanguage.ENGLISH,
        split=NLPDatasetSplit.TRAIN,
        group_id="protected-group",
        annotation_ids=("a",),
        annotator_ids=("human",),
        adjudication_id="d",
        adjudicator_id="adjudicator",
        adjudication_timestamp=FIXED_TIME,
        adjudication_reason="Protection test only.",
    )
    leakage = validate_nlp_dataset_leakage(
        [dataset_row],
        protected_index=before,
        generated_at=FIXED_TIME,
    )
    assert leakage.overall_status == "FAIL"
    assert leakage.protected_final_test_overlap == ("protected-dataset-row",)

    after = assert_protected_nlp_assets_immutable()
    assert after.source_dataset_sha256 == before.source_dataset_sha256
    assert after.final_test_sha256 == before.final_test_sha256
    assert after.source_order_sha256 == before.source_order_sha256
    assert hashlib.sha256(PROTECTED_V1_ARTIFACT_PATH.read_bytes()).hexdigest() == (
        "a12387cdfc753e92656f840ae7f22c35fac6d4d2179994b2b9c3ddc594789ba4"
    )
    assert hashlib.sha256(PROTECTED_V2_ARTIFACT_PATH.read_bytes()).hexdigest() == (
        "ec827431e59116b534c01aba5359410c1a241e8b5c98534339c0ef0d126c560b"
    )


def test_model_assistance_requires_explicit_opt_in(phase15_workspace):
    report = _report("opt-in", "A new local report with no model display by default.")
    with pytest.raises(ValueError, match="explicit local prediction provider"):
        run_nlp_annotation_cli(
            [report],
            NLPAnnotationStore(phase15_workspace / "opt-in.jsonl"),
            annotator_id="human",
            blind_annotation=False,
        )
    view = build_nlp_annotation_view(report)
    rendered = format_nlp_report_for_review(report, view)
    assert "BLIND_ANNOTATION = TRUE" in rendered
    assert MODEL_SUGGESTION_BANNER not in rendered
