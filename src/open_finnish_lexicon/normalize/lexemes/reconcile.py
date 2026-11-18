from open_finnish_lexicon.db import connect
from open_finnish_lexicon.normalize.lexemes.align import align_surface_forms_to_sense_lexemes
from open_finnish_lexicon.normalize.lexemes.dedupe import normalize_lexemes
from open_finnish_lexicon.normalize.lexemes.prune import prune_empty_lexemes
from open_finnish_lexicon.normalize.lexemes.types import ReconcileStats


def reconcile_lexemes(max_passes: int = 12) -> ReconcileStats:
    from open_finnish_lexicon.sources.kaikki_bulk import refresh_lexeme_is_lemma_flags

    normalized_merge_count = 0
    surface_form_alignment_count = 0
    pruned_or_merged_shell_count = 0
    pass_count = 0

    for current_pass in range(1, max_passes + 1):
        pass_count = current_pass
        normalized_merges = normalize_lexemes()
        surface_alignments = align_surface_forms_to_sense_lexemes()
        pruned_or_merged_shells = prune_empty_lexemes()

        normalized_merge_count += normalized_merges
        surface_form_alignment_count += surface_alignments
        pruned_or_merged_shell_count += pruned_or_merged_shells

        if normalized_merges + surface_alignments + pruned_or_merged_shells == 0:
            break

    with connect() as conn:
        refresh_lexeme_is_lemma_flags(conn)
        conn.commit()

    return ReconcileStats(
        normalized_merge_count=normalized_merge_count,
        surface_form_alignment_count=surface_form_alignment_count,
        pruned_or_merged_shell_count=pruned_or_merged_shell_count,
        pass_count=pass_count,
    )
