"""Phase 20R governance checks; these never invoke the protected evaluation."""

from __future__ import annotations

import json

from app.ml.config import file_sha256
from app.ml.evaluation.phase20r_event import (
    ARTIFACT_PATH,
    DATA_ROOT,
    MANIFEST_PATH,
    RECEIPT_PATH,
)


def test_preregistered_families_and_files_remain_sealed():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["status"] == "FROZEN_CONFIGURATION_TEST_NOT_ACCESSED"
    assert manifest["family_disjointness"]["pass"] is True
    assert all(
        value == 0
        for key, value in manifest["family_disjointness"].items()
        if key.endswith("_cross_split")
    )
    assert manifest["batches_per_split"] == {"train": 48, "validation": 48, "test": 48}
    assert manifest["generator_regeneration_byte_equal"] is True
    assert manifest["frozen_event_artifact_sha256"] == file_sha256(ARTIFACT_PATH)
    for name, expected in manifest["file_hashes"].items():
        assert file_sha256(DATA_ROOT / name) == expected


def test_hidden_generator_metadata_is_absent_from_detector_records():
    forbidden = {
        "canonical_event_id", "incident_id", "template_family_id",
        "parameter_family_id", "scenario_family", "split",
    }
    for split in ("train", "validation", "test"):
        with (DATA_ROOT / f"detector_inputs_{split}.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                batch = json.loads(line)
                assert set(batch) == {"batch_id", "inputs"}
                assert all(not forbidden.intersection(record) for record in batch["inputs"])


def test_one_shot_receipt_records_no_production_claim():
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    assert receipt["manifest_sha256"] == file_sha256(MANIFEST_PATH)
    assert receipt["status"] == "REVALIDATED"
    assert receipt["evaluation_invocation_count"] == 1
    assert receipt["rerun_permitted"] is False
    assert receipt["test_used_for_tuning"] is False
    assert receipt["configuration_frozen_before_test"] is True
    assert receipt["production_validation"] == "NOT_VALIDATED"
    assert all(receipt["gate_results"].values())
