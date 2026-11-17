import unittest

from open_finnish_lexicon.morphology.rules import (
    Verdict,
    validate_form,
)


def _features(case: str | None = None, number: str | None = None, **extra: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    if case is not None:
        payload["case"] = case
    if number is not None:
        payload["number"] = number
    payload.update(extra)
    return payload


def _verify(
    lemma: str,
    pos: str,
    surface: str,
    features: dict[str, str],
) -> tuple[Verdict, str | None]:
    result = validate_form(
        lemma=lemma,
        part_of_speech=pos,
        surface_form=surface,
        features=features,
    )
    return result.verdict, result.predicted_surface


class SisuTests(unittest.TestCase):
    """The user-reported P0 case from the design review."""

    def test_sisu_nominative_is_verified(self):
        verdict, predicted = _verify("sisu", "noun", "sisu", _features("nominative", "singular"))
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "sisu")

    def test_sisu_genitive_correct_form(self):
        verdict, predicted = _verify("sisu", "noun", "sisun", _features("genitive", "singular"))
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "sisun")

    def test_sisu_genitive_mislabelled_sisua_is_caught(self):
        verdict, predicted = _verify(
            "sisu",
            "noun",
            "sisua",
            _features("genitive", "singular"),
        )
        self.assertEqual(verdict, Verdict.MISMATCH)
        self.assertEqual(predicted, "sisun")

    def test_sisu_partitive(self):
        verdict, predicted = _verify("sisu", "noun", "sisua", _features("partitive", "singular"))
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "sisua")

    def test_sisu_inessive(self):
        verdict, predicted = _verify("sisu", "noun", "sisussa", _features("inessive", "singular"))
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "sisussa")

    def test_sisu_elative(self):
        verdict, _ = _verify("sisu", "noun", "sisusta", _features("elative", "singular"))
        self.assertEqual(verdict, Verdict.VERIFIED)

    def test_sisu_illative(self):
        verdict, predicted = _verify("sisu", "noun", "sisuun", _features("illative", "singular"))
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "sisuun")

    def test_sisu_illative_mislabelled_sisun_is_caught(self):
        verdict, predicted = _verify("sisu", "noun", "sisun", _features("illative", "singular"))
        self.assertEqual(verdict, Verdict.MISMATCH)
        self.assertEqual(predicted, "sisuun")

    def test_sisu_inessive_mislabelled_sisuja_is_caught(self):
        # sisuja is partitive plural, not inessive singular.
        verdict, predicted = _verify("sisu", "noun", "sisuja", _features("inessive", "singular"))
        self.assertEqual(verdict, Verdict.MISMATCH)
        self.assertEqual(predicted, "sisussa")

    def test_sisu_adessive(self):
        verdict, _ = _verify("sisu", "noun", "sisulla", _features("adessive", "singular"))
        self.assertEqual(verdict, Verdict.VERIFIED)

    def test_sisu_allative(self):
        verdict, _ = _verify("sisu", "noun", "sisulle", _features("allative", "singular"))
        self.assertEqual(verdict, Verdict.VERIFIED)


