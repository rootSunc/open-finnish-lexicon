"""Verb classification and finite-form prediction."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.phonology import (
    _AmbiguousGradation,
    _apply_weak_grade,
    _harmony,
)


# A small explicit table is safer than pretending that all common verbs have
# a compositional present stem. These forms otherwise produce misleading
# predictions such as ``tehdä -> tehn``.
_IRREGULAR_PRESENT_FORMS: dict[str, dict[tuple[str, str], str]] = {
    "olla": {
        ("1", "sg"): "olen", ("2", "sg"): "olet", ("3", "sg"): "on",
        ("1", "pl"): "olemme", ("2", "pl"): "olette", ("3", "pl"): "ovat",
    },
    "tehdä": {
        ("1", "sg"): "teen", ("2", "sg"): "teet", ("3", "sg"): "tekee",
        ("1", "pl"): "teemme", ("2", "pl"): "teette", ("3", "pl"): "tekevät",
    },
    "nähdä": {
        ("1", "sg"): "näen", ("2", "sg"): "näet", ("3", "sg"): "näkee",
        ("1", "pl"): "näemme", ("2", "pl"): "näette", ("3", "pl"): "näkevät",
    },
    "tulla": {
        ("1", "sg"): "tulen", ("2", "sg"): "tulet", ("3", "sg"): "tulee",
        ("1", "pl"): "tulemme", ("2", "pl"): "tulette", ("3", "pl"): "tulevat",
    },
    "mennä": {
        ("1", "sg"): "menen", ("2", "sg"): "menet", ("3", "sg"): "menee",
        ("1", "pl"): "menemme", ("2", "pl"): "menette", ("3", "pl"): "menevät",
    },
    "juosta": {
        ("1", "sg"): "juoksen", ("2", "sg"): "juokset", ("3", "sg"): "juoksee",
        ("1", "pl"): "juoksemme", ("2", "pl"): "juoksette", ("3", "pl"): "juoksevat",
    },
    "sulkea": {
        ("1", "sg"): "suljen", ("2", "sg"): "suljet", ("3", "sg"): "sulkee",
        ("1", "pl"): "suljemme", ("2", "pl"): "suljette", ("3", "pl"): "sulkevat",
    },
    "kulkea": {
        ("1", "sg"): "kuljen", ("2", "sg"): "kuljet", ("3", "sg"): "kulkee",
        ("1", "pl"): "kuljemme", ("2", "pl"): "kuljette", ("3", "pl"): "kulkevat",
    },
    "pyyhkiä": {
        ("1", "sg"): "pyyhin", ("2", "sg"): "pyyhit", ("3", "sg"): "pyyhkii",
        ("1", "pl"): "pyyhimme", ("2", "pl"): "pyyhitte", ("3", "pl"): "pyyhkivät",
    },
    # The ``-lk-/-rk-`` cluster changes to ``-lj-/-rj-`` in the weak
    # present stem for this lexical family: ``polkea -> poljen`` and
    # ``särkeä -> särjen``.  The compact lexeme row does not retain the
    # conjugation template, so keep these source-confirmed paradigms
    # explicit rather than applying the nominal ``lk -> l`` / ``rk -> r``
    # deletion rule.
    "polkea": {
        ("1", "sg"): "poljen", ("2", "sg"): "poljet", ("3", "sg"): "polkee",
        ("1", "pl"): "poljemme", ("2", "pl"): "poljette", ("3", "pl"): "polkevat",
    },
    "särkeä": {
        ("1", "sg"): "särjen", ("2", "sg"): "särjet", ("3", "sg"): "särkee",
        ("1", "pl"): "särjemme", ("2", "pl"): "särjette", ("3", "pl"): "särkevät",
    },
    "nylkeä": {
        ("1", "sg"): "nyljen", ("2", "sg"): "nyljet", ("3", "sg"): "nylkee",
        ("1", "pl"): "nyljemme", ("2", "pl"): "nyljette", ("3", "pl"): "nylkevät",
    },
    "hylkiä": {
        ("1", "sg"): "hyljin", ("2", "sg"): "hyljit", ("3", "sg"): "hylkii",
        ("1", "pl"): "hyljimme", ("2", "pl"): "hyljitte", ("3", "pl"): "hylkivät",
    },
    "sylkeä": {
        ("1", "sg"): "syljen", ("2", "sg"): "syljet", ("3", "sg"): "sylkee",
        ("1", "pl"): "syljemme", ("2", "pl"): "syljette", ("3", "pl"): "sylkevät",
    },
}


_NEGATIVE_AUXILIARY_FORMS = {
    ("indicative", "1", "sg"): "en",
    ("indicative", "2", "sg"): "et",
    ("indicative", "3", "sg"): "ei",
    ("indicative", "1", "pl"): "emme",
    ("indicative", "2", "pl"): "ette",
    ("indicative", "3", "pl"): "eivät",
    ("imperative", "2", "sg"): "älä",
    ("imperative", "3", "sg"): "älköön",
    ("imperative", "1", "pl"): "älkäämme",
    ("imperative", "2", "pl"): "älkää",
    ("imperative", "3", "pl"): "älkööt",
}


def _predict_negative_auxiliary(
    *, mood: str | None, person: str | None, number: str | None, surface: str
) -> tuple[str | None, str | None, str]:
    """Predict finite forms of Finnish ``ei`` when no clitic is present."""

    if person is None or number is None:
        return None, None, "negative auxiliary person/number is missing"
    mood_norm = (mood or "indicative").strip().casefold()
    if mood_norm in {"ind", "indicative"}:
        mood_norm = "indicative"
    elif mood_norm in {"imp", "imperative"}:
        mood_norm = "imperative"
    else:
        return None, None, "negative auxiliary mood is not covered"
    predicted = _NEGATIVE_AUXILIARY_FORMS.get((mood_norm, person, number))
    if predicted is None:
        return None, None, "negative auxiliary person/number is not covered"
    # Some Kaikki rows omit mood on archaic imperative cells. Preserve those
    # explicit source forms when they are a known ``ei`` paradigm variant;
    # contradictory surfaces still become deterministic mismatches.
    if mood is None:
        source_variants = {
            ("2", "sg"): {"ällös"},
            ("3", "sg"): {"älköön"},
            ("1", "pl"): {"älköömme"},
            ("2", "pl"): {"älköötte"},
            ("3", "pl"): {"älkööt"},
        }
        if surface in source_variants.get((person, number), set()):
            return (
                surface,
                f"verb/negative-auxiliary/{mood_norm}.{person}.{number}/source-variant",
                f"ei: source-declared negative auxiliary form = {surface!r}",
            )
    return (
        predicted,
        f"verb/negative-auxiliary/{mood_norm}.{person}.{number}",
        f"ei: negative auxiliary form = {predicted!r}",
    )


# Kotimaisten kielten keskuksen guidance lists these ``-oida/-öidä`` verbs
# as having the less common long ``-oitse/-öitse`` present alongside the
# regular ``-oi/-öi`` paradigm. Keep the lexical list explicit: the short
# form is the default for other verbs in this class.
_OITSE_PRESENT_LEMMAS = frozenset(
    {
        "ahkeroida",
        "aterioida",
        "haravoida",
        "isännöidä",
        "luennoida",
        "mellakoida",
        "ikävöidä",
        "takavarikoida",
        "tupakoida",
        "urakoida",
        "vartioida",
    }
)


def _classify_verb(lemma: str) -> str | None:
    """Return a short verb identifier or ``None`` for unsupported lemmas.

    Currently covers verb types I (52, ``puhua``-style) and II (kotus 53/54),
    which together account for the vast majority of Finnish verbs.
    """

    if not lemma or len(lemma) < 3:
        return None
    if lemma.endswith(("ua", "yä", "oa", "öä", "ia", "iä", "aa", "ää", "ea", "eä")):
        return "type1"
    if lemma.endswith(("da", "dä")):
        return "type2"
    return None


def _verb_stem_type1(lemma: str) -> str:
    return lemma[:-1]


def _verb_stem_type2(lemma: str) -> str:
    return lemma[:-2]


def _verb_present_finite_stem(stem: str) -> str:
    """Return the weak stem used by first-conjugation finite forms.

    The general gradation table contains the nominal ``hk -> h`` deletion
    pattern (``nahka -> nahan``), but common ``-hk-`` verbs retain the
    cluster in the present: ``hehkua -> hehkun`` and ``puhkoa -> puhkon``.
    Their 3rd-person forms already use the strong stem and do not call this
    helper. Keep the exception narrow to a final ``hk`` cluster before the
    stem vowel.
    """

    if len(stem) >= 3 and stem[:-1].endswith("hk"):
        return stem
    return _apply_weak_grade(stem)


def _predict_verb_present(
    *, lemma: str, person: str, number: str
) -> tuple[str | None, str | None, str]:
    irregular_forms = _IRREGULAR_PRESENT_FORMS.get(lemma)
    if irregular_forms is not None:
        predicted = irregular_forms.get((person, number))
        if predicted is not None:
            return (
                predicted,
                f"verb/irregular/pres.{person}.{number}",
                f"{lemma}: irregular present form = {predicted!r}",
            )

    kind = _classify_verb(lemma)
    if kind is None:
        return None, None, f"verb {lemma!r} does not match a covered type"

    stem = _verb_stem_type1(lemma) if kind == "type1" else _verb_stem_type2(lemma)
    try:
        finite_stem = _verb_present_finite_stem(stem) if kind == "type1" else stem
    except _AmbiguousGradation as exc:
        return (
            None,
            None,
            f"{lemma}: verb gradation on {exc.args[0]!r} is too lemma-specific",
        )

    if person == "3" and number == "sg":
        if kind == "type1":
            predicted = stem + stem[-1]
        else:
            # Type-2 verbs (``juoda``, ``syödä``, ``saada``) end in a long
            # vowel after dropping ``-da`` / ``-dä``; the 3sg form is the
            # bare stem with no extra suffix: ``juoda -> juo`` not ``juoe``.
            predicted = stem
        return (
            predicted,
            f"verb/{kind}/pres.3.sg",
            f"{lemma}: pres 3sg = {predicted!r}",
        )

    if person == "3" and number == "pl":
        if kind == "type2":
            # ``juoda -> juovat``: the ``v`` linker bridges the stem to
            # ``-vat`` / ``-vät``.
            suffix = "vat" if _harmony(stem) == "back" else "vät"
        else:
            suffix = "vat" if _harmony(stem) == "back" else "vät"
        predicted = stem + suffix
        return (
            predicted,
            f"verb/{kind}/pres.3.pl",
            f"{lemma}: pres 3pl = {stem!r} + {suffix}",
        )

    finite_suffix = {
        ("1", "sg"): "n",
        ("2", "sg"): "t",
        ("1", "pl"): "mme",
        ("2", "pl"): "tte",
    }.get((person, number))
    if finite_suffix is None:
        return None, None, f"verb form person={person} number={number} not covered"

    return (
        finite_stem + finite_suffix,
        f"verb/{kind}/pres.{person}.{number}",
        f"{lemma}: pres {person}{number} = {finite_stem!r} + {finite_suffix}",
    )


def _predict_verb_oitse_variant(
    *, lemma: str, person: str, number: str, source_class: str | None = None
) -> str | None:
    """Return the explicitly supported long ``-oitse`` present variant."""

    source_class_norm = (source_class or "").casefold()
    if (
        lemma not in _OITSE_PRESENT_LEMMAS
        and "68/tupakoida" not in source_class_norm
    ):
        return None
    suffixes = {
        ("1", "sg"): "tsen",
        ("2", "sg"): "tset",
        ("3", "sg"): "tsee",
        ("1", "pl"): "tsemme",
        ("2", "pl"): "tsette",
        ("3", "pl"): "tsevat" if _harmony(lemma) == "back" else "tsevät",
    }
    suffix = suffixes.get((person, number))
    return lemma[:-2] + suffix if suffix is not None else None


def _predict_verb(
    *,
    lemma: str,
    tense: str | None,
    mood: str | None,
    person: str | None,
    number: str | None,
    infinitive: bool,
) -> tuple[str | None, str | None, str]:
    if infinitive:
        return lemma, "verb/infinitive", f"{lemma}: infinitive form = base"
    tense_norm = tense.lower() if tense else None
    mood_norm = mood.lower() if mood else None
    if tense_norm in {None, "pres", "present"} and mood_norm in {None, "ind", "indicative"}:
        if person and number:
            return _predict_verb_present(lemma=lemma, person=person, number=number)
    return None, None, "verb tense/mood combination not covered"
