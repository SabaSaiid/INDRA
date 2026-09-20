#!/usr/bin/env python3
"""
Train the event-type classifier and measure it on the frozen test split.

    cd backend && .venv/bin/python ../scripts/train_event_classifier.py

Writes backend/app/ml/artifacts/event_classifier_v1.joblib and
event_classifier_v1.metrics.json, and prints the headline numbers. See
app/ml/event_classifier.py for the method and the acceptance gate.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.ml import event_classifier  # noqa: E402


def main() -> int:
    result = event_classifier.train_and_evaluate()
    event_classifier.save(result)
    m = result["metrics"]
    print(json.dumps({
        "chosen": m["selection"]["chosen"],
        "cv_macro_f1": m["selection"]["cv_macro_f1"],
        "test_accuracy": m["test"]["accuracy"],
        "test_macro_f1": m["test"]["macro_f1"],
        "accuracy_by_language": m["test"]["accuracy_by_language"],
        "gate": {k: (v["value"], v["pass"]) for k, v in m["gate"].items()},
        "accepted": m["accepted"],
    }, indent=2))
    print(f"wrote {event_classifier.ARTIFACT_PATH} and {event_classifier.METRICS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
