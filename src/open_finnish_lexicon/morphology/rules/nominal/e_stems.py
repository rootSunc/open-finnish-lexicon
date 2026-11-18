"""Nominal -e / hame / nalle stem paradigms and gradation."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.nominal.classify import (
    _has_neutral_terminal_component,
)
from open_finnish_lexicon.morphology.rules.phonology import (
    _AmbiguousGradation,
    _apply_weak_grade,
    _is_vowel,
    _suffix_with_harmony,
)
from open_finnish_lexicon.morphology.rules.types import ALL_VOWELS

_E_STEM_NALLE_LEMMAS = frozenset(
    {
        # Kaikki's ``fi-decl-nalle`` loans use the lemma as the singular
        # stem: ``steve -> steven``, not ``steveen``.
        "steve",
        "college",
        "house",
        "madame",
        "pelle",
        "eve",
        "empire",
        "nalle",
        "nukke",
        "karate",
        # Omorfi also exposes the lemma-preserving loanword path for these
        # common Finnish e-final loans (``ale -> alen``, ``anime -> animen``).
        # Keep this explicit: an arbitrary ``-e`` lemma must not be silently
        # reclassified as nalle-style merely because one analyser emits a
        # competing form.
        "agaave",
        "akne",
        "ale",
        "anime",
        "beagle",
        "beige",
        "bisse",
        "bridge",
        "byte",
        "deadline",
        "drone",
        "faksimile",
        "halinalle",
        "hype",
        "inarinsaame",
        "jade",
        "kalle",
        "karaoke",
        "kurre",
        "lande",
        "lasagne",
        "latte",
        "manne",
        "mate",
        "menarke",
        "nasse",
        "nisse",
        "ope",
        "pohjoissaame",
        "polle",
        "pose",
        "psyyke",
        "saame",
        "sake",
        "single",
        "skene",
        "some",
        "tele",
        "törmänne",
    }
)


def _hame_strong_stem(lemma: str) -> str:
    """Build the strong ``-ee-`` stem of the Finnish ``hame`` template."""

    base = lemma[:-1]
    for weak, strong in (
        ("ll", "lt"),
        ("nn", "nt"),
        ("rr", "rt"),
        ("ng", "nk"),
        ("hd", "ht"),
    ):
        if base.endswith(weak):
            return base[: -len(weak)] + strong + "ee"
    if base.endswith("d"):
        return base[:-1] + "t" + "ee"
    if base.endswith("v"):
        return base[:-1] + "p" + "ee"
    if base.endswith("j"):
        return base[:-1] + "k" + "ee"
    # ``pyyhe`` is a lexical hame-template family whose strong stem is
    # ``pyyhkee-``. Ordinary ``-he`` words such as ``perhe`` and compounds
    # ending in ``-perhe`` keep ``-hee-``; broadening this branch to every
    # final ``h`` creates false ``hkee`` stems.
    if base.endswith("pyyh"):
        return base + "kee"
    if (
        len(base) >= 2
        and base[-1] in {"k", "p", "t"}
        and _is_vowel(base[-2])
        and not base.endswith(base[-1] * 2)
    ):
        return base + base[-1] + "ee"
    return base + "ee"


def _hame_suffix_with_harmony(stem: str, back_suffix: str, front_suffix: str) -> str:
    """Choose harmony for the final component of an ``-e`` stem.

    Compounds ending in a neutral-vowel component (``aaltoliike``) follow
    front harmony even when an earlier component contains ``a`` or ``o``.
    The compact lemma has no component boundary, so a terminal run of at
    least two neutral vowels is the conservative signal for that pattern.
    """

    if stem.endswith("e") and _has_neutral_terminal_component(stem[:-1]):
        return front_suffix
    return _suffix_with_harmony(stem, back_suffix, front_suffix)


def _predict_hame_stem_variants(*, lemma: str, case: str, number: str) -> set[str]:
    """Return alternatives produced by the regular ``hame`` template."""

    variants: set[str] = set()
    hame_stem = _hame_strong_stem(lemma)
    if number == "pl" and case in {"nom", "acc"}:
        variants.add(hame_stem + "t")
    elif number == "pl" and case in {"abe", "ins", "com"}:
        plural_stem = hame_stem[:-1] + "i"
        if case == "abe":
            suffix = _hame_suffix_with_harmony(hame_stem, "tta", "ttä")
            variants.add(plural_stem + suffix)
        elif case == "ins":
            variants.add(plural_stem + "n")
        else:
            variants.add(plural_stem + "ne")
    elif number == "sg":
        if case == "gen":
            variants.add(hame_stem + "n")
        elif case == "acc":
            variants.add(hame_stem + "n")
        elif case == "abe":
            variants.update({hame_stem + "tta", hame_stem + "ttä"})
        elif case == "par":
            variants.update({lemma + "tta", lemma + "ttä"})
        elif case in {"ine", "ela", "ade", "abl"}:
            suffixes = {
                "ine": ("ssa", "ssä"),
                "ela": ("sta", "stä"),
                "ade": ("lla", "llä"),
                "abl": ("lta", "ltä"),
            }
            back_suffix, front_suffix = suffixes[case]
            variants.update(
                {
                    hame_stem + back_suffix,
                    hame_stem + front_suffix,
                }
            )
        elif case == "ill":
            variants.add(hame_stem + "seen")
        elif case == "ess":
            variants.update({hame_stem + "na", hame_stem + "nä"})
        elif case == "all":
            variants.add(hame_stem + "lle")
        elif case == "tra":
            variants.add(hame_stem + "ksi")
    return variants


def _predict_e_stem_doubled_stop_variant(
    *, lemma: str, case: str, number: str
) -> set[str]:
    """Return the source-confirmed ``k/p/t`` doubling path for ``-e`` nouns.

    A subset of Kotus-48 words such as ``hanke -> hankkeen`` and
    ``polte -> poltteen`` restores a stop that is already preceded by a
    consonant. The compact lexeme does not retain the declension template,
    so expose this exact alternative to source validation while leaving
    ordinary words such as ``piste -> pisteen`` on the primary path.
    """

    if not lemma.endswith("e") or len(lemma) < 4:
        return set()
    base = lemma[:-1]
    if base[-1] not in {"k", "p", "t"}:
        return set()
    if base[-2] in ALL_VOWELS or base[-2] == base[-1]:
        return set()

    strong_stem = base + base[-1] + "ee"
    if number == "pl" and case in {"nom", "acc"}:
        return {strong_stem + "t"}
    if number == "pl" and case in {"abe", "ins", "com"}:
        plural_stem = strong_stem[:-1] + "i"
        if case == "abe":
            return {plural_stem + "tta", plural_stem + "ttä"}
        if case == "ins":
            return {plural_stem + "n"}
        return {plural_stem + "ne"}
    if number != "sg":
        return set()
    if case in {"gen", "acc"}:
        return {strong_stem + "n"}
    if case == "abe":
        return {strong_stem + "tta", strong_stem + "ttä"}
    if case == "par":
        return set()
    if case in {"ine", "ela", "ade", "abl"}:
        suffixes = {
            "ine": ("ssa", "ssä"),
            "ela": ("sta", "stä"),
            "ade": ("lla", "llä"),
            "abl": ("lta", "ltä"),
        }
        back_suffix, front_suffix = suffixes[case]
        return {
            strong_stem
            + _hame_suffix_with_harmony(strong_stem, back_suffix, front_suffix)
        }
    if case == "ill":
        return {strong_stem + "seen"}
    if case == "ess":
        return {
            strong_stem
            + _hame_suffix_with_harmony(strong_stem, "na", "nä")
        }
    if case == "all":
        return {strong_stem + "lle"}
    if case == "tra":
        return {strong_stem + "ksi"}
    return set()


def _predict_e_stem_weak_grade_variant(
    *, lemma: str, case: str, number: str
) -> set[str]:
    """Return the weak-grade path for source-confirmed ``-e`` loans.

    Some ``-e`` words with a final ``kk/pp/tt`` cluster use the shortened
    weak stem in their oblique and plural forms: ``jeppe -> jepen`` and
    ``ringette -> ringeten``. This is deliberately separate from the
    regular ``hame`` path because the compact lexeme cannot retain the
    source template that selects it.
    """

    if not lemma.endswith("e") or len(lemma) < 4:
        return set()
    base = lemma[:-1]
    if base[-1] not in {"k", "p", "t"} or base[-2] != base[-1]:
        return set()
    try:
        weak_base = _apply_weak_grade(lemma)[:-1]
    except _AmbiguousGradation:
        return set()

    if number == "pl" and case in {"nom", "acc"}:
        return {weak_base + "et"}
    if number == "pl" and case in {"abe", "ins", "com"}:
        plural_stem = weak_base + "i"
        if case == "abe":
            return {plural_stem + "tta", plural_stem + "ttä"}
        if case == "ins":
            return {plural_stem + "n"}
        return {plural_stem + "ne"}
    if number != "sg":
        return set()
    if case in {"gen", "acc"}:
        return {weak_base + "en"}
    if case == "abe":
        return {weak_base + "etta", weak_base + "että"}
    if case in {"ine", "ela", "ade", "abl"}:
        suffixes = {
            "ine": ("essa", "essä"),
            "ela": ("esta", "estä"),
            "ade": ("ella", "ellä"),
            "abl": ("elta", "eltä"),
        }
        back_suffix, front_suffix = suffixes[case]
        return {weak_base + _suffix_with_harmony(weak_base, back_suffix, front_suffix)}
    if case == "all":
        return {weak_base + "elle"}
    if case == "tra":
        return {weak_base + "eksi"}
    return set()


def _e_stem_weak_bases(lemma: str) -> set[str]:
    """Return weak bases for ``-e`` alternations in source paradigms."""

    if not lemma.endswith("e") or len(lemma) < 3:
        return set()
    base = lemma[:-1]
    variants = {base}
    try:
        variants.add(_apply_weak_grade(base))
    except _AmbiguousGradation as exc:
        # The source template resolves single p/t/k gradation lexically.
        # Keep the common lenition and deletion paths as validation-only
        # alternatives (hapene -> haven, autere -> auer).
        consonant = exc.args[0]
        variants.add(base.replace(consonant, {"p": "v", "t": "d", "k": "g"}[consonant], 1))
        variants.add(base.replace(consonant, "", 1))
    return variants


def _predict_e_stem_variants(*, lemma: str, case: str, number: str) -> set[str]:
    """Return exact alternatives for ``hame`` and selected ``nalle`` loans."""

    variants = _predict_hame_stem_variants(lemma=lemma, case=case, number=number)
    weak_bases = _e_stem_weak_bases(lemma)
    for weak_base in weak_bases:
        if number == "sg" and case == "nom":
            variants.add(weak_base)
        elif number == "sg" and case in {"gen", "acc"}:
            variants.add(weak_base + "en")
        elif number == "sg" and case == "par":
            variants.update({weak_base + "ta", weak_base + "tä"})
        elif number == "sg" and case == "abe":
            variants.update({weak_base + "tta", weak_base + "ttä"})
        elif number == "sg" and case in {"ine", "ela", "ade", "abl"}:
            suffixes = {
                "ine": ("ssa", "ssä"),
                "ela": ("sta", "stä"),
                "ade": ("lla", "llä"),
                "abl": ("lta", "ltä"),
            }
            back_suffix, front_suffix = suffixes[case]
            variants.update(
                {
                    weak_base + back_suffix,
                    weak_base + front_suffix,
                }
            )
        elif number == "sg" and case == "ess":
            variants.update({weak_base + "na", weak_base + "nä"})
        elif number == "sg" and case == "all":
            variants.add(weak_base + "lle")
        elif number == "sg" and case == "tra":
            variants.add(weak_base + "ksi")
        elif number == "pl" and case in {"nom", "acc"}:
            variants.add(weak_base + "et")
        elif number == "pl" and case == "abe":
            variants.update({weak_base + "itta", weak_base + "ittä"})
        elif number == "pl" and case == "ins":
            variants.add(weak_base + "in")
        elif number == "pl" and case == "com":
            variants.add(weak_base + "ine")

    # The compact lemma cannot distinguish the regular ``kirje`` path from
    # hame-style loans such as ``hylje``.  Keep the regular strong stem as a
    # second validation path; this also preserves lexical vowel harmony in
    # compounds like ``akkreditointikirje -> ...kirjeessä``.
    regular_stem = _e_stem_strong(lemma)
    if number == "sg":
        if case in {"gen", "acc"}:
            variants.add(regular_stem + "n")
        elif case == "abe":
            variants.update({regular_stem + "tta", regular_stem + "ttä"})
        elif case in {"ine", "ela", "ade", "abl"}:
            suffixes = {
                "ine": ("ssa", "ssä"),
                "ela": ("sta", "stä"),
                "ade": ("lla", "llä"),
                "abl": ("lta", "ltä"),
            }
            back_suffix, front_suffix = suffixes[case]
            variants.update(
                {regular_stem + back_suffix, regular_stem + front_suffix}
            )
        elif case == "ess":
            variants.update({regular_stem + "na", regular_stem + "nä"})
        elif case == "all":
            variants.add(regular_stem + "lle")
        elif case == "tra":
            variants.add(regular_stem + "ksi")
        elif case == "ill":
            variants.add(regular_stem + "seen")
    elif number == "pl":
        plural_stem = regular_stem[:-1] + "i"
        if case in {"nom", "acc"}:
            variants.add(regular_stem + "t")
        elif case == "abe":
            variants.update({plural_stem + "tta", plural_stem + "ttä"})
        elif case == "ins":
            variants.add(plural_stem + "n")
        elif case == "com":
            variants.add(plural_stem + "ne")

    # A generic nalle-style fallback is useful only to validation callers
    # that know the row came from Kaikki; the caller applies that guard so
    # Omorfi rows are not silently reclassified.
    if lemma not in _E_STEM_NALLE_LEMMAS:
        nalle_base = lemma[:-1]
        if number == "pl" and case in {"nom", "acc"}:
            variants.add(nalle_base + "et")
        elif number == "pl" and case == "abe":
            variants.update({nalle_base + "eitta", nalle_base + "eittä"})
        elif number == "pl" and case == "ins":
            variants.add(nalle_base + "ein")
        elif number == "pl" and case == "com":
            variants.add(nalle_base + "eine")
        elif number == "sg":
            suffixes = {
                "gen": "en",
                "acc": "en",
                "abe": "etta",
                "ine": _suffix_with_harmony(lemma, "essa", "essä"),
                "ela": _suffix_with_harmony(lemma, "esta", "estä"),
                "ade": _suffix_with_harmony(lemma, "ella", "ellä"),
                "abl": _suffix_with_harmony(lemma, "elta", "eltä"),
                "all": "elle",
                "ess": _suffix_with_harmony(lemma, "ena", "enä"),
                "tra": "eksi",
                "ill": "een",
                # Loanwords in the nalle family keep the final ``e`` in the
                # partitive: ``akne -> aknea``, ``aborigine -> aboriginea``.
                # The other cells use the shorter oblique stem above.
                "par": lemma + _suffix_with_harmony(lemma, "a", "ä"),
            }
            suffix = suffixes.get(case)
            if suffix is not None:
                # The partitive is the one cell that retains the final e;
                # all other generic nalle alternatives attach to the
                # shortened oblique base (``akne -> aknen``).
                if case == "par":
                    variants.add(lemma + _suffix_with_harmony(lemma, "a", "ä"))
                else:
                    variants.add(nalle_base + suffix)
                    if case == "abe":
                        variants.add(nalle_base + "että")
            if case == "par":
                variants.update({lemma + "a", lemma + "ä"})
        return variants

    # The nalle template's ordinary loanword path keeps the lemma as its
    # stem. ``nukke`` additionally has kk~k gradation in the oblique cells.
    weak_base = lemma[:-1]
    try:
        # Keep the final ``-e`` while applying the pre-final cluster rule
        # (``nukke -> nuke``), then remove it from the weak stem.
        weak_base = _apply_weak_grade(lemma)[:-1]
    except _AmbiguousGradation:
        weak_base = None

    if number == "pl" and case in {"nom", "acc"}:
        variants.add(lemma + "t")
    elif number == "pl" and case == "abe":
        variants.update({lemma + "itta", lemma + "ittä"})
        # ``nukke`` has the lexical weak stem ``nuke`` in the plural
        # abessive (``nukeitta``).  The compact lemma does not retain the
        # nalle template's stem alternation, so keep this exact weak path
        # alongside the regular loanword form.
        if weak_base and weak_base != lemma[:-1]:
            variants.update({weak_base + "eitta", weak_base + "eittä"})
    elif number == "pl" and case == "ins":
        variants.add(lemma + "in")
    elif number == "pl" and case == "com":
        variants.add(lemma + "ine")
    elif number == "sg":
        suffixes = {
            "gen": "n",
            "acc": "n",
            "abe": _suffix_with_harmony(lemma, "tta", "ttä"),
            "ine": _suffix_with_harmony(lemma, "ssa", "ssä"),
            "ela": _suffix_with_harmony(lemma, "sta", "stä"),
            "ade": _suffix_with_harmony(lemma, "lla", "llä"),
            "abl": _suffix_with_harmony(lemma, "lta", "ltä"),
            "all": "lle",
            "ess": _suffix_with_harmony(lemma, "na", "nä"),
            "tra": "ksi",
            "ill": "en",
            "par": _suffix_with_harmony(lemma, "a", "ä"),
        }
        suffix = suffixes.get(case)
        if suffix is not None:
            variants.add(lemma + suffix)
        if case == "par":
            variants.update({lemma + "a", lemma + "ä"})

        if weak_base and weak_base != lemma[:-1]:
            if case == "gen":
                variants.add(weak_base + "en")
            elif case in {"ine", "ela", "ade", "abl"}:
                oblique_suffixes = {
                    "ine": ("essa", "essä"),
                    "ela": ("esta", "estä"),
                    "ade": ("ella", "ellä"),
                    "abl": ("elta", "eltä"),
                }
                back_suffix, front_suffix = oblique_suffixes[case]
                variants.add(
                    weak_base
                    + _suffix_with_harmony(weak_base, back_suffix, front_suffix)
                )
            elif case == "ill":
                variants.add(lemma[:-1] + "een")
            elif case == "ess":
                variants.add(lemma[:-1] + _suffix_with_harmony(lemma, "ena", "enä"))
            elif case == "all":
                variants.add(weak_base + "elle")
            elif case == "tra":
                variants.add(weak_base + "eksi")
            elif case == "nom" and number == "sg":
                variants.add(lemma)
    if number == "pl" and case == "nom" and weak_base:
        variants.add(weak_base + "et")
    return variants


# Reverse gradation map keyed on the *consonant* cluster sitting just
# before the lemma's final ``-e``. The value is the strengthened cluster
# that reappears in oblique stems (e.g. ``kaide`` ``d`` -> ``t``).
_E_STEM_CONSONANT_GRADATION: tuple[tuple[str, str], ...] = (
    ("mm", "mp"),
    ("nn", "nt"),
    ("ll", "lt"),
    ("rr", "rt"),
    ("ng", "nk"),
    ("hd", "ht"),
    ("d", "t"),
)


def _e_stem_strong(lemma: str) -> str:
    """Return the strong-grade ``-ee`` stem of a kotus 48 ``-e`` noun.

    The lemma is the weak-grade nominative; gen / plural / illative use
    the long-``ee`` strong stem::

        perhe   -> perhee
        kaide   -> kaitee     (d -> t)
        tunne   -> tuntee     (nn -> nt)
        kaavake -> kaavakkee  (k -> kk)
        aate    -> aattee     (t -> tt)

    The caller appends the case suffix (``-n`` for genitive, ``-t`` for
    nominative plural, and so on) without further stem changes.
    """

    if not lemma.endswith("e") or len(lemma) < 3:
        return lemma + "e"
    base = lemma[:-1]  # everything before the final -e

    for weak, strong in _E_STEM_CONSONANT_GRADATION:
        if base.endswith(weak) and len(base) > len(weak):
            return base[: -len(weak)] + strong + "ee"

    # Single ``p`` / ``t`` / ``k`` after a vowel: geminate
    # (kaavake -> kaavakkee, aate -> aattee, liike -> liikkee).
    if len(base) >= 2 and base[-1] in {"k", "p", "t"} and _is_vowel(base[-2]):
        return base + base[-1] + "ee"

    return base + "ee"


def _e_stem(lemma: str) -> str:
    """Lemma form ends in -e; the oblique stem doubles the final e."""

    return _e_stem_strong(lemma)
