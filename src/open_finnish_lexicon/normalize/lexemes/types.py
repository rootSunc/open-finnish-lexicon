from __future__ import annotations

from dataclasses import dataclass

LEXEME_DELETE_BATCH_SIZE = 250

POS_ALIASES: dict[str, str] = {
    "adjective": "adj",
    "adverb": "adv",
    "conjunction": "conj",
    "cconj": "conj",
    "sconj": "conj",
    "determiner": "det",
    "interjection": "intj",
    "noun": "noun",
    "numeral": "num",
    "postposition": "postp",
    "preposition": "prep",
    "pronoun": "pron",
    "propernoun": "name",
    "proper_noun": "name",
    "proper noun": "name",
    "propn": "name",
    "verb": "verb",
}


@dataclass(frozen=True)
class ReconcileStats:
    normalized_merge_count: int
    surface_form_alignment_count: int
    pruned_or_merged_shell_count: int
    pass_count: int


def normalize_part_of_speech(value: str) -> str:
    folded = value.strip().casefold()
    return POS_ALIASES.get(folded, folded)
