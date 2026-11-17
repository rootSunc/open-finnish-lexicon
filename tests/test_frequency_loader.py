import tempfile
import unittest
from pathlib import Path

import psycopg

from open_finnish_lexicon.cli import main
from open_finnish_lexicon.sources.frequency_loader import _validate_frequency_replacement
from support import get_test_database_url


class FrequencyLoaderTests(unittest.TestCase):
    def test_frequency_loader_rejects_unmatched_input_without_removing_existing_signals(self):
        self.assertEqual(main(["ingest-omorfi", "--input", "tests/fixtures/omorfi.tsv"]), 0)
        self.assertEqual(main(["ingest-frequency", "--input", "tests/fixtures/frequency.csv"]), 0)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "unmatched.txt"
            input_path.write_text("not-a-finnish-lexeme 10\n")

            with self.assertRaisesRegex(ValueError, "matched no lexemes"):
                main(["ingest-frequency", "--input", str(input_path)])

        with psycopg.connect(get_test_database_url()) as conn:
            signal = conn.execute(
                """
                select fs.raw_count
                from lexicon.frequency_signal fs
                join lexicon.lexeme l on l.id = fs.lexeme_id
                where l.lemma = 'juosta' and fs.source_name = 'frequency'
                """
            ).fetchone()

        self.assertIsNotNone(signal)
        self.assertEqual(signal[0], 4_200)

    def test_frequency_loader_rejects_implausibly_sparse_large_replacement(self):
        class FakeConnection:
            def execute(self, _query, _params):
                class Result:
                    def fetchone(self):
                        return (10_000,)

                return Result()

        with self.assertRaisesRegex(ValueError, "likely source/schema mismatch"):
            _validate_frequency_replacement(
                FakeConnection(),
                input_row_count=50_000,
                resolved_rows=[(1, 100, 1.0)],
            )

        with self.assertRaisesRegex(ValueError, "shrink matched lexemes"):
            _validate_frequency_replacement(
                FakeConnection(),
                input_row_count=500,
                resolved_rows=[(1, 100, 1.0)] * 100,
            )
    def test_frequency_loader_prefers_canonical_analyzed_lemma_over_inflected_entry(self):
        self.assertEqual(main(["ingest-omorfi", "--input", "tests/fixtures/omorfi.tsv"]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            canonical_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                on conflict (lemma, part_of_speech) do update
                set display_lemma = excluded.display_lemma
                returning id
                """,
                ("juosta", "juosta", "verb"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                on conflict (lexeme_id, sense_key) do nothing
                """,
                (canonical_lexeme_id, "manual-canonical", "to run", 1),
            )
            inflected_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                on conflict (lemma, part_of_speech) do nothing
                returning id
                """,
                ("juoksen", "juoksen", "verb"),
            ).fetchone()[0]
            conn.commit()

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                input_path = Path(temp_dir) / "fi_50k.txt"
                input_path.write_text("juoksen 927\njuosta 73\n")

                exit_code = main(["ingest-frequency", "--input", str(input_path)])

            self.assertEqual(exit_code, 0)

            with psycopg.connect(get_test_database_url()) as conn:
                canonical_signal = conn.execute(
                    """
                    select fs.raw_count, fs.normalized_score
                    from lexicon.frequency_signal fs
                    join lexicon.lexeme l on l.id = fs.lexeme_id
                    where l.lemma = 'juosta' and l.part_of_speech = 'verb'
                    """
                ).fetchone()
                inflected_signal_count = conn.execute(
                    """
                    select count(*)
                    from lexicon.frequency_signal fs
                    join lexicon.lexeme l on l.id = fs.lexeme_id
                    where l.lemma = 'juoksen' and l.part_of_speech = 'verb'
                    """
                ).fetchone()[0]

            self.assertIsNotNone(canonical_signal)
            self.assertEqual(canonical_signal[0], 1_000)
            self.assertAlmostEqual(float(canonical_signal[1]), 1.0, places=5)
            self.assertEqual(inflected_signal_count, 0)
        finally:
            with psycopg.connect(get_test_database_url()) as conn:
                conn.execute(
                    """
                    delete from lexicon.lexeme_sense
                    where lexeme_id = %s and sense_key = %s
                    """,
                    (canonical_lexeme_id, "manual-canonical"),
                )
                conn.execute(
                    """
                    delete from lexicon.frequency_signal
                    where lexeme_id = %s and source_name = %s
                    """,
                    (inflected_lexeme_id, "frequency"),
                )
                conn.execute("delete from lexicon.form where lexeme_id = %s", (inflected_lexeme_id,))
                conn.execute("delete from lexicon.lexeme where id = %s", (inflected_lexeme_id,))
                conn.commit()

    def test_frequency_loader_supports_plaintext_frequency_words_and_form_fallback(self):
        self.assertEqual(main(["ingest-omorfi", "--input", "tests/fixtures/omorfi.tsv"]), 0)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "fi_50k.txt"
            input_path.write_text("juoksen 927\njuosta 73\nhups 4\n")
            input_path_str = str(input_path)

            exit_code = main(["ingest-frequency", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            frequency_rows = conn.execute(
                """
                select l.id, l.part_of_speech, l.frequency_rank, fs.source_name, fs.raw_count, fs.normalized_score
                from lexicon.frequency_signal fs
                join lexicon.lexeme l on l.id = fs.lexeme_id
                where l.lemma = 'juosta'
                """
            ).fetchall()
            document_count = conn.execute(
                """
                select count(*)
                from warehouse.source_document d
                join warehouse.source_file f on f.id = d.source_file_id
                where d.external_id like 'frequency:%%'
                  and f.local_path = %s
                """,
                (input_path_str,),
            ).fetchone()[0]

        self.assertEqual(len(frequency_rows), 1)
        _lexeme_id, _part_of_speech, frequency_rank, source_name, raw_count, normalized_score = frequency_rows[0]
        self.assertEqual(source_name, "frequency")
        self.assertEqual(raw_count, 1_000)
        self.assertAlmostEqual(float(normalized_score), 1.0, places=5)
        self.assertEqual(frequency_rank, 1)
        self.assertEqual(document_count, 3)

    def test_frequency_loader_keeps_csv_support(self):
        self.assertEqual(main(["ingest-omorfi", "--input", "tests/fixtures/omorfi.tsv"]), 0)

        exit_code = main(["ingest-frequency", "--input", "tests/fixtures/frequency.csv"])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            frequency_rank = conn.execute(
                """
                select frequency_rank
                from lexicon.lexeme
                where lemma = 'juosta' and part_of_speech = 'verb'
                """
            ).fetchone()[0]
            source_name, raw_count, normalized_score = conn.execute(
                """
                select source_name, raw_count, normalized_score
                from lexicon.frequency_signal fs
                join lexicon.lexeme l on l.id = fs.lexeme_id
                where l.lemma = 'juosta' and l.part_of_speech = 'verb'
                """
            ).fetchone()

        self.assertEqual(source_name, "frequency")
        self.assertEqual(raw_count, 4_200)
        self.assertAlmostEqual(float(normalized_score), 0.82, places=5)
        self.assertEqual(frequency_rank, 1)

    def test_frequency_loader_prefers_unique_sense_bearing_exact_lemma_match(self):
        token = "zzfreqlemma"
        with psycopg.connect(get_test_database_url()) as conn:
            shell_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "aux"),
            ).fetchone()[0]
            rich_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "verb"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                """,
                (rich_lexeme_id, "zzfreqlemma-sense", "to do something", 1),
            )
            conn.commit()

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                input_path = Path(temp_dir) / "fi_50k.txt"
                input_path.write_text(f"{token} 123\n")
                exit_code = main(["ingest-frequency", "--input", str(input_path)])

            self.assertEqual(exit_code, 0)

            with psycopg.connect(get_test_database_url()) as conn:
                shell_count = conn.execute(
                    """
                    select count(*)
                    from lexicon.frequency_signal
                    where lexeme_id = %s
                    """,
                    (shell_lexeme_id,),
                ).fetchone()[0]
                rich_row = conn.execute(
                    """
                    select raw_count
                    from lexicon.frequency_signal
                    where lexeme_id = %s
                    """,
                    (rich_lexeme_id,),
                ).fetchone()

            self.assertEqual(shell_count, 0)
            self.assertEqual(rich_row[0], 123)
        finally:
            with psycopg.connect(get_test_database_url()) as conn:
                conn.execute("delete from lexicon.frequency_signal where lexeme_id in (%s, %s)", (shell_lexeme_id, rich_lexeme_id))
                conn.execute("delete from lexicon.lexeme_sense where lexeme_id = %s and sense_key = %s", (rich_lexeme_id, "zzfreqlemma-sense"))
                conn.execute("delete from lexicon.lexeme where id in (%s, %s)", (shell_lexeme_id, rich_lexeme_id))
                conn.commit()
