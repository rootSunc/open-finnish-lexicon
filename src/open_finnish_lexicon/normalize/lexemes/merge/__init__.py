"""Lexeme merge helpers."""

from open_finnish_lexicon.normalize.lexemes.merge.batch import _delete_lexeme_ids_in_batches
from open_finnish_lexicon.normalize.lexemes.merge.bulk import _merge_no_sense_lexemes_bulk
from open_finnish_lexicon.normalize.lexemes.merge.lexeme import _merge_lexeme_into
from open_finnish_lexicon.normalize.lexemes.merge.refs import _cleanup_relation_duplicates

__all__ = [
    "_cleanup_relation_duplicates",
    "_delete_lexeme_ids_in_batches",
    "_merge_lexeme_into",
    "_merge_no_sense_lexemes_bulk",
]
