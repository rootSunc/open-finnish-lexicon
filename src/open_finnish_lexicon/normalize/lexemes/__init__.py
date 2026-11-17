"""Lexeme normalization, merge, alignment, and reconciliation."""

from open_finnish_lexicon.normalize.lexemes.align import align_surface_forms_to_sense_lexemes
from open_finnish_lexicon.normalize.lexemes.dedupe import normalize_lexemes
from open_finnish_lexicon.normalize.lexemes.merge import (
    _cleanup_relation_duplicates,
    _merge_lexeme_into,
)
from open_finnish_lexicon.normalize.lexemes.prune import prune_empty_lexemes
from open_finnish_lexicon.normalize.lexemes.reconcile import reconcile_lexemes
from open_finnish_lexicon.normalize.lexemes.types import (
    LEXEME_DELETE_BATCH_SIZE,
    ReconcileStats,
    normalize_part_of_speech,
)

__all__ = [
    "LEXEME_DELETE_BATCH_SIZE",
    "ReconcileStats",
    "_cleanup_relation_duplicates",
    "_merge_lexeme_into",
    "align_surface_forms_to_sense_lexemes",
    "normalize_lexemes",
    "normalize_part_of_speech",
    "prune_empty_lexemes",
    "reconcile_lexemes",
]
