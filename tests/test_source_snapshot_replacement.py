import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import psycopg

from open_finnish_lexicon.cli import main
from open_finnish_lexicon.normalize.lexemes.merge import _merge_lexeme_into
from open_finnish_lexicon.sources.kaikki_project import project_kaikki_entries
from open_finnish_lexicon.sources.kaikki_stage import stage_kaikki_entries
from open_finnish_lexicon.sources.omorfi_loader import OmorfiRow
from open_finnish_lexicon.sources.omorfi_project import project_omorfi_rows
from open_finnish_lexicon.sources.omorfi_stage import stage_omorfi_rows
from open_finnish_lexicon.sources.registry import finalize_source_snapshot
from open_finnish_lexicon.sources.tatoeba_project import project_tatoeba_rows
from open_finnish_lexicon.sources.tatoeba_stage import stage_tatoeba_rows
from open_finnish_lexicon.sources.warehouse import (
    clear_retired_source_registry_documents,
    clear_retired_source_registry_documents_in_batches,
    retire_stale_pending_source_files,
    upsert_source_file,
    upsert_source_registry,
)
from support import get_test_database_url


class SourceSnapshotReplacementTests(unittest.TestCase):
    def _reset_runtime_tables(self) -> None:
        with psycopg.connect(get_test_database_url()) as conn:
            conn.execute(
                """
                truncate semantic.zh_gloss_selection,
                         semantic.zh_gloss_candidate,
                         semantic.sense_alignment,
                         semantic.sense_alignment_candidate,
                         zh_layer.zh_gloss,
                         zh_layer.zh_example_translation,
                         zh_layer.zh_note,
                         zh_layer.zh_warning,
                         lexicon.collocation,
                         lexicon.sense_example,
                         lexicon.example,
                         lexicon.lexical_relation_source,
                         lexicon.lexical_relation,
                         lexicon.frequency_signal,
                         lexicon.form_analysis,
                         lexicon.form,
                         lexicon.usage_warning,
                         lexicon.grammar_note,
                         lexicon.pronunciation,
                         lexicon.derivation_relation,
                         lexicon.lexeme_sense,
                         lexicon.lexeme,
                         warehouse.source_claim,
                         warehouse.source_document,
                         warehouse.source_file,
                         warehouse.source_registry,
                         warehouse.source_release
                restart identity cascade
                """
            )
            conn.commit()

    def setUp(self) -> None:
        self._reset_runtime_tables()

    def tearDown(self) -> None:
        self._reset_runtime_tables()

    def test_upsert_active_source_file_retires_a_previous_path(self) -> None:
        with psycopg.connect(get_test_database_url()) as conn:
            registry_id = upsert_source_registry(
                conn,
                name="manual-review-source",
                source_kind="manual-tsv",
                version="v1",
                source_url="test://manual-review-source",
            )
            first_id = upsert_source_file(
                conn,
                source_registry_id=registry_id,
                local_path=Path("/tmp/manual-review-first.tsv"),
            )
            second_id = upsert_source_file(
                conn,
                source_registry_id=registry_id,
                local_path=Path("/tmp/manual-review-second.tsv"),
            )
            states = dict(
                conn.execute(
                    "select id, snapshot_state from warehouse.source_file where source_registry_id = %s",
                    (registry_id,),
                ).fetchall()
            )
            retired_reason = conn.execute(
                "select retire_reason from warehouse.source_file where id = %s",
                (first_id,),
            ).fetchone()[0]
            conn.commit()

        self.assertEqual(states, {first_id: "retired", second_id: "active"})
        self.assertEqual(retired_reason, "superseded by newer active source file")

    def test_retired_source_cleanup_preserves_selected_gloss_provenance(self) -> None:
        with psycopg.connect(get_test_database_url()) as conn:
            registry_id = conn.execute(
                """
                insert into warehouse.source_registry (name, source_kind, version, source_url)
                values ('selected-gloss-retention', 'manual-tsv', 'v1', 'test://retention')
                returning id
                """
            ).fetchone()[0]
            source_file_id = conn.execute(
                """
                insert into warehouse.source_file (
                    source_registry_id, local_path, snapshot_state, checksum_sha256
                )
                values (%s, 'manual_fixed/zh_gloss_completed.tsv', 'retired', '')
                returning id
                """,
                (registry_id,),
            ).fetchone()[0]
            selected_document_id = conn.execute(
                """
                insert into warehouse.source_document (source_file_id, external_id, payload)
                values (%s, 'selected', '{}'::jsonb)
                returning id
                """,
                (source_file_id,),
            ).fetchone()[0]
            stale_document_id = conn.execute(
                """
                insert into warehouse.source_document (source_file_id, external_id, payload)
                values (%s, 'stale', '{}'::jsonb)
                returning id
                """,
                (source_file_id,),
            ).fetchone()[0]
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values ('säilyä', 'säilyä', 'verb')
                returning id
                """
            ).fetchone()[0]
            sense_id = conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, sort_order)
                values (%s, 'sense-1', 'to remain', 1)
                returning id
                """,
                (lexeme_id,),
            ).fetchone()[0]
            selected_candidate_id = conn.execute(
                """
                insert into semantic.zh_gloss_candidate (
                    target_sense_id, source_name, source_document_id,
                    gloss_zh, confidence_score, candidate_payload
                )
                values (%s, 'manual_ai_zh', %s, '保留', 0.95, '{}'::jsonb)
                returning id
                """,
                (sense_id, selected_document_id),
            ).fetchone()[0]
            conn.execute(
                """
                insert into semantic.zh_gloss_selection (
                    target_sense_id, zh_gloss_candidate_id, gloss_zh,
                    selected_by, confidence_score, selection_reason
                )
                values (%s, %s, '保留', 'manual', 0.95, 'human decision')
                """,
                (sense_id, selected_candidate_id),
            )
            stale_candidate_id = conn.execute(
                """
                insert into semantic.zh_gloss_candidate (
                    target_sense_id, source_name, source_document_id,
                    gloss_zh, confidence_score, candidate_payload
                )
                values (%s, 'manual_ai_zh', %s, '过期', 0.95, '{}'::jsonb)
                returning id
                """,
                (sense_id, stale_document_id),
            ).fetchone()[0]
            clear_retired_source_registry_documents(
                conn,
                source_registry_id=registry_id,
            )
            conn.commit()

            retained = conn.execute(
                """
                select d.id, candidate.id, selection.gloss_zh
                from warehouse.source_document d
                join semantic.zh_gloss_candidate candidate
                  on candidate.source_document_id = d.id
                join semantic.zh_gloss_selection selection
                  on selection.zh_gloss_candidate_id = candidate.id
                where d.id = %s
                """,
                (selected_document_id,),
            ).fetchone()
            stale_count = conn.execute(
                """
                select count(*)
                from warehouse.source_document d
                left join semantic.zh_gloss_candidate candidate
                  on candidate.source_document_id = d.id
                where d.id = %s or candidate.id = %s
                """,
                (stale_document_id, stale_candidate_id),
            ).fetchone()[0]

        self.assertEqual(retained, (selected_document_id, selected_candidate_id, "保留"))
        self.assertEqual(stale_count, 0)

    def test_retired_source_cleanup_commits_each_file_batch(self) -> None:
        with psycopg.connect(get_test_database_url()) as conn:
            registry_id = conn.execute(
                """
                insert into warehouse.source_registry (name, source_kind)
                values ('batched-cleanup-test', 'fixture')
                returning id
                """
            ).fetchone()[0]
            source_file_ids = []
            for index in range(2):
                source_file_id = conn.execute(
                    """
                    insert into warehouse.source_file (
                        source_registry_id, local_path, snapshot_state
                    )
                    values (%s, %s, 'retired')
                    returning id
                    """,
                    (registry_id, f'/tmp/batched-cleanup-{index}'),
                ).fetchone()[0]
                source_file_ids.append(source_file_id)
                conn.execute(
                    """
                    insert into warehouse.source_document (source_file_id, external_id, payload)
                    values (%s, %s, '{}'::jsonb)
                    """,
                    (source_file_id, f'document-{index}'),
                )
            conn.commit()

        first_batch = clear_retired_source_registry_documents_in_batches(
            source_registry_id=registry_id,
            batch_size=1,
            max_files=1,
        )
        second_batch = clear_retired_source_registry_documents_in_batches(
            source_registry_id=registry_id,
            batch_size=1,
            max_files=1,
        )

        with psycopg.connect(get_test_database_url()) as conn:
            document_count = conn.execute(
                """
                select count(*)
                from warehouse.source_document
                where source_file_id = any(%s)
                """,
                (source_file_ids,),
            ).fetchone()[0]
            states = conn.execute(
                """
                select count(*)
                from warehouse.source_file
                where id = any(%s) and snapshot_state = 'retired'
                """,
                (source_file_ids,),
            ).fetchone()[0]
            conn.execute(
                """
                delete from warehouse.source_file where id = any(%s)
                """,
                (source_file_ids,),
            )
            conn.execute(
                """
                delete from warehouse.source_registry where id = %s
                """,
                (registry_id,),
            )
            conn.commit()

        self.assertEqual(first_batch, 1)
        self.assertEqual(second_batch, 1)
        self.assertEqual(document_count, 0)
        self.assertEqual(states, 2)

    def _seed_juosta(self) -> None:
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values ('juosta', 'juosta', 'verb')
                returning id
                """
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, sort_order)
                values (%s, 'sense-1', 'to run', 1),
                       (%s, 'sense-2', 'to flow', 2)
                """,
                (lexeme_id, lexeme_id),
            )
            conn.commit()

    def _source_counts(self, source_name: str, input_path: Path) -> tuple[int, int, int]:
        with psycopg.connect(get_test_database_url()) as conn:
            return conn.execute(
                """
                select
                  count(distinct d.id),
                  count(distinct c.id),
                  count(distinct sc.id)
                from warehouse.source_file f
                left join warehouse.source_document d on d.source_file_id = f.id
                left join semantic.zh_gloss_candidate c on c.source_document_id = d.id
                left join warehouse.source_claim sc on sc.source_document_id = d.id
                join warehouse.source_registry r on r.id = f.source_registry_id
                where r.name = %s and f.local_path = %s
                """,
                (source_name, str(input_path)),
            ).fetchone()

    def _source_registry_counts(self, source_name: str) -> tuple[int, int, int]:
        with psycopg.connect(get_test_database_url()) as conn:
            return conn.execute(
                """
                select
                  count(distinct d.id),
                  count(distinct c.id),
                  count(distinct sc.id)
                from warehouse.source_registry r
                left join warehouse.source_file f on f.source_registry_id = r.id
                left join warehouse.source_document d on d.source_file_id = f.id
                left join semantic.zh_gloss_candidate c on c.source_document_id = d.id
                left join warehouse.source_claim sc on sc.source_document_id = d.id
                where r.name = %s
                """,
                (source_name,),
            ).fetchone()

    def test_wiktionary_zh_replaces_disappeared_documents_and_candidates(self):
        self._seed_juosta()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_input_path = root / "wiktionary-v1.jsonl"
            second_input_path = root / "wiktionary-v2.jsonl"
            first_input_path.write_text(
                json.dumps(
                    {
                        "word": "juosta",
                        "lang_code": "fi",
                        "pos": "verb",
                        "senses": [{"glosses": ["跑"]}, {"glosses": ["流动"]}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-wiktionary-zh", "--input", str(first_input_path)]), 0)
            self.assertEqual(self._source_counts("wiktionary_zh", first_input_path), (1, 2, 3))

            second_input_path.write_text(
                json.dumps(
                    {
                        "word": "kissa",
                        "lang_code": "fi",
                        "pos": "noun",
                        "senses": [{"glosses": ["猫"]}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-wiktionary-zh", "--input", str(second_input_path)]), 0)

            self.assertEqual(self._source_counts("wiktionary_zh", second_input_path), (1, 0, 1))
            self.assertEqual(self._source_registry_counts("wiktionary_zh"), (1, 0, 1))

    def test_dbnary_zh_replaces_disappeared_documents_and_candidates(self):
        self._seed_juosta()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_path = root / "dbnary-v1"
            second_path = root / "dbnary-v2"
            first_path.mkdir()
            second_path.mkdir()
            first_input_path = first_path / "fi_dbnary_ontolex.ttl"
            first_enhancement_path = first_path / "fi_dbnary_enhancement.ttl"
            second_input_path = second_path / "fi_dbnary_ontolex.ttl"
            second_enhancement_path = second_path / "fi_dbnary_enhancement.ttl"
            shutil.copyfile(
                "tests/fixtures/dbnary-zh-exolex.ttl",
                first_input_path,
            )
            shutil.copyfile(
                "tests/fixtures/dbnary-zh-enhancement.ttl",
                first_enhancement_path,
            )

            self.assertEqual(main(["ingest-dbnary-zh", "--input", str(first_input_path)]), 0)
            self.assertEqual(self._source_counts("dbnary_zh", first_input_path), (2, 2, 4))

            shutil.copyfile(first_input_path, second_input_path)
            second_enhancement_path.write_text(
                """
                @prefix dbnary: <http://kaiko.getalp.org/dbnary#> .
                @prefix lexvo: <http://lexvo.org/id/iso639-3/> .
                @prefix ex: <https://example.test/dbnary/> .

                ex:t1 dbnary:isTranslationOf ex:juosta-sense-1 ;
                  dbnary:targetLanguage lexvo:cmn ;
                  dbnary:writtenForm "跑步" .
                """.strip()
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-dbnary-zh", "--input", str(second_input_path)]), 0)

            self.assertEqual(self._source_counts("dbnary_zh", second_input_path), (1, 1, 2))
            self.assertEqual(self._source_registry_counts("dbnary_zh"), (1, 1, 2))

    def test_dbnary_zh_rejects_snapshot_without_chinese_candidates(self):
        self._seed_juosta()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "fi_dbnary_ontolex.ttl"
            enhancement_path = temp_path / "fi_dbnary_enhancement.ttl"
            shutil.copyfile(
                "tests/fixtures/dbnary-zh-exolex.ttl",
                input_path,
            )
            shutil.copyfile(
                "tests/fixtures/dbnary-zh-enhancement.ttl",
                enhancement_path,
            )
            self.assertEqual(main(["ingest-dbnary-zh", "--input", str(input_path)]), 0)
            enhancement_path.write_text(
                "@prefix dbnary: <http://kaiko.getalp.org/dbnary#> .\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "no valid Chinese candidates"):
                main(["ingest-dbnary-zh", "--input", str(input_path)])

            self.assertEqual(self._source_counts("dbnary_zh", input_path), (2, 2, 4))



    def test_omorfi_rejects_empty_snapshot_without_deleting_existing_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "omorfi.tsv"
            input_path.write_text(
                'juoksen\tjuosta\tVERB\t{"person":"1"}\n',
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-omorfi", "--input", str(input_path)]), 0)
            self.assertEqual(self._source_counts("omorfi", input_path), (1, 0, 2))

            input_path.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no rows"):
                main(["ingest-omorfi", "--input", str(input_path)])

            self.assertEqual(self._source_counts("omorfi", input_path), (1, 0, 2))

    def test_omorfi_replaces_disappeared_forms_and_analyses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_input_path = Path(temp_dir) / "omorfi-v1.tsv"
            second_input_path = Path(temp_dir) / "omorfi-v2.tsv"
            first_input_path.write_text(
                'juoksen\tjuosta\tVERB\t{"person":"1"}\n',
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-omorfi", "--input", str(first_input_path)]), 0)

            second_input_path.write_text(
                'juosta\tjuosta\tVERB\t{"verb_form":"Inf"}\n',
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-omorfi", "--input", str(second_input_path)]), 0)

            with psycopg.connect(get_test_database_url()) as conn:
                form_rows = conn.execute(
                    """
                    select f.surface_form, fa.normalized_query
                    from lexicon.form f
                    left join lexicon.form_analysis fa on fa.lexeme_id = f.lexeme_id
                    where f.form_kind = 'omorfi'
                    order by f.surface_form
                    """
                ).fetchall()

        self.assertEqual(form_rows, [("juosta", "juosta")])

    def test_omorfi_same_path_retry_projects_only_pending_source_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "omorfi.hfst"
            input_path.write_bytes(b"fixture model")
            first_row = OmorfiRow(
                surface_form="zzoldform",
                lemma="zzoldlemma",
                part_of_speech="noun",
                features={"Number": "Sing"},
            )
            second_row = OmorfiRow(
                surface_form="zznewform",
                lemma="zznewlemma",
                part_of_speech="noun",
                features={"Number": "Sing"},
            )
            with patch(
                "open_finnish_lexicon.sources.omorfi_stage.analyse_omorfi_model_rows",
                return_value=iter([first_row]),
            ):
                stage_omorfi_rows(
                    input_path,
                    version="omorfi-v1",
                    source_url=str(input_path),
                )
            project_omorfi_rows(input_path)
            finalize_source_snapshot("omorfi", input_path)

            with patch(
                "open_finnish_lexicon.sources.omorfi_stage.analyse_omorfi_model_rows",
                return_value=iter([second_row]),
            ):
                stage_omorfi_rows(
                    input_path,
                    version="omorfi-v2",
                    source_url=str(input_path),
                )
            project_omorfi_rows(input_path)
            finalize_source_snapshot("omorfi", input_path)

        with psycopg.connect(get_test_database_url()) as conn:
            forms = conn.execute(
                """
                select f.surface_form, l.lemma
                from lexicon.form f
                join lexicon.lexeme l on l.id = f.lexeme_id
                where f.form_kind = 'omorfi'
                order by f.surface_form
                """
            ).fetchall()

        self.assertEqual(forms, [("zznewform", "zznewlemma")])

    def test_finalize_uses_the_staged_attempt_id_when_a_same_path_retry_arrives(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "omorfi.tsv"
            shutil.copyfile("tests/fixtures/omorfi.tsv", input_path)
            first_source_file_id = stage_omorfi_rows(
                input_path,
                version="omorfi-v1",
                source_url=str(input_path),
            )
            second_source_file_id = stage_omorfi_rows(
                input_path,
                version="omorfi-v2",
                source_url=str(input_path),
            )

            # The second attempt is newer, but the first attempt is the one
            # whose project completed. Finalization must not publish the
            # unprojected second attempt.
            self.assertNotEqual(first_source_file_id, second_source_file_id)
            self.assertEqual(
                project_omorfi_rows(input_path, source_file_id=first_source_file_id),
                first_source_file_id,
            )
            finalize_source_snapshot(
                "omorfi",
                input_path,
                source_file_id=first_source_file_id,
            )

            with psycopg.connect(get_test_database_url()) as conn:
                states = conn.execute(
                    """
                    select id, snapshot_state
                    from warehouse.source_file
                    order by id
                    """
                ).fetchall()

        self.assertEqual(
            states,
            [
                (first_source_file_id, "active"),
                (second_source_file_id, "retired"),
            ],
        )

    def test_kaikki_projection_reads_the_immutable_staged_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki.jsonl"
            input_path.write_text(
                json.dumps(
                    {
                        "word": "zzimmutablekaikki",
                        "lang": "Finnish",
                        "pos": "noun",
                        "senses": [{"id": "sense-1", "glosses": ["staged gloss"]}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            source_file_id = stage_kaikki_entries(
                input_path,
                version="immutable-v1",
                source_url=str(input_path),
                reject_empty_snapshot=True,
            )
            input_path.write_text(
                json.dumps(
                    {
                        "word": "zzimmutablekaikki",
                        "lang": "Finnish",
                        "pos": "noun",
                        "senses": [{"id": "sense-1", "glosses": ["mutated gloss"]}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            project_kaikki_entries(
                input_path,
                source_file_id=source_file_id,
                replace_snapshot=True,
            )
            finalize_source_snapshot(
                "kaikki",
                input_path,
                source_file_id=source_file_id,
            )

            with psycopg.connect(get_test_database_url()) as conn:
                gloss = conn.execute(
                    """
                    select ls.gloss_en
                    from lexicon.lexeme l
                    join lexicon.lexeme_sense ls on ls.lexeme_id = l.id
                    where l.lemma = 'zzimmutablekaikki'
                      and ls.sense_key = 'sense-1'
                    """
                ).fetchone()[0]

        self.assertEqual(gloss, "staged gloss")

    def test_omorfi_projection_reads_the_immutable_staged_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "omorfi.tsv"
            input_path.write_text(
                'zzstagedform\tzzstagedlemma\tNOUN\t{"Number":"Sing"}\n',
                encoding="utf-8",
            )
            source_file_id = stage_omorfi_rows(
                input_path,
                version="immutable-v1",
                source_url=str(input_path),
            )
            input_path.write_text(
                'zzmutatedform\tzzmutatedlemma\tNOUN\t{"Number":"Sing"}\n',
                encoding="utf-8",
            )

            project_omorfi_rows(input_path, source_file_id=source_file_id)
            finalize_source_snapshot(
                "omorfi",
                input_path,
                source_file_id=source_file_id,
            )

            with psycopg.connect(get_test_database_url()) as conn:
                forms = conn.execute(
                    """
                    select f.surface_form, l.lemma
                    from lexicon.form f
                    join lexicon.lexeme l on l.id = f.lexeme_id
                    where f.form_kind = 'omorfi'
                    order by f.surface_form
                    """
                ).fetchall()

        self.assertEqual(forms, [("zzstagedform", "zzstagedlemma")])

    def test_tatoeba_projection_reads_the_immutable_staged_snapshot(self):
        self._seed_juosta()
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "tatoeba.tsv"
            input_path.write_text(
                "sense-1\tHän juoksee.\tHe runs.\t0.95\n",
                encoding="utf-8",
            )
            source_file_id = stage_tatoeba_rows(
                input_path,
                version="immutable-v1",
                source_url=str(input_path),
            )
            input_path.write_text(
                "sense-1\tHän juoksee uudelleen.\tHe runs again.\t0.95\n",
                encoding="utf-8",
            )

            project_tatoeba_rows(input_path, source_file_id=source_file_id)
            finalize_source_snapshot(
                "tatoeba",
                input_path,
                source_file_id=source_file_id,
            )

            with psycopg.connect(get_test_database_url()) as conn:
                text_fi = conn.execute(
                    "select text_fi from lexicon.example where source_label = 'tatoeba'"
                ).fetchone()[0]

        self.assertEqual(text_fi, "Hän juoksee.")

    def test_kaikki_replaces_auxiliary_metadata_across_source_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_path = root / "kaikki-v1.jsonl"
            second_path = root / "kaikki-v2.jsonl"
            first_path.write_text(
                json.dumps(
                    {
                        "word": "zzsnapshotaux",
                        "lang": "Finnish",
                        "pos": "noun",
                        "sounds": [{"ipa": "/old/"}],
                        "etymology_text": "Old etymology.",
                        "senses": [
                            {
                                "id": "sense-1",
                                "glosses": ["old gloss"],
                                "note": "Old note.",
                                "warning": "Old warning.",
                                "topics": ["old-topic"],
                            }
                        ],
                        "derived": [{"word": "zzsnapshotderived"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            for input_path in (first_path, second_path):
                if input_path is second_path:
                    input_path.write_text(
                        json.dumps(
                            {
                                "word": "zzsnapshotaux",
                                "lang": "Finnish",
                                "pos": "noun",
                                "senses": [{"id": "sense-1", "glosses": ["new gloss"]}],
                            }
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                stage_kaikki_entries(
                    input_path,
                    version=input_path.stem,
                    source_url=str(input_path),
                    reject_empty_snapshot=True,
                )
                project_kaikki_entries(input_path, replace_snapshot=True)

            with psycopg.connect(get_test_database_url()) as conn:
                lexeme_id, sense_id = conn.execute(
                    """
                    select l.id, ls.id
                    from lexicon.lexeme l
                    join lexicon.lexeme_sense ls on ls.lexeme_id = l.id
                    where l.lemma = 'zzsnapshotaux'
                      and l.part_of_speech = 'noun'
                      and ls.sense_key = 'sense-1'
                    """
                ).fetchone()
                manual_child_id = conn.execute(
                    """
                    insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                    values ('zzsnapshotmanualchild', 'zzsnapshotmanualchild', 'noun')
                    returning id
                    """
                ).fetchone()[0]
                conn.execute(
                    """
                    insert into lexicon.pronunciation (lexeme_id, ipa, tts_voice)
                    values (%s, '/manual/', 'fi')
                    """,
                    (lexeme_id,),
                )
                conn.execute(
                    """
                    insert into lexicon.grammar_note (lexeme_id, note_en, note_kind)
                    values (%s, 'Manual note.', 'editorial')
                    """,
                    (lexeme_id,),
                )
                conn.execute(
                    """
                    insert into lexicon.grammar_note (sense_id, note_en, note_kind)
                    values (%s, 'Manual sense note.', 'editorial')
                    """,
                    (sense_id,),
                )
                conn.execute(
                    """
                    insert into lexicon.usage_warning (sense_id, warning_en, warning_kind)
                    values (%s, 'Manual warning.', 'editorial')
                    """,
                    (sense_id,),
                )
                conn.execute(
                    """
                    insert into lexicon.derivation_relation (
                        parent_lexeme_id, child_lexeme_id, relation_type, note
                    )
                    values (%s, %s, 'manual-relation', 'manual')
                    """,
                    (lexeme_id, manual_child_id),
                )
                conn.execute(
                    """
                    insert into lexicon.topic_taxonomy (id, label_en, source)
                    values ('manual-topic', 'Manual topic', 'manual')
                    on conflict (id) do nothing
                    """
                )
                conn.execute(
                    """
                    insert into lexicon.lexeme_topic (
                        lexeme_id, sense_id, topic_id, confidence, source
                    )
                    values (%s, %s, 'manual-topic', 0.9, 'manual')
                    """,
                    (lexeme_id, sense_id),
                )
                conn.commit()

            with psycopg.connect(get_test_database_url()) as conn:
                lexeme_id = conn.execute(
                    """
                    select id
                    from lexicon.lexeme
                    where lemma = 'zzsnapshotaux' and part_of_speech = 'noun'
                    """
                ).fetchone()[0]
                stale_auxiliary_counts = conn.execute(
                    """
                    select
                      (select count(*) from lexicon.pronunciation where lexeme_id = %s and ipa = '/old/'),
                      (select count(*) from lexicon.grammar_note where lexeme_id = %s and note_en = 'Old etymology.'),
                      (select count(*)
                       from lexicon.grammar_note gn
                       join lexicon.lexeme_sense ls on ls.id = gn.sense_id
                       where ls.lexeme_id = %s and gn.note_en = 'Old note.'),
                      (select count(*)
                       from lexicon.usage_warning uw
                       join lexicon.lexeme_sense ls on ls.id = uw.sense_id
                       where ls.lexeme_id = %s and uw.warning_en = 'Old warning.'),
                      (select count(*)
                       from lexicon.derivation_relation
                       where parent_lexeme_id = %s and note = 'kaikki-derived'),
                      (select count(*)
                       from lexicon.lexeme_topic lt
                       where lt.lexeme_id = %s and lt.source = 'kaikki-topic')
                    """,
                    (lexeme_id,) * 6,
                ).fetchone()
                manual_auxiliary_counts = conn.execute(
                    """
                    select
                      (select count(*) from lexicon.pronunciation where lexeme_id = %s and ipa = '/manual/'),
                      (select count(*) from lexicon.grammar_note where lexeme_id = %s and note_en = 'Manual note.'),
                      (select count(*)
                       from lexicon.grammar_note gn
                       join lexicon.lexeme_sense ls on ls.id = gn.sense_id
                       where ls.lexeme_id = %s and gn.note_en = 'Manual sense note.'),
                      (select count(*)
                       from lexicon.usage_warning uw
                       join lexicon.lexeme_sense ls on ls.id = uw.sense_id
                       where ls.lexeme_id = %s and uw.warning_en = 'Manual warning.'),
                      (select count(*)
                       from lexicon.derivation_relation dr
                       join lexicon.lexeme child on child.id = dr.child_lexeme_id
                       where dr.parent_lexeme_id = %s and child.lemma = 'zzsnapshotmanualchild'),
                      (select count(*)
                       from lexicon.lexeme_topic lt
                       where lt.lexeme_id = %s and lt.source = 'manual')
                    """,
                    (lexeme_id,) * 6,
                ).fetchone()

            self.assertEqual(stale_auxiliary_counts, (0, 0, 0, 0, 0, 0))
            self.assertEqual(manual_auxiliary_counts, (1, 1, 1, 1, 1, 1))

    def test_kaikki_stage_keeps_previous_snapshot_until_projection_finishes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_path = root / "kaikki-v1.jsonl"
            second_path = root / "kaikki-v2.jsonl"
            for input_path, gloss in (
                (first_path, "old gloss"),
                (second_path, "new gloss"),
            ):
                input_path.write_text(
                    json.dumps(
                        {
                            "word": "zzpendingkaikki",
                            "lang": "Finnish",
                            "pos": "noun",
                            "senses": [{"id": "sense-1", "glosses": [gloss]}],
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                stage_kaikki_entries(
                    input_path,
                    version=input_path.stem,
                    source_url=str(input_path),
                    reject_empty_snapshot=True,
                )

            with psycopg.connect(get_test_database_url()) as conn:
                document_count = conn.execute(
                    """
                    select count(*)
                    from warehouse.source_document d
                    join warehouse.source_file f on f.id = d.source_file_id
                    join warehouse.source_registry r on r.id = f.source_registry_id
                    where r.name = 'kaikki'
                    """
                ).fetchone()[0]

        self.assertEqual(document_count, 2)

    def test_kaikki_projection_failure_keeps_previous_active_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_path = root / "kaikki-active-v1.jsonl"
            second_path = root / "kaikki-pending-v2.jsonl"
            first_entry = {
                "word": "zzatomickaikki",
                "lang": "Finnish",
                "pos": "noun",
                "senses": [{"id": "sense-1", "glosses": ["old gloss"]}],
            }
            second_entry = {
                **first_entry,
                "senses": [{"id": "sense-1", "glosses": ["new gloss"]}],
            }
            first_path.write_text(json.dumps(first_entry) + "\n", encoding="utf-8")
            second_path.write_text(json.dumps(second_entry) + "\n", encoding="utf-8")

            stage_kaikki_entries(
                first_path,
                version="atomic-v1",
                source_url=str(first_path),
                reject_empty_snapshot=True,
            )
            project_kaikki_entries(first_path, replace_snapshot=True)
            finalize_source_snapshot("kaikki", first_path)

            stage_kaikki_entries(
                second_path,
                version="atomic-v2",
                source_url=str(second_path),
                reject_empty_snapshot=True,
            )

            def broken_reader(_conn, _source_file_id):
                yield second_entry
                raise RuntimeError("simulated Kaikki projection failure")

            with patch(
                "open_finnish_lexicon.sources.kaikki_project._iter_staged_kaikki_entries",
                side_effect=broken_reader,
            ):
                with self.assertRaisesRegex(RuntimeError, "simulated Kaikki projection failure"):
                    project_kaikki_entries(second_path, replace_snapshot=True)

            with psycopg.connect(get_test_database_url()) as conn:
                states = dict(
                    conn.execute(
                        """
                        select local_path, snapshot_state
                        from warehouse.source_file
                        where local_path = any(%s)
                        """,
                        ([str(first_path), str(second_path)],),
                    ).fetchall()
                )
                active_gloss = conn.execute(
                    """
                    select ls.gloss_en
                    from lexicon.lexeme l
                    join lexicon.lexeme_sense ls on ls.lexeme_id = l.id
                    where l.lemma = 'zzatomickaikki'
                      and l.part_of_speech = 'noun'
                      and ls.sense_key = 'sense-1'
                    """
                ).fetchone()[0]
                registry_metadata = conn.execute(
                    """
                    select version, source_url
                    from warehouse.source_registry
                    where name = 'kaikki'
                    """
                ).fetchone()

            self.assertEqual(states[str(first_path)], "active")
            self.assertEqual(states[str(second_path)], "pending")
            self.assertEqual(active_gloss, "old gloss")
            self.assertEqual(registry_metadata, ("atomic-v1", str(first_path)))

    def test_kaikki_same_path_retry_preserves_active_warehouse_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki.jsonl"
            first_entry = {
                "word": "zzsamepathkaikki",
                "lang": "Finnish",
                "pos": "noun",
                "senses": [{"id": "sense-1", "glosses": ["old raw gloss"]}],
            }
            second_entry = {
                **first_entry,
                "senses": [{"id": "sense-1", "glosses": ["new raw gloss"]}],
            }
            input_path.write_text(json.dumps(first_entry) + "\n", encoding="utf-8")
            stage_kaikki_entries(
                input_path,
                version="same-path-v1",
                source_url=str(input_path),
                reject_empty_snapshot=True,
            )
            project_kaikki_entries(input_path, replace_snapshot=True)
            finalize_source_snapshot("kaikki", input_path)

            input_path.write_text(json.dumps(second_entry) + "\n", encoding="utf-8")
            stage_kaikki_entries(
                input_path,
                version="same-path-v2",
                source_url=str(input_path),
                reject_empty_snapshot=True,
            )

            def broken_reader(_conn, _source_file_id):
                yield second_entry
                raise RuntimeError("simulated same-path projection failure")

            with patch(
                "open_finnish_lexicon.sources.kaikki_project._iter_staged_kaikki_entries",
                side_effect=broken_reader,
            ):
                with self.assertRaisesRegex(RuntimeError, "simulated same-path projection failure"):
                    project_kaikki_entries(input_path, replace_snapshot=True)

            with psycopg.connect(get_test_database_url()) as conn:
                states = dict(
                    conn.execute(
                        """
                        select snapshot_state, count(*)
                        from warehouse.source_file sf
                        join warehouse.source_registry sr on sr.id = sf.source_registry_id
                        where sr.name = 'kaikki' and sf.local_path = %s
                        group by snapshot_state
                        """,
                        (str(input_path),),
                    ).fetchall()
                )
                active_document = conn.execute(
                    """
                    select d.payload #>> '{senses,0,glosses,0}'
                    from warehouse.source_document d
                    join warehouse.source_file sf on sf.id = d.source_file_id
                    join warehouse.source_registry sr on sr.id = sf.source_registry_id
                    where sr.name = 'kaikki'
                      and sf.local_path = %s
                      and sf.snapshot_state = 'active'
                    """,
                    (str(input_path),),
                ).fetchone()[0]

            self.assertEqual(states, {"active": 1, "pending": 1})
            self.assertEqual(active_document, "old raw gloss")

    def test_stale_pending_attempt_is_retired_without_touching_active_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "kaikki-stale-attempt.jsonl"
            input_path.write_text(
                json.dumps(
                    {
                        "word": "zzstaleattempt",
                        "lang": "Finnish",
                        "pos": "noun",
                        "senses": [{"id": "sense-1", "glosses": ["old gloss"]}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            stage_kaikki_entries(
                input_path,
                version="stale-v1",
                source_url=str(input_path),
                reject_empty_snapshot=True,
            )
            project_kaikki_entries(input_path, replace_snapshot=True)
            finalize_source_snapshot("kaikki", input_path)

            input_path.write_text(
                json.dumps(
                    {
                        "word": "zzstaleattempt",
                        "lang": "Finnish",
                        "pos": "noun",
                        "senses": [{"id": "sense-1", "glosses": ["new gloss"]}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            stage_kaikki_entries(
                input_path,
                version="stale-v2",
                source_url=str(input_path),
                reject_empty_snapshot=True,
            )
            with psycopg.connect(get_test_database_url()) as conn:
                conn.execute(
                    """
                    update warehouse.source_file
                    set imported_at = now() - interval '2 hours'
                    where local_path = %s and snapshot_state = 'pending'
                    """,
                    (str(input_path),),
                )
                retired_count = retire_stale_pending_source_files(conn, older_than_hours=1)
                conn.commit()

            with psycopg.connect(get_test_database_url()) as conn:
                states = dict(
                    conn.execute(
                        """
                        select snapshot_state, count(*)
                        from warehouse.source_file sf
                        join warehouse.source_registry sr on sr.id = sf.source_registry_id
                        where sr.name = 'kaikki' and sf.local_path = %s
                        group by snapshot_state
                        """,
                        (str(input_path),),
                    ).fetchall()
                )
                retired_metadata = conn.execute(
                    """
                    select retired_at is not null, retire_reason
                    from warehouse.source_file sf
                    join warehouse.source_registry sr on sr.id = sf.source_registry_id
                    where sr.name = 'kaikki'
                      and sf.local_path = %s
                      and sf.snapshot_state = 'retired'
                    """,
                    (str(input_path),),
                ).fetchone()
                active_document = conn.execute(
                    """
                    select d.payload #>> '{senses,0,glosses,0}'
                    from warehouse.source_document d
                    join warehouse.source_file sf on sf.id = d.source_file_id
                    join warehouse.source_registry sr on sr.id = sf.source_registry_id
                    where sr.name = 'kaikki'
                      and sf.local_path = %s
                      and sf.snapshot_state = 'active'
                    """,
                    (str(input_path),),
                ).fetchone()[0]
                pending_documents = conn.execute(
                    """
                    select count(*)
                    from warehouse.source_document d
                    join warehouse.source_file sf on sf.id = d.source_file_id
                    where sf.local_path = %s and sf.snapshot_state = 'pending'
                    """,
                    (str(input_path),),
                ).fetchone()[0]

        self.assertEqual(retired_count, 1)
        self.assertEqual(states, {"active": 1, "retired": 1})
        self.assertEqual(retired_metadata, (True, "stale-pending-attempt"))
        self.assertEqual(active_document, "old gloss")
        self.assertEqual(pending_documents, 0)

    def test_lexeme_merge_preserves_form_source_ownership(self):
        with psycopg.connect(get_test_database_url()) as conn:
            source_registry_id = conn.execute(
                """
                insert into warehouse.source_registry (name, source_kind, version)
                values ('ownership-fixture', 'tsv', 'test')
                returning id
                """
            ).fetchone()[0]
            source_file_id = conn.execute(
                """
                insert into warehouse.source_file (source_registry_id, local_path)
                values (%s, '/tmp/ownership-fixture.tsv')
                returning id
                """,
                (source_registry_id,),
            ).fetchone()[0]
            source_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values ('zzownership-source', 'zzownership-source', 'noun')
                returning id
                """
            ).fetchone()[0]
            target_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values ('zzownership-target', 'zzownership-target', 'noun')
                returning id
                """
            ).fetchone()[0]
            form_id = conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, 'zzownership-target', 'zzownership-target', 'omorfi', '{}')
                returning id
                """,
                (source_lexeme_id,),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form_source (form_id, source_file_id)
                values (%s, %s)
                """,
                (form_id, source_file_id),
            )
            conn.commit()

        with psycopg.connect(get_test_database_url()) as conn:
            _merge_lexeme_into(conn, source_lexeme_id, target_lexeme_id)
            conn.commit()

        with psycopg.connect(get_test_database_url()) as conn:
            ownership_count = conn.execute(
                """
                select count(*)
                from lexicon.form_source fs
                join lexicon.form f on f.id = fs.form_id
                where fs.source_file_id = %s
                  and f.lexeme_id = %s
                """,
                (source_file_id, target_lexeme_id),
            ).fetchone()[0]

        self.assertEqual(ownership_count, 1)

    def test_lexeme_merge_preserves_auxiliary_source_ownership(self):
        with psycopg.connect(get_test_database_url()) as conn:
            source_registry_id = conn.execute(
                """
                insert into warehouse.source_registry (name, source_kind, version)
                values ('aux-ownership-fixture', 'jsonl', 'test')
                returning id
                """
            ).fetchone()[0]
            source_file_id = conn.execute(
                """
                insert into warehouse.source_file (source_registry_id, local_path)
                values (%s, '/tmp/aux-ownership-fixture.jsonl')
                returning id
                """,
                (source_registry_id,),
            ).fetchone()[0]
            source_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values ('zzauxownership-source', 'zzauxownership-source', 'noun')
                returning id
                """
            ).fetchone()[0]
            target_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values ('zzauxownership-target', 'zzauxownership-target', 'noun')
                returning id
                """
            ).fetchone()[0]
            child_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values ('zzauxownership-child', 'zzauxownership-child', 'noun')
                returning id
                """
            ).fetchone()[0]
            pronunciation_id = conn.execute(
                """
                insert into lexicon.pronunciation (lexeme_id, ipa, tts_voice)
                values (%s, '/aux/', 'fi')
                returning id
                """,
                (source_lexeme_id,),
            ).fetchone()[0]
            grammar_note_id = conn.execute(
                """
                insert into lexicon.grammar_note (lexeme_id, note_en, note_kind)
                values (%s, 'Auxiliary note.', 'etymology')
                returning id
                """,
                (source_lexeme_id,),
            ).fetchone()[0]
            usage_warning_id = conn.execute(
                """
                insert into lexicon.usage_warning (lexeme_id, warning_en, warning_kind)
                values (%s, 'Auxiliary warning.', 'source-warning')
                returning id
                """,
                (source_lexeme_id,),
            ).fetchone()[0]
            relation_id = conn.execute(
                """
                insert into lexicon.derivation_relation (
                    parent_lexeme_id, child_lexeme_id, relation_type, note
                )
                values (%s, %s, 'derived-term', 'kaikki-derived')
                returning id
                """,
                (source_lexeme_id, child_lexeme_id),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.topic_taxonomy (id, label_en, source)
                values ('aux-ownership-topic', 'Auxiliary topic', 'kaikki')
                on conflict (id) do nothing
                """
            )
            topic_id = conn.execute(
                """
                insert into lexicon.lexeme_topic (
                    lexeme_id, topic_id, confidence, source
                )
                values (%s, 'aux-ownership-topic', 0.7, 'kaikki-topic')
                returning id
                """,
                (source_lexeme_id,),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.pronunciation_source (pronunciation_id, source_file_id)
                values (%s, %s)
                """,
                (pronunciation_id, source_file_id),
            )
            conn.execute(
                """
                insert into lexicon.grammar_note_source (grammar_note_id, source_file_id)
                values (%s, %s)
                """,
                (grammar_note_id, source_file_id),
            )
            conn.execute(
                """
                insert into lexicon.usage_warning_source (usage_warning_id, source_file_id)
                values (%s, %s)
                """,
                (usage_warning_id, source_file_id),
            )
            conn.execute(
                """
                insert into lexicon.derivation_relation_source (relation_id, source_file_id)
                values (%s, %s)
                """,
                (relation_id, source_file_id),
            )
            conn.execute(
                """
                insert into lexicon.lexeme_topic_source (lexeme_topic_id, source_file_id)
                values (%s, %s)
                """,
                (topic_id, source_file_id),
            )
            conn.commit()

        with psycopg.connect(get_test_database_url()) as conn:
            _merge_lexeme_into(conn, source_lexeme_id, target_lexeme_id)
            conn.commit()

        with psycopg.connect(get_test_database_url()) as conn:
            ownership_counts = conn.execute(
                """
                select
                  (select count(*)
                   from lexicon.pronunciation_source ps
                   join lexicon.pronunciation p on p.id = ps.pronunciation_id
                   where ps.source_file_id = %s and p.lexeme_id = %s),
                  (select count(*)
                   from lexicon.grammar_note_source gns
                   join lexicon.grammar_note gn on gn.id = gns.grammar_note_id
                   where gns.source_file_id = %s and gn.lexeme_id = %s),
                  (select count(*)
                   from lexicon.usage_warning_source uws
                   join lexicon.usage_warning uw on uw.id = uws.usage_warning_id
                   where uws.source_file_id = %s and uw.lexeme_id = %s),
                  (select count(*)
                   from lexicon.derivation_relation_source drs
                   join lexicon.derivation_relation dr on dr.id = drs.relation_id
                   where drs.source_file_id = %s and dr.parent_lexeme_id = %s),
                  (select count(*)
                   from lexicon.lexeme_topic_source lts
                   join lexicon.lexeme_topic lt on lt.id = lts.lexeme_topic_id
                   where lts.source_file_id = %s and lt.lexeme_id = %s)
                """,
                (source_file_id, target_lexeme_id) * 5,
            ).fetchone()

        self.assertEqual(ownership_counts, (1, 1, 1, 1, 1))

    def test_sense_merge_preserves_auxiliary_source_ownership(self):
        with psycopg.connect(get_test_database_url()) as conn:
            source_registry_id = conn.execute(
                """
                insert into warehouse.source_registry (name, source_kind, version)
                values ('sense-ownership-fixture', 'jsonl', 'test')
                returning id
                """
            ).fetchone()[0]
            source_file_id = conn.execute(
                """
                insert into warehouse.source_file (source_registry_id, local_path)
                values (%s, '/tmp/sense-ownership-fixture.jsonl')
                returning id
                """,
                (source_registry_id,),
            ).fetchone()[0]
            source_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values ('zzsenseownership-source', 'zzsenseownership-source', 'noun')
                returning id
                """
            ).fetchone()[0]
            target_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values ('zzsenseownership-target', 'zzsenseownership-target', 'noun')
                returning id
                """
            ).fetchone()[0]
            source_sense_id = conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en)
                values (%s, 'same-sense', 'source gloss')
                returning id
                """,
                (source_lexeme_id,),
            ).fetchone()[0]
            target_sense_id = conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en)
                values (%s, 'same-sense', 'target gloss')
                returning id
                """,
                (target_lexeme_id,),
            ).fetchone()[0]
            grammar_note_id = conn.execute(
                """
                insert into lexicon.grammar_note (sense_id, note_en, note_kind)
                values (%s, 'Source sense note.', 'usage-note')
                returning id
                """,
                (source_sense_id,),
            ).fetchone()[0]
            usage_warning_id = conn.execute(
                """
                insert into lexicon.usage_warning (sense_id, warning_en, warning_kind)
                values (%s, 'Source sense warning.', 'sense-warning')
                returning id
                """,
                (source_sense_id,),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.topic_taxonomy (id, label_en, source)
                values ('sense-ownership-topic', 'Sense ownership topic', 'kaikki')
                on conflict (id) do nothing
                """
            )
            topic_id = conn.execute(
                """
                insert into lexicon.lexeme_topic (
                    lexeme_id, sense_id, topic_id, confidence, source
                )
                values (%s, %s, 'sense-ownership-topic', 0.7, 'kaikki-topic')
                returning id
                """,
                (source_lexeme_id, source_sense_id),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.grammar_note_source (grammar_note_id, source_file_id)
                values (%s, %s)
                """,
                (grammar_note_id, source_file_id),
            )
            conn.execute(
                """
                insert into lexicon.usage_warning_source (usage_warning_id, source_file_id)
                values (%s, %s)
                """,
                (usage_warning_id, source_file_id),
            )
            conn.execute(
                """
                insert into lexicon.lexeme_topic_source (lexeme_topic_id, source_file_id)
                values (%s, %s)
                """,
                (topic_id, source_file_id),
            )
            conn.commit()

        with psycopg.connect(get_test_database_url()) as conn:
            _merge_lexeme_into(conn, source_lexeme_id, target_lexeme_id)
            conn.commit()

        with psycopg.connect(get_test_database_url()) as conn:
            ownership_counts = conn.execute(
                """
                select
                  (select count(*)
                   from lexicon.grammar_note_source gns
                   join lexicon.grammar_note gn on gn.id = gns.grammar_note_id
                   where gns.source_file_id = %s and gn.sense_id = %s),
                  (select count(*)
                   from lexicon.usage_warning_source uws
                   join lexicon.usage_warning uw on uw.id = uws.usage_warning_id
                   where uws.source_file_id = %s and uw.sense_id = %s),
                  (select count(*)
                   from lexicon.lexeme_topic_source lts
                   join lexicon.lexeme_topic lt on lt.id = lts.lexeme_topic_id
                   where lts.source_file_id = %s and lt.sense_id = %s)
                """,
                (source_file_id, target_sense_id) * 3,
            ).fetchone()

        self.assertEqual(ownership_counts, (1, 1, 1))

    def test_finnwordnet_replaces_relations_across_source_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_path = root / "finnwordnet-v1"
            second_path = root / "finnwordnet-v2"
            first_path.mkdir()
            second_path.mkdir()
            for snapshot_path in (first_path, second_path):
                (snapshot_path / "fiwn-lexrels.tsv").write_text("", encoding="utf-8")

            (first_path / "fiwn-wsenses.tsv").write_text(
                "fi:v00000001\tzzfwnrun\t0\nfi:v00000001\tzzfwnjog\t0\n",
                encoding="utf-8",
            )
            (first_path / "fiwn-lexrels.tsv").write_text(
                "fi:v00000001\tzzfwnrun\tfi:v00000002\tzzfwnwalk\t$\tverb group\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-finnwordnet", "--input", str(first_path)]), 0)

            (second_path / "fiwn-wsenses.tsv").write_text(
                "fi:v00000003\tzzfwnunrelated\t0\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-finnwordnet", "--input", str(second_path)]), 0)

            with psycopg.connect(get_test_database_url()) as conn:
                relation_count = conn.execute(
                    """
                    select count(*)
                    from lexicon.lexical_relation rel
                    join lexicon.lexeme source on source.id = rel.source_lexeme_id
                    join lexicon.lexeme target on target.id = rel.target_lexeme_id
                    where source.lemma in ('zzfwnrun', 'zzfwnwalk')
                       or target.lemma in ('zzfwnrun', 'zzfwnwalk')
                    """
                ).fetchone()[0]
                source_owned_count = conn.execute(
                    """
                    select count(*)
                    from lexicon.lexical_relation_source rls
                    join warehouse.source_file sf on sf.id = rls.source_file_id
                    join warehouse.source_registry sr on sr.id = sf.source_registry_id
                    where sr.name = 'finnwordnet'
                    """
                ).fetchone()[0]

            self.assertEqual(relation_count, 0)
            self.assertEqual(source_owned_count, 0)

    def test_wiktionary_zh_rejects_empty_snapshot_without_deleting_existing_data(self):
        self._seed_juosta()
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "wiktionary-zh.jsonl"
            input_path.write_text(
                json.dumps(
                    {
                        "word": "juosta",
                        "lang_code": "fi",
                        "pos": "verb",
                        "senses": [{"glosses": ["跑"]}, {"glosses": ["流动"]}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-wiktionary-zh", "--input", str(input_path)]), 0)
            input_path.write_text("not-json\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "no valid Finnish entries"):
                main(["ingest-wiktionary-zh", "--input", str(input_path)])

            self.assertEqual(self._source_counts("wiktionary_zh", input_path), (1, 2, 3))
