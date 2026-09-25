# Anomaly annotation guide

## Purpose and scope

An anomaly in INDRA is an observation or contiguous observation window that a
human reviewer can support as abnormal for the stated station, time, and
measurement context. An annotation is ground truth only after review; a high
statistical score is evidence for review, not a label.

The repository currently exposes only `rainfall_mm` (a 24-hour accumulation)
and optional `river_level_m` as approved station measurements. Do not infer or
record temperature, humidity, pressure, wind, or other values that are not in
the supplied evidence.

## Required judgment

Choose exactly one label:

- `ANOMALY`: the supplied evidence supports an abnormal observation/window.
- `NORMAL`: the supplied evidence supports ordinary or expected behavior.
- `UNCERTAIN`: available evidence cannot resolve the judgment. Never force an
  anomaly or normal label to complete a dataset.

For `ANOMALY`, select a domain and, when the evidence supports it, one anomaly
type. The type is optional; use the explicit `UNCERTAIN` type/domain rather
than guessing. Record the target ID, station, observation IDs, point/window
scope, annotator, annotation timestamp, reason, evidence, observed time span,
and any event context. Preserve each annotator's original record; resolve
disagreement through a new adjudication record in a future workflow rather
than overwriting a judgment.

## Statistical evidence is not truth

`STATISTICAL_OUTLIER_SCORE` is an absolute robust standardized deviation:

```text
abs(value - reference_median)
-----------------------------------------------
max(1.4826 * MAD, quantile_scale, measurement_floor)
```

`quantile_scale` is `(Q_upper - Q_lower) / (NormalPPF(upper) -
NormalPPF(lower))`; the default 0.25/0.75 quantiles reduce to approximately
`IQR / 1.349`.

Rate-of-change evidence is separately scaled against a configured physical
review threshold. Neither score is a probability. A statistically unusual
reading may be legitimate; a sensor problem may also produce a value that is
not statistically extreme.

## Keep the two anomaly domains separate

Use `DATA_QUALITY_ANOMALY` for evidence of invalid or unreliable data, such as
negative rainfall accumulation, a non-finite value, impossible coordinates, or
a sustained sensor gap. Do not infer a particular hardware failure without
supporting evidence.

Use `WEATHER_BEHAVIOR_ANOMALY` for plausible but unusual environmental
behavior, such as a real extreme rainfall increase or persistent river-level
deviation. A high positive rainfall value is not automatically bad data.

If an observation is clearly anomalous but the evidence cannot distinguish
sensor quality from weather behavior, use the `UNCERTAIN` anomaly domain. If
the evidence cannot establish whether it is anomalous at all, use the
`UNCERTAIN` annotation label. Do not collapse the domains.

## Supported anomaly types

- `VALUE_OUTLIER`: an individual value departs strongly from its past-only
  reference distribution.
- `RATE_OF_CHANGE`: a change per unit time exceeds the configured review
  threshold.
- `PERSISTENT_DEVIATION`: multiple consecutive values remain outside the
  past-only reference distribution; annotate as a window.
- `MISSINGNESS_PATTERN`: repeated absence forms a meaningful data-availability
  pattern; annotate as a data-quality window only when the context supports it.
- `UNCERTAIN`: use only when an anomaly type cannot be resolved.

Missing input alone is not an anomaly. Record `MISSING_INPUT`,
`SEASONALLY_UNAVAILABLE`, `SENSOR_GAP`, or `UNKNOWN` as the applicable data
state. A single absent optional measurement normally remains insufficient
evidence.

## Review procedure

1. Confirm station identity, timezone-aware timestamps, measurement units, and
   point versus window scope.
2. Review only evidence available for the observation time. Do not use later
   outcomes to relabel earlier detector inputs.
3. Compare against the documented baseline span and seasonality stratum, if
   present. Confirm that the baseline precedes the target.
4. Decide whether the evidence supports normal, anomaly, or uncertain.
5. For anomalies, independently choose domain and supported type. Explain why
   the evidence indicates data quality or weather behavior.
6. Record concrete evidence and limitations. Do not copy the detector decision
   as the annotation reason.

## Evaluation controls

Keep earlier periods in training, later periods in validation, and the latest
period in test. Thresholds may be selected on validation only and must be
frozen before test evaluation. Report station membership and overlap; use
station-disjoint evaluation when the intended claim concerns unseen stations.
Unit-test fixtures are never annotation or performance data.

No validated anomaly annotation dataset exists in Phase 9. Production metrics,
calibrated anomaly probabilities, and deployment claims are `NOT_AVAILABLE`.
