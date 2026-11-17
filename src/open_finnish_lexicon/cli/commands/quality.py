"""CLI command handlers for quality."""

from __future__ import annotations

from open_finnish_lexicon.cli.parsers import _parse_example_morphology_args, _parse_zh_gloss_sanitize_args
from open_finnish_lexicon.quality.zh_gloss_sanitize import (
    render_zh_gloss_sanitize_stats,
    sanitize_invalid_zh_glosses,
)


def dispatch(argv: list[str]) -> int | None:
    if argv and argv[0] == "sanitize-invalid-zh-glosses":
        apply = _parse_zh_gloss_sanitize_args(argv)
        print(render_zh_gloss_sanitize_stats(sanitize_invalid_zh_glosses(apply=apply)))
        return 0
    if argv and argv[0] == "validate-example-morphology":
        # Needs the optional Omorfi extra; import lazily so the base install works.
        from open_finnish_lexicon.quality.example_morphology import (
            render_example_morphology_stats,
            validate_example_morphology,
        )

        limit, source_family, revalidate, dry_run = _parse_example_morphology_args(argv)
        stats = validate_example_morphology(
            limit=limit,
            source_family=source_family,
            revalidate=revalidate,
            dry_run=dry_run,
        )
        print(render_example_morphology_stats(stats))
        return 0
    return None
