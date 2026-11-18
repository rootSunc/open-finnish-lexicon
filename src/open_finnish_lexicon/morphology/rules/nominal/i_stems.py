"""Nominal -i / -si / comparative / numeral / foreign -ori stem paradigms."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.nominal.classify import (
    _has_neutral_terminal_component,
    _is_usi_family,
)
from open_finnish_lexicon.morphology.rules.phonology import (
    _AmbiguousGradation,
    _apply_weak_grade,
    _is_vowel,
    _suffix_with_harmony,
)

def _i_stem_genitive(lemma: str) -> str:
    """Native -i stem (kotus 5): ``risti`` -> ``ristin``.

    Foreign loans (kotus 6, ``paperi``) use the same singular pattern.
    """

    if _is_usi_family(lemma):
        return lemma[:-2] + "de"
    try:
        weak = _apply_weak_grade(lemma)
    except _AmbiguousGradation:
        return lemma
    if weak != lemma:
        # ``akuutti`` -> ``akuut-i`` -> ``akuutin`` and
        # ``antiikki`` -> ``antiik-i`` -> ``antiikin``.
        return weak[:-1] + "i"
    return lemma


# A compact lexeme row does not retain the Kotus declension number.  Most
# ``-i`` nouns are regular enough for the risti/paperi pattern, but several
# high-frequency words use an e-stem in singular oblique forms and/or retain
# the i-stem in plural oblique forms.  These tables are deliberately used as
# validation alternatives; the generic path remains the deterministic
# prediction for unseen loanwords.
_I_STEM_SINGULAR_STEM_OVERRIDES = {
    "kieli": "kiele",
    "mieli": "miele",
    "nimi": "nime",
    "ovi": "ove",
    "kuusi": "kuuse",
    "lapsi": "lapse",
    "käsi": "käde",
    "uusi": "uude",
    "pieni": "piene",
    "suuri": "suure",
    "lumi": "lume",
    "tuli": "tule",
    "veri": "vere",
    "vuosi": "vuode",
    "täysi": "täyde",
    "sieni": "siene",
    "nuori": "nuore",
    "puoli": "puole",
    "tyyni": "tyyne",
    "tosi": "tode",
    "laki": "lai",
    "joki": "joe",
    "kansi": "kanne",
    "varsi": "varre",
    "kuori": "kuore",
    "vuori": "vuore",
    "veli": "velje",
    "meri": "mere",
}

_I_STEM_PLURAL_STEM_OVERRIDES = {
    # The value includes the plural ``-i-`` before case endings.  Thus
    # ``kieli`` + ``ssä`` gives ``kielissä`` while ``risti`` uses
    # ``ristei`` and gives ``risteissä``.
    "kieli": "kieli",
    "mieli": "mieli",
    "nimi": "nimi",
    "ovi": "ovi",
    "koti": "kodei",
    "kuusi": "kuusi",
    "lapsi": "lapsi",
    "käsi": "käsi",
    "uusi": "uusi",
    "pieni": "pieni",
    "suuri": "suuri",
    "lumi": "lumi",
    "tuli": "tuli",
    "veri": "veri",
    "vuosi": "vuosi",
    "täysi": "täysi",
    "sieni": "sieni",
    "äiti": "äidei",
    "nuori": "nuori",
    "puoli": "puoli",
    "tyyni": "tyyni",
    "tosi": "tosi",
    "laki": "laei",
    "joki": "joi",
    "kansi": "kansi",
    "varsi": "varsi",
    "kuori": "kuori",
    "vuori": "vuori",
    "veli": "velji",
    "meri": "meri",
}

_I_STEM_NOMINATIVE_PLURAL_OVERRIDES = {
    "kieli": "kielet",
    "mieli": "mielet",
    "nimi": "nimet",
    "ovi": "ovet",
    "koti": "kodit",
    "kuusi": "kuuset",
    "lapsi": "lapset",
    "käsi": "kädet",
    "uusi": "uudet",
    "pieni": "pienet",
    "suuri": "suuret",
    "lumi": "lumet",
    "tuli": "tulet",
    "veri": "veret",
    "vuosi": "vuodet",
    "täysi": "täydet",
    "sieni": "sienet",
    "laki": "laet",
    "nuori": "nuoret",
    "puoli": "puolet",
    "tyyni": "tyynet",
    "tosi": "todet",
    "kansi": "kannet",
    "varsi": "varret",
    "kuori": "kuoret",
    "vuori": "vuoret",
    "veli": "veljet",
    "meri": "meret",
}

_I_STEM_PARTITIVE_SINGULAR_OVERRIDES = {
    "kieli": "kieltä",
    "mieli": "mieltä",
    "koti": "kotia",
    "kuusi": "kuusta",
    "lapsi": "lasta",
    "käsi": "kättä",
    "uusi": "uutta",
    "pieni": "pientä",
    "suuri": "suurta",
    "lumi": "lunta",
    "tuli": "tulta",
    "veri": "verta",
    "vuosi": "vuotta",
    "täysi": "täyttä",
    "sieni": "sientä",
    "nuori": "nuorta",
    "puoli": "puolta",
    "tyyni": "tyyntä",
    "tosi": "totta",
    "kansi": "kantta",
    "varsi": "vartta",
    "vesi": "vettä",
    "kuori": "kuorta",
    "vuori": "vuorta",
    "veli": "veljeä",
    "meri": "merta",
    "toimi": "tointa",
    "lohi": "lohta",
    "syli": "syltä",
    "uni": "unta",
    "kasi": "kasta",
    "kusi": "kusta",
    "kypsi": "kystä",
    "sonsari": "sonsarta",
}

_I_STEM_STRONG_SINGULAR_STEM_OVERRIDES = {
    # The same lexical families that have a ``d`` weak stem use ``t`` before
    # the singular illative and essive suffixes: uusi -> uute-en/uute-na,
    # käsi -> käte-en/käte-nä.
    "uusi": "uute",
    "käsi": "käte",
    "vesi": "vete",
    "vuosi": "vuote",
    "täysi": "täyte",
    "kansi": "kante",
    "varsi": "varte",
    "veli": "velje",
}

_I_STEM_PLURAL_GENITIVE_VARIANTS = {
    "kieli": {"kielien", "kielten"},
    "mieli": {"mielien", "mielten"},
    "lapsi": {"lapsien", "lasten"},
    "pieni": {"pienien", "pienten"},
    "suuri": {"suurien", "suurten"},
    "kuusi": {"kuusien", "kuusten"},
    "paperi": {"paperien", "papereiden", "papereitten"},
    "nuori": {"nuorien", "nuorten"},
    "puoli": {"puolien", "puolten"},
    "tyyni": {"tyynien", "tyynten"},
    "laki": {"lakien", "laitten"},
    "kansi": {"kansien", "kantten"},
    "varsi": {"varsien", "varsten"},
    "vesi": {"vesien", "vetten"},
    "kuori": {"kuorien", "kuorten"},
    "vuori": {"vuorien", "vuorten"},
    "veli": {"veljien", "veljten"},
    "meri": {"merien", "merten"},
    "toimi": {"toimien", "tointen"},
    "lumi": {"lumien", "lunten"},
    "tuli": {"tulien", "tulten"},
    "sieni": {"sienien", "sienten"},
    "syli": {"sylien", "sylten"},
    "uni": {"unien", "unten"},
    "kasi": {"kasien", "kasten"},
    "kusi": {"kusien", "kusten"},
    "kypsi": {"kypsien", "kysten"},
    "sonsari": {"sonsarien", "sonsarten"},
}


_I_STEM_CLUSTER_WEAKENINGS = (
    ("nk", "ng"),
    ("rk", "rj"),
    ("lk", "lj"),
    ("ns", "nn"),
    ("rs", "rr"),
    ("ls", "ll"),
    ("ks", "hd"),
)

_I_STEM_STRONGENINGS = (
    ("ks", "ht"),
    ("rs", "rt"),
    ("ls", "lt"),
    ("ns", "nt"),
    ("s", "t"),
)


def _i_stem_weak_base_variants(lemma: str) -> set[str]:
    """Return consonant bases used by native ``-i`` alternations.

    The general phonology helper intentionally refuses ambiguous single
    ``p/t/k`` gradation.  The ``-i`` declension has several productive
    source patterns around that ambiguity, so keep their alternatives local
    to this rule instead of changing consonant gradation for every noun:
    ``hanki -> hang-``, ``kurki -> kurj-``, ``hupi -> huv-``, and
    ``joki -> jo-``.
    """

    if not lemma.endswith("i"):
        return set()
    base = lemma[:-1]
    variants = {base}
    try:
        weak = _apply_weak_grade(lemma)
    except _AmbiguousGradation:
        weak = lemma
    if weak != lemma:
        variants.add(weak[:-1])

    for strong, weak_cluster in _I_STEM_CLUSTER_WEAKENINGS:
        if base.endswith(strong):
            variants.add(base[: -len(strong)] + weak_cluster)

    for strong, weak_cluster in (("gg", "g"), ("bb", "b"), ("ff", "f")):
        if base.endswith(strong):
            variants.add(base[: -len(strong)] + weak_cluster)

    if base.endswith("p") and not base.endswith("pp"):
        variants.add(base[:-1] + "v")
    elif base.endswith("t") and not base.endswith("tt"):
        variants.add(base[:-1] + "d")
    elif base.endswith("k") and (len(base) == 1 or _is_vowel(base[-2])):
        # ``laki -> lai`` / ``joki -> joi`` have a deleted-k path.  Keep the
        # g-grade too; it is used by a small number of loanword families.
        variants.add(base[:-1])
        variants.add(base[:-1] + "g")
    elif base.endswith("s") and not base.endswith(("ns", "rs")):
        variants.add(base[:-1] + "d")
    return variants


def _i_stem_strong_base_variants(lemma: str) -> set[str]:
    """Return strong bases used by ``-s`` i-stem allomorphs."""

    if not lemma.endswith("i"):
        return set()
    base = lemma[:-1]
    variants: set[str] = set()
    for strong, strengthened in _I_STEM_STRONGENINGS:
        if base.endswith(strong):
            variants.add(base[: -len(strong)] + strengthened)
    return variants


def _is_foreign_ori_family(lemma: str) -> bool:
    """Whether ``lemma`` uses the long-``ii`` ``ori`` loanword pattern."""

    # ``kuori`` and ``vuori`` are native e-stem families, not ``ori`` loans.
    return lemma.endswith("ori") and not lemma.endswith(("kuori", "vuori"))


def _i_stem_suffix_with_harmony(
    stem: str,
    back_suffix: str,
    front_suffix: str,
    *,
    lemma: str | None = None,
) -> str:
    """Choose an i-stem suffix without letting compound prefixes dominate."""

    harmony_root = lemma[:-1] if lemma and lemma.endswith("i") else stem
    if _has_neutral_terminal_component(harmony_root):
        return front_suffix
    return _suffix_with_harmony(stem, back_suffix, front_suffix)


def _i_stem_suffix_options(
    stem: str,
    back_suffix: str,
    front_suffix: str,
    *,
    lemma: str,
) -> set[str]:
    """Return both the lexical and conservative compound-harmony paths."""

    # A compact lemma cannot tell whether a neutral-vowel ending is an
    # independent compound component (front harmony) or part of a loanword
    # whose earlier back vowel still controls harmony. Keep both complete
    # suffix choices as validation alternatives; the deterministic path
    # continues to use the ordinary lexical harmony rule.
    return {
        back_suffix,
        front_suffix,
        _suffix_with_harmony(stem, back_suffix, front_suffix),
        _i_stem_suffix_with_harmony(
            stem, back_suffix, front_suffix, lemma=lemma
        ),
    }


def _i_stem_component_override(
    lemma: str, overrides: dict[str, str]
) -> str | None:
    """Apply a known final component override to a compound lemma."""

    for component in sorted(overrides, key=len, reverse=True):
        if lemma.endswith(component):
            return lemma[: -len(component)] + overrides[component]
    return None


def _i_stem_singular_stem_variants(lemma: str) -> set[str]:
    """Return common singular stems for ``-i`` nouns.

    ``risti`` and ``paperi`` use the lemma as their singular stem, while
    ``kieli``/``nimi``/``ovi`` use ``-e-`` in the oblique paradigm.  The
    final ``-si`` and ``-ti`` families also have productive-looking ``d``
    alternations, but their illative and partitive cells are lexical; those
    cells are handled separately below.
    """

    if not lemma.endswith("i"):
        return set()
    base = lemma[:-1]
    variants = {lemma, base + "e"}
    for weak_base in _i_stem_weak_base_variants(lemma):
        variants.update({weak_base + "i", weak_base + "e"})
    for strong_base in _i_stem_strong_base_variants(lemma):
        variants.add(strong_base + "e")
    override = _I_STEM_SINGULAR_STEM_OVERRIDES.get(lemma)
    if override:
        variants.add(override)
    component_override = _i_stem_component_override(
        lemma, _I_STEM_SINGULAR_STEM_OVERRIDES
    )
    if component_override:
        variants.add(component_override)
    strong_override = _I_STEM_STRONG_SINGULAR_STEM_OVERRIDES.get(lemma)
    if strong_override:
        variants.add(strong_override)
    strong_component_override = _i_stem_component_override(
        lemma, _I_STEM_STRONG_SINGULAR_STEM_OVERRIDES
    )
    if strong_component_override:
        variants.add(strong_component_override)
    if _is_foreign_ori_family(lemma):
        variants.add(lemma[:-1] + "ii")
    for component, stem in {
        "kuusi": "kuute",
        "viisi": "viite",
    }.items():
        if lemma.endswith(component) and lemma != component:
            variants.add(lemma[: -len(component)] + stem)
    if lemma.endswith("si"):
        variants.add(lemma[:-2] + "de")
    if lemma.endswith("ti"):
        variants.add(lemma[:-2] + "di")
        variants.add(lemma[:-2] + "de")
        variants.add(lemma[:-2] + "d")
    if lemma.endswith("si"):
        variants.add(lemma[:-2] + "de")
        variants.add(lemma[:-2] + "d")
    return variants


def _i_stem_plural_stem_variants(lemma: str) -> set[str]:
    """Return plural oblique stems including ``ristei``-style variants."""

    if not lemma.endswith("i"):
        return set()
    variants = {lemma, lemma[:-1] + "ei"}
    for stem in _i_stem_singular_stem_variants(lemma):
        if stem.endswith("i"):
            variants.update({stem, stem[:-1] + "ei"})
        elif stem.endswith("e"):
            variants.add(stem + "i")
    override = _I_STEM_PLURAL_STEM_OVERRIDES.get(lemma)
    if override:
        variants.add(override)
    component_override = _i_stem_component_override(
        lemma, _I_STEM_PLURAL_STEM_OVERRIDES
    )
    if component_override:
        variants.add(component_override)
    if lemma.endswith("ti"):
        variants.update(
            {
                lemma[:-2] + "dei",
                lemma[:-2] + "di",
            }
        )
    if lemma.endswith("si"):
        variants.add(lemma[:-2] + "dei")
    if _is_foreign_ori_family(lemma):
        variants.add(lemma[:-1] + "ii")
    return variants


def _predict_i_stem_comparative_variants(
    *, lemma: str, case: str, number: str
) -> set[str]:
    """Return the ``-mpi`` adjective paradigm (vanhempi/parempi)."""

    if not lemma.endswith("mpi") or len(lemma) <= 3:
        return set()
    weak = lemma[:-3] + "mm"
    strong = lemma[:-1]
    values: set[str] = set()
    if number == "sg":
        if case in {"gen", "acc"}:
            values.update({weak + "an", weak + "än"})
        elif case == "par":
            values.update({strong + "aa", strong + "ää"})
        elif case == "abe":
            values.update({weak + "atta", weak + "ättä"})
        elif case in {"ine", "ela", "ade", "abl"}:
            suffixes = {
                "ine": ("assa", "ässä"),
                "ela": ("asta", "ästä"),
                "ade": ("alla", "ällä"),
                "abl": ("alta", "ältä"),
            }
            back_suffix, front_suffix = suffixes[case]
            values.update({weak + back_suffix, weak + front_suffix})
        elif case == "ill":
            values.update({strong + "aan", strong + "ään"})
        elif case == "ess":
            values.update({strong + "ana", strong + "änä"})
        elif case == "all":
            values.update({weak + "alle", weak + "älle"})
        elif case == "tra":
            values.update({weak + "aksi", weak + "äksi"})
    elif number == "pl":
        if case in {"nom", "acc"}:
            values.update({weak + "at", weak + "ät"})
        elif case == "gen":
            values.add(lemma + "en")
        elif case == "par":
            values.update({strong + "ia", strong + "iä"})
        elif case in {"ine", "ela", "ade", "abl"}:
            suffixes = {
                "ine": ("ssa", "ssä"),
                "ela": ("sta", "stä"),
                "ade": ("lla", "llä"),
                "abl": ("lta", "ltä"),
            }
            back_suffix, front_suffix = suffixes[case]
            values.update({weak + back_suffix, weak + front_suffix})
        elif case == "ill":
            values.add(strong + "iin")
        elif case == "ess":
            values.update({strong + "ina", strong + "inä"})
        elif case == "all":
            values.add(weak + "ille")
        elif case == "tra":
            values.add(weak + "iksi")
        elif case == "ins":
            values.add(weak + "in")
        elif case == "com":
            values.add(strong + "ine")
        elif case == "abe":
            values.update({weak + "itta", weak + "ittä"})
    return values


def _predict_i_stem_numeral_variants(
    *, lemma: str, case: str, number: str
) -> set[str]:
    """Return compound variants ending in ``kaksi`` or ``yksi``."""

    if number != "sg":
        return set()
    if lemma.endswith("kaksi"):
        ending = "kaksi"
        oblique = "kahde"
        strong = "kahte"
        partitive = "kahta"
        essive = "kahtena"
    elif lemma.endswith("yksi"):
        ending = "yksi"
        oblique = "yhde"
        strong = "yhte"
        partitive = "yhtä"
        essive = "yhtenä"
    else:
        return set()
    prefix = lemma[: -len(ending)]
    oblique_stem = prefix + oblique
    values: set[str] = set()
    if case in {"gen", "acc"}:
        values.add(oblique_stem + "n")
    elif case == "par":
        values.add(prefix + partitive)
    elif case == "abe":
        values.update({oblique_stem + "tta", oblique_stem + "ttä"})
    elif case in {"ine", "ela", "ade", "abl"}:
        suffixes = {
            "ine": ("ssa", "ssä"),
            "ela": ("sta", "stä"),
            "ade": ("lla", "llä"),
            "abl": ("lta", "ltä"),
        }
        back_suffix, front_suffix = suffixes[case]
        values.update(
            oblique_stem + suffix
            for suffix in {back_suffix, front_suffix}
        )
    elif case == "ill":
        values.add(prefix + strong + "en")
    elif case == "ess":
        values.add(prefix + essive)
    elif case == "all":
        values.add(oblique_stem + "lle")
    elif case == "tra":
        values.add(oblique_stem + "ksi")
    return values


def _predict_i_stem_foreign_ori_variants(
    *, lemma: str, case: str, number: str
) -> set[str]:
    """Return the long-``ii`` ``ori`` loanword paradigm."""

    if not _is_foreign_ori_family(lemma):
        return set()
    stem = lemma[:-1] + "ii"
    if number == "sg":
        if case == "par":
            return {lemma + "tta"}
        suffixes = {
            "gen": "n",
            "acc": "n",
            "abe": "tta",
            "ine": "ssa",
            "ela": "sta",
            "ade": "lla",
            "abl": "lta",
            "ill": "seen",
            "ess": "na",
            "all": "lle",
            "tra": "ksi",
        }
        suffix = suffixes.get(case)
        return {stem + suffix} if suffix is not None else set()
    if number == "pl":
        if case in {"nom", "acc"}:
            return {lemma + "it"}
        if case == "gen":
            return {lemma + "iden", lemma + "itten"}
        if case == "par":
            return {lemma + "ita"}
        if case in {"ine", "ela", "ade", "abl"}:
            suffixes = {
                "ine": "ssa",
                "ela": "sta",
                "ade": "lla",
                "abl": "lta",
            }
            return {stem + suffixes[case]}
        if case == "ill":
            return {stem + "hin", stem + "siin"}
        if case == "ess":
            return {stem + "na"}
        if case == "all":
            return {stem + "lle"}
        if case == "tra":
            return {stem + "ksi"}
        if case == "ins":
            return {stem + "n"}
        if case == "com":
            return {stem + "ne"}
        if case == "abe":
            return {stem + "tta"}
    return set()


def _predict_i_stem_variants(
    *, lemma: str, case: str, number: str
) -> set[str]:
    """Return source-compatible alternatives for the common ``-i`` classes."""

    if not lemma.endswith("i"):
        return set()
    values: set[str] = set()
    values.update(
        _predict_i_stem_numeral_variants(
            lemma=lemma,
            case=case,
            number=number,
        )
    )
    values.update(
        _predict_i_stem_comparative_variants(
            lemma=lemma,
            case=case,
            number=number,
        )
    )
    values.update(
        _predict_i_stem_foreign_ori_variants(
            lemma=lemma,
            case=case,
            number=number,
        )
    )
    if number == "sg":
        for stem in _i_stem_singular_stem_variants(lemma):
            if case in {"gen", "acc"}:
                values.add(stem + "n")
            elif case == "abe":
                values.update(
                    stem + suffix
                    for suffix in _i_stem_suffix_options(
                        stem, "tta", "ttä", lemma=lemma
                    )
                )
            elif case == "par":
                values.update(
                    stem + suffix
                    for suffix in _i_stem_suffix_options(
                        stem, "a", "ä", lemma=lemma
                    )
                )
            elif case in {"ine", "ela", "ade", "abl"}:
                suffixes = {
                    "ine": ("ssa", "ssä"),
                    "ela": ("sta", "stä"),
                    "ade": ("lla", "llä"),
                    "abl": ("lta", "ltä"),
                }
                back_suffix, front_suffix = suffixes[case]
                values.update(
                    stem + suffix
                    for suffix in _i_stem_suffix_options(
                        stem, back_suffix, front_suffix, lemma=lemma
                    )
                )
            elif case == "ill":
                values.add(stem + ("en" if stem.endswith("e") else "in"))
            elif case == "ess":
                values.update(
                    stem + suffix
                    for suffix in _i_stem_suffix_options(
                        stem, "na", "nä", lemma=lemma
                    )
                )
            elif case == "all":
                values.add(stem + "lle")
            elif case == "tra":
                values.add(stem + "ksi")
        override = _I_STEM_PARTITIVE_SINGULAR_OVERRIDES.get(lemma)
        if case == "par" and override:
            values.add(override)
        component_override = _i_stem_component_override(
            lemma, _I_STEM_PARTITIVE_SINGULAR_OVERRIDES
        )
        if case == "par" and component_override:
            values.add(component_override)
        if case == "par":
            base = lemma[:-1]
            if base.endswith("ks"):
                values.update(
                    base[:-2] + "ht" + suffix
                    for suffix in _i_stem_suffix_options(
                        base, "a", "ä", lemma=lemma
                    )
                )
            elif base.endswith("s"):
                values.update(
                    base[:-1] + "tt" + suffix
                    for suffix in _i_stem_suffix_options(
                        base, "a", "ä", lemma=lemma
                    )
                )
        # ``äiti``/``koti``/``uusi`` and the other -ti/-si families retain
        # an i- or d-stem in selected cells rather than the simple e-stem.
        if lemma == "äiti":
            values.update(
                {
                    "äidin" if case in {"gen", "acc"} else "äitiin"
                    if case == "ill"
                    else "äitinä"
                    if case == "ess"
                    else "äitiä"
                    if case == "par"
                    else "äidittä"
                    if case == "abe"
                    else "äidissä"
                    if case == "ine"
                    else "äidistä"
                    if case == "ela"
                    else "äidillä"
                    if case == "ade"
                    else "äidiltä"
                    if case == "abl"
                    else "äidille"
                    if case == "all"
                    else "äidiksi"
                    if case == "tra"
                    else lemma
                }
            )
    elif number == "pl":
        for stem in _i_stem_plural_stem_variants(lemma):
            if case in {"ine", "ela", "ade", "abl"}:
                suffixes = {
                    "ine": ("ssa", "ssä"),
                    "ela": ("sta", "stä"),
                    "ade": ("lla", "llä"),
                    "abl": ("lta", "ltä"),
                }
                back_suffix, front_suffix = suffixes[case]
                values.update(
                    stem + suffix
                    for suffix in _i_stem_suffix_options(
                        stem, back_suffix, front_suffix, lemma=lemma
                    )
                )
            elif case == "ill":
                values.update({stem + "in", stem + "hin"})
            elif case == "ess":
                values.update(
                    stem + suffix
                    for suffix in _i_stem_suffix_options(
                        stem, "na", "nä", lemma=lemma
                    )
                )
            elif case == "all":
                values.add(stem + "lle")
            elif case == "tra":
                values.add(stem + "ksi")
            elif case == "ins":
                values.add(stem + "n")
            elif case == "com":
                values.add(stem + "ne")
            elif case == "abe":
                values.update(
                    stem + suffix
                    for suffix in _i_stem_suffix_options(
                        stem, "tta", "ttä", lemma=lemma
                    )
                )
        if case in {"nom", "acc"}:
            values.add(lemma[:-1] + "et")
            values.update(
                stem + "t"
                for stem in _i_stem_singular_stem_variants(lemma)
                if stem.endswith(("i", "e"))
            )
            if lemma.endswith(("si", "ti")):
                values.update(
                    {
                        lemma[:-2] + "det",
                        lemma[:-2] + "dit",
                    }
                )
            override = _I_STEM_NOMINATIVE_PLURAL_OVERRIDES.get(lemma)
            if override:
                values.add(override)
            component_override = _i_stem_component_override(
                lemma, _I_STEM_NOMINATIVE_PLURAL_OVERRIDES
            )
            if component_override:
                values.add(component_override)
        if case == "gen":
            values.add(lemma + "en")
            values.update(
                {
                    lemma[:-1] + "eiden",
                    lemma[:-1] + "eitten",
                }
            )
            values.update(_I_STEM_PLURAL_GENITIVE_VARIANTS.get(lemma, set()))
            for component, variants_for_component in _I_STEM_PLURAL_GENITIVE_VARIANTS.items():
                if lemma.endswith(component):
                    prefix = lemma[: -len(component)]
                    values.update(
                        prefix + variant
                        for variant in variants_for_component
                    )
            base = lemma[:-1]
            if base.endswith("ks"):
                values.add(base[:-2] + "hten")
            elif base.endswith("s"):
                values.add(base[:-1] + "tten")
        if case == "par":
            plural_e_stem = lemma[:-1] + "e"
            values.update(
                plural_e_stem + suffix
                for suffix in _i_stem_suffix_options(
                    plural_e_stem, "ja", "jä", lemma=lemma
                )
            )
            values.update(
                plural_e_stem + suffix
                for suffix in _i_stem_suffix_options(
                    plural_e_stem, "ita", "itä", lemma=lemma
                )
            )
            values.update(
                lemma + suffix
                for suffix in _i_stem_suffix_options(
                    lemma, "a", "ä", lemma=lemma
                )
            )
            for stem in _i_stem_plural_stem_variants(lemma):
                if stem.endswith("i"):
                    values.update({stem + "a", stem + "ä"})
    return values
