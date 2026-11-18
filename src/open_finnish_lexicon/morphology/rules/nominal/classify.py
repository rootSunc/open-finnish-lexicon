"""Nominal Kotus stem-class identification and compound harmony helpers."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.phonology import _is_vowel

_I_STEM_LONG_VOWEL_COMPONENTS = (
    "kieli",
    "mieli",
    "kuusi",
    "viisi",
    "uusi",
    "pieni",
    "suuri",
    "sieni",
    "nuori",
    "puoli",
    "tyyni",
    "kuori",
    "vuori",
)


def _is_usi_family(lemma: str) -> bool:
    """Whether an ``-usi`` lemma follows the ``kausi/susi`` template."""

    return lemma.endswith(("kausi", "susi"))


def _classify_nominal(lemma: str) -> str | None:
    """Return a short kotus identifier or ``None`` for unsupported lemmas.

    Identifiers:

    * ``vowel_short``  - kotus 1/2/3/4: single short vowel ending, no
                         gradation needed for genitive (sisu, talo, kissa,
                         valo, kala-like with stem identity).
    * ``a_stem_grad``  - kotus 9/10/11 -a/-ä ending with consonant gradation.
                         Stem identity is the lemma; gradation only kicks
                         in on the genitive-style stem.
    * ``nen``          - kotus 38 (nainen): -nen with stem nais-.
    * ``as_grad``      - kotus 41 (sisukas/vieras): -as/-äs adjectives
                         with strong-grade plural / illative stem.
    * ``e_stem``       - kotus 48 (perhe/kirje): -e ending with -ee- stem.
    * ``i_stem``       - kotus 5/6 (risti/paperi): consonant + -i ending.
    * ``us_stem``      - kotus 39 (vastaus): -us/-ys abstract nouns.
    """

    if not lemma:
        return None
    if len(lemma) < 2:
        return None
    last = lemma[-1]
    second_last = lemma[-2]

    if lemma.endswith("nen") and len(lemma) > 3:
        return "nen"
    # Kotus 40/41 abstract nouns formed off an adjective + ``-Us``:
    # ``naisuus -> naisuuden``, ``ylevyys -> ylevyyden``. They always
    # end in a long ``-uus``/``-yys`` (double vowel) and inflect with
    # the stem ``-Vude-`` / ``-Vyde-``.
    if lemma.endswith(("uus", "yys")) and len(lemma) > 3:
        return "uus_stem"
    if lemma.endswith(("us", "ys", "os", "ös")) and len(lemma) > 2 and _is_vowel(lemma[-3]):
        # kotus 39 abstract / action noun: vastaus -> vastauksen
        return "us_stem"
    if lemma.endswith(("as", "äs")) and len(lemma) > 2 and not _is_vowel(lemma[-3]):
        return "as_grad"
    if last == "e" and len(lemma) >= 3 and not _is_vowel(second_last):
        return "e_stem"
    if last == "i":
        # Kotus 5/6 words have a short vowel before the final consonant
        # (``risti``, ``hanki``). Long-vowel/diphthong families such as
        # ``saari`` and ``kausi`` need their own templates; do not force
        # them through the regular i-stem generator. Known irregular final
        # components are retained for their explicit validation variants.
        base = lemma[:-1]
        if _is_usi_family(lemma) or lemma.endswith(_I_STEM_LONG_VOWEL_COMPONENTS):
            return "i_stem"
        if base and not _is_vowel(base[-1]):
            vowel_index = next(
                (index for index in range(len(base) - 1, -1, -1) if _is_vowel(base[index])),
                -1,
            )
            if vowel_index >= 0 and (
                vowel_index == 0 or not _is_vowel(base[vowel_index - 1])
            ):
                return "i_stem"
        return None
    if last in {"a", "ä"} and not _is_vowel(second_last):
        return "a_stem_grad"
    if last in {"o", "u", "y", "ö"} and not _is_vowel(second_last):
        return "vowel_short"

    # Long vowel / diphthong / double-letter endings (maa, työ) are not
    # covered yet; defer to the LLM.
    return None


def _has_neutral_terminal_component(root: str) -> bool:
    """Detect a neutral-vowel final component in a compound root.

    The root is scanned from the right until a harmonic vowel is reached.
    At least two neutral vowels, or one neutral vowel after a consonant
    cluster, is a conservative signal for compounds such as ``aamuihmi-``,
    ``ranskankieli-``, and ``...piste-``. A single neutral suffix vowel in
    ``nai-`` therefore does not override the stem's back harmony.
    """

    neutral_vowels = 0
    terminal_consonants = 0
    for char in reversed(root):
        if char in {"e", "i"}:
            neutral_vowels += 1
            continue
        if _is_vowel(char):
            break
        if not neutral_vowels:
            terminal_consonants += 1
    return neutral_vowels >= 2 or (neutral_vowels >= 1 and terminal_consonants >= 2)
