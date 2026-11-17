import unittest

from open_finnish_lexicon.morphology.sentence import (
    FinnishWordRecognizer,
    VERDICT_EMPTY,
    VERDICT_UNKNOWN_TOKENS,
    VERDICT_VALID,
    tokenize_finnish_sentence,
)


# Stands in for the Omorfi HFST model: the words it covers are the ones Omorfi
# actually analyses, and the ones it omits are the classes Omorfi is measurably
# missing (productive -minen nominals, compounds, proper nouns).
OMORFI_KNOWN = frozenset(
    {
        "Hän",
        "on",
        "ja",
        "kotona",
        "puu",
        "pöytä",
        "ulko",
        "varastossa",
        "äänne",
        "kirjaimen",
        "Helsingissä",
        "juoksentelisinkohan",
        "sujuminen",
        "lisättiin",
        "pääte",
        "persoonassa",
        "pop",
    }
)

PROJECT_FORMS = frozenset(
    {
        "puu",
        "pöytä",
        "puupöytä",
        "ulko",
        "varasto",
        "varastossa",
        "sujuminen",
        "kaatuminen",
        "kaatua",
        "museo",
        "virasto",
        "sana",
        "sanaan",
    }
)

PROJECT_LEMMAS = frozenset(
    {"puu", "pöytä", "ulko", "varasto", "museo", "virasto", "kaatua", "sana"}
)


def build_recognizer() -> FinnishWordRecognizer:
    return FinnishWordRecognizer(
        analyse=lambda token: token in OMORFI_KNOWN,
        forms=PROJECT_FORMS,
        lemmas=PROJECT_LEMMAS,
    )


class TokenizerTests(unittest.TestCase):
    def test_digit_bearing_tokens_are_skipped_whole(self):
        """``4H-kerholla`` must not leave a bare ``H-kerholla`` to be flagged."""

        self.assertEqual(tokenize_finnish_sentence("Se oli 4H-kerholla."), ["Se", "oli"])
        self.assertEqual(tokenize_finnish_sentence("Tapahtui 1990-luvulla."), ["Tapahtui"])

    def test_joined_word_parts_stay_in_one_token(self):
        self.assertEqual(tokenize_finnish_sentence("USA:ssa asuu"), ["USA:ssa", "asuu"])
        self.assertEqual(tokenize_finnish_sentence("p-äänne kuuluu"), ["p-äänne", "kuuluu"])

    def test_empty_input(self):
        self.assertEqual(tokenize_finnish_sentence(""), [])
        self.assertEqual(tokenize_finnish_sentence(None), [])


class RecognizerLayerTests(unittest.TestCase):
    def setUp(self):
        self.recognizer = build_recognizer()

    def test_analyser_covers_inflection_and_sentence_initial_capitals(self):
        self.assertTrue(self.recognizer.is_known("Hän"))
        self.assertTrue(self.recognizer.is_known("juoksentelisinkohan"))

    def test_project_lexicon_covers_what_omorfi_omits(self):
        """Omorfi 0.9.12 has no ``puupöytä``; our Kaikki-derived table does."""

        self.assertFalse("puupöytä" in OMORFI_KNOWN)
        self.assertTrue(self.recognizer.is_known("puupöytä"))

    def test_inflected_minen_nominals_resolve_to_their_nominative(self):
        for token in ("sujumisesta", "sujumisessa", "sujumista", "sujumiseksi"):
            with self.subTest(token=token):
                self.assertTrue(self.recognizer.is_known(token))

    def test_minen_restoration_still_needs_a_real_base(self):
        self.assertFalse(self.recognizer.is_known("qwertymisesta"))

    def test_compounds_split_into_known_parts(self):
        self.assertTrue(self.recognizer.is_known("ulkovarastossa"))
        self.assertTrue(self.recognizer.is_known("museovirasto"))

    def test_compound_split_rejects_an_unknown_part(self):
        self.assertFalse(self.recognizer.is_known("museokrunk"))

    def test_abbreviation_with_case_suffix(self):
        """Lowercase heads count too: ``kg`` and ``d`` are real abbreviations."""

        for token in ("USA:ssa", "USA:n", "kg:n", "d:llä", "pop-LP:tä"):
            with self.subTest(token=token):
                self.assertTrue(self.recognizer.is_known(token))

    def test_abbreviation_rule_needs_a_short_case_ending(self):
        self.assertFalse(self.recognizer.is_known("krunk:kruuutunen"))

    def test_hyphen_compound_with_a_single_letter_part(self):
        self.assertTrue(self.recognizer.is_known("p-äänne"))
        self.assertTrue(self.recognizer.is_known("L-kirjaimen"))

    def test_hyphen_compound_rejects_an_unknown_part(self):
        self.assertFalse(self.recognizer.is_known("p-krunk"))

    def test_real_typos_are_still_rejected(self):
        """These are actual rows from the table, and they are genuinely broken."""

        self.assertFalse(self.recognizer.is_known("persooonassa"))
        self.assertFalse(self.recognizer.is_known("voimisssa"))


