"""One-shot, family-disjoint synthetic revalidation of the frozen Phase 20 grouper.

This is a new benchmark, not a rerun or amendment of the Phase 20 test. The
detector receives only SyntheticDetectorInput records; generator identity and
canonical-event labels live in separate ground-truth files.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.ml.config import file_sha256
from app.ml.contracts import DuplicatePrediction, PredictionStatus, TextPrediction
from app.ml.data.synthetic_event.generator import (
    SyntheticDetectorInput,
    SyntheticEventGroundTruth,
)
from app.ml.training.event_validation import (
    ARTIFACT_ROOT,
    EventBatch,
    calculate_grouping_metrics,
    load_event_development_artifact,
    predict_batches,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = PROJECT_ROOT / "data" / "labelled" / "events" / "phase20r_v1"
MANIFEST_PATH = ARTIFACT_ROOT / "event_grouping_phase20r_v1.manifest.json"
RECEIPT_PATH = ARTIFACT_ROOT / "event_grouping_phase20r_v1.final_test_receipt.json"
ARTIFACT_PATH = ARTIFACT_ROOT / "event_grouping_v1.json"
SCENARIOS = (
    "COMPACT",
    "SPATIAL_TWO",
    "TEMPORAL_TWO",
    "TYPE_TWO",
    "DUPLICATE",
    "BRIDGE_TWO",
    "SINGLE",
    "MISSING_NLP",
)
EVENT_TYPES = ("URBAN_FLOOD", "RIVER_BREACH", "CLOUDBURST", "CYCLONE_INUNDATION")
NLP_TYPES = (*EVENT_TYPES, "NOT_RELEVANT")
GATES = {
    "minimum_event_matching_f1": 0.85,
    "minimum_event_level_f1": 0.70,
    "maximum_false_merge_rate": 0.10,
    "require_detector_parity": True,
    "require_no_confirmed_events": True,
}


@dataclass(frozen=True)
class Family:
    template_id: str
    parameter_id: str
    shape: tuple[tuple[float, float], ...]
    scale_km: float
    minute_step: int
    spatial_separation_km: float
    temporal_separation_min: int


# Shapes and parameter ranges are deliberately different across splits, not
# merely relabelled copies of one plan. Scenario *semantics* repeat, while the
# concrete geometry and timing templates do not.
FAMILIES: dict[str, tuple[Family, ...]] = {
    "train": (
        Family("tr-axial", "tr-tight-fast", ((-1, 0), (-.5, 0), (0, 0), (.5, 0), (1, 0), (0, .4)), .20, 4, 8.0, 230),
        Family("tr-crescent", "tr-narrow-fast", ((-1, 0), (-.7, .5), (-.2, .8), (.4, .7), (.9, .3), (1, -.2)), .28, 6, 8.4, 240),
        Family("tr-cross", "tr-wide-fast", ((0, -1), (-.8, 0), (0, 0), (.8, 0), (0, 1), (.4, .5)), .36, 8, 8.8, 250),
    ),
    "validation": (
        Family("va-triangle", "va-mid-stepped", ((0, 1), (-.8, -.5), (.8, -.5), (-.4, .2), (.4, .2), (0, -.2)), .48, 11, 9.2, 265),
        Family("va-chevron", "va-broad-stepped", ((-1, -.6), (-.5, 0), (0, .6), (.5, 0), (1, -.6), (0, -.2)), .58, 13, 9.6, 275),
        Family("va-columns", "va-offset-stepped", ((-.8, -1), (-.8, 0), (-.8, 1), (.7, -.6), (.7, .4), (.7, 1)), .68, 15, 10.0, 285),
    ),
    "test": (
        Family("te-diamond", "te-large-slow", ((0, 1), (1, 0), (0, -1), (-1, 0), (.3, .3), (-.3, -.3)), .80, 18, 10.6, 310),
        Family("te-spiral", "te-larger-slow", ((0, 0), (.3, .3), (.7, .2), (.5, -.6), (-.4, -.8), (-1, .2)), .92, 20, 11.0, 325),
        Family("te-asymmetric-l", "te-largest-slow", ((-1, -1), (-1, 0), (-1, 1), (-.2, -1), (.6, -1), (1, -.7)), 1.04, 22, 11.4, 340),
    ),
}


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _uuid(value: str):
    return uuid5(NAMESPACE_URL, "indra-phase20r-v1/" + value)


def _base(split: str, ordinal: int) -> tuple[float, float, datetime]:
    bases = {
        "train": (20.295, 85.824, datetime(2026, 1, 1, tzinfo=timezone.utc)),
        "validation": (23.259, 77.412, datetime(2026, 3, 1, tzinfo=timezone.utc)),
        "test": (18.520, 73.856, datetime(2026, 5, 1, tzinfo=timezone.utc)),
    }
    lat, lon, origin = bases[split]
    return lat + (ordinal % 5) * .02, lon + (ordinal % 7) * .02, origin + timedelta(hours=12 * ordinal)


def _prediction(label: str | None) -> TextPrediction:
    if label is None:
        return TextPrediction(status=PredictionStatus.NOT_IMPLEMENTED, reason_codes=["CONTROLLED_NLP_MISSING"])
    return TextPrediction(
        status=PredictionStatus.AVAILABLE,
        label=label,
        probabilities={item: (.88 if item == label else .03) for item in NLP_TYPES},
        confidence=.88,
        model_version="phase20r-controlled-fixture-not-frozen-nlp",
        evidence=["CONTROLLED_SYNTHETIC_NLP_NOT_PRODUCTION_INFERENCE"],
    )


def _batch(split: str, family: Family, family_index: int, scenario: str, repetition: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ordinal = family_index * len(SCENARIOS) * 2 + SCENARIOS.index(scenario) * 2 + repetition
    batch_id = "batch-" + _digest(f"{split}|{family.template_id}|{scenario}|{repetition}".encode())[:20]
    lat0, lon0, start = _base(split, ordinal)
    two = scenario in {"SPATIAL_TWO", "TEMPORAL_TWO", "TYPE_TWO", "BRIDGE_TWO"}
    count = 8 if two else (1 if scenario == "SINGLE" else 6)
    label_a = EVENT_TYPES[(ordinal + family_index) % len(EVENT_TYPES)]
    label_b = EVENT_TYPES[(ordinal + family_index + 1) % len(EVENT_TYPES)] if scenario == "TYPE_TWO" else label_a
    report_ids = [_uuid(f"report/{batch_id}/{index}") for index in range(count)]
    canonical_ids = [f"event-{_uuid(f'event/{batch_id}/{event_index}')}" for event_index in range(2 if two else 1)]
    truth_rows: list[dict[str, Any]] = []
    input_rows: list[dict[str, Any]] = []
    for index in range(count):
        event_index = int(two and index >= 4)
        local_index = index % 4 if two else index
        east, north = family.shape[local_index]
        east *= family.scale_km
        north *= family.scale_km
        minute = local_index * family.minute_step
        if event_index and scenario == "SPATIAL_TWO":
            east += family.spatial_separation_km
        if event_index and scenario == "TEMPORAL_TWO":
            minute += family.temporal_separation_min
        if scenario == "BRIDGE_TWO":
            east = (-2.8 + local_index * .22) if not event_index else (2.5 + local_index * .22)
            north = .12 * (local_index % 2)
        if scenario == "DUPLICATE" and index == 1:
            east, north, minute = (family.shape[0][0] * family.scale_km, family.shape[0][1] * family.scale_km, 0)
        latitude = lat0 + north / 111.2
        longitude = lon0 + east / (111.2 * .94)
        occurred_at = start + timedelta(minutes=minute)
        label = label_b if event_index else label_a
        source = ("CITIZEN", "NGO", "WARD_OFFICE")[index % 3]
        if scenario == "DUPLICATE" and index == 1:
            source = "CITIZEN"
        text = f"Local water incident observed near a city landmark; report {str(report_ids[index])[:8]}."
        truth = SyntheticEventGroundTruth(
            canonical_event_id=canonical_ids[event_index],
            event_type=label,
            report_id=report_ids[index],
            incident_id=f"incident-{_uuid(f'incident/{batch_id}/{event_index}')}",
            timestamp=occurred_at,
            latitude=latitude,
            longitude=longitude,
            source_family=source,
            duplicate_family=(f"duplicate-{batch_id}" if scenario == "DUPLICATE" and index in {0, 1} else None),
            duplicate_of_report_id=(report_ids[0] if scenario == "DUPLICATE" and index == 1 else None),
            language="en",
            report_text=text,
            split=split,
            batch_id=batch_id,
            scenario_family=scenario,
            noise_profile=("MISSING_NLP" if scenario == "MISSING_NLP" and index in {0, 5} else "CLEAN"),
            report_ordinal=index,
        )
        duplicate = scenario == "DUPLICATE" and index == 1
        detector_input = SyntheticDetectorInput(
            report_id=report_ids[index],
            report_text=text,
            language="en",
            occurred_at=occurred_at,
            latitude=latitude,
            longitude=longitude,
            source_type=source,
            text_prediction=_prediction(None if scenario == "MISSING_NLP" and index in {0, 5} else label),
            duplicate_prediction=DuplicatePrediction(
                status=PredictionStatus.AVAILABLE if duplicate else PredictionStatus.NOT_APPLICABLE,
                is_duplicate=duplicate,
                matched_report_id=report_ids[0] if duplicate else None,
                similarity=.99 if duplicate else None,
                method="PROJECT_GENERATED_RELATION" if duplicate else "NO_PROJECT_GENERATED_RELATION",
            ),
        )
        truth_rows.append(truth.model_dump(mode="json"))
        input_rows.append(detector_input.model_dump(mode="json"))
    meta = {
        "batch_id": batch_id,
        "split": split,
        "scenario_family": scenario,
        "template_family_id": family.template_id,
        "parameter_family_id": family.parameter_id,
        "report_ids": [str(item) for item in report_ids],
        "canonical_event_ids": canonical_ids,
    }
    return ({**meta, "truth": truth_rows}, {"batch_id": batch_id, "inputs": input_rows}, meta)


def _generate() -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    files: dict[str, bytes] = {}
    index: list[dict[str, Any]] = []
    forbidden = {"canonical_event_id", "incident_id", "template_family_id", "parameter_family_id", "scenario_family", "split"}
    for split, families in FAMILIES.items():
        truth_lines: list[bytes] = []
        input_lines: list[bytes] = []
        for family_index, family in enumerate(families):
            for scenario in SCENARIOS:
                for repetition in range(2):
                    truth, detector_input, meta = _batch(split, family, family_index, scenario, repetition)
                    if any(forbidden.intersection(row) for row in detector_input["inputs"]):
                        raise AssertionError("generator metadata reached detector inputs")
                    truth_lines.append(_json_bytes(truth))
                    input_lines.append(_json_bytes(detector_input))
                    index.append(meta)
        files[f"ground_truth_{split}.jsonl"] = b"".join(truth_lines)
        files[f"detector_inputs_{split}.jsonl"] = b"".join(input_lines)
    files["family_index.json"] = _json_bytes(index)
    return files, index


def _leakage_audit(index: list[dict[str, Any]]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for field in ("template_family_id", "parameter_family_id", "batch_id"):
        sets = {split: {row[field] for row in index if row["split"] == split} for split in FAMILIES}
        checks[f"{field}_cross_split"] = sum(len(sets[left] & sets[right]) for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")))
        checks[f"{field}_sets"] = {split: sorted(values) for split, values in sets.items()}
    for field in ("report_ids", "canonical_event_ids"):
        sets = {split: {value for row in index if row["split"] == split for value in row[field]} for split in FAMILIES}
        checks[f"{field}_cross_split"] = sum(len(sets[left] & sets[right]) for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")))
    if any(value for key, value in checks.items() if key.endswith("_cross_split")):
        raise AssertionError("Phase 20R family or identity leakage")
    checks["pass"] = True
    return checks


def _load(split: str, files: dict[str, bytes] | None = None) -> list[EventBatch]:
    if files is None:
        truth_text = (DATA_ROOT / f"ground_truth_{split}.jsonl").read_text(encoding="utf-8")
        input_text = (DATA_ROOT / f"detector_inputs_{split}.jsonl").read_text(encoding="utf-8")
    else:
        truth_text = files[f"ground_truth_{split}.jsonl"].decode("utf-8")
        input_text = files[f"detector_inputs_{split}.jsonl"].decode("utf-8")
    truth_lines = truth_text.splitlines()
    input_lines = input_text.splitlines()
    if len(truth_lines) != len(input_lines):
        raise AssertionError("ground truth and detector batch counts differ")
    batches = []
    for truth_line, input_line in zip(truth_lines, input_lines, strict=True):
        truth = json.loads(truth_line)
        detector = json.loads(input_line)
        if truth["batch_id"] != detector["batch_id"]:
            raise AssertionError("batch IDs differ")
        truth_rows = tuple(SyntheticEventGroundTruth.model_validate(row) for row in truth["truth"])
        input_rows = tuple(SyntheticDetectorInput.model_validate(row) for row in detector["inputs"])
        if {row.report_id for row in truth_rows} != {row.report_id for row in input_rows}:
            raise AssertionError("batch report IDs differ")
        batches.append(EventBatch(split, truth["batch_id"], truth["scenario_family"], truth_rows, input_rows))
    return batches


def _evaluate(split: str, config, files: dict[str, bytes] | None = None) -> dict[str, Any]:
    batches = _load(split, files)
    predictions = predict_batches(batches, config, actual_detector=True)
    parity = predict_batches(batches, config, actual_detector=False)
    mismatches = [batch.batch_id for batch in batches if set(predictions[batch.batch_id].clusters) != set(parity[batch.batch_id].clusters)]
    confirmed = sum(candidate.status.value == "CONFIRMED" for result in predictions.values() for candidate in result.candidates)
    metrics = calculate_grouping_metrics(batches, {key: value.clusters for key, value in predictions.items()})
    by_scenario = {
        scenario: calculate_grouping_metrics(
            selected := [batch for batch in batches if batch.scenario_family == scenario],
            {batch.batch_id: predictions[batch.batch_id].clusters for batch in selected},
        )
        for scenario in SCENARIOS
    }
    return {"split": split, "metrics": metrics, "by_scenario": by_scenario, "detector_parity_mismatches": mismatches, "confirmed_count": confirmed}


def prepare() -> dict[str, Any]:
    """Pre-register the unchanged configuration and seal an unseen test split."""
    if DATA_ROOT.exists() or MANIFEST_PATH.exists() or RECEIPT_PATH.exists():
        raise RuntimeError("Phase 20R preparation is one-time; existing evidence must not be overwritten")
    artifact, config = load_event_development_artifact()
    files, index = _generate()
    regenerated, _ = _generate()
    if files != regenerated:
        raise AssertionError("Phase 20R generation is not byte-reproducible")
    audit = _leakage_audit(index)
    development = {split: _evaluate(split, config, files) for split in ("train", "validation")}
    manifest = {
        "schema_version": "phase20r-family-disjoint-synthetic-v1",
        "status": "FROZEN_CONFIGURATION_TEST_NOT_ACCESSED",
        "provenance": "PROJECT_AUTHORED_SYNTHETIC",
        "production_validation": "NOT_VALIDATED",
        "generator_source_sha256": file_sha256(Path(__file__)),
        "frozen_event_artifact_sha256": file_sha256(ARTIFACT_PATH),
        "frozen_event_artifact_hash": artifact.artifact_hash,
        "frozen_configuration": config.model_dump(mode="json"),
        "file_hashes": {name: _digest(content) for name, content in files.items()},
        "family_disjointness": audit,
        "family_specifications": {split: [asdict(family) for family in families] for split, families in FAMILIES.items()},
        "scenarios": SCENARIOS,
        "batches_per_split": {split: sum(row["split"] == split for row in index) for split in FAMILIES},
        "generator_regeneration_byte_equal": True,
        "detector_input_generator_metadata_excluded": True,
        "controlled_text_predictions_not_frozen_nlp": True,
        "selection_split": "validation",
        "test_ground_truth_accessed_for_selection": False,
        "test_evaluation_invocation_count": 0,
        "acceptance_gates_predeclared": GATES,
        "development_metrics": development,
    }
    DATA_ROOT.mkdir(parents=True)
    for name, content in files.items():
        with (DATA_ROOT / name).open("xb") as stream:
            stream.write(content)
    with MANIFEST_PATH.open("xb") as stream:
        stream.write(_json_bytes(manifest))
    return manifest


def evaluate_test_once() -> dict[str, Any]:
    """Claim the protected test before reading its labels, then lock the result."""
    if RECEIPT_PATH.exists():
        raise RuntimeError("Phase 20R protected test is one-shot; receipt already exists")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest["status"] != "FROZEN_CONFIGURATION_TEST_NOT_ACCESSED":
        raise RuntimeError("Phase 20R is not preregistered")
    if file_sha256(Path(__file__)) != manifest["generator_source_sha256"]:
        raise RuntimeError("Phase 20R code changed after preregistration")
    if file_sha256(ARTIFACT_PATH) != manifest["frozen_event_artifact_sha256"]:
        raise RuntimeError("frozen event artifact changed")
    for name, expected in manifest["file_hashes"].items():
        if file_sha256(DATA_ROOT / name) != expected:
            raise RuntimeError(f"Phase 20R dataset changed: {name}")
    _, config = load_event_development_artifact()
    if config.model_dump(mode="json") != manifest["frozen_configuration"]:
        raise RuntimeError("event configuration changed after preregistration")
    claim = {
        "schema_version": "phase20r-one-shot-receipt-v1",
        "status": "FINAL_EVALUATION_IN_PROGRESS",
        "evaluation_invocation_count": 1,
        "rerun_permitted": False,
        "manifest_sha256": file_sha256(MANIFEST_PATH),
        "frozen_event_artifact_sha256": manifest["frozen_event_artifact_sha256"],
        "test_ground_truth_sha256": manifest["file_hashes"]["ground_truth_test.jsonl"],
    }
    with RECEIPT_PATH.open("x", encoding="utf-8") as stream:
        json.dump(claim, stream, sort_keys=True)
        stream.write("\n")
    try:
        result = _evaluate("test", config)
        metrics = result["metrics"]
        gates = manifest["acceptance_gates_predeclared"]
        gate_results = {
            "event_matching_f1": metrics["event_matching_f1"] >= gates["minimum_event_matching_f1"],
            "event_level_f1": metrics["event_level_f1"] >= gates["minimum_event_level_f1"],
            "false_merge_rate": metrics["false_merge_rate"] <= gates["maximum_false_merge_rate"],
            "detector_parity": not result["detector_parity_mismatches"],
            "no_confirmed_events": result["confirmed_count"] == 0,
        }
        receipt = {
            **claim,
            "status": "REVALIDATED" if all(gate_results.values()) else "REVALIDATION_FAILED",
            "test_used_for_tuning": False,
            "configuration_frozen_before_test": True,
            "family_disjointness": manifest["family_disjointness"],
            "test_result": result,
            "gate_results": gate_results,
            "production_validation": "NOT_VALIDATED",
        }
    except Exception as error:
        receipt = {**claim, "status": "REVALIDATION_FAILED_LOCKED", "error_type": type(error).__name__, "error": str(error)}
        RECEIPT_PATH.write_bytes(_json_bytes(receipt))
        raise
    RECEIPT_PATH.write_bytes(_json_bytes(receipt))
    return receipt
