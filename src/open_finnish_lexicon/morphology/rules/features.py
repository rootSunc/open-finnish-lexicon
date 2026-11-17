"""Morphological feature normalisation and out-of-scope guards."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.types import CASE_CANONICAL, NUMBER_CANONICAL

def _features_lookup(features: dict[str, str], *keys: str) -> str | None:
    if not features:
        return None
    fold = {key.casefold() for key in keys}
    for key, value in features.items():
        if key.casefold() in fold and value:
            return str(value)
    return None


def _normalise_case(features: dict[str, str]) -> str | None:
    raw = _features_lookup(features, "case", "Case")
    if not raw:
        return None
    return CASE_CANONICAL.get(raw.casefold())


def _normalise_number(features: dict[str, str]) -> str:
    raw = _features_lookup(features, "number", "Number")
    if not raw:
        return "sg"
    return NUMBER_CANONICAL.get(raw.casefold(), "sg")


def _normalise_person(features: dict[str, str]) -> str | None:
    raw = _features_lookup(features, "person", "Person")
    if not raw:
        return None
    raw = raw.lower().rstrip(".")
    if raw.endswith("sg") or raw.endswith("pl"):
        raw = raw[:-2]
    return {"1": "1", "2": "2", "3": "3"}.get(raw[0]) if raw else None


def _contains_possessive(features: dict[str, str]) -> bool:
    for key, value in features.items():
        if not value:
            continue
        # ``source_possessive`` is loader metadata describing the
        # Wiktionary template, not a surface-level possessive suffix on this
        # particular form.
        if key.casefold() == "source_possessive":
            continue
        if "poss" in key.casefold() or "psor" in key.casefold():
            return True
    return False


def _looks_like_infinitive(features: dict[str, str]) -> bool:
    raw = _features_lookup(features, "verbForm", "VerbForm", "form")
    if raw and "inf" in raw.lower():
        return True
    if _features_lookup(features, "infinitive", "Inf"):
        return True
    return False


def _is_base_infinitive(features: dict[str, str]) -> bool:
    """The base infinitive (kotus Inf=1) is the only one we model.

    UD tag set surfaces this as ``VerbForm=Inf`` paired with ``InfForm=1``
    and no case feature; anything else (Inf=2, 3, 4 in various cases) is
    a non-finite participial form we do not yet predict.
    """

    if not _looks_like_infinitive(features):
        return False
    infinitive_kind = _features_lookup(features, "infinitive", "Inf")
    if infinitive_kind and infinitive_kind.strip().casefold() not in {
        "1",
        "inf1",
        "first",
        "base",
    }:
        return False
    inf_form = _features_lookup(features, "infForm", "InfForm")
    if inf_form and inf_form.strip().lower() not in {"1", "inf1"}:
        return False
    case = _features_lookup(features, "case", "Case")
    if case:
        # An infinitive in some oblique case is the 2nd/3rd infinitive's
        # case form (e.g. illative is 3rd inf "tekemään"). Out of scope.
        return False
    return True


def _has_clitic(features: dict[str, str]) -> bool:
    value = _features_lookup(features, "clitic", "Clitic", "clit", "Clit")
    return bool(value)


def _has_non_positive_degree(features: dict[str, str]) -> bool:
    value = _features_lookup(features, "degree", "Degree")
    if not value:
        return False
    return value.strip().lower() not in {"pos", "positive"}


def _is_participle(features: dict[str, str]) -> bool:
    value = _features_lookup(features, "verbForm", "VerbForm")
    if value and "part" in value.lower():
        return True
    if _features_lookup(features, "partForm", "PartForm"):
        return True
    return False


def _is_non_indicative_finite(features: dict[str, str]) -> bool:
    """Conditional, imperative, potential moods are not yet modelled."""

    mood = _features_lookup(features, "mood", "Mood")
    if not mood:
        return False
    norm = mood.strip().lower()
    if norm in {"ind", "indicative"}:
        return False
    if norm in {"cnd", "cond", "imp", "imper", "pot", "potential"}:
        return True
    return False


def _is_non_present_finite(features: dict[str, str]) -> bool:
    tense = _features_lookup(features, "tense", "Tense")
    if not tense:
        return False
    norm = tense.strip().lower()
    return norm not in {"pres", "present"}


def _is_passive_voice(features: dict[str, str]) -> bool:
    voice = _features_lookup(features, "voice", "Voice")
    return bool(voice) and voice.strip().lower() in {"pass", "passive"}


def _is_connegative(features: dict[str, str]) -> bool:
    value = _features_lookup(features, "connegative", "Connegative")
    if value:
        return value.strip().lower() in {"yes", "true", "1"}
    return False


def _is_nonstandard_style(features: dict[str, str]) -> bool:
    value = _features_lookup(features, "style", "Style")
    if not value:
        return False
    return value.strip().casefold() not in {"std", "standard", "neutral"}


def _is_typo_marked(features: dict[str, str]) -> bool:
    value = _features_lookup(features, "typo", "Typo")
    return bool(value) and value.strip().casefold() in {"yes", "true", "1"}


def _is_abbreviation(features: dict[str, str]) -> bool:
    value = _features_lookup(features, "abbr", "Abbr", "abbreviation")
    return bool(value) and value.strip().casefold() in {"yes", "true", "1"}


def _uncertain_guard_reason(features: dict[str, str], is_verb: bool) -> str | None:
    """Cheap pre-flight gate: forms we deliberately don't try to predict.

    Returning ``None`` means the form is within scope; any other string
    is the explanation the caller logs on the ``UNCERTAIN`` verdict.
    """

    if _has_clitic(features):
        return "clitic suffix (-han / -pa / -ko / -kin / -kaan ...) not modelled"
    if _has_non_positive_degree(features):
        return "comparative / superlative adjectives not modelled"
    if _is_participle(features):
        return "participial forms not modelled"
    if _is_nonstandard_style(features):
        return "non-standard style variants not modelled"
    if _is_typo_marked(features):
        return "typo-marked variants not modelled"
    if _is_abbreviation(features):
        return "abbreviations are not modelled"
    derivation = _features_lookup(features, "derivation", "Derivation")
    if derivation:
        # Omorfi labels verbal nouns such as ``oleminen`` with the
        # ``Minen`` derivation while keeping the source lemma ``olla``.  A
        # lemma-only paradigm rule would compare the derived noun against
        # the verb and report a false mismatch.  Other derivational forms
        # have the same shape problem, so leave them for source/LLM review.
        return "derived form not modelled"
    if is_verb:
        if _features_lookup(features, "case", "Case"):
            return "case-bearing non-finite verb form not modelled"
        if _is_passive_voice(features):
            return "passive voice not modelled"
        if _is_connegative(features):
            return "connegative form not modelled"
        if _is_non_indicative_finite(features):
            return "non-indicative finite mood not modelled"
        if _is_non_present_finite(features):
            return "non-present tense not modelled"
    return None
