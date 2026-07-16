"""Calcium network pipeline (stages 2–3: CASCADE + metrics)."""
from .config import RecordingConfig, ConfigError, load_config, ROUTE_FAMILY

__all__ = [
    "RecordingConfig", "ConfigError", "load_config", "ROUTE_FAMILY",
    "run_cascade", "run_metrics", "run",
]


def __getattr__(name):
    # Lazy re-exports so importing the package doesn't drag in numpy / TensorFlow
    # (run_cascade) until a caller actually needs a stage function.
    if name == "run_cascade":
        from .run_cascade import run_cascade
        return run_cascade
    if name == "run_metrics":
        from .run_metrics import run_metrics
        return run_metrics
    if name == "run":
        from .run_pipeline import run
        return run
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
