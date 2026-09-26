"""Synthetic, test-only golden regression scenarios and benchmark helpers."""

from app.ml.golden.benchmark import (
    LocalPerformanceBenchmark,
    run_local_performance_benchmark,
)
from app.ml.golden.runner import (
    execute_golden_scenario,
    validate_golden_scenario,
)
from app.ml.golden.schema import (
    GOLDEN_SCENARIO_PATH,
    GoldenScenario,
    GoldenScenarioSuite,
    load_golden_scenarios,
)

__all__ = [
    "GOLDEN_SCENARIO_PATH",
    "GoldenScenario",
    "GoldenScenarioSuite",
    "LocalPerformanceBenchmark",
    "execute_golden_scenario",
    "load_golden_scenarios",
    "run_local_performance_benchmark",
    "validate_golden_scenario",
]
