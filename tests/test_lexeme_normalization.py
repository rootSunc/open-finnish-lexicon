import unittest
from uuid import uuid4
from unittest.mock import patch

import psycopg
from psycopg.types.json import Jsonb

from open_finnish_lexicon.cli import main
from open_finnish_lexicon.normalize.lexemes import align_surface_forms_to_sense_lexemes
from support import get_test_database_url


class LexemeNormalizationTests(unittest.TestCase):
    def test_normalize_lexemes_merges_part_of_speech_case_variants(self):
        token = f"zznorm-{uuid4().hex[:8]}"
        with psycopg.connect(get_test_database_url()) as conn:
            source_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "VERB"),
            ).fetchone()[0]
            target_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "verb"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (source_lexeme_id, f"{token}n", f"{token}n", "omorfi"),
            )
            conn.execute(
                """
                insert into lexicon.form_analysis (normalized_query, lexeme_id, analysis_rank, confidence, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (f"{token}n", source_lexeme_id, 1, 1.0),
            )
            source_sense_id = conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                returning id
                """,
                (source_lexeme_id, "sense-1", "to run", 1),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                """,
                (target_lexeme_id, "sense-2", "to flow", 2),
            )
            example_id = conn.execute(
                """
                insert into lexicon.example (text_fi, text_en, source_label, quality_score)
                values (%s, %s, %s, %s)
                returning id
                """,
                (f"{token} example.", f"{token} example.", "fixture", 1.0),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.sense_example (sense_id, example_id, is_core, sort_order)
                values (%s, %s, true, 1)
                """,
                (source_sense_id, example_id),
            )
            conn.execute(
                """
                insert into lexicon.frequency_signal (lexeme_id, source_name, raw_count, normalized_score)
                values (%s, %s, %s, %s)
                """,
                (source_lexeme_id, "frequency", 42, 0.5),
            )
            conn.commit()

        self.assertEqual(main(["normalize-lexemes"]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_rows = conn.execute(
                """
                select id, part_of_speech
                from lexicon.lexeme
                where lemma = %s
                order by id
                """,
                (token,),
            ).fetchall()
            form_count = conn.execute(
                "select count(*) from lexicon.form where lexeme_id = %s and normalized_form = %s",
                (target_lexeme_id, f"{token}n"),
            ).fetchone()[0]
            analysis_count = conn.execute(
                "select count(*) from lexicon.form_analysis where lexeme_id = %s and normalized_query = %s",
                (target_lexeme_id, f"{token}n"),
            ).fetchone()[0]
            sense_count = conn.execute(
                "select count(*) from lexicon.lexeme_sense where lexeme_id = %s",
                (target_lexeme_id,),
            ).fetchone()[0]
            example_count = conn.execute(
                """
                select count(*)
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                where ls.lexeme_id = %s
                """,
                (target_lexeme_id,),
            ).fetchone()[0]
            frequency_count = conn.execute(
                "select count(*) from lexicon.frequency_signal where lexeme_id = %s",
                (target_lexeme_id,),
            ).fetchone()[0]

        self.assertEqual(lexeme_rows, [(target_lexeme_id, "verb")])
        self.assertEqual(form_count, 1)
        self.assertEqual(analysis_count, 1)
        self.assertEqual(sense_count, 2)
        self.assertEqual(example_count, 1)
        self.assertEqual(frequency_count, 1)

    def test_normalize_lexemes_moves_semantic_rows_when_duplicate_senses_collapse(self):
        token = f"zzsemantic-{uuid4().hex[:8]}"
        with psycopg.connect(get_test_database_url()) as conn:
            conn.execute(
                """
                truncate semantic.zh_gloss_selection,
                         semantic.zh_gloss_candidate,
                         semantic.sense_alignment,
                         semantic.sense_alignment_candidate,
                         warehouse.source_claim,
                         warehouse.source_document,
                         warehouse.source_file,
                         warehouse.source_registry
                restart identity cascade
                """
            )
            source_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "VERB"),
            ).fetchone()[0]
            target_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "verb"),
            ).fetchone()[0]
            source_sense_id = conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                returning id
                """,
                (source_lexeme_id, "sense-1", "to run", 1),
            ).fetchone()[0]
            target_sense_id = conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                returning id
                """,
                (target_lexeme_id, "sense-1", "to run", 1),
            ).fetchone()[0]
            source_registry_id = conn.execute(
                """
                insert into warehouse.source_registry (name, source_kind, version, source_url)
                values (%s, %s, %s, %s)
                returning id
                """,
                (f"{token}-registry", "fixture", "test", "fixture://semantic-merge"),
            ).fetchone()[0]
            source_file_id = conn.execute(
                """
                insert into warehouse.source_file (source_registry_id, local_path, checksum_sha256)
                values (%s, %s, %s)
                returning id
                """,
                (source_registry_id, f"{token}.jsonl", ""),
            ).fetchone()[0]
            source_document_id = conn.execute(
                """
                insert into warehouse.source_document (source_file_id, external_id, payload)
                values (%s, %s, '{}'::jsonb)
                returning id
                """,
                (source_file_id, f"{token}-doc"),
            ).fetchone()[0]
            candidate_id = conn.execute(
                """
                insert into semantic.zh_gloss_candidate (
                    target_sense_id, source_name, source_document_id, gloss_zh, confidence_score, candidate_payload
                )
                values (%s, %s, %s, %s, %s, %s)
                returning id
                """,
                (
                    source_sense_id,
                    "example_zh",
                    source_document_id,
                    "跑；奔跑",
                    0.91,
                    Jsonb({"requires_llm_review": True}),
                ),
            ).fetchone()[0]
            conn.execute(
                """
                insert into semantic.sense_alignment_candidate (
                    source_name, source_document_id, target_sense_id, candidate_kind, confidence_score, match_payload
                )
                values (%s, %s, %s, %s, %s, '{}'::jsonb)
                """,
                ("example_zh", source_document_id, source_sense_id, "llm-generated", 0.91),
            )
            conn.execute(
                """
                insert into semantic.sense_alignment (
                    source_name, source_document_id, target_sense_id, status, confidence_score, selection_reason
                )
                values (%s, %s, %s, %s, %s, %s)
                """,
                ("example_zh", source_document_id, source_sense_id, "accepted", 0.91, "fixture"),
            )
            conn.execute(
                """
                insert into semantic.zh_gloss_selection (
                    target_sense_id, zh_gloss_candidate_id, gloss_zh, selected_by, confidence_score, selection_reason
                )
                values (%s, %s, %s, %s, %s, %s)
                """,
                (source_sense_id, candidate_id, "跑；奔跑", "llm", 0.91, "fixture"),
            )
            conn.commit()

        self.assertEqual(main(["normalize-lexemes"]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            candidate_rows = conn.execute(
                """
                select target_sense_id, count(*)
                from semantic.zh_gloss_candidate
                where source_name = 'example_zh'
                group by target_sense_id
                """
            ).fetchall()
            selection_row = conn.execute(
                """
                select target_sense_id
                from semantic.zh_gloss_selection
                """
            ).fetchone()
            source_sense_exists = conn.execute(
                "select count(*) from lexicon.lexeme_sense where id = %s",
                (source_sense_id,),
            ).fetchone()[0]

        self.assertEqual(source_sense_exists, 0)
        self.assertEqual(candidate_rows, [(target_sense_id, 1)])
        self.assertEqual(selection_row[0], target_sense_id)

    def test_reconcile_lexemes_merges_singleton_form_only_shell_into_unique_sense_target(self):
        token = f"zzalignsingle-{uuid4().hex[:8]}"
        with psycopg.connect(get_test_database_url()) as conn:
            conn.execute(
                """
                truncate semantic.zh_gloss_selection,
                         semantic.zh_gloss_candidate,
                         semantic.sense_alignment,
                         semantic.sense_alignment_candidate,
                         zh_layer.zh_warning,
                         zh_layer.zh_note,
                         zh_layer.zh_gloss,
                         lexicon.sense_example,
                         lexicon.example,
                         lexicon.collocation,
                         lexicon.lexical_relation,
                         lexicon.derivation_relation,
                         lexicon.pronunciation,
                         lexicon.grammar_note,
                         lexicon.usage_warning,
                         lexicon.frequency_signal,
                         lexicon.form_validation,
                         lexicon.form_analysis,
                         lexicon.form,
                         lexicon.lexeme_sense,
                         lexicon.lexeme
                restart identity cascade
                """
            )
            target_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech, frequency_rank)
                values (%s, %s, %s, %s)
                returning id
                """,
                (token, token, "verb", None),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                """,
                (target_lexeme_id, f"{token}-sense", "past tense form", 1),
            )
            source_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech, frequency_rank)
                values (%s, %s, %s, %s)
                returning id
                """,
                (f"{token}-base", f"{token}-base", "x", 77),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, %s)
                """,
                (source_lexeme_id, token, token, "omorfi", Jsonb({"case": "fixture"})),
            )
            conn.execute(
                """
                insert into lexicon.form_analysis (normalized_query, lexeme_id, analysis_rank, confidence, features)
                values (%s, %s, %s, %s, %s)
                """,
                (token, source_lexeme_id, 1, 0.91, Jsonb({"case": "fixture"})),
            )
            conn.execute(
                """
                insert into lexicon.frequency_signal (lexeme_id, source_name, raw_count, normalized_score)
                values (%s, %s, %s, %s)
                """,
                (source_lexeme_id, "frequency", 123, 0.88),
            )
            conn.commit()

        with patch.dict(
            "os.environ",
            {
                "OFL_DATABASE_URL": get_test_database_url(),
                "OFL_PROFILE": "real",
            },
            clear=False,
        ):
            self.assertGreaterEqual(align_surface_forms_to_sense_lexemes(), 1)

        with psycopg.connect(get_test_database_url()) as conn:
            source_exists = conn.execute(
                "select count(*) from lexicon.lexeme where id = %s",
                (source_lexeme_id,),
            ).fetchone()[0]
            merged_form_count = conn.execute(
                "select count(*) from lexicon.form where lexeme_id = %s and normalized_form = %s",
                (target_lexeme_id, token),
            ).fetchone()[0]
            merged_analysis_count = conn.execute(
                """
                select count(*)
                from lexicon.form_analysis
                where lexeme_id = %s and normalized_query = %s
                """,
                (target_lexeme_id, token),
            ).fetchone()[0]
            merged_frequency_count = conn.execute(
                """
                select count(*)
                from lexicon.frequency_signal
                where lexeme_id = %s and raw_count = 123
                """,
                (target_lexeme_id,),
            ).fetchone()[0]
            target_frequency_rank = conn.execute(
                "select frequency_rank from lexicon.lexeme where id = %s",
                (target_lexeme_id,),
            ).fetchone()[0]

        self.assertEqual(source_exists, 0)
        self.assertEqual(merged_form_count, 1)
        self.assertEqual(merged_analysis_count, 1)
        self.assertEqual(merged_frequency_count, 1)
        self.assertEqual(target_frequency_rank, 77)

    def test_reconcile_lexemes_moves_matching_form_rows_out_of_multi_form_source(self):
        token = f"zzalignmulti-{uuid4().hex[:8]}"
        moved_form = f"{token}-target"
        kept_form = f"{token}-keep"
        with psycopg.connect(get_test_database_url()) as conn:
            conn.execute(
                """
                truncate semantic.zh_gloss_selection,
                         semantic.zh_gloss_candidate,
                         semantic.sense_alignment,
                         semantic.sense_alignment_candidate,
                         zh_layer.zh_warning,
                         zh_layer.zh_note,
                         zh_layer.zh_gloss,
                         lexicon.sense_example,
                         lexicon.example,
                         lexicon.collocation,
                         lexicon.lexical_relation,
                         lexicon.derivation_relation,
                         lexicon.pronunciation,
                         lexicon.grammar_note,
                         lexicon.usage_warning,
                         lexicon.frequency_signal,
                         lexicon.form_validation,
                         lexicon.form_analysis,
                         lexicon.form,
                         lexicon.lexeme_sense,
                         lexicon.lexeme
                restart identity cascade
                """
            )
            target_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (moved_form, moved_form, "adj"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                """,
                (target_lexeme_id, f"{token}-sense", "fixture gloss", 1),
            )
            source_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (f"{token}-base", f"{token}-base", "noun"),
            ).fetchone()[0]
            for normalized_form in (moved_form, kept_form):
                conn.execute(
                    """
                    insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                    values (%s, %s, %s, %s, %s)
                    """,
                    (
                        source_lexeme_id,
                        normalized_form,
                        normalized_form,
                        "omorfi",
                        Jsonb({"normalized_form": normalized_form}),
                    ),
                )
                conn.execute(
                    """
                    insert into lexicon.form_analysis (normalized_query, lexeme_id, analysis_rank, confidence, features)
                    values (%s, %s, %s, %s, %s)
                    """,
                    (
                        normalized_form,
                        source_lexeme_id,
                        1,
                        0.95,
                        Jsonb({"normalized_form": normalized_form}),
                    ),
                )
            conn.commit()

        with patch.dict(
            "os.environ",
            {
                "OFL_DATABASE_URL": get_test_database_url(),
                "OFL_PROFILE": "real",
            },
            clear=False,
        ):
            self.assertGreaterEqual(align_surface_forms_to_sense_lexemes(), 1)

        with psycopg.connect(get_test_database_url()) as conn:
            moved_form_on_target = conn.execute(
                """
                select count(*)
                from lexicon.form
                where lexeme_id = %s and normalized_form = %s
                """,
                (target_lexeme_id, moved_form),
            ).fetchone()[0]
            moved_analysis_on_target = conn.execute(
                """
                select count(*)
                from lexicon.form_analysis
                where lexeme_id = %s and normalized_query = %s
                """,
                (target_lexeme_id, moved_form),
            ).fetchone()[0]
            kept_form_on_source = conn.execute(
                """
                select count(*)
                from lexicon.form
                where lexeme_id = %s and normalized_form = %s
                """,
                (source_lexeme_id, kept_form),
            ).fetchone()[0]
            moved_form_on_source = conn.execute(
                """
                select count(*)
                from lexicon.form
                where lexeme_id = %s and normalized_form = %s
                """,
                (source_lexeme_id, moved_form),
            ).fetchone()[0]

        self.assertEqual(moved_form_on_target, 1)
        self.assertEqual(moved_analysis_on_target, 1)
        self.assertEqual(kept_form_on_source, 1)
        self.assertEqual(moved_form_on_source, 0)

    def test_prune_empty_lexemes_removes_safe_shells_only(self):
        token = f"zzprune-{uuid4().hex[:8]}"
        keep_token = f"{token}-keep"
        with psycopg.connect(get_test_database_url()) as conn:
            doomed_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "verb"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (doomed_lexeme_id, token, token, "lemma"),
            )

            kept_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (keep_token, keep_token, "verb"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (kept_lexeme_id, keep_token, keep_token, "lemma"),
            )
            conn.execute(
                """
                insert into lexicon.form_analysis (normalized_query, lexeme_id, analysis_rank, confidence, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (keep_token, kept_lexeme_id, 1, 1.0),
            )
            conn.commit()

        self.assertEqual(main(["prune-empty-lexemes"]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            doomed_exists = conn.execute(
                "select count(*) from lexicon.lexeme where id = %s",
                (doomed_lexeme_id,),
            ).fetchone()[0]
            kept_exists = conn.execute(
                "select count(*) from lexicon.lexeme where id = %s",
                (kept_lexeme_id,),
            ).fetchone()[0]

        self.assertEqual(doomed_exists, 0)
        self.assertEqual(kept_exists, 1)

    def test_prune_empty_lexemes_merges_derivation_only_shell_into_richer_sibling(self):
        token = f"zzmerge-{uuid4().hex[:8]}"
        with psycopg.connect(get_test_database_url()) as conn:
            parent_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (f"{token}-parent", f"{token}-parent", "verb"),
            ).fetchone()[0]
            sibling_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "noun"),
            ).fetchone()[0]
            shell_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "verb"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (sibling_lexeme_id, token, token, "lemma"),
            )
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (shell_lexeme_id, token, token, "lemma"),
            )
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                """,
                (sibling_lexeme_id, f"{token}-sense", "runner", 1),
            )
            conn.execute(
                """
                insert into lexicon.derivation_relation (parent_lexeme_id, child_lexeme_id, relation_type, note)
                values (%s, %s, %s, %s)
                """,
                (parent_lexeme_id, shell_lexeme_id, "derived-term", "fixture"),
            )
            conn.commit()

        self.assertEqual(main(["prune-empty-lexemes"]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            shell_exists = conn.execute(
                "select count(*) from lexicon.lexeme where id = %s",
                (shell_lexeme_id,),
            ).fetchone()[0]
            derivation_target = conn.execute(
                """
                select child_lexeme_id
                from lexicon.derivation_relation
                where parent_lexeme_id = %s
                """,
                (parent_lexeme_id,),
            ).fetchone()[0]

        self.assertEqual(shell_exists, 0)
        self.assertEqual(derivation_target, sibling_lexeme_id)

    def test_prune_empty_lexemes_merges_analysis_bearing_shell_into_unique_richer_sibling(self):
        token = f"zzmergeanalysis-{uuid4().hex[:8]}"
        with psycopg.connect(get_test_database_url()) as conn:
            rich_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "verb"),
            ).fetchone()[0]
            shell_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "aux"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                """,
                (rich_lexeme_id, f"{token}-sense", "to exist", 1),
            )
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (shell_lexeme_id, token, token, "lemma"),
            )
            conn.execute(
                """
                insert into lexicon.form_analysis (normalized_query, lexeme_id, analysis_rank, confidence, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (token, shell_lexeme_id, 1, 1.0),
            )
            conn.commit()

        self.assertEqual(main(["prune-empty-lexemes"]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            shell_exists = conn.execute(
                "select count(*) from lexicon.lexeme where id = %s",
                (shell_lexeme_id,),
            ).fetchone()[0]
            merged_form_count = conn.execute(
                "select count(*) from lexicon.form where lexeme_id = %s and normalized_form = %s",
                (rich_lexeme_id, token),
            ).fetchone()[0]
            merged_analysis_count = conn.execute(
                "select count(*) from lexicon.form_analysis where lexeme_id = %s and normalized_query = %s",
                (rich_lexeme_id, token),
            ).fetchone()[0]

        self.assertEqual(shell_exists, 0)
        self.assertEqual(merged_form_count, 1)
        self.assertEqual(merged_analysis_count, 1)

    def test_prune_empty_lexemes_merges_multiple_shells_with_same_form_index(self):
        token = f"zzmergebatch-{uuid4().hex[:8]}"
        with psycopg.connect(get_test_database_url()) as conn:
            rich_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "verb"),
            ).fetchone()[0]
            first_shell_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "aux"),
            ).fetchone()[0]
            second_shell_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "particle"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                """,
                (rich_lexeme_id, f"{token}-sense", "to remain", 1),
            )
            for shell_id, score in ((first_shell_id, 0.4), (second_shell_id, 0.9)):
                conn.execute(
                    """
                    insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                    values (%s, %s, %s, %s, '{}'::jsonb)
                    """,
                    (shell_id, token, token, "lemma"),
                )
            conn.commit()

        self.assertEqual(main(["prune-empty-lexemes"]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            shell_count = conn.execute(
                "select count(*) from lexicon.lexeme where id in (%s, %s)",
                (first_shell_id, second_shell_id),
            ).fetchone()[0]

        self.assertEqual(shell_count, 0)

    def test_prune_empty_lexemes_merges_shell_frequency_and_notes_into_richer_sibling(self):
        token = f"zzmergeattrs-{uuid4().hex[:8]}"
        with psycopg.connect(get_test_database_url()) as conn:
            rich_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "verb"),
            ).fetchone()[0]
            shell_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (token, token, "aux"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                """,
                (rich_lexeme_id, f"{token}-sense", "to remain", 1),
            )
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (shell_lexeme_id, token, token, "lemma"),
            )
            conn.execute(
                """
                insert into lexicon.form_analysis (normalized_query, lexeme_id, analysis_rank, confidence, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (token, shell_lexeme_id, 1, 1.0),
            )
            conn.execute(
                """
                insert into lexicon.frequency_signal (lexeme_id, source_name, raw_count, normalized_score)
                values (%s, %s, %s, %s)
                """,
                (shell_lexeme_id, "frequency", 42, 0.42),
            )
            conn.execute(
                """
                insert into lexicon.grammar_note (lexeme_id, note_kind, note_en, note_fi)
                values (%s, %s, %s, %s)
                """,
                (shell_lexeme_id, "usage-note", "helper note", "apu huomio"),
            )
            conn.commit()

        self.assertEqual(main(["prune-empty-lexemes"]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            shell_exists = conn.execute(
                "select count(*) from lexicon.lexeme where id = %s",
                (shell_lexeme_id,),
            ).fetchone()[0]
            rich_frequency_count = conn.execute(
                "select count(*) from lexicon.frequency_signal where lexeme_id = %s and raw_count = 42",
                (rich_lexeme_id,),
            ).fetchone()[0]
            rich_note_count = conn.execute(
                "select count(*) from lexicon.grammar_note where lexeme_id = %s and note_en = %s",
                (rich_lexeme_id, "helper note"),
            ).fetchone()[0]

        self.assertEqual(shell_exists, 0)
        self.assertEqual(rich_frequency_count, 1)
        self.assertEqual(rich_note_count, 1)
