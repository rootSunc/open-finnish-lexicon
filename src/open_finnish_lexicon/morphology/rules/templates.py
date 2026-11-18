"""Source-template agreement guards, enclitic suffixes, and lexical variants."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.types import ALL_VOWELS

# These Kaikki class labels identify paradigms whose stem is not recoverable
# from the compact lemma alone: component-inflected compounds, ordinal
# compounds, foreign loan templates, and a few lexical gradation families.
# The loader has already filtered the source table down to explicit positive
# morphology cells, so an exact source form is a better trust signal than a
# lemma-only approximation in these families.
_SOURCE_TEMPLATE_FALLBACK_MARKERS = frozenset(
    {
        # The source occasionally emits the compact class without the
        # gradation letter/star.  These are still complete source paradigms
        # (not guesses from the lemma), so keep their explicit cells.
        "8/nalle",
        "18/maa",
        "26/pieni",
        "38/nainen",
        "39/vastaus",
        "40*f/kalleus",
        "41*a/vieras",
        "48*e/hame",
        "48*c/hame",
        "49*e/askel",
        "61/sallia",
        "kaikaa",
        "1*m/valo",
        "1*d/valo",
        "28*k/kynsi",
        "10*a/koira",
        "10/koira",
        "8*b/nalle",
        "8*c/nalle",
        "9*j/kala",
        "21/rosé",
        "23/tiili",
        "31*f/kaksi",
        "45*j/kahdeksas",
        "48/hame",
        "49*b/askel",
        "5/risti",
        "7*d/ovi",
        "8*a/nalle",
        "10*l/koira",
        "10*/koira",
        "58*/laskea",
        "61*/sallia",
        "risti",
    }
)


def _uses_source_template_fallback(source_class: str) -> bool:
    return any(marker in source_class for marker in _SOURCE_TEMPLATE_FALLBACK_MARKERS)


def _shares_lexical_prefix(lemma_norm: str, surface_norm: str) -> bool:
    if len(lemma_norm) < 2:
        return True
    prefix_len = min(2, len(lemma_norm) - 1)
    return surface_norm[:prefix_len] == lemma_norm[:prefix_len]


def _matches_nominal_source_template(
    *,
    lemma_norm: str,
    surface_norm: str,
    case: str,
    number: str,
    source_class: str,
) -> bool:
    """Accept a Kotus source-template override only when its case/number
    ending and stem prefix are morphologically consistent."""

    if not _uses_source_template_fallback(source_class):
        return False
    if not _shares_lexical_prefix(lemma_norm, surface_norm):
        return False
    if case == "nom" and number == "sg":
        return surface_norm == lemma_norm
    if case == "acc" and number == "sg":
        return surface_norm == lemma_norm or surface_norm.endswith("n")
    if case in {"nom", "acc"} and number == "pl":
        return surface_norm.endswith("t")
    if case == "gen" and number == "sg":
        return surface_norm.endswith("n") and surface_norm != lemma_norm
    if case == "gen" and number == "pl":
        return surface_norm.endswith(("en", "in", "ten", "den", "tten"))
    if case == "par":
        return surface_norm.endswith(("a", "ä", "ta", "tä"))
    if case == "ine":
        return surface_norm.endswith(("ssa", "ssä"))
    if case == "ela":
        return surface_norm.endswith(("sta", "stä"))
    if case == "ill":
        return (
            len(surface_norm) >= 3
            and surface_norm.endswith("n")
            and surface_norm[-2] in ALL_VOWELS
        )
    if case == "ade":
        return surface_norm.endswith(("lla", "llä"))
    if case == "abl":
        return surface_norm.endswith(("lta", "ltä"))
    if case == "all":
        return surface_norm.endswith("lle")
    if case == "ess":
        return surface_norm.endswith(("na", "nä"))
    if case == "tra":
        return surface_norm.endswith("ksi")
    if case == "abe":
        return surface_norm.endswith(("tta", "ttä"))
    if case == "com":
        return surface_norm.endswith(
            ("ne", "ine", "neen", "ni", "si", "nsa", "nsä", "mme", "nne")
        )
    if case == "ins":
        return surface_norm.endswith("n")
    return False


def _matches_verb_source_template(
    *,
    lemma_norm: str,
    surface_norm: str,
    person: str | None,
    number: str | None,
    passive: bool,
    source_class: str,
) -> bool:
    if not _uses_source_template_fallback(source_class):
        return False
    if not _shares_lexical_prefix(lemma_norm, surface_norm):
        return False
    if passive:
        return surface_norm.endswith(("aan", "ään"))
    if (person, number) == ("1", "sg"):
        return surface_norm.endswith("n")
    if (person, number) == ("2", "sg"):
        return surface_norm.endswith("t")
    if (person, number) == ("3", "sg"):
        return bool(surface_norm) and surface_norm[-1] in ALL_VOWELS
    if (person, number) == ("1", "pl"):
        return surface_norm.endswith("mme")
    if (person, number) == ("2", "pl"):
        return surface_norm.endswith("tte")
    if (person, number) == ("3", "pl"):
        return surface_norm.endswith(("vat", "vät"))
    return False


def _uses_source_comitative_possessive(
    *, form_kind: str | None, case: str, number: str, surface: str
) -> bool:
    """Recognize Kaikki's unlabelled possessive comitative cells."""

    return (
        form_kind == "kaikki"
        and case == "com"
        and number == "pl"
        and surface.endswith("neen")
    )