class SentenceVerdictTests(unittest.TestCase):
    def setUp(self):
        self.recognizer = build_recognizer()

    def test_clean_sentence_is_valid(self):
        result = self.recognizer.validate_sentence("Hän on kotona.")
        self.assertEqual(result.verdict, VERDICT_VALID)
        self.assertEqual(result.token_count, 3)
        self.assertEqual(result.unknown_tokens, ())

    def test_sentence_with_a_broken_word_is_flagged(self):
        result = self.recognizer.validate_sentence("Hän on persooonassa.")
        self.assertEqual(result.verdict, VERDICT_UNKNOWN_TOKENS)
        self.assertEqual(result.unknown_tokens, ("persooonassa",))
        self.assertEqual(result.unknown_count, 1)

    def test_repeated_unknown_word_is_reported_once(self):
        result = self.recognizer.validate_sentence("krunk ja krunk.")
        self.assertEqual(result.unknown_count, 1)
        self.assertEqual(result.unknown_tokens, ("krunk",))

    def test_affix_stub_dressed_as_a_sentence_is_flagged(self):
        """A real generated row: an affix entry rendered as if it were a sentence."""

        result = self.recognizer.validate_sentence("Sanaan lisättiin pääte -eliäs.")
        self.assertEqual(result.verdict, VERDICT_UNKNOWN_TOKENS)
        self.assertIn("eliäs", result.unknown_tokens)

    def test_capitalized_unknowns_are_name_like_not_defects(self):
        """Omorfi's gazetteer is small; ``Manchesterista`` is not a broken word."""

        result = self.recognizer.validate_sentence("Hän on Manchesterista.")
        self.assertEqual(result.verdict, VERDICT_VALID)
        self.assertEqual(result.unknown_tokens, ())
        self.assertEqual(result.name_like_tokens, ("Manchesterista",))

    def test_sentence_initial_capitals_are_name_like_too(self):
        """Sampling found these to be names (``Brazzavillen``), not typos."""

        result = self.recognizer.validate_sentence("Brazzavillen Kongo on kotona.")
        self.assertEqual(result.verdict, VERDICT_VALID)
        self.assertEqual(result.name_like_tokens, ("Brazzavillen", "Kongo"))

    def test_single_letters_are_never_defects(self):
        result = self.recognizer.validate_sentence("Hän on č kotona.")
        self.assertEqual(result.verdict, VERDICT_VALID)

    def test_sentence_without_word_tokens_is_empty(self):
        result = self.recognizer.validate_sentence("1990 — 2020.")
        self.assertEqual(result.verdict, VERDICT_EMPTY)
        self.assertEqual(result.token_count, 0)


if __name__ == "__main__":
    unittest.main()
