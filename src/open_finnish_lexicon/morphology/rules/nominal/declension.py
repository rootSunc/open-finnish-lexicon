"""Core nominal case-stem builders and general case/number prediction."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.nominal.classify import (
    _classify_nominal,
    _has_neutral_terminal_component,
    _is_usi_family,
)
from open_finnish_lexicon.morphology.rules.nominal.consonant_stems import (
    _as_strong_stem,
    _as_strong_stem_variants,
    _nen_stem,
    _predict_as_aks_variant,
    _predict_as_foreign_i_variant,
    _predict_as_long_variant,
    _predict_as_variant,
    _us_stem,
    _uus_stem,
)
from open_finnish_lexicon.morphology.rules.nominal.e_stems import (
    _e_stem,
    _e_stem_strong,
    _hame_suffix_with_harmony,
)
from open_finnish_lexicon.morphology.rules.nominal.i_stems import (
    _I_STEM_NOMINATIVE_PLURAL_OVERRIDES,
    _I_STEM_PLURAL_STEM_OVERRIDES,
    _i_stem_component_override,
    _i_stem_genitive,
    _i_stem_plural_stem_variants,
)
from open_finnish_lexicon.morphology.rules.phonology import (
    _AmbiguousGradation,
    _apply_weak_grade,
    _suffix_with_harmony,
)
from open_finnish_lexicon.morphology.rules.types import ALL_VOWELS

def _illative_singular(stem: str) -> str:
    """Predict illative singular for a vowel-ending stem.

    Rules:
    * Short single vowel ending: vowel doubling + ``n`` (sisu -> sisuun).
    * Long vowel (-aa, -ää, -ee, -oo, -uu, -yy, -öö, -ii): ``-seen``.
    """

    if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] in ALL_VOWELS:
        return stem + "seen"
    last = stem[-1]
    if last in ALL_VOWELS:
        return stem + last + "n"
    return stem + "Vn"  # unknown shape; caller treats as uncertain


def _partitive_singular_nominal(kotus: str, lemma: str, stem: str) -> str:
    """Pick the partitive suffix variant for a nominal lemma."""

    harmony_suffix = _suffix_with_harmony(stem, "a", "ä")
    if kotus == "vowel_short":
        return lemma + harmony_suffix
    if kotus == "a_stem_grad":
        # kotus 9 partitive uses the lemma + a/ä even when the lemma ends
        # in -a (kala -> kalaa).
        return lemma + harmony_suffix
    if kotus == "nen":
        return lemma[:-3] + "st" + harmony_suffix
    if kotus == "as_grad":
        return lemma + ("t" + harmony_suffix)
    if kotus == "e_stem":
        return lemma + "tt" + harmony_suffix
    if kotus == "i_stem":
        if _is_usi_family(lemma):
            return lemma[:-2] + "tt" + _suffix_with_harmony(lemma, "a", "ä")
        return lemma + harmony_suffix
    if kotus == "us_stem":
        # Two paradigms share the ``-Vus`` shape and we can't tell them
        # apart from the lemma alone: type 39 ``vastaus -> vastausta``
        # vs type 67 ``runous -> runoutta``. Type 39 is far more common
        # in derivational vocabulary (``vastaus``, ``kysymys``, action
        # nouns built off a verb), so we predict that variant and let
        # the LLM stage flip the rare type-67 lemmas. See
        # ``CoreParadigmsTests.test_vastaus_us_stem`` for the canonical case.
        return lemma + "t" + harmony_suffix
    if kotus == "uus_stem":
        # ``naisuus -> naisuutta``, ``ylevyys -> ylevyyttä``: drop the
        # final ``-s`` and attach the geminate ``-tta``/``-ttä``.
        return lemma[:-1] + "tt" + harmony_suffix
    raise ValueError(f"unsupported kotus for partitive: {kotus}")


def _genitive_stem(kotus: str, lemma: str, *, apply_gradation: bool = True) -> str:
    if kotus == "vowel_short":
        return _apply_weak_grade(lemma) if apply_gradation else lemma
    if kotus == "a_stem_grad":
        return _apply_weak_grade(lemma) if apply_gradation else lemma
    if kotus == "nen":
        return _nen_stem(lemma)
    if kotus == "as_grad":
        return _as_strong_stem(lemma)
    if kotus == "e_stem":
        return _e_stem(lemma)
    if kotus == "i_stem":
        return _i_stem_genitive(lemma)
    if kotus == "us_stem":
        return _us_stem(lemma)
    if kotus == "uus_stem":
        return _uus_stem(lemma)
    raise ValueError(f"unsupported kotus for genitive: {kotus}")


def _essive_stem(kotus: str, lemma: str) -> str:
    """The essive ``-na``/``-nä`` attaches to the strong-grade stem.

    Unlike the inessive / elative / adessive / ablative (which use the
    weak-grade genitive stem), the essive in Finnish keeps the strong
    grade alive: ``tukka -> tukkana``, ``lukko -> lukkona``. For kotus
    types without gradation, the strong and weak stems are the same
    string so this collapses to the lemma.
    """

    if kotus in {"vowel_short", "a_stem_grad"}:
        return lemma
    if kotus == "i_stem":
        if _is_usi_family(lemma):
            return lemma[:-2] + "te"
        # Loanwords such as ``akuutti`` keep the strong grade in the
        # essive: akuuttina, while e-stem/si-family exceptions are handled
        # by validation alternatives.
        return lemma
    if kotus == "uus_stem":
        # Strong stem: ``naisuus -> naisuute``, ``ylevyys -> ylevyyte``.
        return lemma[:-1] + "te"
    # The other kotus types either have no gradation or already use a
    # gradation-aware stem helper that produces the strong grade.
    return _genitive_stem(kotus, lemma)


def _nominative_plural(
    kotus: str, lemma: str, *, apply_gradation: bool = True
) -> str | None:
    """Predict the nominative-plural surface form for ``lemma``.

    The plural marker ``-t`` attaches to the same stem as the genitive
    ``-n``, i.e. the gradation-weakened stem for kotus types with
    consonant gradation. So ``kala -> kalat`` (no gradation), but
    ``ojikko -> ojikot`` (``kk`` -> ``k``) and ``kauppa -> kaupat``
    (``pp`` -> ``p``). Ambiguous single-consonant gradation propagates
    as ``_AmbiguousGradation`` so the caller can downgrade to UNCERTAIN.
    """

    if kotus in {"vowel_short", "a_stem_grad"}:
        stem = _apply_weak_grade(lemma) if apply_gradation else lemma
        return stem + "t"
    if kotus == "as_grad":
        return _as_strong_stem(lemma) + "t"
    if kotus == "nen":
        return _nen_stem(lemma) + "t"
    if kotus == "us_stem":
        return _us_stem(lemma) + "t"
    if kotus == "uus_stem":
        return _uus_stem(lemma) + "t"
    if kotus == "e_stem":
        return _e_stem_strong(lemma) + "t"
    if kotus == "i_stem":
        if _is_usi_family(lemma):
            return lemma[:-2] + "de" + "t"
        override = _i_stem_component_override(
            lemma, _I_STEM_NOMINATIVE_PLURAL_OVERRIDES
        )
        if override:
            return override
        try:
            weak = _apply_weak_grade(lemma)
        except _AmbiguousGradation:
            weak = lemma
        if weak != lemma:
            return weak[:-1] + "it"
        return lemma + "t"
    return None


def _plural_oblique_stem(
    kotus: str, lemma: str, *, apply_gradation: bool = True
) -> str | None:
    """Return the stem before plural ``-i-`` case endings.

    The less frequent Finnish cases are still useful in fixed expressions,
    so the rule engine should not discard them merely because they are not
    part of the core ``missa-mista-mihin`` inventory.  These stems mirror
    the same declension families used by the core paradigm:

    * ``talo -> taloi`` and ``kala -> kaloi``;
    * ``perhe -> perhei`` and ``nainen -> naisi``;
    * ``vastaus -> vastauksi`` and ``naisuus -> naisuuksi``.
    """

    if kotus == "vowel_short":
        # The plural stem keeps the weak grade: aalto -> aallo-i,
        # lukko -> luko-i.  This is easy to miss because the nominative
        # lemma itself is the strong-grade form.
        stem = _apply_weak_grade(lemma) if apply_gradation else lemma
        return stem + "i"
    if kotus == "a_stem_grad":
        weak = _apply_weak_grade(lemma) if apply_gradation else lemma
        # Front-vowel a-stems use ``-i-`` directly (pöytä -> pöydi), while
        # back-vowel a-stems keep the productive ``-oi-`` sequence.
        if lemma.endswith("ä"):
            return weak[:-1] + "i"
        return weak[:-1] + "oi"
    if kotus == "as_grad":
        return _as_strong_stem(lemma)[:-1] + "i"
    if kotus == "nen":
        return _nen_stem(lemma)[:-1] + "i"
    if kotus == "e_stem":
        return _e_stem_strong(lemma)[:-1] + "i"
    if kotus == "i_stem":
        if _is_usi_family(lemma):
            return lemma
        override = _i_stem_component_override(
            lemma, _I_STEM_PLURAL_STEM_OVERRIDES
        )
        if override:
            return override
        try:
            weak = _apply_weak_grade(lemma)
        except _AmbiguousGradation:
            weak = lemma
        return weak[:-1] + "ei"
    if kotus == "us_stem":
        return _us_stem(lemma)[:-1] + "i"
    if kotus == "uus_stem":
        return lemma[:-1] + "ksi"
    return None


def _plural_oblique_stem_variants(kotus: str, lemma: str) -> set[str]:
    """Return source-compatible variants for plural oblique stems."""

    # This helper is only used after the primary prediction has already
    # produced a mismatch.  It must therefore be best-effort: a
    # lexeme-specific single ``k``/``t``/``p`` should not abort validation
    # while we are checking the extended-case alternatives.
    try:
        stem = _plural_oblique_stem(kotus, lemma)
    except _AmbiguousGradation:
        if kotus == "vowel_short":
            stem = lemma + "i"
        elif kotus == "a_stem_grad":
            stem = lemma[:-1] + ("i" if lemma.endswith("ä") else "oi")
        else:
            return set()
    if stem is None:
        return set()
    variants = {stem}
    if kotus == "vowel_short":
        # A few source paradigms retain the strong grade in these rare
        # cells (and some loans use the lemma-shaped plural stem).
        variants.add(lemma + "i")
    elif kotus == "a_stem_grad":
        try:
            weak = _apply_weak_grade(lemma)
        except _AmbiguousGradation:
            weak = lemma
        # Kotus sources alternate between -i- and -oi- stems in these rare
        # cells.  The final -ä additionally has the productive -öi- path:
        # näyttelijä -> näyttelijöin / näyttelijöittä.
        variants.update(
            {
                weak[:-1] + "i",
                weak[:-1] + "oi",
                weak[:-1] + ("öi" if lemma.endswith("ä") else "i"),
                lemma[:-1] + "i",
                lemma[:-1] + "oi",
                lemma[:-1] + ("öi" if lemma.endswith("ä") else "i"),
                lemma + "i",
            }
        )
    elif kotus == "i_stem":
        variants.update(_i_stem_plural_stem_variants(lemma))
    elif kotus == "as_grad":
        variants.update(
            strong[:-1] + "i" for strong in _as_strong_stem_variants(lemma)
        )
        base = lemma[:-2]
        aks = base + ("äks" if lemma.endswith("äs") else "aks")
        variants.add(aks + "i")
    return variants


def _predict_nominal_case_variants(
    *, lemma: str, case: str, number: str
) -> set[str]:
    """Return complete alternatives for the less common nominal cases."""

    kotus = _classify_nominal(lemma)
    if kotus is None:
        return set()

    if case == "abe" and number == "sg":
        # ``-tta/-ttä`` attaches to the same oblique stem as the genitive.
        if kotus == "as_grad":
            values: set[str] = set()
            values.update(_predict_as_variant(lemma=lemma, case=case, number=number))
            values.update(_predict_as_aks_variant(lemma=lemma, case=case, number=number))
            values.update(_predict_as_long_variant(lemma=lemma, case=case, number=number))
            values.update(
                _predict_as_foreign_i_variant(
                    lemma=lemma, case=case, number=number
                )
            )
            return values
        return set()

    if case not in {"abe", "ins", "com"} or number != "pl":
        return set()

    values = set()
    for stem in _plural_oblique_stem_variants(kotus, lemma):
        if case == "ins":
            values.add(stem + "n")
        elif case == "com":
            values.add(stem + "ne")
        else:
            if kotus == "e_stem":
                suffix = _hame_suffix_with_harmony(
                    _e_stem_strong(lemma), "tta", "ttä"
                )
            elif kotus == "nen" and _has_neutral_terminal_component(lemma[:-3]):
                suffix = "ttä"
            else:
                suffix = _suffix_with_harmony(lemma, "tta", "ttä")
            values.add(stem + suffix)

    if kotus == "as_grad":
        values.update(_predict_as_variant(lemma=lemma, case=case, number=number))
        values.update(_predict_as_aks_variant(lemma=lemma, case=case, number=number))
        values.update(_predict_as_long_variant(lemma=lemma, case=case, number=number))
        values.update(
            _predict_as_foreign_i_variant(
                lemma=lemma, case=case, number=number
            )
        )
    return values


def _predict_vowel_short_variants(
    *, lemma: str, case: str, number: str
) -> set[str]:
    """Return exact loanword variants for short-vowel nominals.

    ``go`` is listed with the Finnish ``rosé`` template: its singular
    partitive and illative are ``gota`` and ``gohon`` rather than the
    productive ``-a``/vowel-doubling forms.  Keep this lexical exception
    narrow so ordinary short-vowel nouns remain fully checked.  ``hobby``
    likewise keeps back-harmony suffixes in the source paradigm despite its
    final ``-y``.
    """

    variants: dict[tuple[str, str, str], str] = {
        ("go", "par", "sg"): "gota",
        ("go", "ill", "sg"): "gohon",
        ("hobby", "par", "sg"): "hobbya",
        ("hobby", "abe", "pl"): "hobbyitta",
        ("hobby", "ade", "sg"): "hobbylla",
        ("hobby", "abl", "sg"): "hobbylta",
        ("hobby", "ess", "sg"): "hobbyna",
        ("hobby", "ine", "sg"): "hobbyssa",
        ("hobby", "ela", "sg"): "hobbysta",
        ("hobby", "abe", "sg"): "hobbytta",
    }
    value = variants.get((lemma, case, number))
    if value is not None:
        return {value}

    # Established loanwords ending in ``-y`` often keep the back-harmony
    # path from their source table even when the final Finnish spelling
    # suggests front harmony (``bodya``, ``curryssa``, ``rugbytta``).
    if lemma.endswith("y") and any(vowel in lemma for vowel in "aou"):
        back_suffixes = {
            ("par", "sg"): "a",
            ("abe", "sg"): "tta",
            ("ine", "sg"): "ssa",
            ("ela", "sg"): "sta",
            ("ade", "sg"): "lla",
            ("abl", "sg"): "lta",
            ("ess", "sg"): "na",
            ("abe", "pl"): "itta",
        }
        suffix = back_suffixes.get((case, number))
        if suffix is not None:
            return {lemma + suffix}
    return set()


def _predict_nominal(
    *, lemma: str, case: str, number: str, apply_gradation: bool = True
) -> tuple[str | None, str | None, str]:
    """Predict the surface form for ``(lemma, case, number)``.

    Returns ``(predicted, rule, explanation)``. ``predicted`` is ``None``
    when this engine does not cover the requested form, including cases
    where ambiguous single-consonant gradation prevents a confident
    prediction.
    """

    kotus = _classify_nominal(lemma)
    if kotus is None:
        return None, None, f"lemma {lemma!r} does not match a supported kotus pattern"

    rule = f"nominal/{kotus}/{case}.{number}"

    try:
        if number == "sg":
            if case == "nom":
                return lemma, rule, f"{lemma}: nominative singular = base form"

            if case == "acc":
                stem = _genitive_stem(kotus, lemma, apply_gradation=apply_gradation)
                return stem + "n", rule, f"{lemma}: acc sg = stem {stem!r} + -n"

            if case == "gen":
                stem = _genitive_stem(kotus, lemma, apply_gradation=apply_gradation)
                return stem + "n", rule, f"{lemma}: gen sg = stem {stem!r} + -n"

            if case == "par":
                predicted = _partitive_singular_nominal(kotus, lemma, lemma)
                return predicted, rule, f"{lemma}: par sg = {predicted!r}"

            if case == "abe":
                stem = _genitive_stem(kotus, lemma, apply_gradation=apply_gradation)
                suffix = _suffix_with_harmony(stem, "tta", "ttä")
                return stem + suffix, rule, f"{lemma}: abe sg = stem {stem!r} + {suffix}"

            if case in {"ine", "ela", "ade", "abl"}:
                stem = _genitive_stem(kotus, lemma, apply_gradation=apply_gradation)
                if case == "ine":
                    suffix = _suffix_with_harmony(stem, "ssa", "ssä")
                elif case == "ela":
                    suffix = _suffix_with_harmony(stem, "sta", "stä")
                elif case == "ade":
                    suffix = _suffix_with_harmony(stem, "lla", "llä")
                else:
                    suffix = _suffix_with_harmony(stem, "lta", "ltä")
                return (
                    stem + suffix,
                    rule,
                    f"{lemma}: {case} sg = stem {stem!r} + {suffix}",
                )

            if case == "all":
                stem = _genitive_stem(kotus, lemma, apply_gradation=apply_gradation)
                return stem + "lle", rule, f"{lemma}: all sg = stem {stem!r} + -lle"

            if case == "ill":
                if kotus == "as_grad":
                    stem = _as_strong_stem(lemma)
                    predicted = stem + "seen"
                    return predicted, rule, f"{lemma}: ill sg = {stem!r} + -seen"
                if kotus == "nen":
                    stem = _nen_stem(lemma)
                    predicted = stem + "en"
                    return predicted, rule, f"{lemma}: ill sg = {stem!r} + -en"
                if kotus == "us_stem":
                    stem = _us_stem(lemma)
                    predicted = stem + "en"
                    return predicted, rule, f"{lemma}: ill sg = {stem!r} + -en"
                if kotus == "uus_stem":
                    # ``naisuus -> naisuuteen``: long-vowel stem keeps the
                    # ``-een`` illative suffix straight off the lemma.
                    stem = lemma[:-1] + "te"
                    predicted = stem + "en"
                    return predicted, rule, f"{lemma}: ill sg = {stem!r} + -en"
                if kotus == "e_stem":
                    stem = _e_stem(lemma)
                    predicted = stem + "seen"
                    return predicted, rule, f"{lemma}: ill sg = {stem!r} + -seen"
                if kotus == "i_stem" and _is_usi_family(lemma):
                    stem = lemma[:-2] + "te"
                    predicted = stem + "en"
                    return predicted, rule, f"{lemma}: ill sg = {stem!r} + -en"
                return (
                    _illative_singular(lemma),
                    rule,
                    f"{lemma}: ill sg = {lemma!r} doubled vowel + -n",
                )

            if case == "ess":
                stem = _essive_stem(kotus, lemma)
                suffix = _suffix_with_harmony(stem, "na", "nä")
                return stem + suffix, rule, f"{lemma}: ess sg = stem {stem!r} + {suffix}"

            if case == "tra":
                stem = _genitive_stem(kotus, lemma, apply_gradation=apply_gradation)
                return stem + "ksi", rule, f"{lemma}: tra sg = stem {stem!r} + -ksi"

        if number == "pl" and case == "nom":
            plural = _nominative_plural(kotus, lemma, apply_gradation=apply_gradation)
            if plural is None:
                return None, None, f"{lemma}: nom pl not covered for kotus {kotus}"
            return plural, rule, f"{lemma}: nom pl = {plural!r}"

        if number == "pl" and case == "acc":
            plural = _nominative_plural(kotus, lemma, apply_gradation=apply_gradation)
            if plural is None:
                return None, None, f"{lemma}: acc pl not covered for kotus {kotus}"
            return plural, rule, f"{lemma}: acc pl = nominative plural {plural!r}"

        if number == "pl" and case in {"abe", "ins", "com"}:
            stem = _plural_oblique_stem(kotus, lemma, apply_gradation=apply_gradation)
            if stem is None:
                return None, None, f"{lemma}: {case} pl not covered for kotus {kotus}"
            if case == "ins":
                suffix = "n"
            elif case == "com":
                suffix = "ne"
            else:
                suffix = _suffix_with_harmony(stem, "tta", "ttä")
            return stem + suffix, rule, f"{lemma}: {case} pl = stem {stem!r} + {suffix}"

        if number == "pl" and kotus == "i_stem":
            if case == "gen":
                predicted = lemma + "en"
                return predicted, rule, f"{lemma}: gen pl = {predicted!r}"
            if case == "par":
                if _is_usi_family(lemma):
                    predicted = lemma + "a"
                    return predicted, rule, f"{lemma}: par pl = {predicted!r}"
                stem = lemma[:-1] + "e"
                suffix = _suffix_with_harmony(stem, "ja", "jä")
                predicted = stem + suffix
                return predicted, rule, f"{lemma}: par pl = {predicted!r}"
            if case in {"ine", "ela", "ade", "abl"}:
                stem = _plural_oblique_stem(kotus, lemma, apply_gradation=apply_gradation)
                assert stem is not None
                suffixes = {
                    "ine": ("ssa", "ssä"),
                    "ela": ("sta", "stä"),
                    "ade": ("lla", "llä"),
                    "abl": ("lta", "ltä"),
                }
                back_suffix, front_suffix = suffixes[case]
                suffix = _suffix_with_harmony(stem, back_suffix, front_suffix)
                predicted = stem + suffix
                return predicted, rule, f"{lemma}: {case} pl = {predicted!r}"
            if case == "ill":
                stem = _plural_oblique_stem(kotus, lemma, apply_gradation=apply_gradation)
                assert stem is not None
                predicted = stem + ("in" if stem == lemma else "hin")
                return predicted, rule, f"{lemma}: ill pl = {predicted!r}"
            if case == "ess":
                stem = _plural_oblique_stem(kotus, lemma, apply_gradation=apply_gradation)
                assert stem is not None
                suffix = _suffix_with_harmony(stem, "na", "nä")
                predicted = stem + suffix
                return predicted, rule, f"{lemma}: ess pl = {predicted!r}"
            if case == "all":
                stem = _plural_oblique_stem(kotus, lemma, apply_gradation=apply_gradation)
                assert stem is not None
                predicted = stem + "lle"
                return predicted, rule, f"{lemma}: all pl = {predicted!r}"
            if case == "tra":
                stem = _plural_oblique_stem(kotus, lemma, apply_gradation=apply_gradation)
                assert stem is not None
                predicted = stem + "ksi"
                return predicted, rule, f"{lemma}: tra pl = {predicted!r}"
    except _AmbiguousGradation as exc:
        return (
            None,
            None,
            f"{lemma}: single-consonant gradation on {exc.args[0]!r} is too "
            "lemma-specific to predict deterministically",
        )

    return None, None, f"{lemma}: case {case} in number {number} not covered"