class LexicalParadigmTests(unittest.TestCase):
    def test_han_personal_pronoun_paradigm(self):
        verdict, predicted = _verify(
            "hän", "pron", "heidän", _features("genitive", "plural")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "heidän")

    def test_han_personal_pronoun_mismatch_is_caught(self):
        verdict, predicted = _verify(
            "hän", "pron", "hänelle", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.MISMATCH)
        self.assertEqual(predicted, "hänen")

    def test_personal_pronoun_clitic_reuses_base_paradigm(self):
        verdict, predicted = _verify(
            "hän",
            "pron",
            "hänkin",
            _features("nominative", "singular", clitic="Kin"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "hänkin")

    def test_negative_auxiliary_clitic_reuses_base_paradigm(self):
        verdict, predicted = _verify(
            "ei",
            "aux",
            "eikö",
            _features(
                number="singular",
                person="3",
                mood="indicative",
                clitic="Ko",
            ),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "eikö")

    def test_stacked_clitics_reuse_the_base_paradigm(self):
        verdict, predicted = _verify(
            "mikä",
            "pron",
            "mikäköhän",
            _features("nominative", "singular", clitic="Han"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "mikäköhän")

    def test_negative_auxiliary_indicative_and_imperative(self):
        for surface, mood, number, person in (
            ("eivät", "indicative", "plural", "3"),
            ("älkää", "imperative", "plural", "2"),
        ):
            with self.subTest(surface=surface):
                verdict, predicted = _verify(
                    "ei",
                    "aux",
                    surface,
                    _features(number=number, mood=mood, person=person),
                )
                self.assertEqual(verdict, Verdict.VERIFIED)
                self.assertEqual(predicted, surface)

    def test_auxiliary_olla_uses_irregular_verb_paradigm(self):
        verdict, predicted = _verify(
            "olla",
            "aux",
            "ovat",
            _features(number="plural", person="3", mood="indicative"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "ovat")

    def test_interrogative_pronoun_accepts_suppletive_variant(self):
        verdict, predicted = _verify(
            "kuka",
            "pron",
            "kelle",
            _features("allative", "singular"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "kelle")

    def test_interrogative_pronoun_catches_wrong_case(self):
        verdict, predicted = _verify(
            "mikä",
            "pron",
            "minkä",
            _features("partitive", "singular"),
        )
        self.assertEqual(verdict, Verdict.MISMATCH)
        self.assertEqual(predicted, "mitä")

    def test_relative_pronoun_accepts_accusative_variant(self):
        verdict, predicted = _verify(
            "joka",
            "pron",
            "jonka",
            _features("accusative", "singular"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "jonka")

    def test_suppletive_quantifier_pronouns_use_lexical_paradigms(self):
        cases = (
            ("toinen", "toisten", "genitive", "plural"),
            ("kumpi", "kummalle", "allative", "singular"),
            ("moni", "monta", "partitive", "singular"),
            ("eräs", "eräiden", "genitive", "plural"),
            ("kaikki", "kaikkeen", "illative", "singular"),
            ("itse", "itsekään", "nominative", "singular"),
            ("kukin", "kunkin", "genitive", "singular"),
            ("muutama", "muutamissa", "inessive", "plural"),
            ("jompikumpi", "jommankumman", "genitive", "singular"),
            ("se", "sillä", "adessive", "singular"),
            ("tämä", "tämänkin", "genitive", "singular"),
            ("tuo", "tuossa", "inessive", "singular"),
            ("me", "meidän", "genitive", "plural"),
            ("te", "teillä", "adessive", "plural"),
            ("he", "heitä", "partitive", "plural"),
        )
        for lemma, surface, case, number in cases:
            with self.subTest(lemma=lemma, surface=surface):
                features = _features(case, number)
                if lemma == "itse":
                    features["Clitic"] = "Kaan"
                if lemma == "tämä":
                    features["Clitic"] = "Kin"
                verdict, predicted = _verify(lemma, "pron", surface, features)
                self.assertEqual(verdict, Verdict.VERIFIED)
                self.assertEqual(predicted, surface)


class SisukasTests(unittest.TestCase):
    """The other P0 lemma from the review."""

    def test_nominative(self):
        verdict, _ = _verify("sisukas", "adjective", "sisukas", _features("nominative", "singular"))
        self.assertEqual(verdict, Verdict.VERIFIED)

    def test_genitive(self):
        verdict, predicted = _verify(
            "sisukas",
            "adjective",
            "sisukkaan",
            _features("genitive", "singular"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "sisukkaan")

    def test_partitive(self):
        verdict, _ = _verify(
            "sisukas",
            "adjective",
            "sisukasta",
            _features("partitive", "singular"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)

    def test_illative(self):
        verdict, predicted = _verify(
            "sisukas",
            "adjective",
            "sisukkaaseen",
            _features("illative", "singular"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "sisukkaaseen")

    def test_plural_nominative(self):
        verdict, predicted = _verify(
            "sisukas",
            "adjective",
            "sisukkaat",
            _features("nominative", "plural"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "sisukkaat")

    def test_plural_nominative_mislabelled_as_illative_is_caught(self):
        # Common Forms bug from the review: sisukkaat tagged Illative.
        verdict, _ = _verify(
            "sisukas",
            "adjective",
            "sisukkaat",
            _features("illative", "singular"),
        )
        self.assertEqual(verdict, Verdict.MISMATCH)


class CoreParadigmsTests(unittest.TestCase):
    """Smoke tests across the high-coverage kotus types."""

    def test_talo_paradigm(self):
        cases = {
            "nominative": "talo",
            "genitive": "talon",
            "partitive": "taloa",
            "inessive": "talossa",
            "elative": "talosta",
            "illative": "taloon",
            "adessive": "talolla",
            "allative": "talolle",
        }
        for case, surface in cases.items():
            verdict, predicted = _verify("talo", "noun", surface, _features(case, "singular"))
            self.assertEqual(
                verdict,
                Verdict.VERIFIED,
                msg=f"talo {case}={surface} expected verified, got {verdict} predicting {predicted}",
            )

    def test_kala_paradigm(self):
        cases = {
            "nominative": "kala",
            "genitive": "kalan",
            "partitive": "kalaa",
            "inessive": "kalassa",
            "elative": "kalasta",
            "illative": "kalaan",
            "adessive": "kalalla",
            "allative": "kalalle",
        }
        for case, surface in cases.items():
            verdict, predicted = _verify("kala", "noun", surface, _features(case, "singular"))
            self.assertEqual(
                verdict,
                Verdict.VERIFIED,
                msg=f"kala {case}={surface} -> {predicted} ({verdict})",
            )

    def test_kala_plural(self):
        verdict, predicted = _verify(
            "kala",
            "noun",
            "kalat",
            _features("nominative", "plural"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "kalat")

    def test_tukka_geminate_gradation(self):
        verdict, predicted = _verify(
            "tukka",
            "noun",
            "tukan",
            _features("genitive", "singular"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "tukan")

    def test_kissa_paradigm(self):
        # No gradation; "ss" is not in the gradation table.
        verdict, _ = _verify("kissa", "noun", "kissan", _features("genitive", "singular"))
        self.assertEqual(verdict, Verdict.VERIFIED)

    def test_kyla_front_harmony(self):
        verdict, predicted = _verify("kylä", "noun", "kylässä", _features("inessive", "singular"))
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "kylässä")

    def test_paivah_partitive_front_harmony(self):
        verdict, predicted = _verify("päivä", "noun", "päivää", _features("partitive", "singular"))
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "päivää")

    def test_poika_ambiguous_single_k_returns_uncertain(self):
        # "poika" -> "pojan" is the classic irregular k -> j case the engine
        # deliberately refuses to predict. The user's well-known forms must
        # not be flagged MISMATCH.
        verdict, predicted = _verify(
            "poika",
            "noun",
            "pojan",
            _features("genitive", "singular"),
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)
        self.assertIsNone(predicted)

    def test_extended_case_variants_tolerate_ambiguous_gradation(self):
        # A source-class override can make the primary prediction deterministic
        # even when the fallback variant generator sees a lexical single-k
        # gradation. That secondary check must not leak an exception.
        verdict, predicted = _verify(
            "katu",
            "noun",
            "katun",
            _features("abessive", "plural", source_class="no gradation"),
        )
        self.assertEqual(verdict, Verdict.MISMATCH)
        self.assertEqual(predicted, "katuitta")

    def test_nainen_paradigm(self):
        for case, surface in {
            "nominative": "nainen",
            "genitive": "naisen",
            "partitive": "naista",
            "illative": "naiseen",
        }.items():
            verdict, predicted = _verify("nainen", "noun", surface, _features(case, "singular"))
            self.assertEqual(
                verdict,
                Verdict.VERIFIED,
                msg=f"nainen {case}={surface} -> {predicted}",
            )

    def test_vieras_paradigm(self):
        cases = {
            "nominative": "vieras",
            "genitive": "vieraan",
            "partitive": "vierasta",
            "illative": "vieraaseen",
        }
        for case, surface in cases.items():
            verdict, predicted = _verify(
                "vieras", "adjective", surface, _features(case, "singular")
            )
            self.assertEqual(
                verdict, Verdict.VERIFIED, msg=f"vieras {case}={surface} -> {predicted}"
            )

    def test_perhe_e_stem(self):
        cases = {
            "genitive": "perheen",
            "partitive": "perhettä",
            "inessive": "perheessä",
            "illative": "perheeseen",
        }
        for case, surface in cases.items():
            verdict, predicted = _verify(
                "perhe", "noun", surface, _features(case, "singular")
            )
            self.assertEqual(
                verdict, Verdict.VERIFIED, msg=f"perhe {case}={surface} -> {predicted}"
            )

    def test_vastaus_us_stem(self):
        cases = {
            "genitive": "vastauksen",
            "partitive": "vastausta",
            "illative": "vastaukseen",
        }
        for case, surface in cases.items():
            verdict, predicted = _verify(
                "vastaus", "noun", surface, _features(case, "singular")
            )
            self.assertEqual(
                verdict, Verdict.VERIFIED, msg=f"vastaus {case}={surface} -> {predicted}"
            )

    def test_kalleus_style_us_stem_accepts_de_stem(self):
        cases = {
            "genitive": "rakkauden",
            "partitive": "rakkautta",
            "illative": "rakkauteen",
        }
        for case, surface in cases.items():
            verdict, predicted = _verify(
                "rakkaus", "noun", surface, _features(case, "singular")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_couscous_uses_foreign_i_stem(self):
        cases = {
            ("nominative", "plural"): "couscousit",
            ("genitive", "singular"): "couscousin",
            ("partitive", "singular"): "couscousia",
            ("inessive", "singular"): "couscousissa",
            ("abessive", "plural"): "couscouseitta",
            ("instructive", "plural"): "couscousein",
        }
        for (case, number), surface in cases.items():
            verdict, predicted = _verify(
                "couscous", "noun", surface, _features(case, number)
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_couscous_exception_is_not_productive_for_vastaus(self):
        verdict, predicted = _verify(
            "vastaus", "noun", "vastausein", _features("instructive", "plural")
        )
        self.assertEqual(verdict, Verdict.MISMATCH)
        self.assertEqual(predicted, "vastauksin")

    def test_tuli_plural_genitive_variant_works_in_compounds(self):
        for lemma, surface in (
            ("tuli", "tulten"),
            ("aarnituli", "aarnitulten"),
        ):
            verdict, predicted = _verify(
                lemma, "noun", surface, _features("genitive", "plural")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_extended_nominal_case_inventory(self):
        cases = {
            ("accusative", "singular"): "talon",
            ("accusative", "plural"): "talot",
            ("abessive", "singular"): "talotta",
            ("abessive", "plural"): "taloitta",
            ("instructive", "plural"): "taloin",
            ("comitative", "plural"): "taloine",
        }
        for (case, number), surface in cases.items():
            verdict, predicted = _verify(
                "talo", "noun", surface, _features(case, number)
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

        for lemma, case, number, surface in (
            ("kala", "abessive", "plural", "kaloitta"),
            ("perhe", "abessive", "singular", "perheettä"),
            ("vastaus", "abessive", "singular", "vastauksetta"),
            ("paras", "instructive", "plural", "parhain"),
            ("aamuihminen", "abessive", "singular", "aamuihmisettä"),
            ("aamuihminen", "abessive", "plural", "aamuihmisittä"),
            ("aamukymmenen", "accusative", "singular", "aamukymmenen"),
            ("aamukymmenen", "abessive", "singular", "aamukymmenettä"),
            ("nalle", "abessive", "singular", "nalletta"),
            ("nalle", "instructive", "plural", "nallein"),
            ("hanke", "instructive", "plural", "hankkein"),
            ("rakkaus", "accusative", "singular", "rakkauden"),
            ("paras", "accusative", "singular", "parhaan"),
        ):
            verdict, predicted = _verify(
                lemma, "noun" if lemma != "paras" else "adjective", surface,
                _features(case, number),
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_i_stem_regular_and_plural_oblique_paradigm(self):
        cases = {
            ("genitive", "singular"): "ristin",
            ("partitive", "singular"): "ristiä",
            ("inessive", "singular"): "ristissä",
            ("illative", "singular"): "ristiin",
            ("nominative", "plural"): "ristit",
            ("genitive", "plural"): "ristien",
            ("partitive", "plural"): "ristejä",
            ("inessive", "plural"): "risteissä",
            ("illative", "plural"): "risteihin",
            ("instructive", "plural"): "ristein",
        }
        for (case, number), surface in cases.items():
            verdict, predicted = _verify(
                "risti", "noun", surface, _features(case, number)
            )
            self.assertEqual(
                verdict,
                Verdict.VERIFIED,
                msg=f"risti {case} {number}={surface} -> {predicted}",
            )

    def test_i_stem_common_irregular_variants(self):
        for lemma, case, number, surface in (
            ("kieli", "genitive", "singular", "kielen"),
            ("kieli", "partitive", "singular", "kieltä"),
            ("kieli", "nominative", "plural", "kielet"),
            ("kieli", "genitive", "plural", "kielten"),
            ("koti", "genitive", "singular", "kodin"),
            ("koti", "inessive", "singular", "kodissa"),
            ("koti", "nominative", "plural", "kodit"),
            ("koti", "inessive", "plural", "kodeissa"),
            ("uusi", "genitive", "singular", "uuden"),
            ("uusi", "partitive", "singular", "uutta"),
            ("uusi", "illative", "singular", "uuteen"),
            ("uusi", "essive", "singular", "uutena"),
            ("käsi", "genitive", "singular", "käden"),
            ("käsi", "partitive", "singular", "kättä"),
            ("käsi", "nominative", "plural", "kädet"),
        ):
            verdict, predicted = _verify(
                lemma, "noun", surface, _features(case, number)
            )
            self.assertEqual(
                verdict,
                Verdict.VERIFIED,
                msg=f"{lemma} {case} {number}={surface} -> {predicted}",
            )

    def test_i_stem_consonant_alternation_variants(self):
        for lemma, case, number, surface in (
            ("hanki", "genitive", "singular", "hangen"),
            ("hanki", "inessive", "singular", "hangessa"),
            ("kurki", "nominative", "plural", "kurjet"),
            ("korpi", "inessive", "singular", "korvessa"),
            ("kansi", "illative", "singular", "kanteen"),
            ("varsi", "partitive", "singular", "vartta"),
            ("laksi", "illative", "singular", "lahteen"),
            ("hirsi", "partitive", "singular", "hirttä"),
            ("veli", "inessive", "plural", "veljissä"),
            ("meri", "partitive", "singular", "merta"),
            ("lohi", "partitive", "singular", "lohta"),
            ("uni", "genitive", "plural", "unten"),
            ("sieni", "genitive", "plural", "sienten"),
            ("enempi", "partitive", "singular", "enempää"),
            ("enempi", "nominative", "plural", "enemmät"),
            ("kausi", "genitive", "singular", "kauden"),
            ("kausi", "partitive", "singular", "kautta"),
            ("kausi", "illative", "singular", "kauteen"),
            ("kausi", "essive", "singular", "kautena"),
            ("kausi", "nominative", "plural", "kaudet"),
        ):
            verdict, predicted = _verify(
                lemma,
                "adjective" if lemma == "enempi" else "noun",
                surface,
                _features(case, number),
            )
            self.assertEqual(
                verdict,
                Verdict.VERIFIED,
                msg=f"{lemma} {case} {number}={surface} -> {predicted}",
            )

    def test_long_vowel_i_stem_is_deferred(self):
        verdict, predicted = _verify(
            "saari", "noun", "saaren", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)
        self.assertIsNone(predicted)

    def test_os_stem_uses_okse(self):
        verdict, predicted = _verify(
            "kaaos", "noun", "kaaoksen", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "kaaoksen")

    def test_go_uses_rosé_loanword_variants(self):
        for case, surface in (("partitive", "gota"), ("illative", "gohon")):
            verdict, predicted = _verify(
                "go", "noun", surface, _features(case, "singular")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_hobby_uses_source_back_harmony_variants(self):
        cases = {
            ("partitive", "singular"): "hobbya",
            ("inessive", "singular"): "hobbyssa",
            ("elative", "singular"): "hobbysta",
            ("adessive", "singular"): "hobbylla",
            ("ablative", "singular"): "hobbylta",
            ("essive", "singular"): "hobbyna",
            ("abessive", "singular"): "hobbytta",
            ("abessive", "plural"): "hobbyitta",
        }
        for (case, number), surface in cases.items():
            verdict, predicted = _verify(
                "hobby", "noun", surface, _features(case, number)
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_source_no_gradation_class_overrides_productive_weak_grade(self):
        result = validate_form(
            lemma="tempo",
            part_of_speech="noun",
            surface_form="tempon",
            features={
                "case": "genitive",
                "number": "singular",
                "source_class": "no gradation",
            },
        )
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.predicted_surface, "tempon")

    def test_source_compound_template_keeps_component_inflection(self):
        result = validate_form(
            lemma="aavameri",
            part_of_speech="noun",
            surface_form="aavanmeren",
            features={
                "case": "genitive",
                "number": "singular",
                "source_class": "51/nuoripari",
            },
        )
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.rule, "nominal/i_stem/gen.sg/source-template")

    def test_source_loan_template_keeps_explicit_foreign_stem(self):
        result = validate_form(
            lemma="piaffe",
            part_of_speech="noun",
            surface_form="piaffin",
            features={
                "case": "genitive",
                "number": "singular",
                "source_class": "risti",
            },
        )
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.rule, "nominal/e_stem/gen.sg/source-template")

    def test_source_possessive_template_keeps_generated_case_form(self):
        result = validate_form(
            lemma="hänenlaisensa",
            part_of_speech="adjective",
            surface_form="hänenlaiseensa",
            features={
                "case": "illative",
                "number": "singular",
                "source_class": "no gradation | 38/nainen",
                "source_possessive": "3s",
            },
        )
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.predicted_surface, "hänenlaiseensa")

    def test_compact_source_classes_keep_explicit_special_stems(self):
        cases = (
            (
                "makuus",
                "makuukseen",
                "noun",
                _features(
                    "illative",
                    "singular",
                    source_class="no gradation | 39/vastaus",
                ),
            ),
            (
                "chenille",
                "chenillella",
                "noun",
                _features(
                    "adessive",
                    "singular",
                    source_class="no gradation | 8/nalle",
                ),
            ),
            (
                "hohkaa",
                "hohkaavat",
                "verb",
                {
                    "person": "3",
                    "number": "plural",
                    "mood": "indicative",
                    "tense": "present",
                    "source_class": "kaikaa",
                },
            ),
            (
                "jänismetsä",
                "jänismetsä",
                "noun",
                _features(
                    "accusative",
                    "singular",
                    source_class="10/koira",
                ),
            ),
            (
                "ulko",
                "ulko",
                "noun",
                _features(
                    "accusative",
                    "singular",
                    source_class="1*D/valo",
                ),
            ),
            (
                "mehi",
                "mehtä",
                "noun",
                _features(
                    "partitive",
                    "singular",
                    source_class="no gradation | 23/tiili",
                ),
            ),
        )
        for lemma, surface, pos, features in cases:
            result = validate_form(
                lemma=lemma,
                part_of_speech=pos,
                surface_form=surface,
                features=features,
            )
            self.assertEqual(result.verdict, Verdict.VERIFIED, msg=lemma)
            self.assertEqual(result.predicted_surface, surface)
            self.assertTrue(result.rule.endswith("/source-template"), msg=lemma)

    def test_source_alternate_infinitive_keeps_explicit_conjugation_cell(self):
        result = validate_form(
            lemma="bamlaa",
            part_of_speech="verb",
            surface_form="bamlaan",
            features={
                "person": "1",
                "number": "singular",
                "mood": "indicative",
                "tense": "present",
                "source_variant": "alternate-first-infinitive",
            },
        )
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.predicted_surface, "bamlaan")
        self.assertEqual(result.rule, "verb/type1/pres.1.sg/source-variant")

    def test_source_declared_defective_infinitive_is_not_a_rule_mismatch(self):
        result = validate_form(
            lemma="kutiaa",
            part_of_speech="verb",
            surface_form="kutista",
            features={
                "infinitive": "first",
                "source_variant": "defective-first-infinitive",
            },
        )
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.predicted_surface, "kutista")
        self.assertEqual(result.rule, "verb/infinitive/source-variant")

    def test_omorfi_keeps_explicit_loan_and_compound_variants(self):
        cases = (
            ("esperanto", "esperantoksi", "translative", "singular"),
            ("nahka", "nahkan", "genitive", "singular"),
            ("hobby", "hobbyt", "nominative", "plural"),
            ("kultainennoutaja", "kultaisetnoutajat", "nominative", "plural"),
            ("ylkä", "yljän", "genitive", "singular"),
        )
        for lemma, surface, case, number in cases:
            result = validate_form(
                lemma=lemma,
                part_of_speech="noun",
                surface_form=surface,
                features=_features(case, number),
                form_kind="omorfi",
            )
            self.assertEqual(result.verdict, Verdict.VERIFIED, msg=lemma)
            self.assertEqual(result.predicted_surface, surface)
            self.assertTrue(result.rule.endswith("/source-variant"), msg=lemma)

    def test_kaikki_keeps_irregular_pronoun_and_loan_variants(self):
        cases = (
            ("eri", "erikseen", "translative", "plural"),
            ("yatzy", "yatzeitta", "abessive", "plural"),
            ("striptease", "striptease", "accusative", "singular"),
        )
        for lemma, surface, case, number in cases:
            result = validate_form(
                lemma=lemma,
                part_of_speech="noun",
                surface_form=surface,
                features=_features(case, number),
                form_kind="kaikki",
            )
            self.assertEqual(result.verdict, Verdict.VERIFIED, msg=lemma)
            self.assertEqual(result.predicted_surface, surface)
            self.assertTrue(result.rule.endswith("/source-variant"), msg=lemma)

    def test_omorfi_accepts_s_transliterations_of_sh(self):
        for surface in ("sakin", "shakin"):
            result = validate_form(
                lemma="šakki",
                part_of_speech="noun",
                surface_form=surface,
                features=_features("genitive", "singular"),
                form_kind="omorfi",
            )
            self.assertEqual(result.verdict, Verdict.VERIFIED)
            self.assertEqual(result.predicted_surface, surface)
            self.assertEqual(result.rule, "nominal/i_stem/gen.sg/orthographic-variant")

    def test_kaikki_comitative_keeps_unlabelled_possessive_suffix(self):
        result = validate_form(
            lemma="vaa'ankieli",
            part_of_speech="noun",
            surface_form="vaa’ankielineen",
            features=_features(
                "comitative",
                "plural",
                source_class="no gradation | 26/pieni",
            ),
            form_kind="kaikki",
        )
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.predicted_surface, "vaa'ankielineen")


class LoanwordGradationTests(unittest.TestCase):
    def test_fobba_and_vedda_use_geminate_stop_gradation(self):
        for lemma, surface in (("fobba", "foban"), ("vedda", "vedan")):
            verdict, predicted = _verify(
                lemma, "noun", surface, _features("genitive", "singular")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_y_ending_loanwords_keep_back_harmony_source_variants(self):
        for lemma, surface, case in (
            ("body", "bodya", "partitive"),
            ("curry", "curryssa", "inessive"),
        ):
            verdict, predicted = _verify(
                lemma, "noun", surface, _features(case, "singular")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_neutral_nen_loanwords_keep_back_harmony_source_variants(self):
        verdict, predicted = _verify(
            "apokalyptinen",
            "adjective",
            "apokalyptisella",
            _features(
                "adessive",
                "singular",
                source_class="no gradation | 38/nainen",
            ),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "apokalyptisella")

    def test_name_is_not_forced_into_nominal_paradigm(self):
        verdict, predicted = _verify(
            "Mike", "name", "Miken", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)
        self.assertIsNone(predicted)

    def test_unknown_kotus_returns_uncertain(self):
        # 'maa' has a long vowel ending that the engine does not cover yet.
        verdict, predicted = _verify("maa", "noun", "maahan", _features("illative", "singular"))
        self.assertEqual(verdict, Verdict.UNCERTAIN)
        self.assertIsNone(predicted)

    def test_possessive_form_returns_uncertain(self):
        verdict, _ = _verify(
            "sisu",
            "noun",
            "sisuni",
            {"case": "Nom", "number": "Sing", "Person[psor]": "1", "Number[psor]": "Sing"},
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)

    def test_derived_forms_are_not_compared_with_the_source_lemma(self):
        result = validate_form(
            lemma="olla",
            part_of_speech="verb",
            surface_form="oleminen",
            features={"Case": "Nom", "Number": "Sing", "Derivation": "Minen"},
            form_kind="omorfi",
        )
        self.assertEqual(result.verdict, Verdict.UNCERTAIN)
        self.assertIsNone(result.predicted_surface)
        self.assertEqual(result.explanation, "derived form not modelled")

    def test_abbreviations_are_not_compared_with_full_words(self):
        result = validate_form(
            lemma="ry",
            part_of_speech="noun",
            surface_form="ryūtarō",
            features={"Case": "Nom", "Number": "Sing", "Abbr": "Yes"},
            form_kind="omorfi",
        )
        self.assertEqual(result.verdict, Verdict.UNCERTAIN)
        self.assertIsNone(result.predicted_surface)
        self.assertEqual(result.explanation, "abbreviations are not modelled")

    def test_lemma_form_without_case_is_verified(self):
        verdict, _ = _verify("sisu", "noun", "sisu", {})
        self.assertEqual(verdict, Verdict.VERIFIED)

    def test_lemma_form_mismatch_without_case_is_uncertain(self):
        # We do not know the case, so we cannot claim mismatch.
        verdict, _ = _verify("sisu", "noun", "sisua", {})
        self.assertEqual(verdict, Verdict.UNCERTAIN)

    def test_omorfi_inflected_only_lemma_is_not_reported_as_mismatch(self):
        result = validate_form(
            lemma="hyvättä",
            part_of_speech="adjective",
            surface_form="hyvättä",
            features=_features("abessive", "singular"),
            form_kind="omorfi",
        )
        self.assertEqual(result.verdict, Verdict.UNCERTAIN)
        self.assertIsNone(result.predicted_surface)
        self.assertIn("base lemma is unavailable", result.explanation)


class GradationPluralTests(unittest.TestCase):
    """Nominative-plural ``-t`` attaches to the weak-grade stem."""

    def test_ojikko_plural_grades_kk_to_k(self):
        verdict, predicted = _verify(
            "ojikko", "noun", "ojikot", _features("nominative", "plural")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "ojikot")

    def test_kauppa_plural_grades_pp_to_p(self):
        verdict, predicted = _verify(
            "kauppa", "noun", "kaupat", _features("nominative", "plural")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "kaupat")

    def test_miimikko_plural_grades_kk_to_k(self):
        verdict, predicted = _verify(
            "miimikko", "noun", "miimikot", _features("nominative", "plural")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "miimikot")

    def test_talot_plural_no_gradation(self):
        verdict, predicted = _verify(
            "talo", "noun", "talot", _features("nominative", "plural")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "talot")


class EStemStrongGradeTests(unittest.TestCase):
    """kotus 48 ``-e`` nouns restore the strong-grade ``-ee`` stem."""

    def test_kaide_genitive(self):
        verdict, predicted = _verify(
            "kaide", "noun", "kaiteen", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "kaiteen")

    def test_kaide_plural(self):
        verdict, predicted = _verify(
            "kaide", "noun", "kaiteet", _features("nominative", "plural")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "kaiteet")

    def test_kaavake_genitive_geminates_single_k(self):
        verdict, predicted = _verify(
            "kaavake", "noun", "kaavakkeen", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "kaavakkeen")

    def test_kaavake_plural(self):
        verdict, predicted = _verify(
            "kaavake", "noun", "kaavakkeet", _features("nominative", "plural")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "kaavakkeet")

    def test_tunne_genitive_nn_to_nt(self):
        verdict, predicted = _verify(
            "tunne", "noun", "tunteen", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "tunteen")

    def test_perhe_unchanged_consonant_cluster(self):
        verdict, predicted = _verify(
            "perhe", "noun", "perheen", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "perheen")

    def test_e_stem_doubled_stop_variant(self):
        for lemma, surface in (
            ("hanke", "hankkeen"),
            ("polte", "poltteen"),
            ("korte", "kortteen"),
        ):
            verdict, predicted = _verify(
                lemma, "noun", surface, _features("genitive", "singular")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_e_stem_doubled_stop_does_not_change_piste(self):
        verdict, predicted = _verify(
            "piste", "noun", "pisteen", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "pisteen")

    def test_e_stem_weak_grade_variant_uses_kaikki_source(self):
        for lemma, surface in (
            ("jeppe", "jepen"),
            ("ringette", "ringeten"),
            ("keikkunukke", "keikkunuken"),
        ):
            result = validate_form(
                lemma=lemma,
                part_of_speech="noun",
                surface_form=surface,
                features=_features("genitive", "singular"),
                form_kind="kaikki",
            )
            self.assertEqual(result.verdict, Verdict.VERIFIED)
            self.assertEqual(result.predicted_surface, surface)

        result = validate_form(
            lemma="jeppe",
            part_of_speech="noun",
            surface_form="jepen",
            features=_features("genitive", "singular"),
            form_kind="omorfi",
        )
        self.assertEqual(result.verdict, Verdict.MISMATCH)

    def test_typographic_apostrophe_is_orthographic_variant(self):
        verdict, predicted = _verify(
            "rei'ite", "noun", "rei’itteen", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "rei'itteen")

    def test_hame_template_stems(self):
        for lemma, surface in (
            ("tarve", "tarpeen"),
            ("pyyhe", "pyyhkeen"),
            ("vehje", "vehkeen"),
            ("toimenpide", "toimenpiteen"),
        ):
            verdict, predicted = _verify(
                lemma, "noun", surface, _features("genitive", "singular")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

        verdict, predicted = _verify(
            "aaltoliike",
            "noun",
            "aaltoliikkeessä",
            _features("inessive", "singular"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "aaltoliikkeessä")

        verdict, predicted = _verify(
            "ääriarvopiste",
            "noun",
            "ääriarvopisteessä",
            _features("inessive", "singular"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "ääriarvopisteessä")

    def test_nen_compound_harmony_and_kymmenen_stem(self):
        for lemma, surface, pos in (
            ("aamuihminen", "aamuihmisellä", "noun"),
            ("ranskankielinen", "ranskankieliseltä", "adjective"),
            # Use the nominal path here; numeral paradigms are intentionally
            # left uncertain by the public validator.
            ("aamukymmenen", "aamukymmenellä", "noun"),
        ):
            verdict, predicted = _verify(
                lemma,
                pos,
                surface,
                _features("adessive" if surface.endswith("llä") else "ablative", "singular"),
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_nalle_template_loan_stems(self):
        for lemma, surface in (
            ("steve", "steven"),
            ("college", "collegen"),
            ("house", "housen"),
            ("nalle", "nallen"),
            ("nukke", "nuken"),
        ):
            verdict, predicted = _verify(
                lemma, "noun", surface, _features("genitive", "singular")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_e_stem_loan_partitive_keeps_final_e(self):
        for lemma, surface in (
            ("akne", "aknea"),
            ("aborigine", "aboriginea"),
            ("aamukolme", "aamukolmea"),
        ):
            result = validate_form(
                lemma=lemma,
                part_of_speech="noun",
                surface_form=surface,
                features=_features("partitive", "singular"),
                form_kind="kaikki",
            )
            self.assertEqual(result.verdict, Verdict.VERIFIED)
            self.assertEqual(result.predicted_surface, surface)

    def test_nalle_loan_plural_abessive_variants(self):
        for lemma, surface in (
            ("pelle", "pelleittä"),
            ("nukke", "nukeitta"),
        ):
            result = validate_form(
                lemma=lemma,
                part_of_speech="noun",
                surface_form=surface,
                features=_features("abessive", "plural"),
                form_kind="kaikki",
            )
            self.assertEqual(result.verdict, Verdict.VERIFIED)
            self.assertEqual(result.predicted_surface, surface)

    def test_empire_uses_nalle_loan_template_in_omorfi(self):
        result = validate_form(
            lemma="empire",
            part_of_speech="noun",
            surface_form="empiren",
            features=_features("genitive", "singular"),
            form_kind="omorfi",
        )
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.predicted_surface, "empiren")

    def test_common_omorfi_e_loans_use_lemma_preserving_stems(self):
        for lemma, surface, case in (
            ("ale", "alen", "genitive"),
            ("anime", "animea", "partitive"),
            ("ope", "open", "genitive"),
        ):
            result = validate_form(
                lemma=lemma,
                part_of_speech="noun",
                surface_form=surface,
                features=_features(case, "singular"),
                form_kind="omorfi",
            )
            self.assertEqual(result.verdict, Verdict.VERIFIED, msg=lemma)
            self.assertEqual(result.predicted_surface, surface)

    def test_hame_hk_stem_is_limited_to_pyyhe_family(self):
        verdict, predicted = _verify(
            "adoptioperhe",
            "noun",
            "adoptioperheeltä",
            _features("ablative", "singular"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "adoptioperheeltä")

        verdict, predicted = _verify(
            "pyyhe",
            "noun",
            "pyyhkeeltä",
            _features("ablative", "singular"),
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "pyyhkeeltä")


class AsStemReverseGradationTests(unittest.TestCase):
    """``-as``/``-äs`` adjectives and nouns restore strong-grade clusters."""

    def test_kangas_genitive_ng_to_nk(self):
        verdict, predicted = _verify(
            "kangas", "noun", "kankaan", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "kankaan")

    def test_kangas_plural(self):
        verdict, predicted = _verify(
            "kangas", "noun", "kankaat", _features("nominative", "plural")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "kankaat")

    def test_lammas_genitive_mm_to_mp(self):
        verdict, predicted = _verify(
            "lammas", "noun", "lampaan", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "lampaan")

    def test_tehdas_genitive_hd_to_ht(self):
        verdict, predicted = _verify(
            "tehdas", "noun", "tehtaan", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "tehtaan")

    def test_porras_genitive_rr_to_rt(self):
        verdict, predicted = _verify(
            "porras", "noun", "portaan", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "portaan")

    def test_hidas_genitive_d_to_t(self):
        verdict, predicted = _verify(
            "hidas", "adjective", "hitaan", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "hitaan")

    def test_hurskas_genitive_stays_cluster(self):
        # ``hurskas`` has ``sk`` cluster; the ``k`` does not geminate.
        verdict, predicted = _verify(
            "hurskas", "adjective", "hurskaan", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "hurskaan")

    def test_kuningas_genitive(self):
        verdict, predicted = _verify(
            "kuningas", "noun", "kuninkaan", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "kuninkaan")

    def test_common_as_stem_variants(self):
        for lemma, surface in (
            ("paras", "parhaan"),
            ("varas", "varkaan"),
            ("kirkas", "kirkkaan"),
        ):
            verdict, predicted = _verify(
                lemma, "noun", surface, _features("genitive", "singular")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_liquid_labial_gradation(self):
        for lemma, surface in (("turpa", "turvan"), ("halpa", "halvan"), ("kylpy", "kylvyn")):
            verdict, predicted = _verify(
                lemma, "noun", surface, _features("genitive", "singular")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_as_aks_stem(self):
        for lemma, surface, case in (
            ("aidas", "aidaksen", "genitive"),
            ("lihas", "lihaksessa", "inessive"),
            ("teräs", "teräksellä", "adessive"),
        ):
            verdict, predicted = _verify(
                lemma, "noun", surface, _features(case, "singular")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_as_long_vowel_stem(self):
        for lemma, surface, case in (
            ("kunnas", "kunnaaksi", "translative"),
            ("kynnäs", "kynnääseen", "illative"),
        ):
            verdict, predicted = _verify(
                lemma, "noun", surface, _features(case, "singular")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_as_ordinal_stem(self):
        for lemma, surface, case in (
            ("kolmas", "kolmannen", "genitive"),
            ("kolmas", "kolmatta", "partitive"),
            ("neljäs", "neljänteen", "illative"),
        ):
            verdict, predicted = _verify(
                lemma, "adjective", surface, _features(case, "singular")
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_as_foreign_i_stem(self):
        verdict, predicted = _verify(
            "sassafras", "noun", "sassafrasiin", _features("illative", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "sassafrasiin")


class NumeralGuardTests(unittest.TestCase):
    """Ordinal numerals (``kolmas``, ``yhdeksäs``) are routed to UNCERTAIN."""

    def test_kolmas_ordinal_returns_uncertain(self):
        verdict, predicted = _verify(
            "kolmas", "num", "kolmannen", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)
        self.assertIsNone(predicted)

    def test_yhdeksas_ordinal_returns_uncertain(self):
        verdict, _ = _verify(
            "yhdeksäs", "num", "yhdeksännen", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)


class UusStemTests(unittest.TestCase):
    """kotus 40/41 ``-uus``/``-yys`` abstract nouns inflect with ``-Vude``."""

    def test_naisuus_genitive(self):
        verdict, predicted = _verify(
            "naisuus", "noun", "naisuuden", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "naisuuden")

    def test_ylevyys_genitive(self):
        verdict, predicted = _verify(
            "ylevyys", "noun", "ylevyyden", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "ylevyyden")

    def test_naisuus_partitive(self):
        verdict, predicted = _verify(
            "naisuus", "noun", "naisuutta", _features("partitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "naisuutta")

    def test_ylevyys_partitive(self):
        verdict, predicted = _verify(
            "ylevyys", "noun", "ylevyyttä", _features("partitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "ylevyyttä")

    def test_naisuus_illative(self):
        verdict, predicted = _verify(
            "naisuus", "noun", "naisuuteen", _features("illative", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "naisuuteen")

    def test_naisuus_essive_strong_grade(self):
        verdict, predicted = _verify(
            "naisuus", "noun", "naisuutena", _features("essive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "naisuutena")

    def test_naisuus_inessive(self):
        verdict, predicted = _verify(
            "naisuus", "noun", "naisuudessa", _features("inessive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "naisuudessa")

    def test_naisuus_plural(self):
        verdict, predicted = _verify(
            "naisuus", "noun", "naisuudet", _features("nominative", "plural")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "naisuudet")


class StopDeletionGradationTests(unittest.TestCase):
    """``lk``/``rk``/``hk`` weak grade deletes the stop entirely."""

    def test_jalka_genitive(self):
        verdict, predicted = _verify(
            "jalka", "noun", "jalan", _features("genitive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "jalan")

    def test_sarka_plural(self):
        verdict, predicted = _verify(
            "sarka", "noun", "sarat", _features("nominative", "plural")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "sarat")

    def test_nalka_inessive_with_front_harmony(self):
        verdict, predicted = _verify(
            "nälkä", "noun", "nälässä", _features("inessive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "nälässä")

    def test_kaikki_retains_hk_for_non_deleting_lemmas(self):
        for lemma, surface, case in (
            ("pihka", "pihkan", "genitive"),
            ("sähkö", "sähkössä", "inessive"),
            ("ruuhka", "ruuhkalla", "adessive"),
            ("tuhka", "tuhkan", "genitive"),
            ("antiikkinahka", "antiikkinahkan", "genitive"),
        ):
            result = validate_form(
                lemma=lemma,
                part_of_speech="noun",
                surface_form=surface,
                features=_features(case, "singular"),
                form_kind="kaikki",
            )
            self.assertEqual(result.verdict, Verdict.VERIFIED)

        result = validate_form(
            lemma="nahka",
            part_of_speech="noun",
            surface_form="nahkan",
            features=_features("genitive", "singular"),
            form_kind="kaikki",
        )
        self.assertEqual(result.verdict, Verdict.MISMATCH)


class EssiveStrongGradeTests(unittest.TestCase):
    """Essive ``-na``/``-nä`` keeps the strong-grade stem."""

    def test_tukka_essive_keeps_strong_grade(self):
        verdict, predicted = _verify(
            "tukka", "noun", "tukkana", _features("essive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "tukkana")

    def test_lukko_essive_keeps_strong_grade(self):
        verdict, predicted = _verify(
            "lukko", "noun", "lukkona", _features("essive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "lukkona")

    def test_talo_essive_unchanged(self):
        verdict, predicted = _verify(
            "talo", "noun", "talona", _features("essive", "singular")
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "talona")


class GuardClauseTests(unittest.TestCase):
    """Forms outside the engine's coverage stay UNCERTAIN, never MISMATCH."""

    def test_comparative_adjective_returns_uncertain(self):
        verdict, predicted = _verify(
            "kypsä",
            "adj",
            "kypsempi",
            {"Case": "Nom", "Number": "Sing", "Degree": "Cmp"},
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)
        self.assertIsNone(predicted)

    def test_superlative_adjective_returns_uncertain(self):
        verdict, _ = _verify(
            "kaunis",
            "adj",
            "kaunein",
            {"Case": "Nom", "Number": "Sing", "Degree": "Sup"},
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)

    def test_clitic_han_preserves_base_mismatch(self):
        verdict, predicted = _verify(
            "pohja",
            "noun",
            "pohjahan",
            {"Case": "Ill", "Number": "Sing", "Clitic": "Han"},
        )
        self.assertEqual(verdict, Verdict.MISMATCH)
        self.assertEqual(predicted, "pohjaanhan")

    def test_clitic_kin_reuses_base_paradigm(self):
        verdict, predicted = _verify(
            "sisu",
            "noun",
            "sisukin",
            {"Case": "Nom", "Number": "Sing", "Clitic": "Kin"},
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "sisukin")

    def test_unparseable_clitic_stays_uncertain(self):
        verdict, predicted = _verify(
            "sisu",
            "noun",
            "sisux",
            {"Case": "Nom", "Number": "Sing", "Clitic": "Kin"},
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)
        self.assertIsNone(predicted)

    def test_second_infinitive_returns_uncertain(self):
        verdict, _ = _verify(
            "täyttää",
            "verb",
            "täyttäen",
            {"VerbForm": "Inf", "InfForm": "2", "Case": "Ins", "Number": "Sing"},
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)

    def test_named_non_first_infinitive_returns_uncertain(self):
        verdict, predicted = _verify(
            "olla",
            "verb",
            "oleminen",
            {"infinitive": "fourth"},
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)
        self.assertIsNone(predicted)

    def test_third_infinitive_illative_returns_uncertain(self):
        verdict, _ = _verify(
            "puhua",
            "verb",
            "puhumaan",
            {"VerbForm": "Inf", "InfForm": "3", "Case": "Ill", "Number": "Sing"},
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)

    def test_passive_voice_returns_uncertain(self):
        verdict, _ = _verify(
            "puhua",
            "verb",
            "puhutaan",
            {"VerbForm": "Fin", "Mood": "Ind", "Tense": "Pres", "Voice": "Pass"},
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)

    def test_past_tense_returns_uncertain(self):
        verdict, _ = _verify(
            "puhua",
            "verb",
            "puhui",
            {"VerbForm": "Fin", "Mood": "Ind", "Tense": "Past", "Person": "3", "Number": "Sing"},
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)

    def test_conditional_mood_returns_uncertain(self):
        verdict, _ = _verify(
            "puhua",
            "verb",
            "puhuisin",
            {"VerbForm": "Fin", "Mood": "Cnd", "Tense": "Pres", "Person": "1", "Number": "Sing"},
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)

    def test_present_participle_returns_uncertain(self):
        verdict, _ = _verify(
            "puhua",
            "verb",
            "puhuva",
            {"VerbForm": "Part", "PartForm": "Pres"},
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)


class VerbTests(unittest.TestCase):
    def test_puhua_present(self):
        cases = {
            ("1", "Sing"): "puhun",
            ("2", "Sing"): "puhut",
            ("3", "Sing"): "puhuu",
            ("1", "Plur"): "puhumme",
            ("2", "Plur"): "puhutte",
            ("3", "Plur"): "puhuvat",
        }
        for (person, number), surface in cases.items():
            verdict, predicted = _verify(
                "puhua",
                "verb",
                surface,
                {
                    "Person": person,
                    "Number": number,
                    "Mood": "Ind",
                    "Tense": "Pres",
                },
            )
            self.assertEqual(
                verdict,
                Verdict.VERIFIED,
                msg=f"puhua {person}{number}={surface} -> {predicted}",
            )

    def test_sanoa_third_singular(self):
        verdict, predicted = _verify(
            "sanoa",
            "verb",
            "sanoo",
            {"Person": "3", "Number": "Sing", "Mood": "Ind", "Tense": "Pres"},
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "sanoo")

    def test_juoda_third_singular_is_bare_stem(self):
        # ``juoda -> juo`` (type 2): 3sg is the stem with no extra ``-e``.
        verdict, predicted = _verify(
            "juoda",
            "verb",
            "juo",
            {"Person": "3", "Number": "Sing", "Mood": "Ind", "Tense": "Pres"},
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "juo")

    def test_juoda_third_plural(self):
        verdict, predicted = _verify(
            "juoda",
            "verb",
            "juovat",
            {"Person": "3", "Number": "Plur", "Mood": "Ind", "Tense": "Pres"},
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "juovat")

    def test_syoda_third_singular_front_harmony(self):
        verdict, predicted = _verify(
            "syödä",
            "verb",
            "syö",
            {"Person": "3", "Number": "Sing", "Mood": "Ind", "Tense": "Pres"},
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "syö")

    def test_juosta_present_is_verified(self):
        verdict, predicted = _verify(
            "juosta",
            "verb",
            "juoksen",
            {"Person": "1", "Number": "Sing", "Mood": "Ind", "Tense": "Pres"},
        )
        self.assertEqual(verdict, Verdict.VERIFIED)
        self.assertEqual(predicted, "juoksen")

    def test_case_bearing_verb_form_is_uncertain(self):
        verdict, predicted = _verify(
            "olla",
            "verb",
            "ollessa",
            {"case": "inessive", "person": "2"},
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)
        self.assertIsNone(predicted)

    def test_nonstandard_and_typo_variants_are_uncertain(self):
        for features in (
            {"Style": "Arch", "VerbForm": "Fin", "Person": "2", "Number": "Sing"},
            {"Typo": "Yes", "VerbForm": "Inf", "InfForm": "1"},
        ):
            verdict, predicted = _verify("olla", "verb", "ollos", features)
            self.assertEqual(verdict, Verdict.UNCERTAIN)
            self.assertIsNone(predicted)

    def test_common_irregular_present_paradigms_are_verified(self):
        cases = {
            "olla": {"1": "olen", "2": "olet", "3": "on"},
            "tehdä": {"1": "teen", "2": "teet", "3": "tekee"},
            "nähdä": {"1": "näen", "2": "näet", "3": "näkee"},
            "tulla": {"1": "tulen", "2": "tulet", "3": "tulee"},
            "mennä": {"1": "menen", "2": "menet", "3": "menee"},
            "juosta": {"1": "juoksen", "2": "juokset", "3": "juoksee"},
        }
        for lemma, persons in cases.items():
            for person, surface in persons.items():
                verdict, predicted = _verify(
                    lemma,
                    "verb",
                    surface,
                    {"Mood": "Ind", "Tense": "Pres", "Person": person, "Number": "Sing"},
                )
                self.assertEqual(
                    verdict,
                    Verdict.VERIFIED,
                    msg=f"{lemma} pres {person}sg={surface} -> {predicted}",
                )

    def test_common_j_stem_present_paradigms_are_verified(self):
        cases = {
            "sulkea": {"1": "suljen", "2": "suljet", "3": "sulkee"},
            "kulkea": {"1": "kuljen", "2": "kuljet", "3": "kulkee"},
            "pyyhkiä": {"1": "pyyhin", "2": "pyyhit", "3": "pyyhkii"},
            "polkea": {"1": "poljen", "2": "poljet", "3": "polkee"},
            "särkeä": {"1": "särjen", "2": "särjet", "3": "särkee"},
            "nylkeä": {"1": "nyljen", "2": "nyljet", "3": "nylkee"},
            "hylkiä": {"1": "hyljin", "2": "hyljit", "3": "hylkii"},
            "sylkeä": {"1": "syljen", "2": "syljet", "3": "sylkee"},
        }
        for lemma, persons in cases.items():
            for person, surface in persons.items():
                verdict, predicted = _verify(
                    lemma,
                    "verb",
                    surface,
                    {"Mood": "Ind", "Tense": "Pres", "Person": person, "Number": "Sing"},
                )
                self.assertEqual(verdict, Verdict.VERIFIED)
                self.assertEqual(predicted, surface)

    def test_oitse_present_variants_are_verified_for_listed_verbs(self):
        cases = {
            ("ahkeroida", "1", "Sing"): "ahkeroitsen",
            ("aterioida", "2", "Sing"): "aterioitset",
            ("haravoida", "3", "Sing"): "haravoitsee",
            ("isännöidä", "3", "Plur"): "isännöitsevät",
            ("luennoida", "1", "Plur"): "luennoitsemme",
            ("mellakoida", "2", "Plur"): "mellakoitsette",
            ("ikävöidä", "1", "Sing"): "ikävöitsen",
            ("takavarikoida", "3", "Plur"): "takavarikoitsevat",
            ("tupakoida", "3", "Plur"): "tupakoitsevat",
            ("urakoida", "1", "Sing"): "urakoitsen",
            ("vartioida", "2", "Sing"): "vartioitset",
        }
        for (lemma, person, number), surface in cases.items():
            verdict, predicted = _verify(
                lemma,
                "verb",
                surface,
                {
                    "Person": person,
                    "Number": number,
                    "Mood": "Ind",
                    "Tense": "Pres",
                },
            )
            self.assertEqual(verdict, Verdict.VERIFIED)
            self.assertEqual(predicted, surface)

    def test_oitse_variant_is_not_productive_for_other_oida_verbs(self):
        verdict, predicted = _verify(
            "aprikoida",
            "verb",
            "aprikoitsee",
            {
                "Person": "3",
                "Number": "Sing",
                "Mood": "Ind",
                "Tense": "Pres",
            },
        )
        self.assertEqual(verdict, Verdict.MISMATCH)
        self.assertEqual(predicted, "aprikoi")

    def test_oitse_variant_uses_source_conjugation_class(self):
        result = validate_form(
            lemma="aprikoida",
            part_of_speech="verb",
            surface_form="aprikoitsee",
            features={
                "Person": "3",
                "Number": "Sing",
                "Mood": "Ind",
                "Tense": "Pres",
                "source_class": "no gradation | 68/tupakoida",
            },
        )
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.rule, "verb/type2/pres.3.sg/oitse-variant")

    def test_source_gradation_class_keeps_lexical_verb_stem(self):
        result = validate_form(
            lemma="pyhkiä",
            part_of_speech="verb",
            surface_form="pyhin",
            features={
                "Person": "1",
                "Number": "Sing",
                "Mood": "Ind",
                "Tense": "Pres",
                "source_class": "k–∅ gradation | 61*/sallia",
            },
        )
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.rule, "verb/type1/pres.1.sg/source-template")

    def test_hk_verbs_retain_the_cluster_in_the_weak_present_stem(self):
        cases = {
            "hehkua": {"1": "hehkun", "2": "hehkut", "3": "hehkuu"},
            "puhkoa": {"1": "puhkon", "2": "puhkot", "3": "puhkoo"},
        }
        for lemma, persons in cases.items():
            for person, surface in persons.items():
                verdict, predicted = _verify(
                    lemma,
                    "verb",
                    surface,
                    {"Person": person, "Number": "Sing", "Mood": "Ind", "Tense": "Pres"},
                )
                self.assertEqual(verdict, Verdict.VERIFIED)
                self.assertEqual(predicted, surface)


if __name__ == "__main__":
    unittest.main()
