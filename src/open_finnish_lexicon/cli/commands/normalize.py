"""CLI command handlers for normalize."""

from __future__ import annotations

from open_finnish_lexicon.normalize.lexemes import (
    normalize_lexemes,
    prune_empty_lexemes,
    reconcile_lexemes,
)


def dispatch(argv: list[str]) -> int | None:
    if len(argv) == 1 and argv[0] == "normalize-lexemes":
        normalize_lexemes()
        return 0
    if len(argv) == 1 and argv[0] == "reconcile-lexemes":
        stats = reconcile_lexemes()
        print(
            "reconcile lexemes: "
            f"normalized_merges={stats.normalized_merge_count} "
            f"surface_form_alignments={stats.surface_form_alignment_count} "
            f"pruned_or_merged_shells={stats.pruned_or_merged_shell_count} "
            f"passes={stats.pass_count}"
        )
        return 0
    if len(argv) == 1 and argv[0] == "prune-empty-lexemes":
        prune_empty_lexemes()
        return 0
    return None
