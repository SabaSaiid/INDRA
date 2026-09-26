"""Project-authored synthetic temporal windows for Phase 23."""

from app.ml.data.synthetic_anomaly.generator import (
    GENERATOR_VERSION,
    SCENARIO_FAMILIES,
    SyntheticAnomalyDataset,
    SyntheticAnomalyGeneratorConfig,
    SyntheticAnomalyMetadata,
    SyntheticAnomalyModelRecord,
    generate_synthetic_anomaly_dataset,
    load_hidden_metadata,
    load_model_records,
)

__all__ = [
    "GENERATOR_VERSION",
    "SCENARIO_FAMILIES",
    "SyntheticAnomalyDataset",
    "SyntheticAnomalyGeneratorConfig",
    "SyntheticAnomalyMetadata",
    "SyntheticAnomalyModelRecord",
    "generate_synthetic_anomaly_dataset",
    "load_hidden_metadata",
    "load_model_records",
]
