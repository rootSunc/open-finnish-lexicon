import unittest
import gzip
import tempfile
from pathlib import Path

import psycopg

from open_finnish_lexicon.cli import main
from open_finnish_lexicon.normalize.senses import upsert_kaikki_entries
from open_finnish_lexicon.sources.kaikki_loader import compact_kaikki_entry, read_kaikki_entries
from open_finnish_lexicon.sources.kaikki_stage import stage_kaikki_entries
from support import get_test_database_url


class KaikkiLoaderTests(unittest.TestCase):
    def test_replace_snapshot_rejects_empty_input_before_database_access(self):
        with self.assertRaisesRegex(RuntimeError, "empty projected snapshot"):
            upsert_kaikki_entries([], source_file_id=999_999, replace_snapshot=True)

    @staticmethod
    def _delete_test_lexeme(conn, lexeme_id: int) -> None:
        """Remove a synthetic lexeme without relying on legacy FK cascades."""

        conn.execute(
            """
            delete from semantic.zh_gloss_selection
            where target_sense_id in (
                select id from lexicon.lexeme_sense where lexeme_id = %s
            )
            """,
            (lexeme_id,),
        )
        conn.execute(
            """
            delete from semantic.sense_alignment
            where target_sense_id in (
                select id from lexicon.lexeme_sense where lexeme_id = %s
            )
            """,
            (lexeme_id,),
        )
        conn.execute(
            """
            delete from semantic.sense_alignment_candidate
            where target_sense_id in (
                select id from lexicon.lexeme_sense where lexeme_id = %s
            )
            """,
            (lexeme_id,),
        )
        conn.execute(
            """
            delete from semantic.zh_gloss_candidate
            where target_sense_id in (
                select id from lexicon.lexeme_sense where lexeme_id = %s
            )
            """,
            (lexeme_id,),
        )
        for table in (
            "lexicon.sense_example",
            "lexicon.collocation",
            "lexicon.grammar_note",
            "lexicon.usage_warning",
            "zh_layer.zh_gloss",
            "zh_layer.zh_note",
            "zh_layer.zh_warning",
        ):
            conn.execute(
                f"delete from {table} where sense_id in "
                "(select id from lexicon.lexeme_sense where lexeme_id = %s)",
                (lexeme_id,),
            )
        conn.execute("delete from lexicon.lexeme_sense where lexeme_id = %s", (lexeme_id,))
        for table, column in (
            ("lexicon.collocation", "lexeme_id"),
            ("lexicon.derivation_relation", "parent_lexeme_id"),
            ("lexicon.derivation_relation", "child_lexeme_id"),
            ("lexicon.form", "lexeme_id"),
            ("lexicon.form_analysis", "lexeme_id"),
            ("lexicon.frequency_signal", "lexeme_id"),
            ("lexicon.grammar_note", "lexeme_id"),
            ("lexicon.lexical_relation", "source_lexeme_id"),
            ("lexicon.lexical_relation", "target_lexeme_id"),
            ("lexicon.pronunciation", "lexeme_id"),
            ("lexicon.usage_warning", "lexeme_id"),
            ("zh_layer.zh_note", "lexeme_id"),
            ("zh_layer.zh_warning", "lexeme_id"),
        ):
            conn.execute(f"delete from {table} where {column} = %s", (lexeme_id,))
        conn.execute("delete from lexicon.lexeme where id = %s", (lexeme_id,))

    def test_read_kaikki_entries_skips_malformed_rows_and_child_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-malformed.jsonl"
            input_path.write_text(
                "not-json\n"
                "[]\n"
                '{"word":"bad-senses","lang":"Finnish","pos":"noun","senses":"bad","derived":"bad"}\n'
                '{"word":"missing-id","lang":"Finnish","pos":"noun","senses":[{"glosses":["ignored"]}]}\n'
                '{"word":"good","lang":"Finnish","pos":"noun","sounds":"bad","derived":["bad",{"word":" johdannainen "}],"senses":[null,{"id":"sense-1","glosses":["good"]}]}\n',
                encoding="utf-8",
            )

            rows = list(read_kaikki_entries(input_path))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["word"], "good")
        self.assertEqual(
            rows[0]["senses"],
            [{"id": "sense-1", "glosses": ["good"], "tags": [], "raw_tags": [], "topics": []}],
        )
        self.assertEqual(rows[0]["derived"], [{"word": "johdannainen"}])
        self.assertEqual(rows[0]["sounds"], [])

    def test_personal_pronoun_table_does_not_cross_contaminate_lemmas(self):
        entry = {
            "word": "me",
            "lang": "Finnish",
            "pos": "pron",
            "forms": [
                {
                    "form": "minä",
                    "source": "inflection",
                    "tags": ["nominative", "singular"],
                },
                {
                    "form": "me",
                    "source": "inflection",
                    "tags": ["nominative", "plural"],
                },
                {
                    "form": "minun",
                    "source": "inflection",
                    "tags": ["genitive", "singular"],
                },
                {
                    "form": "meidän",
                    "source": "inflection",
                    "tags": ["genitive", "plural"],
                },
            ],
            "senses": [{"id": "sense-1", "glosses": ["we"]}],
        }

        compact = compact_kaikki_entry(entry)

        self.assertEqual(
            [(row["form"], row["features"]) for row in compact["forms"]],
            [
                ("me", {"case": "nominative", "number": "plural"}),
                ("meidän", {"case": "genitive", "number": "plural"}),
            ],
        )

    def test_compact_kaikki_entry_keeps_only_projection_fields(self):
        entry = {
            "word": "juosta",
            "lang": "Finnish",
            "pos": "VERB",
            "sounds": [{"ipa": "/ˈjuos.tɑ/"}, {"ipa": "/ignored/"}],
            "etymology_text": "Inherited from Proto-Finnic.",
            "forms": [
                {
                    "form": "juoksen",
                    "source": "conjugation",
                    "tags": ["first-person", "indicative", "present", "singular"],
                },
                {"form": "en juokse", "source": "conjugation", "tags": ["negative"]},
            ],
            "head_templates": [{"name": "head"}],
            "senses": [
                {
                    "id": "sense-1",
                    "glosses": ["to run"],
                    "tags": ["literal"],
                    "qualifier": "North Karelia",
                    "raw_tags": ["in loanwords"],
                    "topics": ["finance"],
                    "note": "Often used for physical running.",
                    "warning": "Watch literal usage.",
                    "examples": [{"text": "ignored"}],
                }
            ],
            "derived": [{"word": "juoksija", "extra": "ignored"}],
        }

        compact = compact_kaikki_entry(entry)

        self.assertEqual(compact["word"], "juosta")
        self.assertEqual(compact["pos"], "verb")
        self.assertEqual(compact["sounds"], [{"ipa": "/ˈjuos.tɑ/"}])
        self.assertEqual(compact["etymology_text"], "Inherited from Proto-Finnic.")
        self.assertEqual(compact["derived"], [{"word": "juoksija"}])
        self.assertEqual(
            compact["forms"],
            [
                {
                    "form": "juoksen",
                    "features": {
                        "mood": "indicative",
                        "number": "singular",
                        "person": "1",
                        "tense": "present",
                    },
                    "tags": ["first-person", "indicative", "present", "singular"],
                }
            ],
        )
        self.assertEqual(
            compact["senses"],
            [
                {
                    "id": "sense-1",
                    "glosses": ["to run"],
                    "tags": ["literal"],
                    "qualifier": "North Karelia",
                    "raw_tags": ["in loanwords"],
                    "topics": ["finance"],
                    "note": "Often used for physical running.",
                    "warning": "Watch literal usage.",
                    "examples": [{"text": "ignored"}],
                }
            ],
        )
        self.assertNotIn("head_templates", compact)

    def test_compact_kaikki_entry_keeps_usable_sense_examples(self):
        compact = compact_kaikki_entry(
            {
                "word": "juosta",
                "pos": "VERB",
                "senses": [
                    {
                        "id": "sense-1",
                        "glosses": ["to run"],
                        "examples": [
                            {"text": "  Hän juoksee nopeasti.  ", "english": "He runs quickly."},
                            {"text": "Hän juoksee nopeasti."},
                            {"english": "missing Finnish"},
                            "not-an-object",
                        ],
                    }
                ],
            }
        )

        self.assertEqual(
            compact["senses"][0]["examples"],
            [{"text": "Hän juoksee nopeasti.", "english": "He runs quickly."}],
        )

    def test_compact_kaikki_entry_skips_empty_sounds_until_it_finds_ipa(self):
        compact = compact_kaikki_entry(
            {
                "word": "ääni",
                "lang": "Finnish",
                "pos": "NOUN",
                "sounds": [{"ipa": ""}, {"audio": "later.ogg"}, {"ipa": " /ˈæːni/ "}],
                "senses": [{"id": "sense-1", "glosses": ["sound"]}],
            }
        )

        self.assertEqual(compact["sounds"], [{"ipa": "/ˈæːni/"}])

    def test_compact_kaikki_entry_skips_malformed_text_fields(self):
        compact = compact_kaikki_entry(
            {
                "word": "turvallinen",
                "pos": "adjective",
                "etymology_text": {"unexpected": "object"},
                "senses": [
                    {
                        "id": "sense-1",
                        "glosses": ["safe", 42, " safe "],
                        "tags": ["positive", None],
                        "qualifier": ["not text"],
                        "raw_tags": ["ordinary", 42],
                        "topics": ["everyday", None],
                        "note": {"unexpected": "object"},
                        "warning": " Use with care. ",
                    }
                ],
            }
        )

        self.assertNotIn("etymology_text", compact)
        self.assertEqual(
            compact["senses"],
            [
                {
                    "id": "sense-1",
                    "glosses": ["safe"],
                    "tags": ["positive"],
                    "raw_tags": ["ordinary"],
                    "topics": ["everyday"],
                    "warning": "Use with care.",
                }
            ],
        )

    def test_compact_kaikki_entry_keeps_degree_and_nonfinite_forms(self):
        compact = compact_kaikki_entry(
            {
                "word": "bonjaa",
                "lang": "Finnish",
                "pos": "verb",
                "forms": [
                    {"form": "bonjatessa", "source": "inflection", "tags": ["active", "inessive", "infinitive", "infinitive-ii"]},
                    {"form": "bonjaamassa", "source": "inflection", "tags": ["active", "inessive", "infinitive", "infinitive-iii"]},
                    {"form": "bonjaamatta", "source": "conjugation", "tags": ["abessive", "third-person"]},
                    {"form": "bonjaaminen", "source": "conjugation", "tags": ["fourth-person", "negative", "noun-from-verb"]},
                    {"form": "bonjaamaton", "source": "conjugation", "tags": ["inessive", "negative", "second-person"]},
                    {"form": "bonjaisi", "source": "conjugation", "tags": ["conditional", "present", "singular", "third-person"]},
                    {"form": "vapaampi", "tags": ["comparative"]},
                    {"form": "vapain", "tags": ["superlative"]},
                    {"form": "öbaut", "tags": ["alternative"]},
                ],
                "senses": [{"id": "sense-1", "glosses": ["to help"]}],
            }
        )

        self.assertEqual(
            compact["forms"],
            [
                {
                    "form": "bonjatessa",
                    "features": {"case": "inessive", "infinitive": "second", "voice": "active"},
                    "tags": ["active", "inessive", "infinitive", "infinitive-ii"],
                },
                {
                    "form": "bonjaamassa",
                    "features": {"case": "inessive", "infinitive": "third", "voice": "active"},
                    "tags": ["active", "inessive", "infinitive", "infinitive-iii"],
                },
                {
                    "form": "bonjaamatta",
                    "features": {"case": "abessive", "infinitive": "third"},
                    "tags": ["abessive", "third-person"],
                },
                {
                    "form": "bonjaaminen",
                    "features": {"infinitive": "fourth"},
                    "tags": ["fourth-person", "negative", "noun-from-verb"],
                },
                {
                    "form": "bonjaisi",
                    "features": {
                        "mood": "conditional",
                        "number": "singular",
                        "person": "3",
                        "tense": "present",
                    },
                    "tags": ["conditional", "present", "singular", "third-person"],
                },
                {
                    "form": "vapaampi",
                    "features": {"degree": "comparative"},
                    "tags": ["comparative"],
                },
                {
                    "form": "vapain",
                    "features": {"degree": "superlative"},
                    "tags": ["superlative"],
                },
            ],
        )

    def test_compact_kaikki_entry_drops_unlabelled_possessive_families(self):
        compact = compact_kaikki_entry(
            {
                "word": "herra",
                "pos": "noun",
                "forms": [
                    {"form": "herra", "source": "declension", "tags": ["nominative", "singular"]},
                    {"form": "herrani", "source": "declension", "tags": ["nominative", "singular"]},
                    {"form": "herrasi", "source": "declension", "tags": ["nominative", "singular"]},
                    {"form": "herramme", "source": "declension", "tags": ["nominative", "singular"]},
                    {"form": "herranne", "source": "declension", "tags": ["nominative", "singular"]},
                    {"form": "herransa", "source": "declension", "tags": ["nominative", "singular"]},
                    {"form": "herrassa", "source": "declension", "tags": ["inessive", "singular"]},
                    {"form": "herrassani", "source": "declension", "tags": ["inessive", "singular"]},
                    {"form": "herrassasi", "source": "declension", "tags": ["inessive", "singular"]},
                    {"form": "herrassaan", "source": "declension", "tags": ["inessive", "singular"]},
                    {"form": "herrassansa", "source": "declension", "tags": ["inessive", "singular"]},
                    {"form": "herraksi", "source": "declension", "tags": ["translative", "singular"]},
                    {"form": "herrakseni", "source": "declension", "tags": ["translative", "singular"]},
                    {"form": "herraksesi", "source": "declension", "tags": ["translative", "singular"]},
                    {"form": "herrakseen", "source": "declension", "tags": ["translative", "singular"]},
                    {"form": "jutun", "source": "declension", "tags": ["genitive", "singular"]},
                    {"form": "juttuni", "source": "declension", "tags": ["genitive", "singular"]},
                    {"form": "juttusi", "source": "declension", "tags": ["genitive", "singular"]},
                    {"form": "juttumme", "source": "declension", "tags": ["genitive", "singular"]},
                    {"form": "juttunne", "source": "declension", "tags": ["genitive", "singular"]},
                    {"form": "juttunsa", "source": "declension", "tags": ["genitive", "singular"]},
                    {"form": "juttua", "source": "declension", "tags": ["partitive", "singular"]},
                    {"form": "juttuaan", "source": "declension", "tags": ["partitive", "singular"]},
                ],
                "senses": [{"id": "sense-1", "glosses": ["lord"]}],
            }
        )

        self.assertEqual(
            compact["forms"],
            [
                {
                    "form": "herra",
                    "features": {"case": "nominative", "number": "singular"},
                    "tags": ["nominative", "singular"],
                },
                {
                    "form": "herrassa",
                    "features": {"case": "inessive", "number": "singular"},
                    "tags": ["inessive", "singular"],
                },
                {
                    "form": "herraksi",
                    "features": {"case": "translative", "number": "singular"},
                    "tags": ["singular", "translative"],
                },
                {
                    "form": "jutun",
                    "features": {"case": "genitive", "number": "singular"},
                    "tags": ["genitive", "singular"],
                },
                {
                    "form": "juttua",
                    "features": {"case": "partitive", "number": "singular"},
                    "tags": ["partitive", "singular"],
                },
            ],
        )

    def test_compact_kaikki_entry_preserves_source_class(self):
        compact = compact_kaikki_entry(
            {
                "word": "tempo",
                "pos": "noun",
                "forms": [
                    {"form": "no-table-tags", "source": "declension", "tags": ["table-tags"]},
                    {"form": "fi-decl-valo", "source": "declension", "tags": ["inflection-template"]},
                    {"form": "no gradation", "source": "declension", "tags": ["class"]},
                    {"form": "tempo", "source": "declension", "tags": ["nominative", "singular"]},
                    {"form": "tempon", "source": "declension", "tags": ["genitive", "singular"]},
                ],
                "senses": [{"id": "sense-1", "glosses": ["tempo"]}],
            }
        )

        self.assertEqual(
            compact["forms"][0]["features"]["source_class"], "no gradation"
        )

    def test_compact_kaikki_entry_preserves_template_possessive(self):
        compact = compact_kaikki_entry(
            {
                "word": "hänenlaisensa",
                "pos": "adj",
                "inflection_templates": [
                    {"name": "fi-decl-nainen", "args": {"poss": "3s"}}
                ],
                "forms": [
                    {"form": "no-table-tags", "source": "declension", "tags": ["table-tags"]},
                    {"form": "hänenlaisensa", "source": "declension", "tags": ["nominative", "singular"]},
                    {"form": "hänenlaiseensa", "source": "declension", "tags": ["illative", "singular"]},
                ],
                "senses": [{"id": "sense-1", "glosses": ["of his kind"]}],
            }
        )

        self.assertEqual(
            {form["features"]["source_possessive"] for form in compact["forms"]},
            {"3s"},
        )

    def test_compact_kaikki_entry_marks_alternate_first_infinitive(self):
        compact = compact_kaikki_entry(
            {
                "word": "bamlaa",
                "pos": "verb",
                "forms": [
                    {"form": "bamlaa", "source": "conjugation", "tags": ["infinitive", "infinitive-i"]},
                    {"form": "bamlata", "source": "conjugation", "tags": ["infinitive", "infinitive-i"]},
                    {"form": "bamlaan", "source": "conjugation", "tags": ["first-person", "indicative", "present", "singular"]},
                ],
                "senses": [{"id": "sense-1", "glosses": ["to speak"]}],
            }
        )

        self.assertEqual(
            {form["features"]["source_variant"] for form in compact["forms"]},
            {"alternate-first-infinitive"},
        )

    def test_compact_kaikki_entry_marks_source_declared_defective_infinitive(self):
        compact = compact_kaikki_entry(
            {
                "word": "kutiaa",
                "pos": "verb",
                "forms": [
                    {
                        "form": "kutista",
                        "source": "conjugation",
                        "tags": ["infinitive", "infinitive-i"],
                    },
                    {
                        "form": "kutiaa",
                        "source": "conjugation",
                        "tags": ["indicative", "present", "singular", "third-person"],
                    },
                ],
                "senses": [{"id": "sense-1", "glosses": ["to feel ticklish"]}],
                "inflection_templates": [
                    {"name": "fi-conj-manual", "args": {"type": "selvitä"}}
                ],
            }
        )

        self.assertEqual(
            {form["features"].get("source_variant") for form in compact["forms"]},
            {"defective-first-infinitive"},
        )

    def test_compact_kaikki_entry_does_not_mark_regular_first_infinitive(self):
        compact = compact_kaikki_entry(
            {
                "word": "juosta",
                "pos": "verb",
                "forms": [
                    {"form": "juosta", "source": "conjugation", "tags": ["infinitive", "infinitive-i"]},
                ],
                "senses": [{"id": "sense-1", "glosses": ["to run"]}],
            }
        )

        self.assertNotIn("source_variant", compact["forms"][0]["features"])

    def test_compact_kaikki_entry_prefers_first_repeated_declension_block(self):
        compact = compact_kaikki_entry(
            {
                "word": "zzblock",
                "pos": "noun",
                "forms": [
                    {"form": "no-table-tags", "tags": ["table-tags"], "source": "declension"},
                    {"form": "zzblock", "tags": ["nominative", "singular"], "source": "declension"},
                    {"form": "zzblocks", "tags": ["genitive", "singular"], "source": "declension"},
                    {"form": "no-table-tags", "tags": ["table-tags"], "source": "declension"},
                    {"form": "zzblock", "tags": ["nominative", "singular"], "source": "declension"},
                    {"form": "zzblock-alt", "tags": ["genitive", "singular"], "source": "declension"},
                ],
                "senses": [{"id": "sense-1", "glosses": ["block"]}],
            }
        )
        self.assertEqual(
            [form["form"] for form in compact["forms"]],
            ["zzblock", "zzblocks"],
        )

    def test_compact_kaikki_entry_prefers_first_repeated_conjugation_block(self):
        compact = compact_kaikki_entry(
            {
                "word": "zzconjugate",
                "pos": "verb",
                "forms": [
                    {"form": "no-table-tags", "tags": ["table-tags"], "source": "conjugation"},
                    {"form": "zzconjugate", "tags": ["infinitive", "infinitive-i"], "source": "conjugation"},
                    {"form": "zzconjugatesin", "tags": ["first-person", "indicative", "present", "singular"], "source": "conjugation"},
                    {"form": "no-table-tags", "tags": ["table-tags"], "source": "conjugation"},
                    {"form": "zzconjugate", "tags": ["infinitive", "infinitive-i"], "source": "conjugation"},
                    {"form": "zzconjugate-alt", "tags": ["first-person", "indicative", "present", "singular"], "source": "conjugation"},
                ],
                "senses": [{"id": "sense-1", "glosses": ["conjugate"]}],
            }
        )
        self.assertEqual(
            [form["form"] for form in compact["forms"]],
            ["zzconjugate", "zzconjugatesin"],
        )

    def test_compact_kaikki_entry_keeps_extended_case_forms_and_rejects_errors(self):
        compact = compact_kaikki_entry(
            {
                "word": "kotona",
                "lang": "Finnish",
                "pos": "adv",
                "forms": [
                    {"form": "kotoa", "source": "inflection", "tags": ["separative"]},
                    {"form": "kotona", "source": "inflection", "tags": ["locative"]},
                    {"form": "kotona", "source": "inflection", "tags": ["error-unrecognized-form"]},
                ],
                "senses": [{"id": "sense-1", "glosses": ["at home"]}],
            }
        )

        self.assertEqual(
            compact["forms"],
            [
                {
                    "form": "kotoa",
                    "features": {"case": "separative"},
                    "tags": ["separative"],
                },
                {
                    "form": "kotona",
                    "features": {"case": "locative"},
                    "tags": ["locative"],
                },
            ],
        )

    def test_compact_kaikki_entry_keeps_unicode_internal_joiners(self):
        compact = compact_kaikki_entry(
            {
                "word": "show",
                "lang": "Finnish",
                "pos": "noun",
                "forms": [
                    {"form": "show’t", "source": "declension", "tags": ["plural"]},
                    {
                        "form": "malli–näkymä–käsittelijässä",
                        "source": "declension",
                        "tags": ["inessive", "singular"],
                    },
                    {"form": "ala-", "source": "inflection", "tags": ["nominative"]},
                    {"form": "-y", "source": "declension", "tags": ["nominative"]},
                ],
                "senses": [{"id": "sense-1", "glosses": ["a show"]}],
            }
        )

        self.assertEqual(
            compact["forms"],
            [
                {
                    "form": "show’t",
                    "features": {"number": "plural"},
                    "tags": ["plural"],
                },
                {
                    "form": "malli–näkymä–käsittelijässä",
                    "features": {"case": "inessive", "number": "singular"},
                    "tags": ["inessive", "singular"],
                },
            ],
        )

    def test_kaikki_loader_persists_cleaned_paradigm_forms(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-forms-only.jsonl"
            input_path.write_text(
                '{"word":"zzkaikkiverb","lang":"Finnish","pos":"verb","forms":['
                '{"form":"zzkaikkiverbsin","source":"conjugation","tags":["first-person","indicative","past","singular"]},'
                '{"form":"zzkaikkiverbi","source":"conjugation","tags":["infinitive-i-long","past"]},'
                '{"form":"en zzkaikkiverb","source":"conjugation","tags":["negative"]},'
                '{"form":"zzkaikkiverbni","source":"conjugation","tags":["possessive","singular"]},'
                '{"form":"class","source":"conjugation","tags":["class"]}'
                '],"senses":[{"id":"sense-1","glosses":["to zzkaikkiverb"]}]}\n',
                encoding="utf-8",
            )

            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                "select id from lexicon.lexeme where lemma = 'zzkaikkiverb' and part_of_speech = 'verb'"
            ).fetchone()[0]
            form_rows = conn.execute(
                """
                select f.surface_form, f.features, fs.source_file_id
                from lexicon.form f
                left join lexicon.form_source fs on fs.form_id = f.id
                where f.lexeme_id = %s and f.form_kind = 'kaikki'
                order by surface_form
                """,
                (lexeme_id,),
            ).fetchall()
            self._delete_test_lexeme(conn, lexeme_id)

        self.assertEqual(
            [(surface, dict(features)) for surface, features, source_file_id in form_rows],
            [
                (
                    "zzkaikkiverbi",
                    {"participle": "past participle", "tense": "past"},
                ),
                (
                    "zzkaikkiverbsin",
                    {
                        "mood": "indicative",
                        "number": "singular",
                        "person": "1",
                        "tense": "past",
                    },
                ),
            ],
        )
        self.assertTrue(all(source_file_id is not None for _surface, _features, source_file_id in form_rows))

    def test_kaikki_loader_keeps_form_only_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-form-only-entry.jsonl"
            input_path.write_text(
                '{"word":"zzformonly","lang":"Finnish","pos":"verb","forms":['
                '{"form":"zzformonlyn","source":"conjugation","tags":["first-person","indicative","present","singular"]},'
                '{"form":"en zzformonly","source":"conjugation","tags":["negative"]}'
                ']}\n',
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                "select id from lexicon.lexeme where lemma = 'zzformonly' and part_of_speech = 'verb'"
            ).fetchone()[0]
            forms = conn.execute(
                """
                select surface_form, features
                from lexicon.form
                where lexeme_id = %s and form_kind = 'kaikki'
                """,
                (lexeme_id,),
            ).fetchall()
            sense_count = conn.execute(
                "select count(*) from lexicon.lexeme_sense where lexeme_id = %s",
                (lexeme_id,),
            ).fetchone()[0]
            self._delete_test_lexeme(conn, lexeme_id)

        self.assertEqual(
            [(surface, dict(features)) for surface, features in forms],
            [
                (
                    "zzformonlyn",
                    {
                        "mood": "indicative",
                        "number": "singular",
                        "person": "1",
                        "tense": "present",
                    },
                )
            ],
        )
        self.assertEqual(sense_count, 0)

    def test_kaikki_loader_creates_usage_notes_from_note_and_qualifier_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-notes.jsonl.gz"
            with gzip.open(input_path, "wt", encoding="utf-8") as handle:
                handle.write(
                    '{"word":"kapale","lang":"Finnish","pos":"noun","senses":[{"id":"sense-1","glosses":["piece of wood"],"tags":["dialectal"],"qualifier":"North Karelia","raw_tags":["in loanwords"],"topics":["finance"],"note":"Rare in standard Finnish."}]}\n'
                )

            exit_code = main(["ingest-kaikki", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                "select id from lexicon.lexeme where lemma = 'kapale' and part_of_speech = 'noun'"
            ).fetchone()[0]
            note_rows = conn.execute(
                """
                select note_en
                from lexicon.grammar_note
                where lexeme_id = %s or sense_id in (
                    select id from lexicon.lexeme_sense where lexeme_id = %s
                )
                order by note_en
                """,
                (lexeme_id, lexeme_id),
            ).fetchall()
            topic_rows = conn.execute(
                """
                select tt.id, tt.label_en, lt.confidence, lt.source
                from lexicon.lexeme_topic lt
                join lexicon.topic_taxonomy tt on tt.id = lt.topic_id
                where lt.lexeme_id = %s
                order by tt.id
                """,
                (lexeme_id,),
            ).fetchall()

        notes = [row[0] for row in note_rows]
        self.assertIn("North Karelia", notes)
        self.assertIn("Rare in standard Finnish.", notes)
        self.assertNotIn("in loanwords", notes)
        self.assertNotIn("finance", notes)
        self.assertEqual(
            [
                (topic_id, label_en, float(confidence), source)
                for topic_id, label_en, confidence, source in topic_rows
            ],
            [("finance", "Finance", 0.7, "kaikki-topic")],
        )

    def test_kaikki_loader_replaces_existing_stage_claims_for_same_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-replace.jsonl.gz"
            input_path_str = str(input_path)
            with gzip.open(input_path, "wt", encoding="utf-8") as handle:
                handle.write(
                    '{"word":"kapale","lang":"Finnish","pos":"noun","senses":[{"id":"sense-1","glosses":["piece of wood"]}]}\n'
                )
            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

            with gzip.open(input_path, "wt", encoding="utf-8") as handle:
                handle.write(
                    '{"word":"kapale","lang":"Finnish","pos":"noun","senses":[{"id":"sense-1","glosses":["piece of wood"]},{"id":"sense-2","glosses":["patch of field"]}]}\n'
                )
            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            claim_count = conn.execute(
                """
                select count(*)
                from warehouse.source_claim c
                join warehouse.source_document d on d.id = c.source_document_id
                join warehouse.source_file f on f.id = d.source_file_id
                where d.external_id = 'kaikki:kapale:noun'
                  and c.claim_type = 'sense'
                  and f.local_path = %s
                """,
                (input_path_str,),
            ).fetchone()[0]

        self.assertEqual(claim_count, 2)

    def test_kaikki_loader_removes_stale_owned_senses_but_keeps_unowned_senses(self):
        stale_sense_id = None
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-sense-replace.jsonl"
            input_path.write_text(
                '{"word":"zzsensereplace","lang":"Finnish","pos":"noun","senses":['
                '{"id":"sense-1","glosses":["first meaning"]},'
                '{"id":"sense-2","glosses":["second meaning"]}]}'
                "\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

            with psycopg.connect(get_test_database_url()) as conn:
                lexeme_id = conn.execute(
                    "select id from lexicon.lexeme where lemma = 'zzsensereplace' and part_of_speech = 'noun'"
                ).fetchone()[0]
                stale_sense_id = conn.execute(
                    """
                    select id
                    from lexicon.lexeme_sense
                    where lexeme_id = %s and sense_key = 'sense-1'
                    """,
                    (lexeme_id,),
                ).fetchone()[0]
                conn.execute(
                    """
                    insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en)
                    values (%s, 'manual-sense', 'editorial meaning')
                    """,
                    (lexeme_id,),
                )
                source_document_id = conn.execute(
                    """
                    select id
                    from warehouse.source_document
                    where external_id = 'kaikki:zzsensereplace:noun'
                    order by id desc
                    limit 1
                    """
                ).fetchone()[0]
                candidate_id = conn.execute(
                    """
                    insert into semantic.zh_gloss_candidate (
                        target_sense_id,
                        source_name,
                        source_document_id,
                        gloss_zh,
                        confidence_score
                    )
                    values (%s, 'test', %s, '第一个含义', 0.9)
                    returning id
                    """,
                    (stale_sense_id, source_document_id),
                ).fetchone()[0]
                conn.execute(
                    """
                    insert into semantic.zh_gloss_selection (
                        target_sense_id,
                        zh_gloss_candidate_id,
                        gloss_zh,
                        selected_by,
                        confidence_score,
                        selection_reason
                    )
                    values (%s, %s, '第一个含义', 'test', 0.9, 'cleanup test')
                    """,
                    (stale_sense_id, candidate_id),
                )
                conn.execute(
                    """
                    insert into semantic.sense_alignment_candidate (
                        source_name,
                        source_document_id,
                        target_sense_id,
                        candidate_kind,
                        confidence_score
                    )
                    values ('test', %s, %s, 'same-sense', 0.8)
                    """,
                    (source_document_id, stale_sense_id),
                )
                conn.execute(
                    """
                    insert into semantic.sense_alignment (
                        source_name,
                        source_document_id,
                        target_sense_id,
                        status,
                        confidence_score,
                        selection_reason
                    )
                    values ('test', %s, %s, 'selected', 0.8, 'cleanup test')
                    """,
                    (source_document_id, stale_sense_id),
                )
                conn.commit()

            input_path.write_text(
                '{"word":"zzsensereplace","lang":"Finnish","pos":"noun","senses":['
                '{"id":"sense-2","glosses":["updated second meaning"]}]}'
                "\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                "select id from lexicon.lexeme where lemma = 'zzsensereplace' and part_of_speech = 'noun'"
            ).fetchone()[0]
            senses = conn.execute(
                """
                select sense_key, gloss_en
                from lexicon.lexeme_sense
                where lexeme_id = %s
                order by sense_key
                """,
                (lexeme_id,),
            ).fetchall()
            ownership = conn.execute(
                """
                select ls.sense_key
                from lexicon.sense_source ss
                join lexicon.lexeme_sense ls on ls.id = ss.sense_id
                where ls.lexeme_id = %s
                order by ls.sense_key
                """,
                (lexeme_id,),
            ).fetchall()
            stale_selection_rows = conn.execute(
                """
                select count(*)
                from semantic.zh_gloss_selection
                where target_sense_id = %s
                """,
                (stale_sense_id,),
            ).fetchone()[0]
            stale_alignment_rows = conn.execute(
                """
                select count(*)
                from semantic.sense_alignment
                where target_sense_id = %s
                """,
                (stale_sense_id,),
            ).fetchone()[0]
            stale_alignment_candidate_rows = conn.execute(
                """
                select count(*)
                from semantic.sense_alignment_candidate
                where target_sense_id = %s
                """,
                (stale_sense_id,),
            ).fetchone()[0]
            self._delete_test_lexeme(conn, lexeme_id)

        self.assertEqual(
            senses,
            [("manual-sense", "editorial meaning"), ("sense-2", "updated second meaning")],
        )
        self.assertEqual(ownership, [("sense-2",)])
        self.assertEqual(stale_selection_rows, 0)
        self.assertEqual(stale_alignment_rows, 0)
        self.assertEqual(stale_alignment_candidate_rows, 0)

    def test_kaikki_loader_replaces_stale_source_forms_for_same_lexeme(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-form-replace.jsonl"
            input_path.write_text(
                '{"word":"zzformreplace","lang":"Finnish","pos":"verb","forms":['
                '{"form":"zzformreplace-old","source":"conjugation","tags":["first-person","indicative","present","singular"]}'
                '],"senses":[{"id":"sense-1","glosses":["to replace"]}]}\n',
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

            input_path.write_text(
                '{"word":"zzformreplace","lang":"Finnish","pos":"verb","forms":['
                '{"form":"zzformreplace-new","source":"conjugation","tags":["first-person","indicative","past","singular"]}'
                '],"senses":[{"id":"sense-1","glosses":["to replace"]}]}\n',
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                "select id from lexicon.lexeme where lemma = 'zzformreplace' and part_of_speech = 'verb'"
            ).fetchone()[0]
            forms = conn.execute(
                """
                select surface_form, features
                from lexicon.form
                where lexeme_id = %s and form_kind = 'kaikki'
                order by surface_form
                """,
                (lexeme_id,),
            ).fetchall()
            self._delete_test_lexeme(conn, lexeme_id)

        self.assertEqual(
            [(surface, dict(features)) for surface, features in forms],
            [("zzformreplace-new", {"mood": "indicative", "number": "singular", "person": "1", "tense": "past"})],
        )

    def test_kaikki_loader_keeps_forms_owned_by_another_source_file(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first_path = Path(first_dir) / "kaikki-first.jsonl"
            second_path = Path(second_dir) / "kaikki-second.jsonl"
            first_path.write_text(
                '{"word":"zzformmulti","lang":"Finnish","pos":"verb","forms":['
                '{"form":"zzformmulti-first","source":"conjugation","tags":["first-person","indicative","present","singular"]}'
                '],"senses":[{"id":"sense-1","glosses":["to keep the first"]}]}\n',
                encoding="utf-8",
            )
            second_path.write_text(
                '{"word":"zzformmulti","lang":"Finnish","pos":"verb","forms":['
                '{"form":"zzformmulti-second","source":"conjugation","tags":["first-person","indicative","past","singular"]}'
                '],"senses":[{"id":"sense-1","glosses":["to keep the second"]}]}\n',
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-kaikki", "--input", str(first_path)]), 0)
            self.assertEqual(main(["ingest-kaikki", "--input", str(second_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                "select id from lexicon.lexeme where lemma = 'zzformmulti' and part_of_speech = 'verb'"
            ).fetchone()[0]
            forms = conn.execute(
                """
                select surface_form, features
                from lexicon.form
                where lexeme_id = %s and form_kind = 'kaikki'
                order by surface_form
                """,
                (lexeme_id,),
            ).fetchall()
            self._delete_test_lexeme(conn, lexeme_id)

        self.assertEqual(
            [(surface, dict(features)) for surface, features in forms],
            [
                ("zzformmulti-first", {"mood": "indicative", "number": "singular", "person": "1", "tense": "present"}),
                ("zzformmulti-second", {"mood": "indicative", "number": "singular", "person": "1", "tense": "past"}),
            ],
        )

    def test_kaikki_loader_clears_forms_when_entry_loses_projection_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-form-clear.jsonl"
            input_path.write_text(
                '{"word":"zzformclear","lang":"Finnish","pos":"verb","forms":['
                '{"form":"zzformclear-old","source":"conjugation","tags":["first-person","indicative","present","singular"]}'
                '],"senses":[{"id":"sense-1","glosses":["to clear"]}]}\n',
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

            input_path.write_text(
                '{"word":"zzformclear","lang":"Finnish","pos":"verb","senses":[{"id":"sense-empty","tags":["no-gloss"]}]}\n',
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                "select id from lexicon.lexeme where lemma = 'zzformclear' and part_of_speech = 'verb'"
            ).fetchone()[0]
            form_count = conn.execute(
                "select count(*) from lexicon.form where lexeme_id = %s and form_kind = 'kaikki'",
                (lexeme_id,),
            ).fetchone()[0]
            sense_count = conn.execute(
                "select count(*) from lexicon.lexeme_sense where lexeme_id = %s",
                (lexeme_id,),
            ).fetchone()[0]
            self._delete_test_lexeme(conn, lexeme_id)

        self.assertEqual(form_count, 0)
        self.assertEqual(sense_count, 0)

    def test_kaikki_loader_removes_data_when_entry_disappears_from_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-entry-disappear.jsonl"
            input_path.write_text(
                '{"word":"zzentrydisappear","lang":"Finnish","pos":"noun","forms":['
                '{"form":"zzentrydisappearin","source":"declension","tags":["plural"]}'
                '],"senses":[{"id":"sense-1","glosses":["to disappear"]}]}\n',
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

            input_path.write_text("", encoding="utf-8")
            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                "select id from lexicon.lexeme where lemma = 'zzentrydisappear' and part_of_speech = 'noun'"
            ).fetchone()[0]
            form_count = conn.execute(
                "select count(*) from lexicon.form where lexeme_id = %s and form_kind = 'kaikki'",
                (lexeme_id,),
            ).fetchone()[0]
            sense_count = conn.execute(
                "select count(*) from lexicon.lexeme_sense where lexeme_id = %s",
                (lexeme_id,),
            ).fetchone()[0]
            ownership_count = conn.execute(
                """
                select count(*)
                from lexicon.sense_source ss
                join lexicon.lexeme_sense ls on ls.id = ss.sense_id
                where ls.lexeme_id = %s
                """,
                (lexeme_id,),
            ).fetchone()[0]
            self._delete_test_lexeme(conn, lexeme_id)

        self.assertEqual(form_count, 0)
        self.assertEqual(sense_count, 0)
        self.assertEqual(ownership_count, 0)

    def test_kaikki_stage_rejects_empty_snapshot_without_clearing_old_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-empty-replace.jsonl"
            input_path.write_text(
                '{"word":"zzemptyreplace","lang":"Finnish","pos":"noun","senses":['
                '{"id":"sense-1","glosses":["to remain"]}]}\n',
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

            input_path.write_text("not-json\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "empty projected snapshot"):
                stage_kaikki_entries(
                    input_path,
                    version="manual",
                    source_url=str(input_path.resolve()),
                    reject_empty_snapshot=True,
                )

            with psycopg.connect(get_test_database_url()) as conn:
                document_count = conn.execute(
                    """
                    select count(*)
                    from warehouse.source_document d
                    join warehouse.source_file f on f.id = d.source_file_id
                    where f.local_path = %s
                    """,
                    (str(input_path),),
                ).fetchone()[0]
                sense_count = conn.execute(
                    """
                    select count(*)
                    from lexicon.lexeme_sense ls
                    join lexicon.lexeme l on l.id = ls.lexeme_id
                    where l.lemma = 'zzemptyreplace'
                      and l.part_of_speech = 'noun'
                    """
                ).fetchone()[0]
                lexeme_id = conn.execute(
                    """
                    select id
                    from lexicon.lexeme
                    where lemma = 'zzemptyreplace' and part_of_speech = 'noun'
                    """
                ).fetchone()[0]
                self._delete_test_lexeme(conn, lexeme_id)

        self.assertEqual(document_count, 1)
        self.assertEqual(sense_count, 1)

    def test_kaikki_loader_creates_senses_pronunciation_and_derivations(self):
        exit_code = main(
            ["ingest-kaikki", "--input", "tests/fixtures/kaikki-juosta.jsonl"]
        )

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                "select id from lexicon.lexeme where lemma = 'juosta' and part_of_speech = 'verb'"
            ).fetchone()[0]

            sense_count = conn.execute(
                "select count(*) from lexicon.lexeme_sense where lexeme_id = %s",
                (lexeme_id,),
            ).fetchone()[0]
            ipa = conn.execute(
                "select ipa from lexicon.pronunciation where lexeme_id = %s",
                (lexeme_id,),
            ).fetchone()[0]
            derivation_count = conn.execute(
                "select count(*) from lexicon.derivation_relation where parent_lexeme_id = %s",
                (lexeme_id,),
            ).fetchone()[0]
            source_count = conn.execute(
                "select count(*) from warehouse.source_document where external_id = 'kaikki:juosta:verb'"
            ).fetchone()[0]
            examples = conn.execute(
                """
                select ls.sense_key, e.text_fi, e.source_label
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                join lexicon.example e on e.id = se.example_id
                where ls.lexeme_id = %s
                  and e.source_label = 'kaikki'
                order by ls.sense_key, e.text_fi
                """,
                (lexeme_id,),
            ).fetchall()
            child_part_of_speech = conn.execute(
                """
                select child.part_of_speech
                from lexicon.derivation_relation dr
                join lexicon.lexeme child on child.id = dr.child_lexeme_id
                where dr.parent_lexeme_id = %s
                  and child.lemma = 'juoksija'
                """,
                (lexeme_id,),
            ).fetchone()[0]
            empty_derived_shells = conn.execute(
                """
                select count(*)
                from lexicon.lexeme
                where lemma = 'juoksija' and part_of_speech = 'verb'
                """
            ).fetchone()[0]

        self.assertEqual(sense_count, 2)
        self.assertEqual(ipa, "/ˈjuos.tɑ/")
        self.assertGreaterEqual(derivation_count, 1)
        self.assertGreaterEqual(source_count, 1)
        self.assertEqual(child_part_of_speech, "noun")
        self.assertEqual(empty_derived_shells, 0)
        self.assertEqual(
            examples,
            [
                ("sense-1", "Hän juoksee nopeasti.", "kaikki"),
                ("sense-2", "Aika juoksee nopeasti.", "kaikki"),
            ],
        )

    def test_kaikki_loader_supports_real_gz_input_and_skips_empty_gloss_senses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-fi.jsonl.gz"
            with gzip.open(input_path, "wt", encoding="utf-8") as handle:
                handle.write(
                    '{"word":"juosta","lang":"Finnish","pos":"VERB","sounds":[{"ipa":"/ˈjuos.tɑ/"}],"senses":[{"id":"sense-1","glosses":["to run"],"tags":["literal"],"note":"Often used for physical running.","warning":"Do not confuse this literal motion sense with figurative time expressions."},{"id":"sense-empty","tags":["no-gloss"]}],"derived":[{"word":"juoksija"}]}\n'
                )
                handle.write(
                    '{"word":"correr","lang":"Spanish","pos":"VERB","senses":[{"id":"sense-x","glosses":["to run"]}]}\n'
                )

            exit_code = main(["ingest-kaikki", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                "select id from lexicon.lexeme where lemma = 'juosta' and part_of_speech = 'verb'"
            ).fetchone()[0]
            sense_rows = conn.execute(
                """
                select sense_key, gloss_en
                from lexicon.lexeme_sense
                where lexeme_id = %s
                order by sort_order
                """,
                (lexeme_id,),
            ).fetchall()
            empty_sense_count = conn.execute(
                """
                select count(*)
                from lexicon.lexeme_sense
                where lexeme_id = %s and sense_key = 'sense-empty'
                """,
                (lexeme_id,),
            ).fetchone()[0]
            spanish_count = conn.execute(
                "select count(*) from lexicon.lexeme where lemma = 'correr'"
            ).fetchone()[0]

        self.assertIn(("sense-1", "to run"), sense_rows)
        self.assertEqual(empty_sense_count, 0)
        self.assertEqual(spanish_count, 0)

    def test_kaikki_loader_preserves_all_distinct_glosses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-glosses.jsonl.gz"
            with gzip.open(input_path, "wt", encoding="utf-8") as handle:
                handle.write(
                    '{"word":"zzglosslist","lang":"Finnish","pos":"noun","senses":[{"id":"sense-1","glosses":["a small item","  ","A SMALL ITEM","a token"]}]}\n'
                )

            exit_code = main(["ingest-kaikki", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            gloss_en = conn.execute(
                """
                select ls.gloss_en
                from lexicon.lexeme lx
                join lexicon.lexeme_sense ls on ls.lexeme_id = lx.id
                where lx.lemma = 'zzglosslist' and lx.part_of_speech = 'noun'
                """
            ).fetchone()[0]

        self.assertEqual(gloss_en, "a small item; a token")

    def test_kaikki_loader_skips_entries_without_projection_data_but_keeps_raw_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-empty.jsonl.gz"
            with gzip.open(input_path, "wt", encoding="utf-8") as handle:
                handle.write(
                    '{"word":"zzskipkaikkientry","lang":"Finnish","pos":"noun","senses":[{"id":"sense-empty","tags":["no-gloss"]}]}\n'
                )
                handle.write(
                    '{"word":"zzblankkaikkigloss","lang":"Finnish","pos":"noun","senses":[{"id":"sense-blank","glosses":["", "  "]}]}\n'
                )
                handle.write(
                    '{"word":"zznoteonlykaikkientry","lang":"Finnish","pos":"noun","senses":[{"id":"sense-note-only","note":"Only a note, no dictionary gloss."}]}\n'
                )
                handle.write(
                    '{"word":"zzblankkaikkisound","lang":"Finnish","pos":"noun","sounds":[{"audio":"only.ogg"}]}\n'
                )
                handle.write(
                    '{"word":"zzblankkaikkiderived","lang":"Finnish","pos":"noun","derived":[{"word":""}]}\n'
                )

            exit_code = main(["ingest-kaikki", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_count = conn.execute(
                """
                select count(*)
                from lexicon.lexeme
                where lemma in (
                    'zzskipkaikkientry',
                    'zzblankkaikkigloss',
                    'zznoteonlykaikkientry',
                    'zzblankkaikkisound',
                    'zzblankkaikkiderived'
                ) and part_of_speech = 'noun'
                """
            ).fetchone()[0]
            source_count = conn.execute(
                """
                select count(*)
                from warehouse.source_document
                where external_id in (
                    'kaikki:zzskipkaikkientry:noun',
                    'kaikki:zzblankkaikkigloss:noun',
                    'kaikki:zznoteonlykaikkientry:noun',
                    'kaikki:zzblankkaikkisound:noun',
                    'kaikki:zzblankkaikkiderived:noun'
                )
                """
            ).fetchone()[0]

        self.assertEqual(lexeme_count, 0)
        # Raw source documents are retained so the staged snapshot remains
        # immutable and can clear stale normalized rows even if the local file
        # changes before projection. They must still not create learner-facing
        # lexeme rows.
        self.assertEqual(source_count, 5)

    def test_kaikki_stage_prefers_projectable_duplicate_document(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-duplicate.jsonl"
            input_path.write_text(
                '{"word":"zzduplicateprojection","lang":"Finnish","pos":"noun",'
                '"senses":[{"id":"sense-empty","tags":["no-gloss"]}]}\n'
                '{"word":"zzduplicateprojection","lang":"Finnish","pos":"noun",'
                '"senses":[{"id":"sense-usable","glosses":["a duplicate test entry"]}]}\n',
                encoding="utf-8",
            )

            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            documents = conn.execute(
                """
                select projection_eligible, payload->'senses'->0->>'id'
                from warehouse.source_document
                where external_id = 'kaikki:zzduplicateprojection:noun'
                   or external_id like 'kaikki:zzduplicateprojection:noun:entry-%'
                order by external_id
                """
            ).fetchall()
            lexeme_count = conn.execute(
                """
                select count(*)
                from lexicon.lexeme
                where lemma = 'zzduplicateprojection' and part_of_speech = 'noun'
                """
            ).fetchone()[0]

        self.assertEqual(
            documents,
            [(False, "sense-empty"), (True, "sense-usable")],
        )
        self.assertEqual(lexeme_count, 1)

    def test_kaikki_stage_preserves_all_projectable_duplicate_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-duplicate-projectable.jsonl"
            input_path.write_text(
                '{"word":"zzduplicatecomplete","lang":"Finnish","pos":"noun",'
                '"senses":[{"id":"sense-first","glosses":["first duplicate gloss"]}]}\n'
                '{"word":"zzduplicatecomplete","lang":"Finnish","pos":"noun",'
                '"senses":[{"id":"sense-second","glosses":["second duplicate gloss"]}]}\n',
                encoding="utf-8",
            )

            self.assertEqual(main(["ingest-kaikki", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            document_count = conn.execute(
                """
                select count(*)
                from warehouse.source_document
                where external_id = 'kaikki:zzduplicatecomplete:noun'
                   or external_id like 'kaikki:zzduplicatecomplete:noun:entry-%'
                """
            ).fetchone()[0]
            senses = conn.execute(
                """
                select ls.sense_key, ls.gloss_en
                from lexicon.lexeme l
                join lexicon.lexeme_sense ls on ls.lexeme_id = l.id
                where l.lemma = 'zzduplicatecomplete' and l.part_of_speech = 'noun'
                order by ls.sense_key
                """
            ).fetchall()
            sense_claims = conn.execute(
                """
                select sc.claim_type, sc.subject_key, sc.object_key
                from warehouse.source_claim sc
                join warehouse.source_document d on d.id = sc.source_document_id
                where d.external_id like 'kaikki:zzduplicatecomplete:noun:entry-%'
                  and sc.claim_type = 'sense'
                order by sc.object_key
                """
            ).fetchall()

        self.assertEqual(document_count, 2)
        self.assertEqual(
            senses,
            [
                ("sense-first", "first duplicate gloss"),
                ("sense-second", "second duplicate gloss"),
            ],
        )
        self.assertEqual(
            sense_claims,
            [
                ("sense", "kaikki:zzduplicatecomplete:noun:entry-1", "sense-first"),
                ("sense", "kaikki:zzduplicatecomplete:noun:entry-2", "sense-second"),
            ],
        )
