import unittest

import psycopg

from support import get_test_database_url


class SchemaIndexTests(unittest.TestCase):
    def test_source_file_lifecycle_schema_exists(self):
        with psycopg.connect(get_test_database_url()) as conn:
            column = conn.execute(
                """
                select column_default
                from information_schema.columns
                where table_schema = 'warehouse'
                  and table_name = 'source_file'
                  and column_name = 'snapshot_state'
                """
            ).fetchone()
            metadata_columns = conn.execute(
                """
                select column_name
                from information_schema.columns
                where table_schema = 'warehouse'
                  and table_name = 'source_file'
                  and column_name in (
                      'retired_at', 'retire_reason', 'source_version', 'source_url'
                  )
                order by column_name
                """
            ).fetchall()
            indexes = conn.execute(
                """
                select indexname
                from pg_indexes
                where schemaname = 'warehouse'
                  and tablename = 'source_file'
                  and indexname in (
                      'idx_source_file_one_active_per_registry',
                      'idx_source_file_snapshot_state'
                  )
                order by indexname
                """
            ).fetchall()

        self.assertEqual(column[0], "'active'::text")
        self.assertEqual(
            [row[0] for row in metadata_columns],
            ["retire_reason", "retired_at", "source_url", "source_version"],
        )
        self.assertEqual(
            [row[0] for row in indexes],
            [
                "idx_source_file_one_active_per_registry",
                "idx_source_file_snapshot_state",
            ],
        )

    def test_source_claim_document_index_exists(self):
        with psycopg.connect(get_test_database_url()) as conn:
            row = conn.execute(
                """
                select indexname
                from pg_indexes
                where schemaname = 'warehouse'
                  and tablename = 'source_claim'
                  and indexname = 'idx_source_claim_document_id'
                """
            ).fetchone()

        self.assertEqual(row[0], "idx_source_claim_document_id")

    def test_source_document_projection_flag_exists(self):
        with psycopg.connect(get_test_database_url()) as conn:
            row = conn.execute(
                """
                select column_default
                from information_schema.columns
                where table_schema = 'warehouse'
                  and table_name = 'source_document'
                  and column_name = 'projection_eligible'
                """
            ).fetchone()

        self.assertEqual(row[0], "true")

    def test_example_source_label_indexes_exist(self):
        with psycopg.connect(get_test_database_url()) as conn:
            rows = conn.execute(
                """
                select indexname
                from pg_indexes
                where (
                    schemaname = 'lexicon'
                    and tablename = 'example'
                    and indexname in (
                        'idx_example_source_label',
                        'idx_example_source_label_text_fi_id'
                    )
                ) or (
                    schemaname = 'lexicon'
                    and tablename = 'sense_example'
                    and indexname = 'idx_sense_example_example_id'
                ) or (
                    schemaname = 'zh_layer'
                    and tablename = 'zh_example_translation'
                    and indexname = 'idx_zh_example_translation_example_id'
                  )
                order by indexname
                """
            ).fetchall()

        self.assertEqual(
            [row[0] for row in rows],
            [
                "idx_example_source_label",
                "idx_example_source_label_text_fi_id",
                "idx_sense_example_example_id",
                "idx_zh_example_translation_example_id",
            ],
        )

    def test_lexeme_lower_lemma_index_exists(self):
        with psycopg.connect(get_test_database_url()) as conn:
            row = conn.execute(
                """
                select indexname
                from pg_indexes
                where schemaname = 'lexicon'
                  and tablename = 'lexeme'
                  and indexname = 'idx_lexeme_lower_lemma'
                """
            ).fetchone()

        self.assertEqual(row[0], "idx_lexeme_lower_lemma")



    def test_kaikki_form_source_indexes_exist(self):
        with psycopg.connect(get_test_database_url()) as conn:
            rows = conn.execute(
                """
                select indexname
                from pg_indexes
                where schemaname = 'lexicon'
                  and tablename = 'form_source'
                  and indexname in (
                      'form_source_pkey',
                      'idx_form_source_source_file',
                      'idx_form_source_form'
                  )
                order by indexname
                """
            ).fetchall()

        # form_source_pkey covers (form_id, source_file_id), so a separate
        # single-column index on form_id would only repeat its prefix.
        self.assertEqual(
            [row[0] for row in rows],
            ["form_source_pkey", "idx_form_source_source_file"],
        )



    def test_kaikki_runtime_unique_indexes_exist(self):
        with psycopg.connect(get_test_database_url()) as conn:
            rows = conn.execute(
                """
                select indexname
                from pg_indexes
                where (
                    schemaname = 'lexicon'
                    and tablename = 'derivation_relation'
                    and indexname = 'idx_derivation_relation_unique'
                ) or (
                    schemaname = 'lexicon'
                    and tablename = 'grammar_note'
                    and indexname in ('idx_grammar_note_lexeme_unique', 'idx_grammar_note_sense_unique')
                ) or (
                    schemaname = 'lexicon'
                    and tablename = 'usage_warning'
                    and indexname = 'idx_usage_warning_sense_unique'
                )
                order by indexname
                """
            ).fetchall()

        self.assertEqual(
            [row[0] for row in rows],
            [
                "idx_derivation_relation_unique",
                "idx_grammar_note_lexeme_unique",
                "idx_grammar_note_sense_unique",
                "idx_usage_warning_sense_unique",
            ],
        )

    def test_lexeme_foreign_key_indexes_exist(self):
        with psycopg.connect(get_test_database_url()) as conn:
            rows = conn.execute(
                """
                select indexname
                from pg_indexes
                where (
                    schemaname = 'lexicon'
                    and tablename = 'collocation'
                    and indexname = 'idx_collocation_lexeme_id'
                ) or (
                    schemaname = 'lexicon'
                    and tablename = 'form_analysis'
                    and indexname = 'idx_form_analysis_lexeme_id'
                ) or (
                    schemaname = 'lexicon'
                    and tablename = 'grammar_note'
                    and indexname = 'idx_grammar_note_lexeme_id'
                ) or (
                    schemaname = 'lexicon'
                    and tablename = 'usage_warning'
                    and indexname = 'idx_usage_warning_lexeme_id'
                )
                order by indexname
                """
            ).fetchall()

        self.assertEqual(
            [row[0] for row in rows],
            [
                "idx_collocation_lexeme_id",
                "idx_form_analysis_lexeme_id",
                "idx_grammar_note_lexeme_id",
                "idx_usage_warning_lexeme_id",
            ],
        )
