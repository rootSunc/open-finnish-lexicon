"""Verb classification and finite/passive-form prediction (Types 1–6)."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.phonology import (
    _AmbiguousGradation,
    _apply_weak_grade,
    _harmony,
    _is_vowel,
)
from open_finnish_lexicon.morphology.rules.types import ALL_VOWELS

_IRREGULAR_PRESENT_FORMS: dict[str, dict[tuple[str, str], str]] = {
    "olla": {
        ("1", "sg"): "olen",
        ("2", "sg"): "olet",
        ("3", "sg"): "on",
        ("1", "pl"): "olemme",
        ("2", "pl"): "olette",
        ("3", "pl"): "ovat",
    },
    "tehdä": {
        ("1", "sg"): "teen",
        ("2", "sg"): "teet",
        ("3", "sg"): "tekee",
        ("1", "pl"): "teemme",
        ("2", "pl"): "teette",
        ("3", "pl"): "tekevät",
    },
    "nähdä": {
        ("1", "sg"): "näen",
        ("2", "sg"): "näet",
        ("3", "sg"): "näkee",
        ("1", "pl"): "näemme",
        ("2", "pl"): "näette",
        ("3", "pl"): "näkevät",
    },
    "käydä": {
        ("1", "sg"): "käyn",
        ("2", "sg"): "käyt",
        ("3", "sg"): "käy",
        ("1", "pl"): "käymme",
        ("2", "pl"): "käytte",
        ("3", "pl"): "käyvät",
    },
    "tulla": {
        ("1", "sg"): "tulen",
        ("2", "sg"): "tulet",
        ("3", "sg"): "tulee",
        ("1", "pl"): "tulemme",
        ("2", "pl"): "tulette",
        ("3", "pl"): "tulevat",
    },
    "mennä": {
        ("1", "sg"): "menen",
        ("2", "sg"): "menet",
        ("3", "sg"): "menee",
        ("1", "pl"): "menemme",
        ("2", "pl"): "menette",
        ("3", "pl"): "menevät",
    },
    "juosta": {
        ("1", "sg"): "juoksen",
        ("2", "sg"): "juokset",
        ("3", "sg"): "juoksee",
        ("1", "pl"): "juoksemme",
        ("2", "pl"): "juoksette",
        ("3", "pl"): "juoksevat",
    },
    "syöstä": {
        ("1", "sg"): "syöksen",
        ("2", "sg"): "syökset",
        ("3", "sg"): "syöksee",
        ("1", "pl"): "syöksemme",
        ("2", "pl"): "syöksette",
        ("3", "pl"): "syöksevät",
    },
    "piekstä": {
        ("1", "sg"): "pieksen",
        ("2", "sg"): "piekset",
        ("3", "sg"): "pieksee",
        ("1", "pl"): "pieksemme",
        ("2", "pl"): "pieksette",
        ("3", "pl"): "pieksevät",
    },
    "sulkea": {
        ("1", "sg"): "suljen",
        ("2", "sg"): "suljet",
        ("3", "sg"): "sulkee",
        ("1", "pl"): "suljemme",
        ("2", "pl"): "suljette",
        ("3", "pl"): "sulkevat",
    },
    "kulkea": {
        ("1", "sg"): "kuljen",
        ("2", "sg"): "kuljet",
        ("3", "sg"): "kulkee",
        ("1", "pl"): "kuljemme",
        ("2", "pl"): "kuljette",
        ("3", "pl"): "kulkevat",
    },
    "pyyhkiä": {
        ("1", "sg"): "pyyhin",
        ("2", "sg"): "pyyhit",
        ("3", "sg"): "pyyhkii",
        ("1", "pl"): "pyyhimme",
        ("2", "pl"): "pyyhitte",
        ("3", "pl"): "pyyhkivät",
    },
    "polkea": {
        ("1", "sg"): "poljen",
        ("2", "sg"): "poljet",
        ("3", "sg"): "polkee",
        ("1", "pl"): "poljemme",
        ("2", "pl"): "poljette",
        ("3", "pl"): "polkevat",
    },
    "särkeä": {
        ("1", "sg"): "särjen",
        ("2", "sg"): "särjet",
        ("3", "sg"): "särkee",
        ("1", "pl"): "särjemme",
        ("2", "pl"): "särjette",
        ("3", "pl"): "särkevät",
    },
    "nylkeä": {
        ("1", "sg"): "nyljen",
        ("2", "sg"): "nyljet",
        ("3", "sg"): "nylkee",
        ("1", "pl"): "nyljemme",
        ("2", "pl"): "nyljette",
        ("3", "pl"): "nylkevät",
    },
    "hylkiä": {
        ("1", "sg"): "hyljin",
        ("2", "sg"): "hyljit",
        ("3", "sg"): "hylkii",
        ("1", "pl"): "hyljimme",
        ("2", "pl"): "hyljitte",
        ("3", "pl"): "hylkivät",
    },
    "sylkeä": {
        ("1", "sg"): "syljen",
        ("2", "sg"): "syljet",
        ("3", "sg"): "sylkee",
        ("1", "pl"): "syljemme",
        ("2", "pl"): "syljette",
        ("3", "pl"): "sylkevät",
    },
}

_IRREGULAR_PAST_FORMS: dict[str, dict[tuple[str, str], str]] = {
    "olla": {
        ("1", "sg"): "olin",
        ("2", "sg"): "olit",
        ("3", "sg"): "oli",
        ("1", "pl"): "olimme",
        ("2", "pl"): "olitte",
        ("3", "pl"): "olivat",
    },
    "tehdä": {
        ("1", "sg"): "tein",
        ("2", "sg"): "teit",
        ("3", "sg"): "teki",
        ("1", "pl"): "teimme",
        ("2", "pl"): "teitte",
        ("3", "pl"): "tekivät",
    },
    "nähdä": {
        ("1", "sg"): "näin",
        ("2", "sg"): "näit",
        ("3", "sg"): "näki",
        ("1", "pl"): "näimme",
        ("2", "pl"): "näitte",
        ("3", "pl"): "näkivät",
    },
    "käydä": {
        ("1", "sg"): "kävin",
        ("2", "sg"): "kävit",
        ("3", "sg"): "kävi",
        ("1", "pl"): "kävimme",
        ("2", "pl"): "kävitte",
        ("3", "pl"): "kävivät",
    },
    "tulla": {
        ("1", "sg"): "tulin",
        ("2", "sg"): "tulit",
        ("3", "sg"): "tuli",
        ("1", "pl"): "tulimme",
        ("2", "pl"): "tulitte",
        ("3", "pl"): "tulivat",
    },
    "mennä": {
        ("1", "sg"): "menin",
        ("2", "sg"): "menit",
        ("3", "sg"): "meni",
        ("1", "pl"): "menimme",
        ("2", "pl"): "menitte",
        ("3", "pl"): "menivät",
    },
    "juosta": {
        ("1", "sg"): "juoksin",
        ("2", "sg"): "juoksit",
        ("3", "sg"): "juoksi",
        ("1", "pl"): "juoksimme",
        ("2", "pl"): "juoksitte",
        ("3", "pl"): "juoksivat",
    },
    "syöstä": {
        ("1", "sg"): "syöksin",
        ("2", "sg"): "syöksit",
        ("3", "sg"): "syöksi",
        ("1", "pl"): "syöksimme",
        ("2", "pl"): "syöksitte",
        ("3", "pl"): "syöksivät",
    },
    "piekstä": {
        ("1", "sg"): "pieksin",
        ("2", "sg"): "pieksit",
        ("3", "sg"): "pieksi",
        ("1", "pl"): "pieksimme",
        ("2", "pl"): "pieksitte",
        ("3", "pl"): "pieksivät",
    },
}

_IRREGULAR_CONDITIONAL_STEMS: dict[str, str] = {
    "olla": "olisi",
    "tehdä": "tekisi",
    "nähdä": "näkisi",
    "käydä": "kävisi",
    "tulla": "tulisi",
    "mennä": "menisi",
    "juosta": "juoksisi",
    "syöstä": "syöksisi",
    "piekstä": "pieksisi",
    "sulkea": "sulkisi",
    "kulkea": "kulkisi",
    "polkea": "polkisi",
    "särkeä": "särkisi",
    "nylkeä": "nylkisi",
    "hylkiä": "hylkisi",
    "sylkeä": "sylkisi",
    "pyyhkiä": "pyyhkisi",
}

# Safe 5+ character irregular verb bases that form closed compounds in Finnish
# (e.g. ``ulostehdä``, ``oikosulkea``, ``poissulkea``, ``alaspolkea``) without
# colliding with unrelated simplex verbs such as ``kuolla`` / ``vuolla``.
_COMPOUND_IRREGULAR_BASES: tuple[str, ...] = (
    "pyyhkiä",
    "sulkea",
    "kulkea",
    "polkea",
    "särkeä",
    "nylkeä",
    "hylkiä",
    "sylkeä",
    "juosta",
    "syöstä",
    "piekstä",
    "tehdä",
    "nähdä",
    "käydä",
)


def _split_compound_irregular(lemma: str) -> tuple[str, str] | None:
    if lemma in _IRREGULAR_PRESENT_FORMS:
        return "", lemma
    for base in _COMPOUND_IRREGULAR_BASES:
        if lemma.endswith(base) and len(lemma) >= len(base) + 2:
            prefix = lemma[: -len(base)]
            if prefix[-1] in ALL_VOWELS or prefix[-1] in {"s", "n", "-"}:
                return prefix, base
    return None


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

_TYPE4_ITA_EXCEPTIONS = frozenset(
    {"selvitä", "levitä", "hirvitä", "lämmitä", "silitä", "hellitä"}
)

_TYPE6_LEMMAS = frozenset(
    {
        "vanheta",
        "kylmetä",
        "pimetä",
        "lyhetä",
        "tihetä",
        "suureta",
        "pienetä",
        "nuoreta",
        "kometa",
        "heiketä",
        "tummeta",
        "halveta",
    }
)

_TYPE4_ETA_LEMMAS = frozenset({"nimetä", "herjetä", "kerjetä"})

_NON_GRADATING_CLUSTERS = frozenset(
    {
        "sk",
        "st",
        "ts",
        "tk",
        "hv",
        "nh",
        "hm",
        "hn",
        "hr",
        "hl",
        "rj",
        "lj",
        "vj",
        "ls",
        "rs",
        "ns",
        "ps",
        "ks",
        "ht",
    }
)
_NON_GRADATING_SINGLES = frozenset({"s", "v", "j", "h", "l", "r", "m", "n"})


def _classify_verb(lemma: str, source_class: str = "") -> str | None:
    """Return verb conjugation type (``type1``..``type6``) or ``None``."""

    if not lemma or len(lemma) < 3:
        return None
    sc = source_class.casefold()
    if " and " in sc:
        # Hybrid multi-paradigm verbs (e.g. ``seistä``: ``66/rohkaista and 52/sanoa``).
        return None
    if lemma.endswith(("ua", "yä", "oa", "öä", "ia", "iä", "aa", "ää", "ea", "eä")):
        return "type1"
    if lemma.endswith(("da", "dä")):
        return "type2"
    if lemma.endswith(("lla", "llä", "nna", "nnä", "rra", "rrä", "sta", "stä")):
        return "type3"
    if "72/" in sc or "vanheta" in sc:
        return "type6"
    if lemma.endswith(("ita", "itä")):
        if any(tag in sc for tag in ("73/", "74/", "75/", "salata", "katketa", "selvitä")) or (
            "69/" not in sc and "valita" not in sc and lemma in _TYPE4_ITA_EXCEPTIONS
        ):
            return "type4"
        return "type5"
    if lemma.endswith(("eta", "etä")):
        if lemma in _TYPE6_LEMMAS:
            return "type6"
        if (
            any(tag in sc for tag in ("73/", "74/", "75/", "salata", "katketa", "selvitä"))
            or lemma in _TYPE4_ETA_LEMMAS
        ):
            return "type4"
        return None
    if lemma.endswith(("ata", "ätä", "ota", "ötä", "uta", "ytä")):
        return "type4"
    return None


def _apply_reverse_gradation(base: str, source_class: str = "") -> str | None:
    """Resolve weak-to-strong consonant gradation on ``base`` (Type 3/4/6).

    Returns ``None`` when gradation is lexically ambiguous without an explicit
    ``source_class`` marker so the validator emits ``UNCERTAIN`` instead of a
    false ``MISMATCH``.
    """

    sc = source_class.casefold()
    if "no gradation" in sc:
        return base

    last_vowel_idx = -1
    for idx in range(len(base) - 1, -1, -1):
        if _is_vowel(base[idx]):
            last_vowel_idx = idx
            break
    if last_vowel_idx <= 0:
        return base

    cluster_end = last_vowel_idx
    cluster_start = cluster_end
    while cluster_start > 0 and not _is_vowel(base[cluster_start - 1]):
        cluster_start -= 1

    cluster = base[cluster_start:cluster_end]
    if cluster_start == 0:
        return base

    def _replace_cluster(old_tail: str, new_tail: str) -> str | None:
        if not cluster.endswith(old_tail):
            return None
        return base[:cluster_start] + cluster[: -len(old_tail)] + new_tail + base[cluster_end:]

    explicit_pairs = (
        (("tt–t", "t–tt"), "t", "tt"),
        (("pp–p", "p–pp"), "p", "pp"),
        (("kk–k", "k–kk"), "k", "kk"),
        (("nt–nn", "nn–nt"), "nn", "nt"),
        (("mp–mm", "mm–mp"), "mm", "mp"),
        (("lt–ll", "ll–lt"), "ll", "lt"),
        (("rt–rr", "rr–rt"), "rr", "rt"),
        (("nk–ng", "ng–nk"), "ng", "nk"),
        (("ht–hd", "hd–ht"), "hd", "ht"),
        (("t–d", "d–t"), "d", "t"),
        (("p–v", "v–p"), "v", "p"),
        (("lv–lp", "lp–lv"), "lv", "lp"),
        (("rv–rp", "rp–rv"), "rv", "rp"),
        (("lj–lk", "lk–lj", "rj–rk", "rk–rj", "k–j", "j–k"), "j", "k"),
    )
    for markers, weak_pat, strong_pat in explicit_pairs:
        if any(m in sc for m in markers):
            replaced = _replace_cluster(weak_pat, strong_pat)
            if replaced is not None:
                return replaced

    if "k–∅" in sc or "∅–k" in sc:
        if cluster in {"r", "l", "h"}:
            return base[:cluster_start] + cluster + "k" + base[cluster_end:]
        if not cluster and len(base) >= 2 and _is_vowel(base[-1]) and _is_vowel(base[-2]):
            return base[:-1] + "k" + base[-1]
        return None

    if not cluster:
        # Vowel hiatus (e.g. ``vierailla`` -> ``vierail``, ``hymyillä`` -> ``hymyil``)
        # has no consonant cluster.
        return base

    # Productive polysyllabic ``-tella/-tellä`` verbs (``ajatella -> ajattele-``,
    # ``esitellä -> esittele-``, ``suunnitella -> suunnittele-``) geminate ``t -> tt``.
    if (
        cluster == "t"
        and base.endswith("tel")
        and len(base) >= 5
        and _is_vowel(base[cluster_start - 1])
    ):
        return base[:cluster_start] + "tt" + base[cluster_end:]

    # Unambiguous reverse-gradation clusters even without source_class:
    for weak_pat, strong_pat in (
        ("ng", "nk"),
        ("hd", "ht"),
        ("mm", "mp"),
    ):
        if cluster.endswith(weak_pat):
            return base[:cluster_start] + cluster[: -len(weak_pat)] + strong_pat + base[cluster_end:]

    if cluster in _NON_GRADATING_SINGLES or cluster in _NON_GRADATING_CLUSTERS:
        return base

    return None


def _strong_vowel_stem(lemma: str, kind: str, source_class: str = "") -> str | None:
    if kind == "type1":
        return lemma[:-1]
    if kind == "type2":
        return lemma[:-2]
    if kind == "type3":
        if lemma.endswith(("sta", "stä")):
            # ``nousta -> nouse``, ``pestä -> pese``, ``julkaista -> julkaise``
            base = lemma[:-2]
            strong_base = _apply_reverse_gradation(base, source_class)
            return strong_base + "e" if strong_base is not None else None
        # ``opiskella -> opiskele``, ``purra -> pure``, ``mennä -> mene``
        base = lemma[:-2]
        strong_base = _apply_reverse_gradation(base, source_class)
        return strong_base + "e" if strong_base is not None else None
    if kind == "type4":
        # ``haluta -> halua``, ``avata -> avaa``, ``vastata -> vastaa``
        base = lemma[:-2]
        strong_base = _apply_reverse_gradation(base, source_class)
        if strong_base is None:
            return None
        a_char = "a" if _harmony(lemma) == "back" else "ä"
        return strong_base + a_char
    if kind == "type5":
        # ``tarvita -> tarvitse``, ``valita -> valitse``
        return lemma[:-2] + "tse"
    if kind == "type6":
        # ``vanheta -> vanhene``
        base = lemma[:-2]
        strong_base = _apply_reverse_gradation(base, source_class)
        return strong_base + "ne" if strong_base is not None else None
    return None


def _verb_present_finite_stem(stem: str) -> str:
    if len(stem) >= 3 and stem[:-1].endswith("hk"):
        return stem
    return _apply_weak_grade(stem)


def _personal_suffix(person: str, number: str, stem_for_harmony: str) -> str | None:
    if (person, number) == ("3", "pl"):
        return "vat" if _harmony(stem_for_harmony) == "back" else "vät"
    return {
        ("1", "sg"): "n",
        ("2", "sg"): "t",
        ("1", "pl"): "mme",
        ("2", "pl"): "tte",
    }.get((person, number))


def _predict_verb_present(
    *, lemma: str, person: str, number: str, source_class: str = ""
) -> tuple[str | None, str | None, str]:
    split = _split_compound_irregular(lemma)
    if split is not None:
        prefix, base_verb = split
        irregular_forms = _IRREGULAR_PRESENT_FORMS.get(base_verb)
        if irregular_forms is not None:
            base_pred = irregular_forms.get((person, number))
            if base_pred is not None:
                predicted = prefix + base_pred
                return (
                    predicted,
                    f"verb/irregular/pres.{person}.{number}",
                    f"{lemma}: irregular present form = {predicted!r}",
                )

    kind = _classify_verb(lemma, source_class)
    if kind is None:
        return None, None, f"verb {lemma!r} does not match a covered type"

    stem = _strong_vowel_stem(lemma, kind, source_class)
    if stem is None:
        return None, None, f"{lemma}: reverse gradation stem is ambiguous without template"

    if kind == "type1":
        if "no gradation" in source_class.casefold():
            finite_stem = stem
        else:
            try:
                finite_stem = _verb_present_finite_stem(stem)
            except _AmbiguousGradation as exc:
                return (
                    None,
                    None,
                    f"{lemma}: verb gradation on {exc.args[0]!r} is too lemma-specific",
                )
    else:
        finite_stem = stem

    if person == "3" and number == "sg":
        if kind == "type2":
            predicted = stem
        elif kind == "type4" and len(stem) >= 2 and stem[-1] == stem[-2]:
            # ``avata -> avaa`` (already ends in long ``aa``/``ää``), whereas
            # ``haluta -> haluaa`` (``ua`` + ``a``? No: ``halua`` ends in ``ua``, so ``halua + a = haluaa``!).
            predicted = stem
        else:
            predicted = stem + stem[-1]
        return (
            predicted,
            f"verb/{kind}/pres.3.sg",
            f"{lemma}: pres 3sg = {predicted!r}",
        )

    suffix = _personal_suffix(person, number, lemma)
    if suffix is None:
        return None, None, f"verb form person={person} number={number} not covered"

    target_stem = stem if (person, number) == ("3", "pl") else finite_stem
    predicted = target_stem + suffix
    return (
        predicted,
        f"verb/{kind}/pres.{person}.{number}",
        f"{lemma}: pres {person}{number} = {target_stem!r} + {suffix}",
    )


def _predict_verb_past(
    *, lemma: str, person: str, number: str, source_class: str = ""
) -> tuple[str | None, str | None, str]:
    split = _split_compound_irregular(lemma)
    if split is not None:
        prefix, base_verb = split
        irregular_past = _IRREGULAR_PAST_FORMS.get(base_verb)
        if irregular_past is not None:
            base_pred = irregular_past.get((person, number))
            if base_pred is not None:
                predicted = prefix + base_pred
                return (
                    predicted,
                    f"verb/irregular/past.{person}.{number}",
                    f"{lemma}: irregular past form = {predicted!r}",
                )

    kind = _classify_verb(lemma, source_class)
    if kind is None:
        return None, None, f"verb {lemma!r} does not match a covered type"

    suffix = "" if (person, number) == ("3", "sg") else _personal_suffix(person, number, lemma)
    if suffix is None:
        return None, None, f"verb past person={person} number={number} not covered"

    if kind == "type1":
        # ``-aa/-ää`` and ``-ea/-eä`` past stems split lexically between ``-oi/-i``
        # and ``-si`` assibilation; keep deterministic prediction to ``-ua/-yä``,
        # ``-oa/-öä`` and ``-ia/-iä``.
        if not lemma.endswith(("ua", "yä", "oa", "öä", "ia", "iä")):
            return None, None, f"{lemma}: type-1 past vowel/assibilation is lemma-specific"
        strong_stem = lemma[:-1]
        if (person, number) in {("3", "sg"), ("3", "pl")} or "no gradation" in source_class.casefold():
            stem_used = strong_stem
        else:
            try:
                stem_used = _verb_present_finite_stem(strong_stem)
            except _AmbiguousGradation as exc:
                return (
                    None,
                    None,
                    f"{lemma}: verb past gradation on {exc.args[0]!r} is too lemma-specific",
                )
        past_stem = stem_used if stem_used.endswith("i") else stem_used + "i"
        predicted = past_stem + suffix
        return (
            predicted,
            f"verb/type1/past.{person}.{number}",
            f"{lemma}: past {person}{number} = {predicted!r}",
        )

    if kind == "type2":
        stem = lemma[:-2]
        if stem.endswith(("uo", "yö", "ie")):
            past_stem = stem[:-2] + stem[-1] + "i"
        elif len(stem) >= 2 and stem[-1] == stem[-2] and _is_vowel(stem[-1]):
            past_stem = stem[:-1] + "i"
        elif stem.endswith("i"):
            past_stem = stem
        else:
            return None, None, f"{lemma}: type-2 past stem not covered"
        predicted = past_stem + suffix
        return (
            predicted,
            f"verb/type2/past.{person}.{number}",
            f"{lemma}: past {person}{number} = {predicted!r}",
        )

    stem = _strong_vowel_stem(lemma, kind, source_class)
    if stem is None:
        return None, None, f"{lemma}: past stem gradation is ambiguous"

    if kind in {"type3", "type5", "type6"}:
        # ``opiskele -> opiskeli``, ``tarvitse -> tarvitsi``, ``vanhene -> vanheni``
        past_stem = stem[:-1] + "i"
    elif kind == "type4":
        # ``halua -> halusi``, ``avaa -> avasi``, ``tarjoa -> tarjosi``
        past_stem = stem[:-1] + "si"
    else:
        return None, None, f"{lemma}: past stem not covered"

    predicted = past_stem + suffix
    return (
        predicted,
        f"verb/{kind}/past.{person}.{number}",
        f"{lemma}: past {person}{number} = {predicted!r}",
    )


def _predict_verb_conditional(
    *, lemma: str, person: str, number: str, source_class: str = ""
) -> tuple[str | None, str | None, str]:
    suffix = "" if (person, number) == ("3", "sg") else _personal_suffix(person, number, lemma)
    if suffix is None:
        return None, None, f"verb conditional person={person} number={number} not covered"

    split = _split_compound_irregular(lemma)
    if split is not None:
        prefix, base_verb = split
        cond_base = _IRREGULAR_CONDITIONAL_STEMS.get(base_verb)
        if cond_base is not None:
            predicted = prefix + cond_base + suffix
            return (
                predicted,
                f"verb/irregular/cnd.{person}.{number}",
                f"{lemma}: conditional {person}{number} = {predicted!r}",
            )

    kind = _classify_verb(lemma, source_class)
    if kind is None:
        return None, None, f"verb {lemma!r} does not match a covered type"

    if kind == "type1":
        stem = lemma[:-1]
        cond_stem = (stem[:-1] if stem.endswith(("e", "i")) else stem) + "isi"
    elif kind == "type2":
        stem = lemma[:-2]
        if stem.endswith(("uo", "yö", "ie")):
            cond_stem = stem[:-2] + stem[-1] + "isi"
        elif len(stem) >= 2 and stem[-1] == stem[-2] and _is_vowel(stem[-1]):
            cond_stem = stem[:-1] + "isi"
        elif stem.endswith("i"):
            cond_stem = stem[:-1] + "isi"
        else:
            return None, None, f"{lemma}: type-2 conditional stem not covered"
    else:
        stem = _strong_vowel_stem(lemma, kind, source_class)
        if stem is None:
            return None, None, f"{lemma}: conditional stem gradation is ambiguous"
        if kind == "type4":
            # ``avaa -> avaisi``, ``halua -> haluaisi``
            cond_stem = (stem[:-1] if len(stem) >= 2 and stem[-1] == stem[-2] else stem) + "isi"
        else:
            # ``opiskele -> opiskelisi``, ``tarvitse -> tarvitsisi``, ``vanhene -> vanhenisi``
            cond_stem = stem[:-1] + "isi"

    predicted = cond_stem + suffix
    return (
        predicted,
        f"verb/{kind}/cnd.{person}.{number}",
        f"{lemma}: conditional {person}{number} = {predicted!r}",
    )


def _predict_verb_present_passive(
    *, lemma: str, source_class: str = ""
) -> tuple[str | None, str | None, str]:
    kind = _classify_verb(lemma, source_class)
    if kind is None:
        return None, None, f"verb {lemma!r} does not match a covered type"

    if kind in {"type2", "type3", "type4", "type5", "type6"}:
        # In Finnish, Types 2–6 form the present passive directly from the
        # 1st infinitive + ``-an/-än`` (``juodaan``, ``ollaan``, ``tullaan``,
        # ``opiskellaan``, ``noustaan``, ``halutaan``, ``tarvitaan``, ``vanhetaan``).
        ending = "an" if _harmony(lemma) == "back" else "än"
        predicted = lemma + ending
        return (
            predicted,
            f"verb/{kind}/pres.pass",
            f"{lemma}: present passive = {predicted!r}",
        )

    # Type 1: weak finite stem (with final ``a/ä -> e``) + ``-taan/-tään``.
    split = _split_compound_irregular(lemma)
    if split is not None:
        prefix, base_verb = split
        if base_verb in {"sulkea", "kulkea", "polkea", "särkeä", "nylkeä", "sylkeä"}:
            # ``suljetaan``, ``kuljetaan``, ``särjetään``
            one_sg = _IRREGULAR_PRESENT_FORMS[base_verb][("1", "sg")]
            weak_stem = prefix + one_sg[:-1]
            ending = "taan" if _harmony(lemma) == "back" else "tään"
            predicted = weak_stem + ending
            return (
                predicted,
                "verb/irregular/pres.pass",
                f"{lemma}: present passive = {predicted!r}",
            )
        if base_verb in {"pyyhkiä", "hylkiä"}:
            one_sg = _IRREGULAR_PRESENT_FORMS[base_verb][("1", "sg")]
            weak_stem = prefix + one_sg[:-1]
            ending = "taan" if _harmony(lemma) == "back" else "tään"
            predicted = weak_stem + ending
            return (
                predicted,
                "verb/irregular/pres.pass",
                f"{lemma}: present passive = {predicted!r}",
            )

    strong_stem = lemma[:-1]
    if "no gradation" in source_class.casefold():
        weak_stem = strong_stem
    else:
        try:
            weak_stem = _verb_present_finite_stem(strong_stem)
        except _AmbiguousGradation as exc:
            return (
                None,
                None,
                f"{lemma}: passive gradation on {exc.args[0]!r} is too lemma-specific",
            )
    if weak_stem.endswith(("a", "ä")):
        weak_stem = weak_stem[:-1] + "e"
    ending = "taan" if _harmony(lemma) == "back" else "tään"
    predicted = weak_stem + ending
    return (
        predicted,
        "verb/type1/pres.pass",
        f"{lemma}: present passive = {predicted!r}",
    )


def _predict_verb_oitse_variant(
    *,
    lemma: str,
    person: str,
    number: str,
    source_class: str | None = None,
    mode: str = "pres",
) -> str | None:
    """Return the explicitly supported long ``-oitse`` finite variant (Kotus 68)."""

    source_class_norm = (source_class or "").casefold()
    if lemma not in _OITSE_PRESENT_LEMMAS and "68/tupakoida" not in source_class_norm:
        return None
    vat = "vat" if _harmony(lemma) == "back" else "vät"
    if mode == "pres":
        suffixes = {
            ("1", "sg"): "tsen",
            ("2", "sg"): "tset",
            ("3", "sg"): "tsee",
            ("1", "pl"): "tsemme",
            ("2", "pl"): "tsette",
            ("3", "pl"): f"tse{vat}",
        }
    elif mode == "past":
        suffixes = {
            ("1", "sg"): "tsin",
            ("2", "sg"): "tsit",
            ("3", "sg"): "tsi",
            ("1", "pl"): "tsimme",
            ("2", "pl"): "tsitte",
            ("3", "pl"): f"tsi{vat}",
        }
    elif mode == "cnd":
        suffixes = {
            ("1", "sg"): "tsisin",
            ("2", "sg"): "tsisit",
            ("3", "sg"): "tsisi",
            ("1", "pl"): "tsisimme",
            ("2", "pl"): "tsisitte",
            ("3", "pl"): f"tsisi{vat}",
        }
    else:
        return None
    suffix = suffixes.get((person, number))
    return lemma[:-2] + suffix if suffix is not None else None


def _predict_verb_type4_contracted_conditional(
    *, lemma: str, person: str, number: str, source_class: str = ""
) -> str | None:
    """Return Kotus 74/75 contracted conditional (e.g. ``kirota -> kiroisin``)."""

    if _classify_verb(lemma, source_class) != "type4":
        return None
    stem = _strong_vowel_stem(lemma, "type4", source_class)
    if (
        stem is None
        or len(stem) < 2
        or not _is_vowel(stem[-1])
        or not _is_vowel(stem[-2])
        or stem[-1] == stem[-2]
    ):
        return None
    suffix = "" if (person, number) == ("3", "sg") else _personal_suffix(person, number, lemma)
    if suffix is None:
        return None
    return stem[:-1] + "isi" + suffix


def _predict_verb(
    *,
    lemma: str,
    tense: str | None,
    mood: str | None,
    person: str | None,
    number: str | None,
    infinitive: bool,
    passive: bool = False,
    source_class: str = "",
) -> tuple[str | None, str | None, str]:
    if infinitive:
        return lemma, "verb/infinitive", f"{lemma}: infinitive form = base"
    tense_norm = tense.lower().strip() if tense else None
    mood_norm = mood.lower().strip() if mood else None

    if passive:
        if mood_norm in {None, "ind", "indicative"} and tense_norm in {None, "pres", "present"}:
            return _predict_verb_present_passive(lemma=lemma, source_class=source_class)
        return None, None, "passive tense/mood combination not covered"

    if mood_norm in {"cnd", "cond", "conditional"} and tense_norm in {None, "pres", "present"}:
        if person and number:
            return _predict_verb_conditional(
                lemma=lemma,
                person=person,
                number=number,
                source_class=source_class,
            )
        return None, None, "conditional person/number missing"

    if mood_norm in {None, "ind", "indicative"}:
        if tense_norm in {None, "pres", "present"} and person and number:
            return _predict_verb_present(
                lemma=lemma,
                person=person,
                number=number,
                source_class=source_class,
            )
        if tense_norm in {"past", "imperfect", "impf"} and person and number:
            return _predict_verb_past(
                lemma=lemma,
                person=person,
                number=number,
                source_class=source_class,
            )
    return None, None, "verb tense/mood combination not covered"
