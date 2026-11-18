"""CLI command handlers for quality."""

from __future__ import annotations

from open_finnish_lexicon.cli.parsers import (
    OflArgumentParser,
    non_empty_str,
    positive_int,
)
from open_finnish_lexicon.quality.zh_gloss_sanitize import (
    render_zh_gloss_sanitize_stats,
    sanitize_invalid_zh_glosses,
)


def dispatch(argv: list[str]) -> int | None:
    if not argv:
        return None
    cmd = argv[0]

    if cmd == "sanitize-invalid-zh-glosses":
        parser = OflArgumentParser(
            prog="ofl sanitize-invalid-zh-glosses",
            description="Count or delete invalid materialized Chinese glosses.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Delete invalid rows instead of running a dry-run count",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count invalid rows without modifying the database (default)",
        )
        ns = parser.parse_args(argv[1:])
        apply = bool(ns.apply and not ns.dry_run)
        print(render_zh_gloss_sanitize_stats(sanitize_invalid_zh_glosses(apply=apply)))
        return 0

    if cmd == "validate-example-morphology":
        parser = OflArgumentParser(
            prog="ofl validate-example-morphology",
            description="Validate Finnish example sentence tokens using Omorfi and lexicon forms.",
        )
        parser.add_argument(
            "--limit",
            type=positive_int,
            default=None,
            help="Maximum number of examples to validate",
        )
        parser.add_argument(
            "--source",
            dest="source_family",
            type=non_empty_str,
            default=None,
            help="Filter examples by source family (e.g. tatoeba, kaikki)",
        )
        parser.add_argument(
            "--revalidate",
            action="store_true",
            help="Re-check examples even if already validated under current recognizer version",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute verdicts without persisting them to PostgreSQL",
        )
        ns = parser.parse_args(argv[1:])
        # Needs the optional Omorfi extra; import lazily so the base install works.
        from open_finnish_lexicon.quality.example_morphology import (
            render_example_morphology_stats,
            validate_example_morphology,
        )

        stats = validate_example_morphology(
            limit=ns.limit,
            source_family=ns.source_family,
            revalidate=ns.revalidate,
            dry_run=ns.dry_run,
        )
        print(render_example_morphology_stats(stats))
        return 0

    return None
