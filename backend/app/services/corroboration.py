"""
INDRA Platform — Effective independent reporters (Phase 3 T8 part B, T9)

The Report Density factor used to count reports, so five reports from one
phone were five witnesses, and every report's credibility score was computed at
ingest and read by nothing. It now counts **effective independent reporters**:

    n_eff = Σ over distinct reporters r  of  min(1, max credibility of r's reports / 0.60)

* **0.60 is the citizen baseline** (fusion_engine.SOURCE_RELIABILITY), so a
  clean, specific citizen report counts about 1, and a report the flags marked
  down counts less: a promotional one about 0.2 of a witness.
* **One reporter counts once**, however many reports they send, and at most 1.
* **Forecasts and warnings are excluded** (`not_an_observation`): context, not
  witnesses.
* **Who is a reporter:**
  - a citizen or official report: its `reporter_hash` (the HMAC of the device's
    random id, Phase 1);
  - **a news item: its publisher** (T9). A headline has no reporter id, and ten
    outlets carrying one IMD story are not ten witnesses; Hindi copies are only
    caught by dedup when near-verbatim (BUG-085). So each publisher is one
    reporter, at most 1 per cluster;
  - no id at all: **the report is its own reporter.** Independence cannot be
    proven, but neither can collusion; the receipt counts these as unverified.

**Phase 5** adds two rules:

* **One file, one witness** (T3, `duplicate_media`): reporters whose reports
  carry the same photo or video (the same SHA-256) are counted together, once.
  A WhatsApp forward sent in by five people is one sighting, not five.
* **A bot counts at most 0.5** (T7, `bot_account`): a bot re-posting news is
  not a witness. A group of reporters sharing a file counts as its best
  member, so a citizen who took the photo still counts in full.

`density_basis` in the receipt shows the arithmetic:

    {"reports": 5, "distinct_reporters": 4, "n_eff": 3.62, "excluded": 1,
     "unverified_reporters": 2, "publishers": 1, "baseline": 0.6,
     "merged_by_shared_media": 1, "bot_reporters": 0}
"""

from typing import Any, Dict, Mapping, Sequence, Tuple

CITIZEN_BASELINE = 0.60
BOT_MAX_WITNESS = 0.5


def reporter_key(report: Mapping[str, Any]) -> Tuple[str, str]:
    """(kind, key): who a report counts as. See the module docstring."""
    source = str(report.get("source_type") or "")
    if source == "NEWS_MEDIA":
        publisher = (report.get("publisher") or "").strip().lower()
        if publisher:
            return ("publisher", publisher)
    if report.get("reporter_hash"):
        return ("reporter", str(report["reporter_hash"]))
    return ("unverified", str(report.get("id")))


def _witness_weight(credibility: float, bot: bool) -> float:
    """What one reporter's best report is worth: min(1, c / 0.60), and at most 0.5 for a bot."""
    weight = min(1.0, credibility / CITIZEN_BASELINE)
    return min(BOT_MAX_WITNESS, weight) if bot else weight


def effective_reporters(reports: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """{"n_eff": float, "basis": {...}} for a cluster's reports."""
    best: Dict[Tuple[str, str], float] = {}
    bots: set = set()
    shared_owner: Dict[str, Tuple[str, str]] = {}
    parent: Dict[Tuple[str, str], Tuple[str, str]] = {}

    def root(key: Tuple[str, str]) -> Tuple[str, str]:
        while parent.get(key, key) != key:
            key = parent[key]
        return key

    excluded = counted = 0
    for report in reports:
        if report.get("duplicate_of") is not None:
            continue
        if "not_an_observation" in (report.get("flags") or []):
            excluded += 1
            continue
        counted += 1
        key = reporter_key(report)
        flags = report.get("flags") or []
        weight = _witness_weight(float(report.get("credibility") or 0.0), "bot_account" in flags)
        if "bot_account" in flags:
            bots.add(key)
        best[key] = max(best.get(key, 0.0), weight)
        parent.setdefault(key, key)
        # One file, one witness (T3): join this reporter with whoever sent the
        # same file first.
        for sha in report.get("media_sha256") or []:
            if not sha:
                continue
            if sha in shared_owner:
                a, b = root(key), root(shared_owner[sha])
                if a != b:
                    parent[a] = b
            else:
                shared_owner[sha] = key

    groups: Dict[Tuple[str, str], float] = {}
    for key, weight in best.items():
        r = root(key)
        groups[r] = max(groups.get(r, 0.0), weight)

    n_eff = round(sum(groups.values()), 4)
    return {
        "n_eff": n_eff,
        "basis": {
            "reports": counted,
            "distinct_reporters": len(best),
            "n_eff": n_eff,
            "excluded": excluded,
            "unverified_reporters": sum(1 for kind, _ in best if kind == "unverified"),
            "publishers": sum(1 for kind, _ in best if kind == "publisher"),
            "baseline": CITIZEN_BASELINE,
            # Phase 5: reporters counted together because they sent the same
            # file (T3), and bots, whose weight is capped at 0.5 (T7).
            "merged_by_shared_media": len(best) - len(groups),
            "bot_reporters": len(bots),
            "rule": "sum over distinct reporters of min(1, best credibility / 0.60); forecasts excluded; "
                    "reporters sharing a file count once; a bot at most 0.5",
        },
    }


# ── News counts only when two independent publishers agree (Phase 4 T6) ───────
#
# At scoring time the pipeline gathers the NEWS_MEDIA items in the event's
# cluster, plus warning-tense headlines of the same hazard family, district and
# window, and this counts **distinct publisher domains**. Re-shares of one URL
# were already collapsed at dedup (Phase 2 T7). The rule, published:
#
#   2 or more independent publishers → news contributes 0.75 to Source
#                                      Reliability ("corroborated news")
#   exactly 1 publisher              → 0.55, the NEWS_MEDIA prior
#
# A forecast headline still counts here as corroborating news context: two
# outlets independently reporting an IMD warning for this district is
# evidence the hazard is being taken seriously there. It is still excluded from
# Report Density, where it is not a witness.

NEWS_SINGLE_PUBLISHER = 0.55
NEWS_CORROBORATED = 0.75


def _publisher_key(item: Mapping[str, Any]) -> str:
    domain = (item.get("publisher_domain") or "").strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain or (item.get("publisher") or "").strip().lower()


def news_corroboration(items: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    {"score", "count", "publishers", "line", "rule"} for the news items behind
    an event; score None when there is no news at all. Each item carries
    `publisher_domain` and `publisher` (the display name) and, optionally,
    `forecast` and `in_cluster`.
    """
    names: Dict[str, str] = {}
    forecasts = in_cluster = 0
    for item in items:
        key = _publisher_key(item)
        if not key:
            continue
        names.setdefault(key, (item.get("publisher") or key).strip())
        forecasts += 1 if item.get("forecast") else 0
        in_cluster += 1 if item.get("in_cluster") else 0

    publishers = sorted(names.values(), key=str.lower)
    count = len(publishers)
    if count == 0:
        score, line = None, "no news coverage"
    elif count == 1:
        score, line = NEWS_SINGLE_PUBLISHER, f"reported by 1 publisher: {publishers[0]}"
    else:
        score = NEWS_CORROBORATED
        line = f"reported by {count} independent publishers: {', '.join(publishers)}"
    return {
        "score": score,
        "count": count,
        "publishers": publishers,
        "items": len(items),
        "forecast_items": forecasts,
        "items_in_cluster": in_cluster,
        "line": line,
        "rule": "distinct publisher domains; 2 or more → 0.75, 1 → 0.55; forecasts count as news context",
    }
