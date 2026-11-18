"""Nominal Kotus classification and case/number prediction subpackage."""

from __future__ import annotations

from open_finnish_lexicon.morphology.rules.nominal.classify import (
    _classify_nominal,
    _has_neutral_terminal_component,
    _is_usi_family,
)
from open_finnish_lexicon.morphology.rules.nominal.consonant_stems import (
    _predict_a_stem_strong_variant,
    _predict_as_aks_variant,
    _predict_as_foreign_i_variant,
    _predict_as_long_variant,
    _predict_as_ordinal_variant,
    _predict_as_variant,
    _predict_hk_retention_variant,
    _predict_nen_variants,
    _predict_us_de_variant,
    _predict_us_foreign_i_variant,
)
from open_finnish_lexicon.morphology.rules.nominal.declension import (
    _predict_nominal,
    _predict_nominal_case_variants,
    _predict_vowel_short_variants,
)
from open_finnish_lexicon.morphology.rules.nominal.e_stems import (
    _E_STEM_NALLE_LEMMAS,
    _predict_e_stem_doubled_stop_variant,
    _predict_e_stem_variants,
    _predict_e_stem_weak_grade_variant,
    _predict_hame_stem_variants,
)
from open_finnish_lexicon.morphology.rules.nominal.i_stems import (
    _predict_i_stem_variants,
)
from open_finnish_lexicon.morphology.rules.nominal.pronouns import (
    _lexical_pronoun_variants,
    _predict_personal_pronoun,
)

__all__ = [
    "_E_STEM_NALLE_LEMMAS",
    "_classify_nominal",
    "_has_neutral_terminal_component",
    "_is_usi_family",
    "_lexical_pronoun_variants",
    "_predict_a_stem_strong_variant",
    "_predict_as_aks_variant",
    "_predict_as_foreign_i_variant",
    "_predict_as_long_variant",
    "_predict_as_ordinal_variant",
    "_predict_as_variant",
    "_predict_e_stem_doubled_stop_variant",
    "_predict_e_stem_variants",
    "_predict_e_stem_weak_grade_variant",
    "_predict_hame_stem_variants",
    "_predict_hk_retention_variant",
    "_predict_i_stem_variants",
    "_predict_nen_variants",
    "_predict_nominal",
    "_predict_nominal_case_variants",
    "_predict_personal_pronoun",
    "_predict_us_de_variant",
    "_predict_us_foreign_i_variant",
    "_predict_vowel_short_variants",
]
