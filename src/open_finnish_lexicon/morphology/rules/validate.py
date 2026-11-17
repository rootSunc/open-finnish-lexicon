"""Public morphology rule validation entrypoint."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.features import (
    _contains_possessive,
    _features_lookup,
    _is_base_infinitive,
    _looks_like_infinitive,
    _normalise_case,
    _normalise_number,
    _normalise_person,
    _uncertain_guard_reason,
)
from open_finnish_lexicon.morphology.rules.nominal import (
    _E_STEM_NALLE_LEMMAS,
    _predict_as_variant,
    _predict_as_aks_variant,
    _predict_as_foreign_i_variant,
    _predict_as_long_variant,
    _predict_as_ordinal_variant,
    _predict_e_stem_variants,
    _predict_e_stem_doubled_stop_variant,
    _predict_e_stem_weak_grade_variant,
    _predict_hame_stem_variants,
    _predict_a_stem_strong_variant,
    _predict_hk_retention_variant,
    _predict_i_stem_variants,
    _predict_nen_variants,
    _predict_nominal_case_variants,
    _predict_nominal,
    _lexical_pronoun_variants,
    _predict_personal_pronoun,
    _predict_us_de_variant,
    _predict_us_foreign_i_variant,
    _predict_vowel_short_variants,
)
from open_finnish_lexicon.morphology.rules.phonology import _normalise
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
)


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


def _uses_source_comitative_possessive(
    *, form_kind: str | None, case: str, number: str, surface: str
) -> bool:
    """Recognize Kaikki's unlabelled possessive comitative cells.

    Finnish comitative plurals are normally realized with ``-ineen`` (or
    ``-oineen``) after a possessive suffix, while a few source rows expose
    only ``Case=Com|Number=Plur``. Treat the explicit source surface as the
    authoritative cell instead of reporting a false stem mismatch.
    """

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

    if _contains_possessive(features):
        return RuleVerdict(
            verdict=Verdict.UNCERTAIN,
            predicted_surface=None,
            rule=None,
            explanation="possessive suffixes are validated by the LLM stage",
            confidence=0.0,
        )

    # ``name`` starts with the shorthand ``n`` but is not a noun. Keep the
    # explicit shorthands while avoiding accidental POS-prefix matches.
    is_nominal = pos in NOMINAL_POS or pos.startswith(
        ("noun", "adjective", "pronoun", "numeral", "propn")
    )
    is_verb = pos in VERB_POS or pos.startswith("verb")
    is_auxiliary = pos in {"aux", "auxiliary"} or pos.startswith("aux")
    is_verb_like = is_verb or is_auxiliary
    is_pronoun = pos in {"pron", "pronoun"} or pos.startswith("pron")
    # Numeral paradigms (especially ordinals like ``kolmas``, ``yhdeksäs``)
    # follow their own rules and would confuse the as_grad classifier.
    is_numeral = pos in {"num", "numeral"} or pos.startswith("num")
    if is_numeral:
        return RuleVerdict(
            verdict=Verdict.UNCERTAIN,
            predicted_surface=None,
            rule=None,
            explanation="numeral paradigms are not modelled by the rule engine",
            confidence=0.0,
        )

    # Finnish enclitics are orthographically attached to an already
    # inflected word.  When the source gives us an explicit clitic tag, peel
    # off only the suffixes that tag permits and validate the base form with
    # the same rules as an ordinary row.  This keeps clitic rows out of the
    # false-mismatch queue without turning an unsupported base paradigm into
    # a verified form.
    clitic = _features_lookup(features, "clitic", "Clitic", "clit", "Clit")
    if clitic:
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
                predicted_surface = f"{predicted_base}{suffix}"
                return RuleVerdict(
                    verdict=Verdict.VERIFIED,
                    predicted_surface=predicted_surface,
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
                # Omorfi can expose only the outer clitic in a stacked form
                # such as ``mikäköhän``. If the one-suffix base mismatches,
                # try the other explicitly known Finnish clitics once before
                # deciding that the row is truly wrong.
                for inner_suffix in _ATTACHED_CLITIC_SUFFIXES:
                    if inner_suffix == suffix:
                        continue
                    if not base_surface.endswith(inner_suffix):
                        continue
                    if len(base_surface) <= len(inner_suffix):
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
                        predicted_surface=(
                            f"{predicted_base}{inner_suffix}{suffix}"
                        ),
                        rule=(
                            f"{inner_result.rule}/clitic-{inner_suffix}-"
                            f"{clitic_key}"
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

    guard_reason = _uncertain_guard_reason(features, is_verb_like)

    if lemma_norm == "ei" and is_verb_like and guard_reason in {
        None,
        "non-indicative finite mood not modelled",
    }:
        person = _normalise_person(features)
        number = _normalise_number(features) if person else None
        mood = _features_lookup(features, "mood", "Mood")
        predicted, rule, explanation = _predict_negative_auxiliary(
            mood=mood,
            person=person,
            number=number,
            surface=surface_norm,
        )
        if predicted is not None:
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

    if is_pronoun and guard_reason is None:
        case = _normalise_case(features)
        number = _normalise_number(features)
        if case is not None:
            predicted, rule, explanation = _predict_personal_pronoun(
                lemma=lemma_norm,
                case=case,
                number=number,
            )
            if predicted is not None:
                variants = {
                    _normalise(value)
                    for value in _lexical_pronoun_variants(
                        lemma=lemma_norm,
                        case=case,
                        number=number,
                    )
                }
                verdict = (
                    Verdict.VERIFIED
                    if surface_norm in variants
                    else Verdict.MISMATCH
                )
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

    if guard_reason is not None:
        return RuleVerdict(
            verdict=Verdict.UNCERTAIN,
            predicted_surface=None,
            rule=None,
            explanation=guard_reason,
            confidence=0.0,
        )

    if is_verb_like or _looks_like_infinitive(features):
        person = _normalise_person(features)
        number = _normalise_number(features) if person else None
        tense = _features_lookup(features, "tense", "Tense")
        mood = _features_lookup(features, "mood", "Mood")
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
        )
        if predicted is None:
            return RuleVerdict(Verdict.UNCERTAIN, None, None, explanation, 0.0)
        predicted_norm = _normalise(predicted)
        verdict = Verdict.VERIFIED if predicted_norm == surface_norm else Verdict.MISMATCH
        if verdict is Verdict.MISMATCH and rule and rule.startswith("verb/type2/pres."):
            alternate = _predict_verb_oitse_variant(
                lemma=lemma_norm,
                person=person or "",
                number=number or "",
                source_class=str(features.get("source_class", "")),
            )
            if alternate is not None and _normalise(alternate) == surface_norm:
                predicted_norm = surface_norm
                verdict = Verdict.VERIFIED
                rule = f"{rule}/oitse-variant"
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
            alternate = _OMORFI_VERB_VARIANTS.get(
                (lemma_norm, person or "", number or "")
            )
            if alternate is not None and _normalise(alternate) == surface_norm:
                return RuleVerdict(
                    verdict=Verdict.VERIFIED,
                    predicted_surface=surface_norm,
                    rule=f"{rule}/source-variant",
                    explanation=(
                        f"{lemma_norm}: Omorfi source variant supports "
                        f"{surface_form!r}"
                    ),
                    confidence=0.90,
                )
        if verdict is Verdict.MISMATCH and _uses_source_template_fallback(source_class):
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
                and rule.endswith(
                    ("/oitse-variant", "/orthographic-variant", "/source-variant")
                )
                else 0.97
                if verdict is Verdict.VERIFIED
                else 0.92
            ),
        )

    if not is_nominal:
        return RuleVerdict(
            verdict=Verdict.UNCERTAIN,
            predicted_surface=None,
            rule=None,
            explanation=f"part-of-speech {pos!r} not covered by rule engine",
            confidence=0.0,
        )

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

    # Omorfi occasionally exposes an inflected-only lexeme as its own lemma
    # (for example ``hyvättä`` with an abessive analysis).  Comparing that
    # surface to the same string as a productive a-stem lemma creates a false
    # mismatch such as ``hyvätättä``.  The source row does not contain the
    # missing base lemma, so this is not safely verifiable by a lemma-only
    # rule; keep it out of the mismatch queue instead.
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
    if verdict is Verdict.MISMATCH and form_kind == "omorfi":
        alternate = _OMORFI_NOMINAL_VARIANTS.get((lemma_norm, case, number))
        if alternate is not None and _normalise(alternate) == surface_norm:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/source-variant"
    if verdict is Verdict.MISMATCH and form_kind == "kaikki":
        alternate = _KAIKKI_NOMINAL_VARIANTS.get((lemma_norm, case, number))
        if alternate is not None and _normalise(alternate) == surface_norm:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/source-variant"
    if verdict is Verdict.MISMATCH and (
        "nuoripari" in source_class
        or features.get("source_possessive")
        or _uses_source_template_fallback(source_class)
        or _uses_source_comitative_possessive(
            form_kind=form_kind,
            case=case,
            number=number,
            surface=surface_norm,
        )
    ):
        # These compact rows retain a complete source-declared paradigm that
        # is more specific than the lemma-only rule engine: ``nuoripari``
        # inflects both components of compounds, a possessive template can
        # inflect the base before the stored lemma's possessive suffix, and
        # special loan/gradation templates encode a non-compositional stem.
        # Keep the source form trusted without pretending the generic rule
        # predicted its internal stem alternation.
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
    if verdict is Verdict.MISMATCH and rule and rule.startswith("nominal/vowel_short/"):
        if surface_norm in {
            _normalise(value)
            for value in _predict_vowel_short_variants(
                lemma=lemma_norm,
                case=case,
                number=number,
            )
        }:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/loan-variant"
    if verdict is Verdict.MISMATCH and rule and rule.startswith("nominal/us_stem/"):
        # Kotus 39 and Kotus 40 share the same surface ending but use
        # different oblique stems (``vastaukse-`` vs ``rakkaude-``).
        # Accept the alternative only when the complete case form matches;
        # this still catches a form assigned to the wrong case.
        alternate = _predict_us_de_variant(
            lemma=lemma_norm,
            case=case,
            number=number,
        )
        if alternate is not None and _normalise(alternate) == surface_norm:
            predicted_norm = _normalise(alternate)
            verdict = Verdict.VERIFIED
            rule = f"{rule}/kalleus-variant"
    if verdict is Verdict.MISMATCH and rule and rule.startswith("nominal/us_stem/"):
        if surface_norm in {
            _normalise(value)
            for value in _predict_us_foreign_i_variant(
                lemma=lemma_norm,
                case=case,
                number=number,
            )
        }:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/foreign-i-variant"
    if verdict is Verdict.MISMATCH and rule and rule.startswith("nominal/nen/"):
        if surface_norm in {
            _normalise(value)
            for value in _predict_nen_variants(
                lemma=lemma_norm,
                case=case,
                number=number,
                allow_back_harmony="no gradation" in source_class,
            )
        }:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/compound-variant"
    if (
        verdict is Verdict.MISMATCH
        and rule
        and rule.startswith(("nominal/vowel_short/", "nominal/a_stem_grad/"))
    ):
        if surface_norm in {
            _normalise(value)
            for value in _predict_hk_retention_variant(
                lemma=lemma_norm,
                case=case,
                number=number,
            )
        }:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/retained-hk-variant"
    if verdict is Verdict.MISMATCH and rule and rule.startswith("nominal/a_stem_grad/"):
        if surface_norm in {
            _normalise(value)
            for value in _predict_a_stem_strong_variant(
                lemma=lemma_norm,
                case=case,
                number=number,
            )
        }:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/strong-grade-variant"
    if verdict is Verdict.MISMATCH and rule and rule.startswith("nominal/as_grad/"):
        # ``-as/-äs`` nouns and adjectives encode their weak-to-strong
        # consonant restoration in the source template, which is not kept in
        # the compact lexeme row. Accept a complete alternative paradigm
        # form when it matches exactly. The source has several distinct
        # families, so keep their explanations separate instead of treating
        # every ``-as`` lemma as one productive pattern.
        as_variant_families = (
            ("reverse-gradation-variant", _predict_as_variant),
            ("aks-stem-variant", _predict_as_aks_variant),
            ("long-vowel-variant", _predict_as_long_variant),
            ("ordinal-variant", _predict_as_ordinal_variant),
            ("foreign-i-variant", _predict_as_foreign_i_variant),
        )
        for variant_name, predictor in as_variant_families:
            if surface_norm in {
                _normalise(value)
                for value in predictor(
                    lemma=lemma_norm,
                    case=case,
                    number=number,
                )
            }:
                predicted_norm = surface_norm
                verdict = Verdict.VERIFIED
                rule = f"{rule}/{variant_name}"
                break
    if (
        verdict is Verdict.MISMATCH
        and rule
        and case in {"abe", "com", "ins"}
        and rule.startswith("nominal/")
    ):
        # The plural stem of less common cases has a few regular lexical
        # variants (for example ``risti -> ristein`` and ``tukka -> tukin``).
        # Keep the canonical prediction above, but accept an exact form
        # supported by the source paradigm rather than turning it into a
        # false mismatch.
        if surface_norm in {
            _normalise(value)
            for value in _predict_nominal_case_variants(
                lemma=lemma_norm,
                case=case,
                number=number,
            )
        }:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/extended-case-variant"
    if verdict is Verdict.MISMATCH and rule and rule.startswith("nominal/i_stem/"):
        if surface_norm in {
            _normalise(value)
            for value in _predict_i_stem_variants(
                lemma=lemma_norm,
                case=case,
                number=number,
            )
        }:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/stem-variant"
    if (
        verdict is Verdict.MISMATCH
        and rule
        and rule.startswith("nominal/e_stem/")
    ):
        hame_variants = _predict_hame_stem_variants(
            lemma=lemma_norm,
            case=case,
            number=number,
        )
        nalle_variants = (
            form_kind == "kaikki" or lemma_norm in _E_STEM_NALLE_LEMMAS
        )
        e_stem_variants = {
            _normalise(value)
            for value in _predict_e_stem_variants(
                lemma=lemma_norm,
                case=case,
                number=number,
            )
        }
        doubled_stop_variants = {
            _normalise(value)
            for value in _predict_e_stem_doubled_stop_variant(
                lemma=lemma_norm,
                case=case,
                number=number,
            )
        }
        weak_grade_variants = {
            _normalise(value)
            for value in _predict_e_stem_weak_grade_variant(
                lemma=lemma_norm,
                case=case,
                number=number,
            )
        }
        hame_variant_surfaces = {_normalise(value) for value in hame_variants}
        if surface_norm in doubled_stop_variants:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/doubled-stop-variant"
        elif form_kind == "kaikki" and surface_norm in weak_grade_variants:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/weak-grade-variant"
        elif surface_norm in e_stem_variants and (
            surface_norm in hame_variant_surfaces or nalle_variants
        ):
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/template-variant"
    if verdict is Verdict.MISMATCH and form_kind == "omorfi":
        orthographic_variants = {
            _normalise(value)
            for value in _orthographic_transliteration_variants(predicted_norm)
        }
        if surface_norm in orthographic_variants:
            predicted_norm = surface_norm
            verdict = Verdict.VERIFIED
            rule = f"{rule}/orthographic-variant"
    nice_case = CASE_NAMES.get(case, case)
    nice_number = "singular" if number == "sg" else "plural"
    if verdict is Verdict.VERIFIED:
        explanation_full = (
            f"{lemma_norm}: {nice_case} {nice_number} -> {predicted_norm} "
            f"(declared surface {surface_form!r} matches)"
        )
        confidence = (
            0.90
            if rule
            and rule.endswith(
                (
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
            )
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
