"""CLI argument parsers."""

from open_finnish_lexicon.cli.parsers.ingest import _parse_stale_build_run_args
from open_finnish_lexicon.cli.parsers.quality import _parse_example_morphology_args, _parse_zh_gloss_sanitize_args

__all__ = [
    "_parse_example_morphology_args",
    "_parse_stale_build_run_args",
    "_parse_zh_gloss_sanitize_args",
]
