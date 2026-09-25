from pathlib import Path
from uuid import uuid4

from app.ml.data.duplicate_pairs import DuplicatePairLabel, DuplicatePairRecord
from app.ml.data.loaders import load_csv
from app.ml.data.validation import validate_dataset


DATASET = Path(__file__).resolve().parents[4] / "data" / "labelled" / "reports_v1.csv"


def test_existing_dataset_is_read_only_and_explicitly_validatable():
    records = load_csv(DATASET)
    report = validate_dataset(records, require_split=True)
    assert len(records) == 300
    assert report.valid


def test_validation_uses_exact_text_only_for_contamination():
    records = load_csv(DATASET)
    report = validate_dataset(records, require_split=True)
    assert report.train_test_contamination == []


def test_duplicate_pair_schema_requires_label_provenance():
    pair = DuplicatePairRecord(
        pair_id="pair-1",
        report_a_id=uuid4(),
        report_b_id=uuid4(),
        label=DuplicatePairLabel.DUPLICATE,
        annotator_id="annotator-1",
        annotation_timestamp="2026-09-21T12:00:00Z",
        annotation_reason="same incident wording and location",
        text_relationship="paraphrase",
        label_provenance="human-review-v1",
    )
    assert pair.label_provenance == "human-review-v1"
