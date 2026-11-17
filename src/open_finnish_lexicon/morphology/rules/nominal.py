"""Nominal kotus classification and case/number prediction."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.phonology import (
    _AmbiguousGradation,
    _apply_weak_grade,
    _is_vowel,
    _suffix_with_harmony,
)
from open_finnish_lexicon.morphology.rules.types import ALL_VOWELS


# Personal pronouns are lexical paradigms, not productive Kotus nouns. Keep
# their common case forms explicit so ``pron`` rows do not fall through to
# the noun classifier and become unexplained uncertain results.
_PERSONAL_PRONOUN_FORMS: dict[str, dict[tuple[str, str], str]] = {
    "minä": {
        ("nom", "sg"): "minä", ("gen", "sg"): "minun",
        ("par", "sg"): "minua", ("acc", "sg"): "minut",
        ("ine", "sg"): "minussa", ("ela", "sg"): "minusta",
        ("ill", "sg"): "minuun", ("ade", "sg"): "minulla",
        ("abl", "sg"): "minulta", ("all", "sg"): "minulle",
        ("ess", "sg"): "minuna", ("tra", "sg"): "minuksi",
        ("abe", "sg"): "minutta",
        ("nom", "pl"): "me", ("gen", "pl"): "meidän",
        ("par", "pl"): "meitä", ("acc", "pl"): "meidät",
        ("ine", "pl"): "meissä", ("ela", "pl"): "meistä",
        ("ill", "pl"): "meihin", ("ade", "pl"): "meillä",
        ("abl", "pl"): "meiltä", ("all", "pl"): "meille",
        ("ess", "pl"): "meinä", ("tra", "pl"): "meiksi",
        ("abe", "pl"): "meittä",
    },
    "sinä": {
        ("nom", "sg"): "sinä", ("gen", "sg"): "sinun",
        ("par", "sg"): "sinua", ("acc", "sg"): "sinut",
        ("ine", "sg"): "sinussa", ("ela", "sg"): "sinusta",
        ("ill", "sg"): "sinuun", ("ade", "sg"): "sinulla",
        ("abl", "sg"): "sinulta", ("all", "sg"): "sinulle",
        ("ess", "sg"): "sinuna", ("tra", "sg"): "sinuksi",
        ("abe", "sg"): "sinutta",
        ("nom", "pl"): "te", ("gen", "pl"): "teidän",
        ("par", "pl"): "teitä", ("acc", "pl"): "teidät",
        ("ine", "pl"): "teissä", ("ela", "pl"): "teistä",
        ("ill", "pl"): "teihin", ("ade", "pl"): "teillä",
        ("abl", "pl"): "teiltä", ("all", "pl"): "teille",
        ("ess", "pl"): "teinä", ("tra", "pl"): "teiksi",
        ("abe", "pl"): "teittä",
    },
    "hän": {
        ("nom", "sg"): "hän", ("gen", "sg"): "hänen",
        ("par", "sg"): "häntä", ("acc", "sg"): "hänet",
        ("ine", "sg"): "hänessä", ("ela", "sg"): "hänestä",
        ("ill", "sg"): "häneen", ("ade", "sg"): "hänellä",
        ("abl", "sg"): "häneltä", ("all", "sg"): "hänelle",
        ("ess", "sg"): "hänenä", ("tra", "sg"): "häneksi",
        ("abe", "sg"): "hänettä",
        ("nom", "pl"): "he", ("gen", "pl"): "heidän",
        ("par", "pl"): "heitä", ("acc", "pl"): "heidät",
        ("ine", "pl"): "heissä", ("ela", "pl"): "heistä",
        ("ill", "pl"): "heihin", ("ade", "pl"): "heillä",
        ("abl", "pl"): "heiltä", ("all", "pl"): "heille",
        ("ess", "pl"): "heinä", ("tra", "pl"): "heiksi",
        ("abe", "pl"): "heittä",
    },
}

# Interrogative and relative pronouns are also suppletive lexical paradigms;
# treating ``kuka`` or ``joka`` as productive noun stems produces the wrong
# forms. Keep source-attested alternants together so both standard and common
# short/long variants can be verified without widening productive noun rules.
_ADDITIONAL_LEXICAL_PRONOUN_FORMS: dict[
    str, dict[tuple[str, str], tuple[str, ...]]
] = {
    "kuka": {
        ("nom", "sg"): ("kuka",),
        ("gen", "sg"): ("kenen",),
        ("par", "sg"): ("ketä",),
        ("acc", "sg"): ("kenet",),
        ("ine", "sg"): ("kenessä",),
        ("ela", "sg"): ("kenestä", "kestä"),
        ("ill", "sg"): ("keneen", "kehen"),
        ("ade", "sg"): ("kenellä", "kellä"),
        ("abl", "sg"): ("keneltä", "keltä"),
        ("all", "sg"): ("kenelle", "kelle"),
        ("ess", "sg"): ("kenenä", "kenä"),
        ("tra", "sg"): ("keneksi",),
        ("abe", "sg"): ("kenettä",),
        ("nom", "pl"): ("ketkä", "kutka"),
        ("gen", "pl"): ("keiden", "keitten"),
        ("par", "pl"): ("keitä",),
        ("acc", "pl"): ("ketkä",),
        ("ine", "pl"): ("keissä",),
        ("ela", "pl"): ("keistä",),
        ("ill", "pl"): ("keihin",),
        ("ade", "pl"): ("keillä",),
        ("abl", "pl"): ("keiltä",),
        ("all", "pl"): ("keille",),
        ("ess", "pl"): ("keinä",),
        ("tra", "pl"): ("keiksi",),
        ("abe", "pl"): ("keittä",),
    },
    "mikä": {
        ("nom", "sg"): ("mikä",),
        ("gen", "sg"): ("minkä",),
        ("par", "sg"): ("mitä",),
        ("acc", "sg"): ("minkä",),
        ("ine", "sg"): ("missä",),
        ("ela", "sg"): ("mistä",),
        ("ill", "sg"): ("mihin", "minne"),
        ("ade", "sg"): ("millä",),
        ("abl", "sg"): ("miltä",),
        ("all", "sg"): ("mille",),
        ("ess", "sg"): ("minä",),
        ("tra", "sg"): ("miksi",),
        ("nom", "pl"): ("mitkä",),
    },
    "joka": {
        ("nom", "sg"): ("joka",),
        ("gen", "sg"): ("jonka",),
        ("par", "sg"): ("jota",),
        ("acc", "sg"): ("joka", "jonka"),
        ("ine", "sg"): ("jossa",),
        ("ela", "sg"): ("josta",),
        ("ill", "sg"): ("johon", "jonne"),
        ("ade", "sg"): ("jolla",),
        ("abl", "sg"): ("jolta",),
        ("all", "sg"): ("jolle",),
        ("ess", "sg"): ("jona",),
        ("tra", "sg"): ("joksi",),
        ("abe", "sg"): ("jotta",),
        ("nom", "pl"): ("jotka",),
        ("gen", "pl"): ("joiden", "joitten"),
        ("par", "pl"): ("joita",),
        ("acc", "pl"): ("jotka",),
        ("ine", "pl"): ("joissa",),
        ("ela", "pl"): ("joista",),
        ("ill", "pl"): ("joihin",),
        ("ade", "pl"): ("joilla",),
        ("abl", "pl"): ("joilta",),
        ("all", "pl"): ("joille",),
        ("ess", "pl"): ("joina",),
        ("tra", "pl"): ("joiksi",),
        ("abe", "pl"): ("joitta",),
        ("ins", "pl"): ("join",),
    },
    "toinen": {
        ("nom", "sg"): ("toinen",),
        ("gen", "sg"): ("toisen",),
        ("par", "sg"): ("toista",),
        ("acc", "sg"): ("toisen",),
        ("ine", "sg"): ("toisessa",),
        ("ela", "sg"): ("toisesta",),
        ("ill", "sg"): ("toiseen",),
        ("ade", "sg"): ("toisella",),
        ("abl", "sg"): ("toiselta",),
        ("all", "sg"): ("toiselle",),
        ("ess", "sg"): ("toisena",),
        ("tra", "sg"): ("toiseksi",),
        ("abe", "sg"): ("toisetta",),
        ("nom", "pl"): ("toiset",),
        ("gen", "pl"): ("toisten", "toisien"),
        ("par", "pl"): ("toisia",),
        ("acc", "pl"): ("toiset",),
        ("ine", "pl"): ("toisissa",),
        ("ela", "pl"): ("toisista",),
        ("ill", "pl"): ("toisiin",),
        ("ade", "pl"): ("toisilla",),
        ("abl", "pl"): ("toisilta",),
        ("all", "pl"): ("toisille",),
        ("ess", "pl"): ("toisina",),
        ("tra", "pl"): ("toisiksi",),
        ("abe", "pl"): ("toisitta",),
        ("ins", "pl"): ("toisin",),
        ("com", "sg"): ("toisine",),
        ("com", "pl"): ("toisine",),
    },
    "kumpi": {
        ("nom", "sg"): ("kumpi",),
        ("gen", "sg"): ("kumman",),
        ("par", "sg"): ("kumpaa",),
        ("acc", "sg"): ("kumman",),
        ("ine", "sg"): ("kummassa",),
        ("ela", "sg"): ("kummasta",),
        ("ill", "sg"): ("kumpaan",),
        ("ade", "sg"): ("kummalla",),
        ("abl", "sg"): ("kummalta",),
        ("all", "sg"): ("kummalle",),
        ("ess", "sg"): ("kumpana",),
        ("tra", "sg"): ("kummaksi",),
        ("abe", "sg"): ("kummatta",),
        ("nom", "pl"): ("kummat",),
        ("gen", "pl"): ("kumpien",),
        ("par", "pl"): ("kumpia",),
        ("acc", "pl"): ("kummat",),
        ("ine", "pl"): ("kummissa",),
        ("ela", "pl"): ("kummista",),
        ("ill", "pl"): ("kumpiin",),
        ("ade", "pl"): ("kummilla",),
        ("abl", "pl"): ("kummilta",),
        ("all", "pl"): ("kummille",),
        ("ess", "pl"): ("kumpina",),
        ("tra", "pl"): ("kummiksi",),
        ("abe", "pl"): ("kummitta",),
        ("ins", "pl"): ("kummin",),
        ("com", "sg"): ("kumpine",),
        ("com", "pl"): ("kumpine",),
    },
    "moni": {
        ("nom", "sg"): ("moni",),
        ("gen", "sg"): ("monen",),
        ("par", "sg"): ("monta", "montaa"),
        ("acc", "sg"): ("monen",),
        ("ine", "sg"): ("monessa",),
        ("ela", "sg"): ("monesta",),
        ("ill", "sg"): ("moneen",),
        ("ade", "sg"): ("monella",),
        ("abl", "sg"): ("monelta",),
        ("all", "sg"): ("monelle",),
        ("ess", "sg"): ("monena", "monna"),
        ("tra", "sg"): ("moneksi",),
        ("abe", "sg"): ("monetta",),
        ("nom", "pl"): ("monet",),
        ("gen", "pl"): ("monien",),
        ("par", "pl"): ("monia",),
        ("acc", "pl"): ("monet",),
        ("ine", "pl"): ("monissa",),
        ("ela", "pl"): ("monista",),
        ("ill", "pl"): ("moniin",),
        ("ade", "pl"): ("monilla",),
        ("abl", "pl"): ("monilta",),
        ("all", "pl"): ("monille",),
        ("ess", "pl"): ("monina",),
        ("tra", "pl"): ("moniksi",),
        ("abe", "pl"): ("monitta",),
        ("ins", "pl"): ("monin",),
        ("com", "sg"): ("monine",),
        ("com", "pl"): ("monine",),
    },
    "eräs": {
        ("nom", "sg"): ("eräs",),
        ("gen", "sg"): ("erään",),
        ("par", "sg"): ("erästä",),
        ("acc", "sg"): ("erään",),
        ("ine", "sg"): ("eräässä",),
        ("ela", "sg"): ("eräästä",),
        ("ill", "sg"): ("erääseen",),
        ("ade", "sg"): ("eräällä",),
        ("abl", "sg"): ("eräältä",),
        ("all", "sg"): ("eräälle",),
        ("ess", "sg"): ("eräänä",),
        ("tra", "sg"): ("erääksi",),
        ("abe", "sg"): ("eräättä",),
        ("nom", "pl"): ("eräät",),
        ("gen", "pl"): ("eräiden", "eräitten"),
        ("par", "pl"): ("eräitä",),
        ("acc", "pl"): ("eräät",),
        ("ine", "pl"): ("eräissä",),
        ("ela", "pl"): ("eräistä",),
        ("ill", "pl"): ("eräisiin",),
        ("ade", "pl"): ("eräillä",),
        ("abl", "pl"): ("eräiltä",),
        ("all", "pl"): ("eräille",),
        ("ess", "pl"): ("eräinä",),
        ("tra", "pl"): ("eräiksi",),
        ("abe", "pl"): ("eräittä",),
        ("ins", "pl"): ("eräin",),
        ("com", "sg"): ("eräine",),
        ("com", "pl"): ("eräine",),
    },
    "kaikki": {
        ("nom", "sg"): ("kaikki",),
        ("gen", "sg"): ("kaiken",),
        ("par", "sg"): ("kaikkea", "kaikkee"),
        ("acc", "sg"): ("kaiken",),
        ("ine", "sg"): ("kaikessa",),
        ("ela", "sg"): ("kaikesta",),
        ("ill", "sg"): ("kaikkeen",),
        ("ade", "sg"): ("kaikella",),
        ("abl", "sg"): ("kaikelta",),
        ("all", "sg"): ("kaikelle",),
        ("ess", "sg"): ("kaikkena",),
        ("tra", "sg"): ("kaikeksi",),
        ("abe", "sg"): ("kaiketta",),
        ("nom", "pl"): ("kaikki", "kaiket"),
        ("gen", "pl"): ("kaikkien", "kaikkein"),
        ("par", "pl"): ("kaikkia",),
        ("acc", "pl"): ("kaikki", "kaiket"),
        ("ine", "pl"): ("kaikissa",),
        ("ela", "pl"): ("kaikista",),
        ("ill", "pl"): ("kaikkiin",),
        ("ade", "pl"): ("kaikilla",),
        ("abl", "pl"): ("kaikilta",),
        ("all", "pl"): ("kaikille",),
        ("ess", "pl"): ("kaikkina",),
        ("tra", "pl"): ("kaikiksi",),
        ("abe", "pl"): ("kaikitta",),
        ("ins", "pl"): ("kaikin",),
        ("com", "sg"): ("kaikkine", "kaikkineen"),
        ("com", "pl"): ("kaikkine", "kaikkineen"),
    },
    "itse": {
        ("nom", "sg"): ("itse",),
        ("gen", "sg"): ("itsen",),
        ("par", "sg"): ("itseä",),
        ("acc", "sg"): ("itsen",),
        ("ine", "sg"): ("itsessä",),
        ("ela", "sg"): ("itsestä",),
        ("ill", "sg"): ("itseen",),
        ("ade", "sg"): ("itsellä",),
        ("abl", "sg"): ("itseltä",),
        ("all", "sg"): ("itselle",),
        ("ess", "sg"): ("itsenä",),
        ("tra", "sg"): ("itseksi",),
        ("abe", "sg"): ("itsettä",),
    },
    "kukin": {
        ("nom", "sg"): ("kukin",),
        ("gen", "sg"): ("kunkin",),
        ("par", "sg"): ("kutakin",),
        ("acc", "sg"): ("kukin", "kunkin"),
        ("ine", "sg"): ("kussakin",),
        ("ela", "sg"): ("kustakin",),
        ("ill", "sg"): ("kuhunkin",),
        ("ade", "sg"): ("kullakin",),
        ("abl", "sg"): ("kultakin",),
        ("all", "sg"): ("kullekin",),
        ("ess", "sg"): ("kunakin",),
        ("tra", "sg"): ("kuksikin",),
        ("abe", "sg"): ("kuttakin",),
        ("nom", "pl"): ("kutkin",),
        ("gen", "pl"): ("kuidenkin", "kuittenkin"),
        ("par", "pl"): ("kuitakin",),
        ("acc", "pl"): ("kutkin",),
        ("ine", "pl"): ("kuissakin",),
        ("ela", "pl"): ("kuistakin",),
        ("ill", "pl"): ("kuihinkin",),
        ("ade", "pl"): ("kuillakin",),
        ("abl", "pl"): ("kuiltakin",),
        ("all", "pl"): ("kuillekin",),
        ("ess", "pl"): ("kuinakin",),
        ("tra", "pl"): ("kuiksikin",),
        ("abe", "pl"): ("kuittakin",),
        ("ins", "pl"): ("kuinkin",),
    },
    "muutama": {
        ("nom", "sg"): ("muutama",),
        ("gen", "sg"): ("muutaman",),
        ("par", "sg"): ("muutamaa",),
        ("acc", "sg"): ("muutaman",),
        ("ine", "sg"): ("muutamassa",),
        ("ela", "sg"): ("muutamasta",),
        ("ill", "sg"): ("muutamaan",),
        ("ade", "sg"): ("muutamalla",),
        ("abl", "sg"): ("muutamalta",),
        ("all", "sg"): ("muutamalle",),
        ("ess", "sg"): ("muutamana",),
        ("tra", "sg"): ("muutamaksi",),
        ("abe", "sg"): ("muutamatta",),
        ("nom", "pl"): ("muutamat",),
        ("gen", "pl"): ("muutamien",),
        ("par", "pl"): ("muutamia",),
        ("acc", "pl"): ("muutamat",),
        ("ine", "pl"): ("muutamissa",),
        ("ela", "pl"): ("muutamista",),
        ("ill", "pl"): ("muutamiin",),
        ("ade", "pl"): ("muutamilla",),
        ("abl", "pl"): ("muutamilta",),
        ("all", "pl"): ("muutamille",),
        ("ess", "pl"): ("muutamina",),
        ("tra", "pl"): ("muutamiksi",),
        ("abe", "pl"): ("muutamitta",),
        ("ins", "pl"): ("muutamin",),
        ("com", "sg"): ("muutamine",),
        ("com", "pl"): ("muutamine",),
    },
    "jompikumpi": {
        ("nom", "sg"): ("jompikumpi",),
        ("gen", "sg"): ("jommankumman",),
        ("par", "sg"): ("jompaakumpaa",),
        ("acc", "sg"): ("jommankumman",),
        ("ine", "sg"): ("jommassakummassa",),
        ("ela", "sg"): ("jommastakummasta",),
        ("ill", "sg"): ("jompaankumpaan",),
        ("ade", "sg"): ("jommallakummalla",),
        ("abl", "sg"): ("jommaltakummalta",),
        ("all", "sg"): ("jommallekummalle",),
        ("ess", "sg"): ("jompanakumpana",),
        ("tra", "sg"): ("jommaksikummaksi",),
        ("abe", "sg"): ("jommattakummatta",),
        ("nom", "pl"): ("jommatkummat",),
        ("gen", "pl"): ("jompienkumpien",),
        ("par", "pl"): ("jompiakumpia",),
        ("acc", "pl"): ("jommatkummat",),
        ("ine", "pl"): ("jommissakummissa",),
        ("ela", "pl"): ("jommistakummista",),
        ("ill", "pl"): ("jompiinkumpiin",),
        ("ade", "pl"): ("jommillakummilla",),
        ("abl", "pl"): ("jommiltakummilta",),
        ("all", "pl"): ("jommillekummille",),
        ("ess", "pl"): ("jompinakumpina",),
        ("tra", "pl"): ("jommiksikummiksi",),
        ("abe", "pl"): ("jommittakummitta",),
        ("ins", "pl"): ("jomminkummin",),
        ("com", "sg"): ("jompinekumpine",),
        ("com", "pl"): ("jompinekumpine",),
    },
    "me": {
        ("nom", "pl"): ("me",),
        ("gen", "pl"): ("meidän",),
        ("par", "pl"): ("meitä",),
        ("acc", "pl"): ("meidät",),
        ("ine", "pl"): ("meissä",),
        ("ela", "pl"): ("meistä",),
        ("ill", "pl"): ("meihin",),
        ("ade", "pl"): ("meillä",),
        ("abl", "pl"): ("meiltä",),
        ("all", "pl"): ("meille",),
        ("ess", "pl"): ("meinä",),
        ("tra", "pl"): ("meiksi",),
        ("abe", "pl"): ("meittä",),
    },
    "te": {
        ("nom", "pl"): ("te",),
        ("gen", "pl"): ("teidän",),
        ("par", "pl"): ("teitä",),
        ("acc", "pl"): ("teidät",),
        ("ine", "pl"): ("teissä",),
        ("ela", "pl"): ("teistä",),
        ("ill", "pl"): ("teihin",),
        ("ade", "pl"): ("teillä",),
        ("abl", "pl"): ("teiltä",),
        ("all", "pl"): ("teille",),
        ("ess", "pl"): ("teinä",),
        ("tra", "pl"): ("teiksi",),
        ("abe", "pl"): ("teittä",),
        ("ins", "pl"): ("tein",),
    },
    "he": {
        ("nom", "pl"): ("he",),
        ("gen", "pl"): ("heidän",),
        ("par", "pl"): ("heitä",),
        ("acc", "pl"): ("heidät",),
        ("ine", "pl"): ("heissä",),
        ("ela", "pl"): ("heistä",),
        ("ill", "pl"): ("heihin",),
        ("ade", "pl"): ("heillä",),
        ("abl", "pl"): ("heiltä",),
        ("all", "pl"): ("heille",),
        ("ess", "pl"): ("heinä",),
        ("tra", "pl"): ("heiksi",),
        ("abe", "pl"): ("heittä",),
    },
    "se": {
        ("nom", "sg"): ("se",),
        ("gen", "sg"): ("sen",),
        ("par", "sg"): ("sitä",),
        ("acc", "sg"): ("sen",),
        ("ine", "sg"): ("siinä",),
        ("ela", "sg"): ("siitä",),
        ("ill", "sg"): ("siihen",),
        ("ade", "sg"): ("sillä",),
        ("abl", "sg"): ("siltä",),
        ("all", "sg"): ("sille",),
        ("ess", "sg"): ("sinä",),
        ("tra", "sg"): ("siksi",),
    },
    "tämä": {
        ("nom", "sg"): ("tämä", "tää"),
        ("gen", "sg"): ("tämän", "tän", "tään"),
        ("par", "sg"): ("tätä",),
        ("acc", "sg"): ("tämän",),
        ("ine", "sg"): ("tässä",),
        ("ela", "sg"): ("tästä",),
        ("ill", "sg"): ("tähän",),
        ("ade", "sg"): ("tällä",),
        ("abl", "sg"): ("tältä",),
        ("all", "sg"): ("tälle",),
        ("ess", "sg"): ("tänä",),
        ("tra", "sg"): ("täksi",),
        ("abe", "sg"): ("tättä",),
    },
    "tuo": {
        ("nom", "sg"): ("tuo",),
        ("gen", "sg"): ("tuon",),
        ("par", "sg"): ("tuota",),
        ("acc", "sg"): ("tuon",),
        ("ine", "sg"): ("tuossa",),
        ("ela", "sg"): ("tuosta",),
        ("ill", "sg"): ("tuohon",),
        ("ade", "sg"): ("tuolla",),
        ("abl", "sg"): ("tuolta",),
        ("all", "sg"): ("tuolle",),
        ("ess", "sg"): ("tuona",),
        ("tra", "sg"): ("tuoksi",),
        ("abe", "sg"): ("tuotta",),
    },
}


def _lexical_pronoun_variants(
    *, lemma: str, case: str, number: str
) -> tuple[str, ...]:
    personal = _PERSONAL_PRONOUN_FORMS.get(lemma)
    if personal is not None:
        predicted = personal.get((case, number))
        return (predicted,) if predicted is not None else ()
    return _ADDITIONAL_LEXICAL_PRONOUN_FORMS.get(lemma, {}).get(
        (case, number), ()
    )


def _predict_personal_pronoun(
    *, lemma: str, case: str, number: str
) -> tuple[str | None, str | None, str]:
    variants = _lexical_pronoun_variants(lemma=lemma, case=case, number=number)
    if not variants:
        return None, None, f"lexical pronoun {lemma!r} is not covered"
    predicted = variants[0]
    return (
        predicted,
        f"pronoun/{lemma}/{case}.{number}",
        f"{lemma}: lexical pronoun form = {predicted!r}",
    )


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

    variants: dict[tuple[str, str], str] = {
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
