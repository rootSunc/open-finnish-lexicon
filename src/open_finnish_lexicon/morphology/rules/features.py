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


def _contains_possessive(features: dict[str, str], *, is_verb: bool = False) -> bool:
    for key, value in features.items():
        if not value:
            continue
        key_fold = key.casefold()
        # ``source_possessive`` is loader metadata describing the
        # Wiktionary template, not a surface-level possessive suffix on this
        # particular form.
        if key_fold == "source_possessive":
            continue
        if "poss" in key_fold or "psor" in key_fold:
            return True
        if not is_verb and key_fold == "person":
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
    """The base infinitive (kotus Inf=1) is the only infinitive we model."""

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
    if _features_lookup(features, "partForm", "PartForm", "participle", "Participle"):
        return True
    return False


def _normalise_mood(features: dict[str, str]) -> str | None:
    mood = _features_lookup(features, "mood", "Mood")
    if not mood:
        return None
    norm = mood.strip().lower()
    if norm in {"ind", "indicative"}:
        return "ind"
    if norm in {"cnd", "cond", "conditional"}:
        return "cnd"
    if norm in {"imp", "imper", "imperative"}:
        return "imp"
    if norm in {"pot", "potential"}:
        return "pot"
    return norm


def _normalise_tense(features: dict[str, str]) -> str | None:
    tense = _features_lookup(features, "tense", "Tense")
    if not tense:
        return None
    norm = tense.strip().lower()
    if norm in {"pres", "present"}:
        return "pres"
    if norm in {"past", "imperfect", "impf"}:
        return "past"
    return norm


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
    """Cheap pre-flight gate: forms we deliberately don't try to predict."""

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
        return "derived form not modelled"
    if is_verb:
        if _features_lookup(features, "case", "Case"):
            return "case-bearing non-finite verb form not modelled"
        if _is_connegative(features):
            return "connegative form not modelled"
        mood_norm = _normalise_mood(features)
        tense_norm = _normalise_tense(features)
        if _is_passive_voice(features):
            if mood_norm not in {None, "ind"} or tense_norm not in {None, "pres"}:
                return "non-present or non-indicative passive voice not modelled"
            return None
        if mood_norm not in {None, "ind", "cnd"}:
            return "non-indicative finite mood not modelled"
        if mood_norm == "cnd" and tense_norm not in {None, "pres"}:
            return "non-present conditional tense not modelled"
        if tense_norm not in {None, "pres", "past"}:
            return "non-present tense not modelled"
    return None
