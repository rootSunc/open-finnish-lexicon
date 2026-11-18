"""Nominal -nen, -us/-ys, -uus/-yys, -as/-äs, and gradation/retention variants."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.nominal.classify import (
    _classify_nominal,
    _has_neutral_terminal_component,
)
from open_finnish_lexicon.morphology.rules.phonology import (
    _is_vowel,
    _suffix_with_harmony,
)

def _nen_stem(lemma: str) -> str:
    return lemma[:-3] + "se"


def _us_stem(lemma: str) -> str:
    """Return the strong ``-kse-`` stem for the ``-us/-ys/-os/-ös`` class."""

    for ending, replacement in (
        ("us", "ukse"),
        ("ys", "ykse"),
        ("os", "okse"),
        ("ös", "ökse"),
    ):
        if lemma.endswith(ending):
            return lemma[:-2] + replacement
    return lemma


def _us_de_stem(lemma: str) -> str | None:
    """Return the alternative ``-ude/-yde-`` stem used by Kotus 40.

    Finnish ``-us/-ys`` nouns split between the ``vastaus`` pattern
    (``vastaukse-``) and the ``kalleus`` pattern (``kalleude-``). The lemma
    alone is not enough to distinguish the two, so validation accepts the
    second stem as an explicitly documented lexical variant.
    """

    if lemma.endswith("us"):
        return lemma[:-2] + "ude"
    if lemma.endswith("ys"):
        return lemma[:-2] + "yde"
    return None


def _predict_us_de_variant(
    *, lemma: str, case: str, number: str
) -> str | None:
    """Predict a Kotus-40 alternative for an otherwise ``us_stem`` lemma."""

    stem = _us_de_stem(lemma)
    if stem is None:
        return None
    strong_stem = lemma[:-1] + "te"
    if number == "sg":
        if case == "nom":
            return lemma
        if case in {"gen", "acc"}:
            return stem + "n"
        if case == "abe":
            return stem + _suffix_with_harmony(stem, "tta", "ttä")
        if case == "par":
            suffix = _suffix_with_harmony(lemma, "a", "ä")
            return lemma[:-1] + "tt" + suffix
        if case in {"ine", "ela", "ade", "abl"}:
            suffixes = {
                "ine": ("ssa", "ssä"),
                "ela": ("sta", "stä"),
                "ade": ("lla", "llä"),
                "abl": ("lta", "ltä"),
            }
            back_suffix, front_suffix = suffixes[case]
            return stem + _suffix_with_harmony(stem, back_suffix, front_suffix)
        if case == "ill":
            return strong_stem + "en"
        if case == "ess":
            return strong_stem + _suffix_with_harmony(strong_stem, "na", "nä")
        if case == "all":
            return stem + "lle"
        if case == "tra":
            return stem + "ksi"
    if number == "pl" and case in {"nom", "acc"}:
        return stem + "t"
    return None


# ``couscous`` is a Finnish loanword whose source paradigm uses the risti
# (foreign-i) pattern even though its spelling ends in ``-us``. Keep this
# lexical exception exact: applying it to every ``-us`` noun would turn the
# productive ``vastaus`` paradigm into false positives.
_US_FOREIGN_I_LEMMAS = frozenset({"couscous"})


def _predict_us_foreign_i_variant(
    *, lemma: str, case: str, number: str
) -> set[str]:
    """Return the source-compatible foreign-i paradigm for ``couscous``."""

    if lemma not in _US_FOREIGN_I_LEMMAS:
        return set()
    if number == "sg":
        suffixes = {
            "gen": "in",
            "acc": "in",
            "par": "ia",
            "ine": "issa",
            "ela": "ista",
            "ill": "iin",
            "ade": "illa",
            "abl": "ilta",
            "all": "ille",
            "ess": "ina",
            "tra": "iksi",
            "abe": "itta",
        }
        suffix = suffixes.get(case)
        return {lemma + suffix} if suffix is not None else set()
    if number == "pl":
        suffixes = {
            "nom": "it",
            "acc": "it",
            "gen": "ien",
            "par": "eja",
            "ine": "eissa",
            "ela": "eista",
            "ill": "eihin",
            "ade": "eilla",
            "abl": "eilta",
            "all": "eille",
            "ess": "eina",
            "tra": "eiksi",
            "abe": "eitta",
            "ins": "ein",
            "com": "eine",
        }
        suffix = suffixes.get(case)
        return {lemma + suffix} if suffix is not None else set()
    return set()


def _uus_stem(lemma: str) -> str:
    """``naisuus`` -> ``naisuude``, ``ylevyys`` -> ``ylevyyde``.

    Kotus 40/41 abstract nouns: the final ``-s`` is replaced by ``-de``
    to give the oblique stem. The case suffix attaches directly to it.
    """

    if lemma.endswith("uus"):
        return lemma[:-1] + "de"
    return lemma[:-1] + "de"  # -yys case shares the shape


_AS_STEM_REVERSE_GRADATION: tuple[tuple[str, str], ...] = (
    ("ng", "nk"),
    ("mm", "mp"),
    ("nn", "nt"),
    ("ll", "lt"),
    ("rr", "rt"),
    ("hd", "ht"),
)


def _as_strong_stem(lemma: str) -> str:
    """``sisukas`` -> ``sisukkaa``, ``vieras`` -> ``vieraa``.

    Replace the ``-as`` / ``-äs`` ending with the long ``-aa`` / ``-ää``
    strong stem, applying reverse consonant gradation so:

        kangas  -> kankaa-     (ng -> nk)
        lammas  -> lampaa-     (mm -> mp)
        tehdas  -> tehtaa-     (hd -> ht)
        porras  -> portaa-     (rr -> rt)
        hidas   -> hitaa-      (single d -> t)
        sisukas -> sisukkaa-   (intervocalic k -> kk)
        hurskas -> hurskaa-    (k in cluster, no gemination)
        vieras  -> vieraa-     (no gradation)
    """

    is_back = lemma.endswith("as")
    suffix = "aa" if is_back else "ää"
    base = lemma[:-2]
    if not base:
        return base + suffix

    for weak, strong in _AS_STEM_REVERSE_GRADATION:
        if base.endswith(weak):
            return base[: -len(weak)] + strong + suffix

    last_char = base[-1]
    # Single intervocalic d -> t (hidas -> hitaan).
    if last_char == "d" and len(base) >= 2 and _is_vowel(base[-2]):
        return base[:-1] + "t" + suffix
    # Single intervocalic k / p / t -> geminate (sisukas -> sisukkaan).
    # When the stop is part of a consonant cluster (hurskas), gradation
    # does not apply and the stem stays the same.
    if last_char in {"k", "p", "t"} and len(base) >= 2 and _is_vowel(base[-2]):
        return base + last_char + suffix
    return base + suffix


def _as_strong_stem_variants(lemma: str) -> set[str]:
    """Return plausible strong stems for an ``-as/-äs`` lemma.

    The ``vieras`` template stores the weak and strong consonant separately;
    that information is not present in the normalized lexeme.  Keep the
    deterministic prediction as the primary result, but expose the small
    set of regular reverse-gradation alternatives so source validation does
    not reject common words such as ``paras -> parha-`` and ``varas ->
    varkaa-``.
    """

    base = lemma[:-2]
    if not base:
        return {_as_strong_stem(lemma)}
    suffix = "aa" if lemma.endswith("as") else "ää"
    variants = {_as_strong_stem(lemma)}
    if base[-1] in {"k", "p", "t"} and len(base) >= 2 and not _is_vowel(base[-2]):
        variants.add(base + base[-1] + suffix)
    if base.endswith("r"):
        # ``paras -> parha-`` and ``varas -> varkaa-`` are both productive
        # weak-to-strong alternations, but the lemma does not disambiguate
        # which consonant is restored.
        variants.add(base + "h" + suffix)
        variants.add(base + "k" + suffix)
    if base[-1] == "v":
        variants.add(base[:-1] + "p" + suffix)
    if base[-1] == "l":
        variants.add(base + "k" + suffix)
    return variants


def _predict_as_variant(*, lemma: str, case: str, number: str) -> set[str]:
    """Return full-form alternatives for the ``-as/-äs`` paradigm."""

    stems = _as_strong_stem_variants(lemma)
    if number == "pl" and case in {"nom", "acc"}:
        return {stem + "t" for stem in stems}
    if case == "abe":
        if number == "sg":
            return {
                stem + _suffix_with_harmony(stem, "tta", "ttä")
                for stem in stems
            }
        if number == "pl":
            return {
                stem[:-1]
                + "i"
                + _suffix_with_harmony(stem, "tta", "ttä")
                for stem in stems
            }
    if case == "ins" and number == "pl":
        return {stem[:-1] + "in" for stem in stems}
    if case == "com" and number == "pl":
        return {stem[:-1] + "ine" for stem in stems}
    if number != "sg":
        return set()
    if case in {"gen", "acc"}:
        return {stem + "n" for stem in stems}
    if case in {"ine", "ela", "ade", "abl"}:
        suffixes = {
            "ine": ("ssa", "ssä"),
            "ela": ("sta", "stä"),
            "ade": ("lla", "llä"),
            "abl": ("lta", "ltä"),
        }
        back_suffix, front_suffix = suffixes[case]
        return {
            stem + _suffix_with_harmony(stem, back_suffix, front_suffix)
            for stem in stems
        }
    if case == "ill":
        return {stem + "seen" for stem in stems}
    if case == "ess":
        return {stem + _suffix_with_harmony(stem, "na", "nä") for stem in stems}
    if case == "all":
        return {stem + "lle" for stem in stems}
    if case == "tra":
        return {stem + "ksi" for stem in stems}
    return set()


def _predict_as_aks_variant(*, lemma: str, case: str, number: str) -> set[str]:
    """Return the ``-aks-`` oblique stem used by words such as ``lihas``."""

    base = lemma[:-2]
    stem = base + ("äks" if lemma.endswith("äs") else "aks")
    if number == "pl" and case in {"nom", "acc"}:
        return {stem + "et"}
    if case == "abe":
        if number == "sg":
            return {stem + ("että" if lemma.endswith("äs") else "etta")}
        if number == "pl":
            return {stem + ("ittä" if lemma.endswith("äs") else "itta")}
    if case == "ins" and number == "pl":
        return {stem + "in"}
    if case == "com" and number == "pl":
        return {stem + "ine"}
    if number != "sg":
        return set()
    suffixes = {
        "gen": "en",
        "acc": "en",
        "ine": ("essä" if lemma.endswith("äs") else "essa"),
        "ela": ("estä" if lemma.endswith("äs") else "esta"),
        "ade": ("ellä" if lemma.endswith("äs") else "ella"),
        "abl": ("eltä" if lemma.endswith("äs") else "elta"),
        "ill": "een",
        "ess": ("enä" if lemma.endswith("äs") else "ena"),
        "all": "elle",
        "tra": "eksi",
    }
    suffix = suffixes.get(case)
    return {stem + suffix} if suffix is not None else set()


def _predict_as_long_variant(*, lemma: str, case: str, number: str) -> set[str]:
    """Return the long-vowel strong stem used by ``kunnas`` and ``kynnäs``."""

    base = lemma[:-2]
    stem = base + ("ää" if lemma.endswith("äs") else "aa")
    if number == "pl" and case in {"nom", "acc"}:
        return {stem + "t"}
    if case == "abe":
        if number == "sg":
            return {stem + ("ttä" if lemma.endswith("äs") else "tta")}
        if number == "pl":
            return {
                stem[:-1]
                + "i"
                + ("ttä" if lemma.endswith("äs") else "tta")
            }
    if case == "ins" and number == "pl":
        return {stem[:-1] + "in"}
    if case == "com" and number == "pl":
        return {stem[:-1] + "ine"}
    if number != "sg":
        return set()
    suffixes = {
        "gen": "n",
        "acc": "n",
        "ine": ("ssä" if lemma.endswith("äs") else "ssa"),
        "ela": ("stä" if lemma.endswith("äs") else "sta"),
        "ade": ("llä" if lemma.endswith("äs") else "lla"),
        "abl": ("ltä" if lemma.endswith("äs") else "lta"),
        "ill": "seen",
        "ess": ("nä" if lemma.endswith("äs") else "na"),
        "all": "lle",
        "tra": "ksi",
    }
    suffix = suffixes.get(case)
    return {stem + suffix} if suffix is not None else set()


def _predict_as_ordinal_variant(*, lemma: str, case: str, number: str) -> set[str]:
    """Return the ``-nne-`` paradigm used by ordinal adjectives."""

    base = lemma[:-2]
    front = lemma.endswith("äs")
    stem = base + ("änne" if front else "anne")
    if number == "pl" and case in {"nom", "acc"}:
        return {stem + "t"}
    if number == "pl" and case in {"abe", "ins", "com"}:
        if case == "abe":
            return {base + ("änsittä" if front else "ansitta")}
        if case == "ins":
            return {base + ("änsin" if front else "ansin")}
        return {base + ("änsine" if front else "ansine")}
    if number != "sg":
        return set()
    if case == "par":
        return {base + ("ättä" if front else "atta")}
    if case == "abe":
        return {base + ("ännettä" if front else "annetta")}
    # The illative and essive use the shorter ``-nte-`` allomorph while
    # genitive/locative cells keep the ``-nne-`` stem.
    if case == "ill":
        return {base + ("änteen" if front else "anteen")}
    if case == "ess":
        return {base + ("äntenä" if front else "antena")}
    suffixes = {
        "gen": "n",
        "acc": "n",
        "ine": ("ssä" if front else "ssa"),
        "ela": ("stä" if front else "sta"),
        "ade": ("llä" if front else "lla"),
        "abl": ("ltä" if front else "lta"),
        "all": "lle",
        "tra": "ksi",
    }
    suffix = suffixes.get(case)
    return {stem + suffix} if suffix is not None else set()


def _predict_as_foreign_i_variant(*, lemma: str, case: str, number: str) -> set[str]:
    """Return the ``-i-`` loanword paradigm used by ``sassafras``."""

    front = lemma.endswith("äs")
    if number == "pl" and case in {"nom", "acc"}:
        return {lemma + "it"}
    if case == "abe":
        if number == "sg":
            # Foreign ``-as`` loans such as ``sassafras`` use the i-stem
            # allomorph in the abessive singular: sassafrasitta.
            return {lemma + ("ittä" if front else "itta")}
        if number == "pl":
            return {lemma + ("eittä" if front else "eitta")}
    if case == "ins" and number == "pl":
        return {lemma + "ein"}
    if case == "com" and number == "pl":
        return {lemma + "eine"}
    if number != "sg":
        return set()
    suffixes = {
        "gen": "in",
        "acc": "in",
        "par": ("iä" if front else "ia"),
        "ine": ("issä" if front else "issa"),
        "ela": ("istä" if front else "ista"),
        "ade": ("illä" if front else "illa"),
        "abl": ("iltä" if front else "ilta"),
        "ill": "iin",
        "ess": ("inä" if front else "ina"),
        "all": "ille",
        "tra": "iksi",
    }
    suffix = suffixes.get(case)
    return {lemma + suffix} if suffix is not None else set()


def _predict_nen_variants(
    *, lemma: str, case: str, number: str, allow_back_harmony: bool = False
) -> set[str]:
    """Return compound-harmony and ``kymmenen`` alternatives."""

    if lemma.endswith("kymmenen"):
        plural_base = lemma[:-2]  # kymmen- + -et / -ittä
        if number == "pl" and case in {"nom", "acc"}:
            return {plural_base + "et"}
        if number == "pl" and case in {"abe", "ins", "com"}:
            stem = plural_base + "i"
            if case == "abe":
                return {plural_base + "ittä"}
            if case == "ins":
                return {stem + "n"}
            return {stem + "ne"}
        if number == "sg" and case in {"acc", "gen"}:
            return {lemma[:-1] + "n"}
        if number == "sg" and case == "abe":
            return {lemma[:-1] + "ttä"}

    # Compounds whose final -nen component contains only neutral vowels use
    # front-harmony suffixes even when an earlier component contains a, o or
    # u (aamuihminen -> aamuihmisettä / aamuihmisittä). Loanword tables can
    # select back harmony for the same neutral-vowel shape, so keep both
    # source-compatible suffixes as validation alternatives.
    has_compound_neutral_harmony = _has_neutral_terminal_component(lemma[:-3])
    if number == "pl" and case == "abe" and (
        has_compound_neutral_harmony or allow_back_harmony
    ):
        stem = _nen_stem(lemma)[:-1]
        values = {stem + "ittä"}
        if allow_back_harmony:
            values.add(stem + "itta")
        return values
    if number != "sg":
        return set()

    is_kymmenen = lemma.endswith("kymmenen")
    if is_kymmenen:
        oblique_stem = lemma[:-1]  # kymmene- + n/ssa/...
        root = lemma[:-3]
        if case == "par":
            return {lemma[:-2] + "tä"}
    else:
        oblique_stem = _nen_stem(lemma)
        root = lemma[:-3]
        if not _has_neutral_terminal_component(root) and not allow_back_harmony:
            return set()

    if case == "gen":
        return {oblique_stem + "n"}
    if case == "acc":
        return {oblique_stem + "n"}
    if case == "abe":
        values = {oblique_stem + "ttä"}
        if allow_back_harmony:
            values.add(oblique_stem + "tta")
        return values
    if case == "par":
        if is_kymmenen:
            return {lemma[:-2] + "tä"}
        values = {root + "stä"}
        if allow_back_harmony:
            values.add(root + "sta")
        return values
    if case in {"ine", "ela", "ade", "abl"}:
        suffixes = {
            "ine": ("ssä", "ssa"),
            "ela": ("stä", "sta"),
            "ade": ("llä", "lla"),
            "abl": ("ltä", "lta"),
        }
        suffixes_for_case = suffixes[case]
        values = {oblique_stem + suffixes_for_case[0]}
        if allow_back_harmony:
            values.add(oblique_stem + suffixes_for_case[1])
        return values
    if case == "ill":
        return {oblique_stem + "en"}
    if case == "ess":
        values = {oblique_stem + "nä"}
        if allow_back_harmony:
            values.add(oblique_stem + "na")
        return values
    if case == "all":
        return {oblique_stem + "lle"}
    if case == "tra":
        return {oblique_stem + "ksi"}
    return set()


_HK_RETENTION_EXCLUDED_LEMMAS = frozenset({"nahka", "uhka", "vihko"})


def _predict_hk_retention_variant(*, lemma: str, case: str, number: str) -> set[str]:
    """Return source-confirmed alternatives that retain ``hk``.

    ``hk -> h`` is not productive across the whole Finnish lexicon:
    ``nahka`` and ``uhka`` weaken by deletion, while ``pihka``, ``sähkö``
    and ``ruuhka`` retain ``k``. The compact form does not carry the source
    declension-template arguments, so the retained path is accepted for
    non-deleting lexical families while excluding the deletion families.
    """

    # These are lexical exceptions, not productive suffixes. Checking exact
    # lemmas keeps compounds such as ``antiikkinahka`` and ``tuhka`` from
    # inheriting the deletion pattern merely because they end in ``-nahka``
    # or ``-uhka``.
    if lemma in _HK_RETENTION_EXCLUDED_LEMMAS:
        return set()
    kotus = _classify_nominal(lemma)
    if kotus not in {"vowel_short", "a_stem_grad"}:
        return set()
    if not lemma[:-1].endswith("hk"):
        return set()
    if number == "pl" and case in {"nom", "acc"}:
        return {lemma + "t"}
    if number == "pl" and case in {"abe", "ins", "com"}:
        stem = lemma[:-1] + "i"
        if case == "ins":
            return {stem + "n", lemma[:-1] + "oi" + "n"}
        if case == "com":
            return {stem + "ne", lemma[:-1] + "oi" + "ne"}
        return {
            stem + _suffix_with_harmony(lemma, "tta", "ttä"),
            lemma[:-1]
            + "oi"
            + _suffix_with_harmony(lemma, "tta", "ttä"),
        }
    if number != "sg":
        return set()
    if case in {"gen", "acc"}:
        return {lemma + "n"}
    if case == "abe":
        return {lemma + _suffix_with_harmony(lemma, "tta", "ttä")}
    if case in {"ine", "ela", "ade", "abl"}:
        suffixes = {
            "ine": ("ssa", "ssä"),
            "ela": ("sta", "stä"),
            "ade": ("lla", "llä"),
            "abl": ("lta", "ltä"),
        }
        back_suffix, front_suffix = suffixes[case]
        return {lemma + _suffix_with_harmony(lemma, back_suffix, front_suffix)}
    if case == "all":
        return {lemma + "lle"}
    if case == "tra":
        return {lemma + "ksi"}
    return set()


def _predict_a_stem_strong_variant(
    *, lemma: str, case: str, number: str
) -> set[str]:
    """Return the strong-grade path used by loanwords and lexical items.

    The compact lexeme row does not retain the Kotus template.  A subset of
    ``-a/-ä`` nouns therefore keeps the nominative stem in oblique cells
    (``burka -> burkan``, ``delta -> deltan``) where the productive rule
    would weaken it.  Keep this as a validation-only alternative.
    """

    if not lemma.endswith(("a", "ä")):
        return set()
    if lemma in _HK_RETENTION_EXCLUDED_LEMMAS:
        return set()
    if number == "pl" and case in {"nom", "acc"}:
        return {lemma + "t"}
    if number != "sg":
        return set()
    if case in {"gen", "acc"}:
        return {lemma + "n"}
    if case == "abe":
        return {lemma + _suffix_with_harmony(lemma, "tta", "ttä")}
    if case in {"ine", "ela", "ade", "abl"}:
        suffixes = {
            "ine": ("ssa", "ssä"),
            "ela": ("sta", "stä"),
            "ade": ("lla", "llä"),
            "abl": ("lta", "ltä"),
        }
        back_suffix, front_suffix = suffixes[case]
        return {lemma + _suffix_with_harmony(lemma, back_suffix, front_suffix)}
    if case == "ess":
        return {lemma + _suffix_with_harmony(lemma, "na", "nä")}
    if case == "all":
        return {lemma + "lle"}
    if case == "tra":
        return {lemma + "ksi"}
    return set()
