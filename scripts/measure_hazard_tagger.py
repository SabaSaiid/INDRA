#!/usr/bin/env python3
"""
Measure the hazard tagger and publish the numbers (Phase 3 T3).

    backend/.venv/bin/python scripts/measure_hazard_tagger.py
    backend/.venv/bin/python scripts/measure_hazard_tagger.py --check   # exit 1 if the gate fails

Scores `app/services/hazard_tagger.py` (through `extract_metadata`, exactly as
ingest calls it) and writes `backend/app/services/hazard_tagger_metrics.json`:

* **The fixture** `backend/tests/fixtures/hazards_v1.csv`, per split: per-hazard
  precision, recall and F1 over the multi-label hazard sets; macro-F1 over the
  15 hazards; the share of negatives tagged as an observation; the primary
  hazard's accuracy; tense accuracy on the forecast and past rows; a breakdown
  by language.
* **The gate, set before measuring**, on the held-out `test` split only:
  precision ≥ 0.85 and recall ≥ 0.80 for each of the PS's seven categories,
  macro-F1 ≥ 0.80 across all 15, and at most 10% of negatives tagged. If a
  category misses, tune on `dev` and re-measure; never lower the gate.
* **The real posts** `backend/tests/fixtures/hazards_real_v1.csv`, once they
  are labelled by hand (`sample_real_posts.py` draws them). Published whatever
  they are: they are the honest figure, not a gate. A row the labeller could
  not place is skipped and counted.

**Deterministic.** No timestamps, sorted keys, fixed rounding, and the year the
past-tense rule compares against is pinned (REFERENCE_YEAR), so the same code
and fixtures give a byte-identical file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.hazards import by_precedence  # noqa: E402
from app.services.text_processing import extract_metadata  # noqa: E402

FIXTURE = REPO_ROOT / "backend" / "tests" / "fixtures" / "hazards_v1.csv"
REAL = REPO_ROOT / "backend" / "tests" / "fixtures" / "hazards_real_v1.csv"
REAL_V2 = REPO_ROOT / "backend" / "tests" / "fixtures" / "hazards_real_v2.csv"
# v1 was read to find BUG-108 … BUG-112 and the rules were then fixed, so its
# re-measurement is no longer independent. Its first measurement, before the
# fix, is kept in git (31ea810): micro-F1 0.8339. v2 is the one to quote.
REAL_V1_NOTE = (
    "read on 27 Sep to find BUG-108 … BUG-112, and the rules were fixed after; this re-measurement is "
    "therefore not independent. Its measurement before the fix (commit 31ea810) was micro-F1 0.8339, "
    "English 0.8977, Hindi 0.729. Quote real_posts_v2."
)
OUT = REPO_ROOT / "backend" / "app" / "services" / "hazard_tagger_metrics.json"

# The year "2019 floods" is compared against. Pinned so the metrics file does
# not change on 1 January.
REFERENCE_YEAR = 2026

HAZARDS = [
    "URBAN_FLOOD", "RIVER_BREACH", "CLOUDBURST", "LANDSLIDE", "CYCLONE_INUNDATION", "RAINFALL",
    "THUNDERSTORM", "LIGHTNING", "HAILSTORM", "DUST_STORM", "STRONG_WIND", "CYCLONE", "HEATWAVE",
    "COLD_WAVE", "FOG",
]
# ¶3 of the PS: rainfall, thunderstorms, flooding, heatwaves, fog, dust storms, strong winds.
PS_SEVEN = ["RAINFALL", "THUNDERSTORM", "URBAN_FLOOD", "HEATWAVE", "FOG", "DUST_STORM", "STRONG_WIND"]
GATE = {"precision": 0.85, "recall": 0.80, "macro_f1": 0.80, "negatives_tagged_max": 0.10}


def _r(x: float) -> float:
    return round(x, 4)


def _labels(cell: str) -> List[str]:
    return sorted({h.strip() for h in (cell or "").split(";") if h.strip()})


def _predict(text: str) -> Dict:
    meta = extract_metadata(text, reference_year=REFERENCE_YEAR)
    return {
        "hazards": sorted(h["type"] for h in meta["hazards"]),
        "primary": meta["hazard_primary"],
        "tense": meta["tense"] or "",
    }


def _prf(tp: int, fp: int, fn: int) -> Dict[str, Optional[float]]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else (0.0 if tp + fp + fn else None)
    )
    return {
        "precision": _r(precision) if precision is not None else None,
        "recall": _r(recall) if recall is not None else None,
        "f1": _r(f1) if f1 is not None else None,
        "support": tp + fn,
        "tp": tp, "fp": fp, "fn": fn,
    }


def score(rows: Sequence[Dict]) -> Dict:
    """Metrics for labelled rows, each {text, hazards, tense, group?, lang?}."""
    counts = {h: Counter() for h in HAZARDS}
    by_lang: Dict[str, Counter] = defaultdict(Counter)
    primary_ok = primary_n = 0
    tense_ok = tense_n = 0
    negatives = negatives_tagged = 0
    errors = []

    for row in rows:
        gold = set(row["hazards"])
        pred = _predict(row["text"])
        got = set(pred["hazards"])
        for h in HAZARDS:
            if h in gold and h in got:
                counts[h]["tp"] += 1
            elif h in got:
                counts[h]["fp"] += 1
            elif h in gold:
                counts[h]["fn"] += 1
        lang = row.get("lang") or "unknown"
        by_lang[lang]["tp"] += len(gold & got)
        by_lang[lang]["fp"] += len(got - gold)
        by_lang[lang]["fn"] += len(gold - got)

        is_negative = (row.get("group") or "").startswith("NEG_") or (not gold) or bool(row["tense"])
        if is_negative:
            negatives += 1
            # Tagged = the tagger says a hazard is being observed here.
            if got and not pred["tense"]:
                negatives_tagged += 1
        elif gold:
            primary_n += 1
            want = by_precedence(gold)[0]
            primary_ok += int(pred["primary"] == want)
        if row["tense"]:
            tense_n += 1
            tense_ok += int(pred["tense"] == row["tense"])
        if got != gold or (row["tense"] and pred["tense"] != row["tense"]):
            errors.append(row["id"])

    per_hazard = {h: _prf(c["tp"], c["fp"], c["fn"]) for h, c in counts.items()}
    f1s = [m["f1"] for m in per_hazard.values() if m["f1"] is not None and m["support"]]
    micro = _prf(*(sum(c[k] for c in counts.values()) for k in ("tp", "fp", "fn")))
    return {
        "rows": len(rows),
        "per_hazard": per_hazard,
        "macro_f1": _r(sum(f1s) / len(f1s)) if f1s else None,
        "macro_f1_over": len(f1s),
        "micro": micro,
        "primary_accuracy": _r(primary_ok / primary_n) if primary_n else None,
        "primary_rows": primary_n,
        "negatives": negatives,
        "negatives_tagged": negatives_tagged,
        "negatives_tagged_share": _r(negatives_tagged / negatives) if negatives else None,
        "tense_accuracy": _r(tense_ok / tense_n) if tense_n else None,
        "tense_rows": tense_n,
        "by_language": {
            lang: _prf(c["tp"], c["fp"], c["fn"]) for lang, c in sorted(by_lang.items())
        },
        "rows_wrong": sorted(errors),
    }


def gate(test: Dict) -> Dict:
    checks = {}
    for h in PS_SEVEN:
        m = test["per_hazard"][h]
        checks[h] = {
            "precision": m["precision"],
            "recall": m["recall"],
            "pass": (m["precision"] or 0) >= GATE["precision"] and (m["recall"] or 0) >= GATE["recall"],
        }
    macro_ok = (test["macro_f1"] or 0) >= GATE["macro_f1"]
    neg_ok = (test["negatives_tagged_share"] or 0) <= GATE["negatives_tagged_max"]
    return {
        "thresholds": GATE,
        "ps_seven": checks,
        "macro_f1": {"value": test["macro_f1"], "pass": macro_ok},
        "negatives_tagged": {"value": test["negatives_tagged_share"], "pass": neg_ok},
        "pass": all(c["pass"] for c in checks.values()) and macro_ok and neg_ok,
    }


def _read(path: Path) -> List[Dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_rows(rows: Iterable[Dict], split: str) -> List[Dict]:
    return [
        {"id": r["id"], "text": r["text"], "hazards": _labels(r["hazards"]), "tense": r["tense"],
         "group": r["group"], "lang": r["lang"]}
        for r in rows if r["split"] == split
    ]


def _real_section(path: Path, note: Optional[str] = None) -> Dict:
    if not path.exists():
        return {"status": "not drawn yet", "note": "run scripts/sample_real_posts.py on the server, then label it"}
    raw = _read(path)
    labelled = [r for r in raw if r["hazards"].strip() or r["tense"].strip() or r["notes"].strip()]
    if not labelled:
        return {"status": "drawn, not labelled yet", "rows": len(raw), "file_sha256": _sha256(path)}
    skipped = [r["id"] for r in labelled if r["hazards"].strip().lower() == "skip"]
    rows = [
        {"id": r["id"], "text": r["text"],
         "hazards": [] if r["hazards"].strip().lower() == "none" else _labels(r["hazards"]),
         "tense": r["tense"], "group": "", "lang": "hi" if r["language"].startswith("hi") else "en"}
        for r in labelled if r["id"] not in skipped
    ]
    result = score(rows)
    result.update({
        "status": "labelled",
        "claim": "measured on real #IMD and weather posts and headlines collected from 24 Sep 2026",
        # Who labelled the rows (hazards_real_v1.md). Quote the figure with it.
        "labelled_by": "Claude, 27 Sep 2026, at Aditya's request; not a person (see hazards_real_v1.md)",
        "file_sha256": _sha256(path),
        "rows_drawn": len(raw),
        "rows_skipped": len(skipped),
        "file": str(path.relative_to(REPO_ROOT)),
        "by_stratum": dict(sorted(Counter(r["stratum"] for r in labelled).items())),
    })
    if note:
        result["independent"] = False
        result["note"] = note
    return result


def build() -> Dict:
    fixture = _read(FIXTURE)
    dev = score(_fixture_rows(fixture, "dev"))
    test = score(_fixture_rows(fixture, "test"))
    return {
        "tagger": "app/services/hazard_tagger.py (rules and dictionaries; no model)",
        "reference_year": REFERENCE_YEAR,
        "fixture": {
            "file": "backend/tests/fixtures/hazards_v1.csv",
            "file_sha256": _sha256(FIXTURE),
            "caveat": (
                "written by the same person and session as the rules, just before them; the split was "
                "frozen first. A check across three languages and the named traps, not an independent "
                "accuracy estimate. Quote the real-post figure."
            ),
            "dev": dev,
            "test": test,
        },
        "gate_on_test": gate(test),
        "real_posts": _real_section(REAL, REAL_V1_NOTE),
        "real_posts_v2": _real_section(REAL_V2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if the gate fails on the test split")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    metrics = build()
    args.out.write_text(json.dumps(metrics, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    gate_result = metrics["gate_on_test"]
    print(f"wrote {args.out}")
    for h, c in gate_result["ps_seven"].items():
        print(f"  {h:<13} P={c['precision']} R={c['recall']} {'pass' if c['pass'] else 'MISS'}")
    print(f"  macro-F1 {gate_result['macro_f1']['value']}  negatives tagged {gate_result['negatives_tagged']['value']}")
    v2 = metrics["real_posts_v2"]
    print(f"  gate: {'PASS' if gate_result['pass'] else 'FAIL'}; real posts v2: {v2['status']}"
          + (f", micro-F1 {v2['micro']['f1']}" if v2.get("status") == "labelled" else ""))
    return 1 if args.check and not gate_result["pass"] else 0


if __name__ == "__main__":
    sys.exit(main())
