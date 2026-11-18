"""CLI command handlers for normalize."""

from __future__ import annotations

from open_finnish_lexicon.cli.parsers import OflArgumentParser
from open_finnish_lexicon.normalize.lexemes import (
    normalize_lexemes,
    prune_empty_lexemes,
    reconcile_lexemes,
)


def dispatch(argv: list[str]) -> int | None:
    if not argv:
        return None
    cmd = argv[0]

    if cmd == "normalize-lexemes":
        OflArgumentParser(
            prog="ofl normalize-lexemes",
            description="Merge duplicate lexemes sharing normalized lemma and part of speech.",
        ).parse_args(argv[1:])
        normalize_lexemes()
        return 0

    if cmd == "reconcile-lexemes":
        OflArgumentParser(
            prog="ofl reconcile-lexemes",
            description="Normalize duplicates, align surface forms, and prune empty shells.",
        ).parse_args(argv[1:])
        stats = reconcile_lexemes()
        print(
            "reconcile lexemes: "
            f"normalized_merges={stats.normalized_merge_count} "
            f"surface_form_alignments={stats.surface_form_alignment_count} "
            f"pruned_or_merged_shells={stats.pruned_or_merged_shell_count} "
            f"passes={stats.pass_count}"
        )
        return 0

    if cmd == "prune-empty-lexemes":
        OflArgumentParser(
            prog="ofl prune-empty-lexemes",
            description="Merge or drop lexemes that carry no senses.",
        ).parse_args(argv[1:])
        prune_empty_lexemes()
        return 0

    return None
