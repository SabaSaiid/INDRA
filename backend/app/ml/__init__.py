"""INDRA machine-learning models (layer 4)."""


def validate_ml_release(*args, **kwargs):
    """Lazily run the fail-closed release gate without package import cycles."""

    from app.ml.release_gate import validate_ml_release as _validate_ml_release

    return _validate_ml_release(*args, **kwargs)


__all__ = ["validate_ml_release"]
