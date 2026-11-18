"""Stem normalisation, vowel harmony, and consonant gradation."""

from __future__ import annotations

import unicodedata

from open_finnish_lexicon.morphology.rules.types import ALL_VOWELS, BACK_VOWELS, FRONT_VOWELS

def _normalise(value: str | None) -> str:
    if value is None:
        return ""
    # Kaikki mixes straight and typographic apostrophes in otherwise
    # identical lemmas/forms (for example ``rei'ite``/``rei’ite``). Keep the
    # comparison orthographic rather than treating typography as a lexical
    # mismatch.
    normalised = unicodedata.normalize("NFC", value).strip().lower()
    return normalised.translate(
        str.maketrans(
            {
                "\u2018": "'",
                "\u2019": "'",
                "\u02bc": "'",
                "\uff07": "'",
            }
        )
    )


def _harmony(stem: str) -> str:
    """Return ``"back"`` or ``"front"`` from the rightmost harmonic vowel.

    Neutral vowels (``e``, ``i``) never decide harmony. Finnish words that
    contain only neutral vowels default to front harmony.
    """

    for char in reversed(stem):
        if char in BACK_VOWELS:
            return "back"
        if char in FRONT_VOWELS:
            return "front"
    return "front"


def _suffix_with_harmony(stem: str, back_suffix: str, front_suffix: str) -> str:
    return back_suffix if _harmony(stem) == "back" else front_suffix


def _is_vowel(char: str) -> bool:
    return char in ALL_VOWELS


GRADATION_STRONG_TO_WEAK = (
    ("kk", "k"),
    ("pp", "p"),
    ("tt", "t"),
    # Productive gradation is mostly native vocabulary, but Finnish also
    # applies the geminate-stop pattern to established loanwords such as
    # ``fobba`` -> ``foban`` and ``vedda`` -> ``vedan``.
    ("bb", "b"),
    ("dd", "d"),
    ("nk", "ng"),
    ("mp", "mm"),
    ("nt", "nn"),
    ("lt", "ll"),
    ("rt", "rr"),
    ("ht", "hd"),
    # Labial stops also weaken after a preceding liquid: ``turpa ->
    # turvan``, ``halpa -> halvan``, ``kylpy -> kylvyn``.
    ("lp", "lv"),
    ("rp", "rv"),
    # Stop-deletion patterns: ``jalka -> jalan``, ``sarka -> saran``,
    # ``nälkä -> nälän``. The ``k`` disappears entirely in the weak grade
    # after ``l``/``r``/``h``.
    ("lk", "l"),
    ("rk", "r"),
    ("hk", "h"),
)

GRADATION_AMBIGUOUS = frozenset({"p", "t", "k"})


class _AmbiguousGradation(Exception):
    """Raised when single-consonant gradation could fire ambiguously.

    Single ``p``/``t``/``k`` between vowels can grade to ``v``/``d``/``""``
    in some lemmas but stays unchanged in others (loanwords, names, irregular
    paradigms like ``poika`` -> ``pojan``). When that happens we refuse to
    guess; the orchestrator demotes the row to ``UNCERTAIN`` instead.
    """


def _apply_weak_grade(stem: str) -> str:
    """Apply a single consonant gradation step (strong -> weak) on ``stem``.

    Returns the weak-grade stem when a deterministic geminate rule
    matches (``kk`` -> ``k``, ``pp`` -> ``p`` etc.). Returns the unchanged
    stem when no consonant in the final cluster is subject to gradation.
    Raises :class:`_AmbiguousGradation` when a single ``p``/``t``/``k``
    sits between vowels: the result is too lexeme-specific to predict
    without a curated table.
    """

    if len(stem) < 3:
        return stem
    last_vowel_index = -1
    for index in range(len(stem) - 1, -1, -1):
        if _is_vowel(stem[index]):
            last_vowel_index = index
            break
    if last_vowel_index <= 0:
        return stem

    cluster_end = last_vowel_index
    cluster_start = cluster_end
    while cluster_start > 0 and not _is_vowel(stem[cluster_start - 1]):
        cluster_start -= 1
    if cluster_start == cluster_end:
        return stem
    cluster = stem[cluster_start:cluster_end]
    if cluster_start == 0:
        return stem

    for strong, weak in GRADATION_STRONG_TO_WEAK:
        if cluster.endswith(strong):
            new_cluster = cluster[: -len(strong)] + weak
            return stem[:cluster_start] + new_cluster + stem[cluster_end:]
    if len(cluster) == 1 and cluster in GRADATION_AMBIGUOUS:
        raise _AmbiguousGradation(cluster)
    return stem

