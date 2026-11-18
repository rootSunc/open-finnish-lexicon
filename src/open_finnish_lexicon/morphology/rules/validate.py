"""Public morphology rule validation entrypoint."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.features import (
    _contains_possessive,
    _features_lookup,
    _is_base_infinitive,
    _is_passive_voice,
    _looks_like_infinitive,
    _normalise_case,
    _normalise_number,
    _normalise_person,
    _uncertain_guard_reason,
)
from open_finnish_lexicon.morphology.rules.nominal import (
    _E_STEM_NALLE_LEMMAS,
    _lexical_pronoun_variants,
    _predict_a_stem_strong_variant,
    _predict_as_aks_variant,
    _predict_as_foreign_i_variant,
    _predict_as_long_variant,
    _predict_as_ordinal_variant,
    _predict_as_variant,
    _predict_e_stem_doubled_stop_variant,
    _predict_e_stem_variants,
    _predict_e_stem_weak_grade_variant,
    _predict_hame_stem_variants,
    _predict_hk_retention_variant,
    _predict_i_stem_variants,
    _predict_nen_variants,
    _predict_nominal,
    _predict_nominal_case_variants,
    _predict_personal_pronoun,
    _predict_us_de_variant,
    _predict_us_foreign_i_variant,
    _predict_vowel_short_variants,
)
from open_finnish_lexicon.morphology.rules.phonology import _normalise
from open_finnish_lexicon.morphology.rules.templates import (
    _ATTACHED_CLITIC_SUFFIXES,
    _KAIKKI_NOMINAL_VARIANTS,
    _OMORFI_NOMINAL_VARIANTS,
    _OMORFI_VERB_VARIANTS,
    _clitic_suffix_variants,
    _matches_nominal_source_template,
    _matches_verb_source_template,
    _orthographic_transliteration_variants,
    _uses_source_comitative_possessive,
)
from open_finnish_lexicon.morphology.rules.types import (
    CASE_NAMES,
    NOMINAL_POS,
    VERB_POS,
    RuleVerdict,
    Verdict,
)
from open_finnish_lexicon.morphology.rules.verbs import (
    _predict_negative_auxiliary,
    _predict_verb,
    _predict_verb_oitse_variant,
    _predict_verb_type4_contracted_conditional,
)

_VERB_VARIANT_RULE_SUFFIXES = (
    "/contracted-cnd-variant",
    "/oitse-variant",
    "/orthographic-variant",
    "/source-variant",
)

_NOMINAL_VARIANT_RULE_SUFFIXES = (
    "/kalleus-variant",
    "/reverse-gradation-variant",
    "/aks-stem-variant",
    "/long-vowel-variant",
    "/ordinal-variant",
    "/foreign-i-variant",
    "/strong-grade-variant",
    "/extended-case-variant",
    "/template-variant",
    "/weak-grade-variant",
    "/stem-variant",
    "/orthographic-variant",
    "/source-variant",
)


def _validate_attached_clitic(
    *,
    lemma: str,
    part_of_speech: str | None,
    surface_norm: str,
    features: dict[str, str],
    form_kind: str | None,
    clitic: str,
) -> RuleVerdict | None:
    """Peel explicit Finnish enclitics and validate the underlying base form."""

    clitic_key = clitic.strip().lstrip("-").casefold()
    for suffix in _clitic_suffix_variants(clitic_key):
        if not surface_norm.endswith(suffix) or len(surface_norm) <= len(suffix):
            continue
        base_surface = surface_norm[: -len(suffix)]
        base_features = {
            key: value
            for key, value in features.items()
            if key.casefold() not in {"clitic", "clit"}
        }
        base_result = validate_form(
            lemma=lemma,
            part_of_speech=part_of_speech,
            surface_form=base_surface,
            features=base_features,
            form_kind=form_kind,
        )
        if base_result.verdict is Verdict.VERIFIED:
            predicted_base = base_result.predicted_surface or base_surface
            return RuleVerdict(
                verdict=Verdict.VERIFIED,
                predicted_surface=f"{predicted_base}{suffix}",
                rule=(
                    f"{base_result.rule}/clitic-{clitic_key}"
                    if base_result.rule
                    else f"clitic/{clitic_key}"
                ),
                explanation=(
                    f"{base_result.explanation}; explicit clitic "
                    f"-{suffix} is attached to the validated base form"
                ),
                confidence=base_result.confidence,
            )
        if base_result.verdict is Verdict.MISMATCH:
            for inner_suffix in _ATTACHED_CLITIC_SUFFIXES:
                if (
                    inner_suffix == suffix
                    or not base_surface.endswith(inner_suffix)
                    or len(base_surface) <= len(inner_suffix)
                ):
                    continue
                inner_surface = base_surface[: -len(inner_suffix)]
                inner_result = validate_form(
                    lemma=lemma,
                    part_of_speech=part_of_speech,
                    surface_form=inner_surface,
                    features=base_features,
                    form_kind=form_kind,
                )
                if inner_result.verdict is not Verdict.VERIFIED:
                    continue
                predicted_base = inner_result.predicted_surface or inner_surface
                return RuleVerdict(
                    verdict=Verdict.VERIFIED,
                    predicted_surface=f"{predicted_base}{inner_suffix}{suffix}",
                    rule=(
                        f"{inner_result.rule}/clitic-{inner_suffix}-{clitic_key}"
                        if inner_result.rule
                        else f"clitic/{inner_suffix}-{clitic_key}"
                    ),
                    explanation=(
                        f"{inner_result.explanation}; stacked clitics "
                        f"-{inner_suffix} and -{suffix} are attached to "
                        "the validated base form"
                    ),
                    confidence=inner_result.confidence,
                )
            predicted_base = base_result.predicted_surface or base_surface
            return RuleVerdict(
                verdict=Verdict.MISMATCH,
                predicted_surface=f"{predicted_base}{suffix}",
                rule=(
                    f"{base_result.rule}/clitic-{clitic_key}"
                    if base_result.rule
                    else f"clitic/{clitic_key}"
                ),
                explanation=(
                    f"{base_result.explanation}; explicit clitic "
                    f"-{suffix} is attached to the validated base form"
                ),
                confidence=base_result.confidence,
            )
        break
    return None


def _validate_negative_auxiliary(
    *,
    surface_form: str,
    surface_norm: str,
    features: dict[str, str],
) -> RuleVerdict | None:
    person = _normalise_person(features)
    number = _normalise_number(features) if person else None
    mood = _features_lookup(features, "mood", "Mood")
    predicted, rule, explanation = _predict_negative_auxiliary(
        mood=mood,
        person=person,
        number=number,
        surface=surface_norm,
    )
    if predicted is None:
        return None
    verdict = Verdict.VERIFIED if _normalise(predicted) == surface_norm else Verdict.MISMATCH
    return RuleVerdict(
        verdict=verdict,
        predicted_surface=_normalise(predicted),
        rule=rule,
        explanation=(
            f"{explanation} | declared surface={surface_form!r} matches"
            if verdict is Verdict.VERIFIED
            else f"{explanation} | declared surface={surface_form!r} differs"
        ),
        confidence=0.97 if verdict is Verdict.VERIFIED else 0.92,
    )


def _validate_pronoun_form(
    *,
    lemma_norm: str,
    surface_form: str,
    surface_norm: str,
    features: dict[str, str],
) -> RuleVerdict | None:
    case = _normalise_case(features)
    number = _normalise_number(features)
    if case is None:
        return None
    predicted, rule, explanation = _predict_personal_pronoun(
        lemma=lemma_norm,
        case=case,
        number=number,
    )
    if predicted is None:
        return None
    variants = {
        _normalise(value)
        for value in _lexical_pronoun_variants(
            lemma=lemma_norm,
            case=case,
            number=number,
        )
    }
    verdict = Verdict.VERIFIED if surface_norm in variants else Verdict.MISMATCH
    predicted_norm = _normalise(predicted)
    if verdict is Verdict.VERIFIED and surface_norm != predicted_norm:
        predicted_norm = surface_norm
        rule = f"{rule}/source-variant"
    return RuleVerdict(
        verdict=verdict,
        predicted_surface=predicted_norm,
        rule=rule,
        explanation=(
            f"{explanation} | declared surface={surface_form!r} matches"
            if verdict is Verdict.VERIFIED
            else f"{explanation} | declared surface={surface_form!r} differs"
        ),
        confidence=0.97 if verdict is Verdict.VERIFIED else 0.92,
    )


def _validate_verb_form(
    *,
    lemma_norm: str,
    surface_form: str,
    surface_norm: str,
    features: dict[str, str],
    form_kind: str | None,
    source_class: str,
) -> RuleVerdict:
    person = _normalise_person(features)
    number = _normalise_number(features) if person else None
    tense = _features_lookup(features, "tense", "Tense")
    mood = _features_lookup(features, "mood", "Mood")
    passive = _is_passive_voice(features)
    infinitive = _is_base_infinitive(features)
    if _looks_like_infinitive(features) and not infinitive:
        return RuleVerdict(
            verdict=Verdict.UNCERTAIN,
            predicted_surface=None,
            rule=None,
            explanation="only the base infinitive (Inf=1, no case) is modelled",
            confidence=0.0,
        )

    predicted, rule, explanation = _predict_verb(
        lemma=lemma_norm,
        tense=tense,
        mood=mood,
        person=person,
        number=number,
        infinitive=infinitive,
        passive=passive,
        source_class=source_class,
    )
    if predicted is None:
        return RuleVerdict(Verdict.UNCERTAIN, None, None, explanation, 0.0)

    predicted_norm = _normalise(predicted)
    verdict = Verdict.VERIFIED if predicted_norm == surface_norm else Verdict.MISMATCH

    if verdict is Verdict.MISMATCH and rule and rule.startswith(
        ("verb/type2/pres.", "verb/type2/past.", "verb/type2/cnd.")
    ):
        oitse_mode = rule.split("/")[2].split(".")[0]
        alternate = _predict_verb_oitse_variant(
            lemma=lemma_norm,
            person=person or "",
            number=number or "",
            source_class=str(features.get("source_class", "")),
            mode=oitse_mode,
        )
        if alternate is not None and _normalise(alternate) == surface_norm:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/oitse-variant"

    if verdict is Verdict.MISMATCH and rule and rule.startswith("verb/type4/cnd."):
        alternate = _predict_verb_type4_contracted_conditional(
            lemma=lemma_norm,
            person=person or "",
            number=number or "",
            source_class=source_class,
        )
        if alternate is not None and _normalise(alternate) == surface_norm:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/contracted-cnd-variant"

    if verdict is Verdict.MISMATCH and features.get("source_variant"):
        return RuleVerdict(
            verdict=Verdict.VERIFIED,
            predicted_surface=surface_norm,
            rule=f"{rule}/source-variant",
            explanation=(
                f"{lemma_norm}: source-declared alternate infinitive "
                f"supports {surface_form!r}"
            ),
            confidence=0.90,
        )

    if verdict is Verdict.MISMATCH and form_kind == "omorfi":
        alternate = _OMORFI_VERB_VARIANTS.get((lemma_norm, person or "", number or ""))
        if alternate is not None and _normalise(alternate) == surface_norm:
            return RuleVerdict(
                verdict=Verdict.VERIFIED,
                predicted_surface=surface_norm,
                rule=f"{rule}/source-variant",
                explanation=f"{lemma_norm}: Omorfi source variant supports {surface_form!r}",
                confidence=0.90,
            )

    if verdict is Verdict.MISMATCH and _matches_verb_source_template(
        lemma_norm=lemma_norm,
        surface_norm=surface_norm,
        person=person,
        number=number,
        passive=passive,
        source_class=source_class,
    ):
        return RuleVerdict(
            verdict=Verdict.VERIFIED,
            predicted_surface=surface_norm,
            rule=f"{rule}/source-template",
            explanation=(
                f"{lemma_norm}: source-declared conjugation template "
                f"supports {surface_form!r}"
            ),
            confidence=0.90,
        )

    if verdict is Verdict.MISMATCH and form_kind == "omorfi":
        orthographic_variants = {
            _normalise(value)
            for value in _orthographic_transliteration_variants(predicted_norm)
        }
        if surface_norm in orthographic_variants:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/orthographic-variant"

    return RuleVerdict(
        verdict=verdict,
        predicted_surface=predicted_norm,
        rule=rule,
        explanation=(
            f"{explanation} | declared surface={surface_form!r} matches"
            if verdict is Verdict.VERIFIED
            else f"{explanation} | declared surface={surface_form!r} differs"
        ),
        confidence=(
            0.90
            if verdict is Verdict.VERIFIED
            and rule
            and rule.endswith(_VERB_VARIANT_RULE_SUFFIXES)
            else 0.97
            if verdict is Verdict.VERIFIED
            else 0.92
        ),
    )


def _matches_surface_set(surface_norm: str, candidates: set[str]) -> bool:
    return surface_norm in {_normalise(value) for value in candidates}


def _resolve_nominal_mismatch(
    *,
    lemma_norm: str,
    surface_norm: str,
    predicted_norm: str,
    rule: str | None,
    case: str,
    number: str,
    form_kind: str | None,
    source_class: str,
) -> tuple[Verdict, str, str | None]:
    if form_kind == "omorfi":
        alternate = _OMORFI_NOMINAL_VARIANTS.get((lemma_norm, case, number))
        if alternate is not None and _normalise(alternate) == surface_norm:
            return Verdict.VERIFIED, surface_norm, f"{rule}/source-variant"

    if form_kind == "kaikki":
        alternate = _KAIKKI_NOMINAL_VARIANTS.get((lemma_norm, case, number))
        if alternate is not None and _normalise(alternate) == surface_norm:
            return Verdict.VERIFIED, surface_norm, f"{rule}/source-variant"

    if rule and rule.startswith("nominal/vowel_short/"):
        if _matches_surface_set(
            surface_norm,
            _predict_vowel_short_variants(lemma=lemma_norm, case=case, number=number),
        ):
            return Verdict.VERIFIED, surface_norm, f"{rule}/loan-variant"

    if rule and rule.startswith("nominal/us_stem/"):
        de_alt = _predict_us_de_variant(lemma=lemma_norm, case=case, number=number)
        if de_alt is not None and _normalise(de_alt) == surface_norm:
            return Verdict.VERIFIED, _normalise(de_alt), f"{rule}/kalleus-variant"
        if _matches_surface_set(
            surface_norm,
            _predict_us_foreign_i_variant(lemma=lemma_norm, case=case, number=number),
        ):
            return Verdict.VERIFIED, surface_norm, f"{rule}/foreign-i-variant"

    if rule and rule.startswith("nominal/nen/"):
        if _matches_surface_set(
            surface_norm,
            _predict_nen_variants(
                lemma=lemma_norm,
                case=case,
                number=number,
                allow_back_harmony="no gradation" in source_class,
            ),
        ):
            return Verdict.VERIFIED, surface_norm, f"{rule}/compound-variant"

    if rule and rule.startswith(("nominal/vowel_short/", "nominal/a_stem_grad/")):
        if _matches_surface_set(
            surface_norm,
            _predict_hk_retention_variant(lemma=lemma_norm, case=case, number=number),
        ):
            return Verdict.VERIFIED, surface_norm, f"{rule}/retained-hk-variant"

    if rule and rule.startswith("nominal/a_stem_grad/"):
        if _matches_surface_set(
            surface_norm,
            _predict_a_stem_strong_variant(lemma=lemma_norm, case=case, number=number),
        ):
            return Verdict.VERIFIED, surface_norm, f"{rule}/strong-grade-variant"

    if rule and rule.startswith("nominal/as_grad/"):
        as_variant_families = (
            ("reverse-gradation-variant", _predict_as_variant),
            ("aks-stem-variant", _predict_as_aks_variant),
            ("long-vowel-variant", _predict_as_long_variant),
            ("ordinal-variant", _predict_as_ordinal_variant),
            ("foreign-i-variant", _predict_as_foreign_i_variant),
        )
        for variant_name, predictor in as_variant_families:
            if _matches_surface_set(
                surface_norm,
                predictor(lemma=lemma_norm, case=case, number=number),
            ):
                return Verdict.VERIFIED, surface_norm, f"{rule}/{variant_name}"

    if rule and case in {"abe", "com", "ins"} and rule.startswith("nominal/"):
        if _matches_surface_set(
            surface_norm,
            _predict_nominal_case_variants(lemma=lemma_norm, case=case, number=number),
        ):
            return Verdict.VERIFIED, surface_norm, f"{rule}/extended-case-variant"

    if rule and rule.startswith("nominal/i_stem/"):
        if _matches_surface_set(
            surface_norm,
            _predict_i_stem_variants(lemma=lemma_norm, case=case, number=number),
        ):
            return Verdict.VERIFIED, surface_norm, f"{rule}/stem-variant"

    if rule and rule.startswith("nominal/e_stem/"):
        if _matches_surface_set(
            surface_norm,
            _predict_e_stem_doubled_stop_variant(
                lemma=lemma_norm, case=case, number=number
            ),
        ):
            return Verdict.VERIFIED, surface_norm, f"{rule}/doubled-stop-variant"
        if form_kind == "kaikki" and _matches_surface_set(
            surface_norm,
            _predict_e_stem_weak_grade_variant(lemma=lemma_norm, case=case, number=number),
        ):
            return Verdict.VERIFIED, surface_norm, f"{rule}/weak-grade-variant"
        nalle_variants = form_kind == "kaikki" or lemma_norm in _E_STEM_NALLE_LEMMAS
        if _matches_surface_set(
            surface_norm,
            _predict_e_stem_variants(lemma=lemma_norm, case=case, number=number),
        ) and (
            _matches_surface_set(
                surface_norm,
                _predict_hame_stem_variants(lemma=lemma_norm, case=case, number=number),
            )
            or nalle_variants
        ):
            return Verdict.VERIFIED, surface_norm, f"{rule}/template-variant"

    if form_kind == "omorfi":
        if _matches_surface_set(
            surface_norm,
            _orthographic_transliteration_variants(predicted_norm),
        ):
            return Verdict.VERIFIED, surface_norm, f"{rule}/orthographic-variant"

    return Verdict.MISMATCH, predicted_norm, rule


def _validate_nominal_form(
    *,
    lemma_norm: str,
    surface_form: str,
    surface_norm: str,
    features: dict[str, str],
    form_kind: str | None,
    source_class: str,
) -> RuleVerdict:
    case = _normalise_case(features)
    number = _normalise_number(features)
    if case is None:
        if surface_norm == lemma_norm and number == "sg":
            return RuleVerdict(
                verdict=Verdict.VERIFIED,
                predicted_surface=lemma_norm,
                rule="nominal/identity/lemma.sg",
                explanation=f"{lemma_norm}: lemma form recorded without case features",
                confidence=0.99,
            )
        return RuleVerdict(
            verdict=Verdict.UNCERTAIN,
            predicted_surface=None,
            rule=None,
            explanation="missing case feature for non-nominative form",
            confidence=0.0,
        )

    if form_kind == "omorfi" and surface_norm == lemma_norm and case != "nom":
        return RuleVerdict(
            verdict=Verdict.UNCERTAIN,
            predicted_surface=None,
            rule=None,
            explanation=(
                "Omorfi surface equals lemma for a non-nominative analysis; "
                "base lemma is unavailable for deterministic validation"
            ),
            confidence=0.0,
        )

    predicted, rule, explanation = _predict_nominal(
        lemma=lemma_norm,
        case=case,
        number=number,
        apply_gradation="no gradation"
        not in str(features.get("source_class", "")).casefold(),
    )
    if predicted is None:
        return RuleVerdict(Verdict.UNCERTAIN, None, None, explanation, 0.0)

    predicted_norm = _normalise(predicted)
    verdict = Verdict.VERIFIED if predicted_norm == surface_norm else Verdict.MISMATCH

    if verdict is Verdict.MISMATCH:
        # Check source-specific lexical variants before template overrides so
        # explicit Omorfi/Kaikki exceptions keep their ``/source-variant`` rule.
        if form_kind in {"omorfi", "kaikki"}:
            table = _OMORFI_NOMINAL_VARIANTS if form_kind == "omorfi" else _KAIKKI_NOMINAL_VARIANTS
            alternate = table.get((lemma_norm, case, number))
            if alternate is not None and _normalise(alternate) == surface_norm:
                predicted_norm = surface_norm
                verdict = Verdict.VERIFIED
                rule = f"{rule}/source-variant"

    if verdict is Verdict.MISMATCH and (
        "nuoripari" in source_class
        or features.get("source_possessive")
        or _matches_nominal_source_template(
            lemma_norm=lemma_norm,
            surface_norm=surface_norm,
            case=case,
            number=number,
            source_class=source_class,
        )
        or _uses_source_comitative_possessive(
            form_kind=form_kind,
            case=case,
            number=number,
            surface=surface_norm,
        )
    ):
        return RuleVerdict(
            verdict=Verdict.VERIFIED,
            predicted_surface=surface_norm,
            rule=f"{rule}/source-template",
            explanation=(
                f"{lemma_norm}: source-declared compound/possessive template "
                f"supports {surface_form!r}"
            ),
            confidence=0.90,
        )

    if verdict is Verdict.MISMATCH:
        verdict, predicted_norm, rule = _resolve_nominal_mismatch(
            lemma_norm=lemma_norm,
            surface_norm=surface_norm,
            predicted_norm=predicted_norm,
            rule=rule,
            case=case,
            number=number,
            form_kind=form_kind,
            source_class=source_class,
        )

    nice_case = CASE_NAMES.get(case, case)
    nice_number = "singular" if number == "sg" else "plural"
    if verdict is Verdict.VERIFIED:
        explanation_full = (
            f"{lemma_norm}: {nice_case} {nice_number} -> {predicted_norm} "
            f"(declared surface {surface_form!r} matches)"
        )
        confidence = (
            0.90
            if rule and rule.endswith(_NOMINAL_VARIANT_RULE_SUFFIXES)
            else 0.97
        )
    else:
        explanation_full = (
            f"{lemma_norm}: expected {nice_case} {nice_number} {predicted_norm!r}, "
            f"got {surface_form!r}"
        )
        confidence = 0.92

    return RuleVerdict(
        verdict=verdict,
        predicted_surface=predicted_norm,
        rule=rule,
        explanation=explanation_full,
        confidence=confidence,
    )


def validate_form(
    *,
    lemma: str,
    part_of_speech: str | None,
    surface_form: str,
    features: dict[str, str],
    form_kind: str | None = None,
) -> RuleVerdict:
    """Validate a single ``lexicon.form`` row against the rule engine."""

    lemma_norm = _normalise(lemma)
    surface_norm = _normalise(surface_form)
    pos = (part_of_speech or "").lower()
    source_class = str(features.get("source_class", "")).casefold()

    if not lemma_norm or not surface_norm:
        return RuleVerdict(
            verdict=Verdict.UNCERTAIN,
            predicted_surface=None,
            rule=None,
            explanation="missing lemma or surface",
            confidence=0.0,
        )

    is_nominal = pos in NOMINAL_POS or pos.startswith(
        ("noun", "adjective", "pronoun", "numeral", "propn")
    )
    is_verb = pos in VERB_POS or pos.startswith("verb")
    is_auxiliary = pos in {"aux", "auxiliary"} or pos.startswith("aux")
    is_verb_like = is_verb or is_auxiliary
    is_pronoun = pos in {"pron", "pronoun"} or pos.startswith("pron")

    if _contains_possessive(
        features, is_verb=is_verb_like and not _looks_like_infinitive(features)
    ):
        return RuleVerdict(
            verdict=Verdict.UNCERTAIN,
            predicted_surface=None,
            rule=None,
            explanation="possessive suffixes are not modelled by the rule engine",
            confidence=0.0,
        )

    is_numeral = pos in {"num", "numeral"} or pos.startswith("num")
    if is_numeral:
        return RuleVerdict(
            verdict=Verdict.UNCERTAIN,
            predicted_surface=None,
            rule=None,
            explanation="numeral paradigms are not modelled by the rule engine",
            confidence=0.0,
        )

    clitic = _features_lookup(features, "clitic", "Clitic", "clit", "Clit")
    if clitic:
        clitic_result = _validate_attached_clitic(
            lemma=lemma,
            part_of_speech=part_of_speech,
            surface_norm=surface_norm,
            features=features,
            form_kind=form_kind,
            clitic=clitic,
        )
        if clitic_result is not None:
            return clitic_result

    guard_reason = _uncertain_guard_reason(features, is_verb_like)

    if lemma_norm == "ei" and is_verb_like and guard_reason in {
        None,
        "non-indicative finite mood not modelled",
    }:
        neg_result = _validate_negative_auxiliary(
            surface_form=surface_form,
            surface_norm=surface_norm,
            features=features,
        )
        if neg_result is not None:
            return neg_result

    if is_pronoun and guard_reason is None:
        pron_result = _validate_pronoun_form(
            lemma_norm=lemma_norm,
            surface_form=surface_form,
            surface_norm=surface_norm,
            features=features,
        )
        if pron_result is not None:
            return pron_result

    if guard_reason is not None:
        return RuleVerdict(
            verdict=Verdict.UNCERTAIN,
            predicted_surface=None,
            rule=None,
            explanation=guard_reason,
            confidence=0.0,
        )

    if is_verb_like or _looks_like_infinitive(features):
        return _validate_verb_form(
            lemma_norm=lemma_norm,
            surface_form=surface_form,
            surface_norm=surface_norm,
            features=features,
            form_kind=form_kind,
            source_class=source_class,
        )

    if not is_nominal:
        return RuleVerdict(
            verdict=Verdict.UNCERTAIN,
            predicted_surface=None,
            rule=None,
            explanation=f"part-of-speech {pos!r} not covered by rule engine",
            confidence=0.0,
        )

    return _validate_nominal_form(
        lemma_norm=lemma_norm,
        surface_form=surface_form,
        surface_norm=surface_norm,
        features=features,
        form_kind=form_kind,
        source_class=source_class,
    )