def _clitic_suffix_variants(clitic: str) -> tuple[str, ...]:
    """Return Finnish surface suffixes for an explicit Omorfi clitic tag."""

    return {
        "kin": ("kin",),
        "ko": ("ko", "kö"),
        "han": ("han", "hän"),
        "kaan": ("kaan", "kään"),
        "pa": ("pa", "pä"),
        "ka": ("ka", "kä"),
        "s": ("s",),
    }.get(clitic.casefold(), ())


_ATTACHED_CLITIC_SUFFIXES = (
    "kaan",
    "kään",
    "han",
    "hän",
    "kin",
    "ko",
    "kö",
    "ka",
    "kä",
    "pa",
    "pä",
    "s",
)


def _orthographic_transliteration_variants(surface: str) -> set[str]:
    """Return common Omorfi transliterations of Finnish ``š``."""

    if "š" not in surface:
        return set()
    return {surface.replace("š", "s"), surface.replace("š", "sh")}


_OMORFI_VERB_VARIANTS = {
    ("aprikoida", "1", "sg"): "aprikoitsen",
    ("ilakoida", "3", "sg"): "ilakoitsee",
    ("ilkamoida", "3", "sg"): "ilkamoitsee",
    ("vihkiä", "1", "sg"): "vihin",
    ("vihkiä", "2", "sg"): "vihit",
    ("vihkiä", "1", "pl"): "vihimme",
    ("vihkiä", "2", "pl"): "vihitte",
}

_OMORFI_NOMINAL_VARIANTS = {
    ("aavameri", "nom", "pl"): "aavatmeret",
    ("ampu", "nom", "pl"): "amput",
    ("bantu", "nom", "pl"): "bantut",
    ("esperanto", "gen", "sg"): "esperanton",
    ("esperanto", "ine", "sg"): "esperantossa",
    ("esperanto", "ade", "sg"): "esperantolla",
    ("esperanto", "tra", "sg"): "esperantoksi",
    ("hobby", "nom", "pl"): "hobbyt",
    ("karku", "gen", "sg"): "karkun",
    ("karku", "abe", "sg"): "karkutta",
    ("kiiru", "nom", "pl"): "kiiruut",
    ("kultainennoutaja", "nom", "pl"): "kultaisetnoutajat",
    ("nahka", "gen", "sg"): "nahkan",
    ("nahka", "ela", "sg"): "nahkasta",
    ("nahka", "all", "sg"): "nahkalle",
    ("nahka", "nom", "pl"): "nahkat",
    ("mustaleski", "nom", "pl"): "mustatlesket",
    ("nakupelle", "ess", "sg"): "nakupellenä",
    ("nukke", "abe", "sg"): "nuketta",
    ("nuoriherra", "nom", "pl"): "nuoretherrat",
    ("nuoripari", "nom", "pl"): "nuoretparit",
    ("omatunto", "gen", "sg"): "omantunnon",
    ("puolipäivä", "gen", "sg"): "puolenpäivän",
    ("puolipäivä", "par", "sg"): "puoltapäivää",
    ("puoliväli", "ine", "sg"): "puolessavälissä",
    ("raskassarja", "gen", "sg"): "raskaansarjan",
    ("silestone", "acc", "sg"): "silestone",
    ("silestone", "par", "sg"): "silestonia",
    ("striptease", "acc", "sg"): "striptease",
    ("syvämeri", "gen", "sg"): "syvänmeren",
    ("tempo", "gen", "sg"): "tempon",
    ("uhka", "gen", "sg"): "uhkan",
    ("uhka", "ela", "sg"): "uhkasta",
    ("uhka", "tra", "sg"): "uhkaksi",
    ("uhka", "nom", "pl"): "uhkat",
    ("vihko", "gen", "sg"): "vihkon",
    ("vihko", "nom", "pl"): "vihkot",
    ("ylkä", "gen", "sg"): "yljän",
    ("ylkä", "nom", "pl"): "yljät",
    ("šakki", "ill", "pl"): "sakkeihin",
    ("šekkivihko", "gen", "sg"): "shekkivihkon",
    ("törmänne", "nom", "pl"): "törmänneet",
    ("uksi", "par", "sg"): "usta",
}

_KAIKKI_NOMINAL_VARIANTS = {
    ("eri", "tra", "pl"): "erikseen",
    ("eri", "ade", "pl"): "erillään",
    ("eri", "all", "pl"): "erilleen",
    ("silestone", "acc", "sg"): "silestone",
    ("silestone", "par", "sg"): "silestonia",
    ("striptease", "acc", "sg"): "striptease",
    ("yatzy", "ins", "pl"): "yatzein",
    ("yatzy", "abe", "pl"): "yatzeitta",
    ("yatzy", "acc", "sg"): "yatzy",
}
