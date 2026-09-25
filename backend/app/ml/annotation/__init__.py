"""Local-only human annotation interface."""

_DUPLICATE_EXPORTS = {"format_pair_for_review", "run_annotation_cli"}
_NLP_EXPORTS = {
    "format_nlp_report_for_review",
    "run_nlp_adjudication_cli",
    "run_nlp_annotation_cli",
}

__all__ = [
    "format_nlp_report_for_review",
    "format_pair_for_review",
    "run_annotation_cli",
    "run_nlp_adjudication_cli",
    "run_nlp_annotation_cli",
]


def __getattr__(name: str):
    if name in _DUPLICATE_EXPORTS:
        from app.ml.annotation import cli

        return getattr(cli, name)
    if name in _NLP_EXPORTS:
        from app.ml.annotation import nlp_cli

        return getattr(nlp_cli, name)
    raise AttributeError(name)
