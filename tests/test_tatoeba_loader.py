import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg

from open_finnish_lexicon.cli import main
from support import get_test_database_url


class TatoebaLoaderTests(unittest.TestCase):
    def test_legacy_tatoeba_uses_unique_existing_finnish_sentence_before_generic_sense_key(self):
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values ('zzsentence-resolve', 'zzsentence-resolve', 'verb')
                returning id
                """
            ).fetchone()[0]
            sense_id = conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, sort_order)
                values (%s, 'sense-1', 'to run', 1)
                returning id
                """
                , (lexeme_id,)
            ).fetchone()[0]
            example_id = conn.execute(
                """
                insert into lexicon.example (text_fi, text_en, source_label, quality_score)
                values ('Zzsentence juoksee nopeasti.', null, 'kaikki', 0.70)
                returning id
                """
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.sense_example (sense_id, example_id, is_core, sort_order)
                values (%s, %s, true, 1)
                """,
                (sense_id, example_id),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "tatoeba.tsv"
            input_path.write_text(
                "sense-1\tZzsentence juoksee nopeasti.\tA sentence runs quickly.\t0.95\t句子跑得很快。\n"
            )
            self.assertEqual(main(["ingest-tatoeba", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            linked = conn.execute(
                """
                select l.lemma, ls.gloss_en, e.source_label, zet.text_zh,
                       zet.generation_method
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                join lexicon.lexeme l on l.id = ls.lexeme_id
                join lexicon.example e on e.id = se.example_id
                left join zh_layer.zh_example_translation zet
                  on zet.example_id = e.id and zet.is_primary = true
                where e.source_label = 'tatoeba'
                  and e.text_fi = 'Zzsentence juoksee nopeasti.'
                """
            ).fetchone()

        self.assertEqual(
            linked,
            (
                'zzsentence-resolve',
                'to run',
                'tatoeba',
                '句子跑得很快。',
                'tatoeba-direct-zh',
            ),
        )

    def test_legacy_tatoeba_sense_key_uses_english_to_disambiguate_duplicate_keys(self):
        with psycopg.connect(get_test_database_url()) as conn:
            run_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                ("legacy-run", "legacy-run", "verb"),
            ).fetchone()[0]
            flow_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                ("legacy-flow", "legacy-flow", "verb"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values
                    (%s, 'shared-legacy-key', 'to run', '{}', 1),
                    (%s, 'shared-legacy-key', 'to flow', '{}', 1)
                """,
                (run_lexeme_id, flow_lexeme_id),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "tatoeba.tsv"
            input_path.write_text(
                "shared-legacy-key\tLegacy juoksee nopeasti.\tHe runs quickly.\t0.95\n"
            )
            self.assertEqual(main(["ingest-tatoeba", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            linked_sense = conn.execute(
                """
                select ls.gloss_en
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                join lexicon.example e on e.id = se.example_id
                where e.source_label = 'tatoeba'
                  and e.text_fi = 'Legacy juoksee nopeasti.'
                """
            ).fetchone()

        self.assertEqual(linked_sense, ("to run",))

    def test_legacy_tatoeba_does_not_attach_unique_form_of_probe_without_english_overlap(self):
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                ("zzvisprobe", "zzvisprobe", "noun"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, 'sense-1', 'genitive singular of zzvisprobe', '{}', 1)
                """,
                (lexeme_id,),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "tatoeba.tsv"
            input_path.write_text(
                "sense-1\tHän juoksee nopeasti.\tHe runs quickly.\t0.95\t他跑得很快。\n"
            )
            self.assertEqual(main(["ingest-tatoeba", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            linked = conn.execute(
                """
                select l.lemma, ls.gloss_en
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                join lexicon.lexeme l on l.id = ls.lexeme_id
                join lexicon.example e on e.id = se.example_id
                where e.text_fi = 'Hän juoksee nopeasti.'
                  and l.lemma = 'zzvisprobe'
                """
            ).fetchall()

        self.assertEqual(linked, [])

    def test_legacy_tatoeba_missing_or_ambiguous_sense_is_skipped(self):
        with psycopg.connect(get_test_database_url()) as conn:
            for lemma in ("legacy-ambiguous-a", "legacy-ambiguous-b"):
                lexeme_id = conn.execute(
                    """
                    insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                    values (%s, %s, %s)
                    returning id
                    """,
                    (lemma, lemma, "noun"),
                ).fetchone()[0]
                conn.execute(
                    """
                    insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                    values (%s, 'unresolved-legacy-key', 'unrelated meaning', '{}', 1)
                    """,
                    (lexeme_id,),
                )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "tatoeba.tsv"
            input_path.write_text(
                "missing-legacy-key\tMissing example.\tMissing meaning.\t0.95\n"
                "unresolved-legacy-key\tAmbiguous example.\tNo matching meaning.\t0.95\n"
            )
            self.assertEqual(main(["ingest-tatoeba", "--input", str(input_path)]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            count = conn.execute(
                """
                select count(*)
                from lexicon.example
                where source_label = 'tatoeba'
                  and text_fi in ('Missing example.', 'Ambiguous example.')
                """
            ).fetchone()[0]

        self.assertEqual(count, 0)

    def test_tatoeba_loader_keeps_legacy_tsv_support(self):
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                on conflict (lemma, part_of_speech) do update
                set display_lemma = excluded.display_lemma
                returning id
                """,
                ("legacy-zorbla", "legacy-zorbla", "noun"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                on conflict (lexeme_id, sense_key) do nothing
                """,
                (lexeme_id, "legacy-zorbla-sense", "legacy zorbla", 1),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "tatoeba.tsv"
            input_path.write_text("legacy-zorbla-sense\tLegacy zorbla juoksee.\tLegacy zorbla runs.\t0.95\n")
            input_path_str = str(input_path)

            exit_code = main(["ingest-tatoeba", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            example_row = conn.execute(
                """
                select text_fi, text_en, source_label, quality_score
                from lexicon.example
                where source_label = 'tatoeba'
                """
            ).fetchone()
            sense_example_count = conn.execute(
                """
                select count(*)
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                where ls.sense_key = 'legacy-zorbla-sense'
                """
            ).fetchone()[0]
            document_count = conn.execute(
                """
                select count(*)
                from warehouse.source_document d
                join warehouse.source_file f on f.id = d.source_file_id
                where f.local_path = %s
                """
            ,
                (input_path_str,),
            ).fetchone()[0]

        self.assertEqual(example_row[0], "Legacy zorbla juoksee.")
        self.assertEqual(example_row[1], "Legacy zorbla runs.")
        self.assertEqual(example_row[2], "tatoeba")
        self.assertAlmostEqual(float(example_row[3]), 0.95, places=5)
        self.assertEqual(sense_example_count, 1)
        self.assertEqual(document_count, 1)

    def test_tatoeba_loader_rejects_empty_input_without_deleting_existing_examples(self):
        unique_text = f"zzempty-tatoeba-{uuid4().hex}"
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                ("zzempty-tatoeba", "zzempty-tatoeba", "noun"),
            ).fetchone()[0]
            sense_id = conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, sort_order)
                values (%s, 'sense-1', 'an empty input sentinel', 1)
                returning id
                """,
                (lexeme_id,),
            ).fetchone()[0]
            example_id = conn.execute(
                """
                insert into lexicon.example (text_fi, text_en, source_label, quality_score)
                values (%s, 'sentinel example', 'tatoeba', 0.95)
                returning id
                """,
                (unique_text,),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.sense_example (sense_id, example_id, is_core, sort_order)
                values (%s, %s, true, 1)
                """,
                (sense_id, example_id),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "empty-tatoeba.tsv"
            input_path.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no valid Finnish entries"):
                main(["ingest-tatoeba", "--input", str(input_path)])

        with psycopg.connect(get_test_database_url()) as conn:
            existing_count = conn.execute(
                "select count(*) from lexicon.example where id = %s",
                (example_id,),
            ).fetchone()[0]
            conn.execute("delete from lexicon.sense_example where example_id = %s", (example_id,))
            conn.execute("delete from lexicon.example where id = %s", (example_id,))
            conn.execute("delete from lexicon.lexeme_sense where id = %s", (sense_id,))
            conn.execute("delete from lexicon.lexeme where id = %s", (lexeme_id,))

        self.assertEqual(existing_count, 1)

    def test_tatoeba_loader_keeps_direct_chinese_translation_from_legacy_tsv(self):
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                on conflict (lemma, part_of_speech) do update
                set display_lemma = excluded.display_lemma
                returning id
                """,
                ("legacy-zh-zorbla", "legacy-zh-zorbla", "noun"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                on conflict (lexeme_id, sense_key) do nothing
                """,
                (lexeme_id, "legacy-zh-zorbla-sense", "legacy zh zorbla", 1),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "tatoeba.tsv"
            input_path.write_text(
                "legacy-zh-zorbla-sense\tLegacy zh zorbla juoksee.\tLegacy zh zorbla runs.\t0.95\t他跑得很快。\n"
            )

            exit_code = main(["ingest-tatoeba", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            translation_row = conn.execute(
                """
                select zet.text_zh, zet.generation_method
                from zh_layer.zh_example_translation zet
                join lexicon.example e on e.id = zet.example_id
                where e.text_fi = 'Legacy zh zorbla juoksee.'
                """
            ).fetchone()

        self.assertEqual(translation_row, ("他跑得很快。", "tatoeba-direct-zh"))

    def test_tatoeba_loader_drops_non_standard_direct_chinese_translation(self):
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                ("legacy-dialect-zorbla", "legacy-dialect-zorbla", "noun"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                """,
                (lexeme_id, "legacy-dialect-zorbla-sense", "legacy dialect zorbla", 1),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "tatoeba.tsv"
            input_path.write_text(
                "legacy-dialect-zorbla-sense\tLegacy dialect zorbla juoksee.\tLegacy dialect zorbla runs.\t0.95\t侬欢喜吃点啥？\n"
            )

            exit_code = main(["ingest-tatoeba", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            translation_count = conn.execute(
                """
                select count(*)
                from zh_layer.zh_example_translation zet
                join lexicon.example e on e.id = zet.example_id
                where e.text_fi = 'Legacy dialect zorbla juoksee.'
                """
            ).fetchone()[0]
            staged_text = conn.execute(
                """
                select d.payload->>'text_zh'
                from warehouse.source_document d
                join warehouse.source_file f on f.id = d.source_file_id
                where f.local_path = %s
                """,
                (str(input_path),),
            ).fetchone()[0]

        self.assertEqual(translation_count, 0)
        self.assertEqual(staged_text, "侬欢喜吃点啥？")

    def test_tatoeba_loader_supports_real_detailed_rows_and_keeps_only_linked_examples(self):
        with psycopg.connect(get_test_database_url()) as conn:
            single_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                on conflict (lemma, part_of_speech) do update
                set display_lemma = excluded.display_lemma
                returning id
                """,
                ("zorbla", "zorbla", "noun"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                on conflict do nothing
                """,
                (single_lexeme_id, "Zorblaa", "zorblaa", "manual"),
            )
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                on conflict (lexeme_id, sense_key) do nothing
                """,
                (single_lexeme_id, "zorbla-sense", "zorbla", 1),
            )

            multi_lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                on conflict (lemma, part_of_speech) do update
                set display_lemma = excluded.display_lemma
                returning id
                """,
                ("monila", "monila", "noun"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                on conflict do nothing
                """,
                (multi_lexeme_id, "Monilaa", "monilaa", "manual"),
            )
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s), (%s, %s, %s, '{}', %s)
                on conflict (lexeme_id, sense_key) do nothing
                """,
                (
                    multi_lexeme_id,
                    "monila-sense-1",
                    "monila one",
                    1,
                    multi_lexeme_id,
                    "monila-sense-2",
                    "monila two",
                    2,
                ),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "fin_sentences_detailed.tsv"
            input_path.write_text(
                "\n".join(
                    [
                        "900001\tfin\tZorblaa nopeasti.\ttester\t2026-05-01 00:00:00\t2026-05-01 00:00:00",
                        "900002\tfin\tMonilaa hitaasti.\ttester\t2026-05-01 00:00:00\t2026-05-01 00:00:00",
                    ]
                )
                + "\n"
            )
            input_path_str = str(input_path)

            exit_code = main(["ingest-tatoeba", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            example_count = conn.execute(
                "select count(*) from lexicon.example where source_label = 'tatoeba'"
            ).fetchone()[0]
            single_sense_example_count = conn.execute(
                """
                select count(*)
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                where ls.sense_key = 'zorbla-sense'
                """
            ).fetchone()[0]
            multi_sense_example_count = conn.execute(
                """
                select count(*)
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                where ls.sense_key in ('monila-sense-1', 'monila-sense-2')
                """
            ).fetchone()[0]
            document_count = conn.execute(
                """
                select count(*)
                from warehouse.source_document d
                join warehouse.source_file f on f.id = d.source_file_id
                where f.local_path = %s
                """
            ,
                (input_path_str,),
            ).fetchone()[0]

        self.assertEqual(example_count, 1)
        self.assertEqual(single_sense_example_count, 1)
        self.assertEqual(multi_sense_example_count, 0)
        self.assertEqual(document_count, 2)

    def test_tatoeba_loader_uses_companion_links_and_sentences_for_chinese_translations(self):
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                on conflict (lemma, part_of_speech) do update
                set display_lemma = excluded.display_lemma
                returning id
                """,
                ("zorbla", "zorbla", "noun"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                on conflict do nothing
                """,
                (lexeme_id, "Zorblaa", "zorblaa", "manual"),
            )
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                on conflict (lexeme_id, sense_key) do nothing
                """,
                (lexeme_id, "zorbla-sense", "zorbla", 1),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "fin_sentences_detailed.tsv"
            input_path.write_text("900001\tfin\tZorblaa nopeasti.\ttester\t2026-05-01 00:00:00\t2026-05-01 00:00:00\n")
            (Path(temp_dir) / "links.csv").write_text("900001\t800001\n")
            (Path(temp_dir) / "sentences.csv").write_text("800001\tcmn\t佐布拉快速地跑。\n")

            exit_code = main(["ingest-tatoeba", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            translation_row = conn.execute(
                """
                select zet.text_zh, zet.generation_method
                from zh_layer.zh_example_translation zet
                join lexicon.example e on e.id = zet.example_id
                where e.text_fi = 'Zorblaa nopeasti.'
                """
            ).fetchone()

        self.assertEqual(translation_row[0], "佐布拉快速地跑。")
        self.assertEqual(translation_row[1], "tatoeba-direct-zh")

    def test_tatoeba_loader_uses_two_hop_companion_links_for_chinese_translations(self):
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                on conflict (lemma, part_of_speech) do update
                set display_lemma = excluded.display_lemma
                returning id
                """,
                ("zorbla", "zorbla", "noun"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                on conflict do nothing
                """,
                (lexeme_id, "Zorblaa", "zorblaa", "manual"),
            )
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                on conflict (lexeme_id, sense_key) do nothing
                """,
                (lexeme_id, "zorbla-sense", "zorbla", 1),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "fin_sentences_detailed.tsv"
            input_path.write_text("900004\tfin\tZorblaa nopeasti.\ttester\t2026-05-01 00:00:00\t2026-05-01 00:00:00\n")
            (Path(temp_dir) / "links.csv").write_text("900004\t800004\n800004\t700004\n")
            (Path(temp_dir) / "sentences.csv").write_text(
                "\n".join(
                    [
                        "800004\teng\tZorbla runs quickly.",
                        "700004\tcmn\t佐布拉跑得很快。",
                    ]
                )
                + "\n"
            )

            exit_code = main(["ingest-tatoeba", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            translation_row = conn.execute(
                """
                select zet.text_zh, zet.generation_method
                from zh_layer.zh_example_translation zet
                join lexicon.example e on e.id = zet.example_id
                where e.text_fi = 'Zorblaa nopeasti.'
                """
            ).fetchone()

        self.assertEqual(translation_row[0], "佐布拉跑得很快。")
        self.assertEqual(translation_row[1], "tatoeba-direct-zh")

    def test_tatoeba_loader_uses_companion_links_and_sentences_for_english_translations(self):
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                on conflict (lemma, part_of_speech) do update
                set display_lemma = excluded.display_lemma
                returning id
                """,
                ("zorbla", "zorbla", "noun"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                on conflict do nothing
                """,
                (lexeme_id, "Zorblaa", "zorblaa", "manual"),
            )
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values (%s, %s, %s, '{}', %s)
                on conflict (lexeme_id, sense_key) do nothing
                """,
                (lexeme_id, "zorbla-sense", "zorbla", 1),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "fin_sentences_detailed.tsv"
            input_path.write_text("900001\tfin\tZorblaa nopeasti.\ttester\t2026-05-01 00:00:00\t2026-05-01 00:00:00\n")
            (Path(temp_dir) / "links.csv").write_text("900001\t800002\n")
            (Path(temp_dir) / "sentences.csv").write_text("800002\teng\tZorbla runs quickly.\n")

            exit_code = main(["ingest-tatoeba", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            example_row = conn.execute(
                """
                select text_en
                from lexicon.example
                where text_fi = 'Zorblaa nopeasti.'
                """
            ).fetchone()
            warehouse_row = conn.execute(
                """
                select d.payload->>'text_en'
                from warehouse.source_document d
                join warehouse.source_file f on f.id = d.source_file_id
                join warehouse.source_registry r on r.id = f.source_registry_id
                where r.name = 'tatoeba'
                  and d.payload->>'text_fi' = 'Zorblaa nopeasti.'
                order by d.id desc
                limit 1
                """
            ).fetchone()

        self.assertEqual(example_row[0], "Zorbla runs quickly.")
        self.assertEqual(warehouse_row[0], "Zorbla runs quickly.")

    def test_tatoeba_loader_links_multi_sense_lexeme_when_english_companion_disambiguates(self):
        lemma_suffix = uuid4().hex[:8].translate(str.maketrans("0123456789", "abcdefghij"))
        lemma = f"zzrun{lemma_suffix}"
        surface_form = f"{lemma}n"
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                on conflict (lemma, part_of_speech) do update
                set display_lemma = excluded.display_lemma
                returning id
                """,
                (lemma, lemma, "verb"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                on conflict do nothing
                """,
                (lexeme_id, surface_form, surface_form, "manual"),
            )
            conn.execute(
                """
                insert into lexicon.form_analysis (normalized_query, lexeme_id, analysis_rank, confidence, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (surface_form, lexeme_id, 1, 1.0),
            )
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values
                    (%s, %s, %s, '{}', %s),
                    (%s, %s, %s, '{}', %s)
                on conflict (lexeme_id, sense_key) do nothing
                """,
                (
                    lexeme_id,
                    "juosta-sense-run",
                    "to run (move swiftly)",
                    1,
                    lexeme_id,
                    "juosta-sense-flow",
                    "to flow",
                    2,
                ),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "fin_sentences_detailed.tsv"
            input_path.write_text(
                f"900010\tfin\t{surface_form} nopeasti.\ttester\t2026-05-01 00:00:00\t2026-05-01 00:00:00\n"
            )
            (Path(temp_dir) / "links.csv").write_text("900010\t800010\n")
            (Path(temp_dir) / "sentences.csv").write_text("800010\teng\tI ran quickly.\n")

            exit_code = main(["ingest-tatoeba", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            run_count = conn.execute(
                """
                select count(*)
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                join lexicon.example e on e.id = se.example_id
                where ls.sense_key = 'juosta-sense-run'
                  and e.text_fi = %s
                """
            , (f"{surface_form} nopeasti.",)).fetchone()[0]
            flow_count = conn.execute(
                """
                select count(*)
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                join lexicon.example e on e.id = se.example_id
                where ls.sense_key = 'juosta-sense-flow'
                  and e.text_fi = %s
                """
            , (f"{surface_form} nopeasti.",)).fetchone()[0]

        self.assertEqual(run_count, 1)
        self.assertEqual(flow_count, 0)

    def test_tatoeba_loader_matches_progressive_english_companion_to_run_gloss(self):
        lemma_suffix = uuid4().hex[:8].translate(str.maketrans("0123456789", "abcdefghij"))
        lemma = f"zzrunprog{lemma_suffix}"
        surface_form = f"{lemma}n"
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (lemma, lemma, "verb"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (lexeme_id, surface_form, surface_form, "manual"),
            )
            conn.execute(
                """
                insert into lexicon.form_analysis (normalized_query, lexeme_id, analysis_rank, confidence, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (surface_form, lexeme_id, 1, 1.0),
            )
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values
                    (%s, %s, %s, '{}', %s),
                    (%s, %s, %s, '{}', %s)
                """,
                (
                    lexeme_id,
                    "zzrunprog-sense-run",
                    "to run",
                    1,
                    lexeme_id,
                    "zzrunprog-sense-flow",
                    "to flow",
                    2,
                ),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "fin_sentences_detailed.tsv"
            input_path.write_text(
                f"900011\tfin\t{surface_form} nopeasti.\ttester\t2026-05-01 00:00:00\t2026-05-01 00:00:00\n"
            )
            (Path(temp_dir) / "links.csv").write_text("900011\t800011\n")
            (Path(temp_dir) / "sentences.csv").write_text("800011\teng\tI am running quickly.\n")

            exit_code = main(["ingest-tatoeba", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            run_count = conn.execute(
                """
                select count(*)
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                join lexicon.example e on e.id = se.example_id
                where ls.sense_key = 'zzrunprog-sense-run'
                  and e.text_fi = %s
                """,
                (f"{surface_form} nopeasti.",),
            ).fetchone()[0]
            flow_count = conn.execute(
                """
                select count(*)
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                join lexicon.example e on e.id = se.example_id
                where ls.sense_key = 'zzrunprog-sense-flow'
                  and e.text_fi = %s
                """,
                (f"{surface_form} nopeasti.",),
            ).fetchone()[0]

        self.assertEqual(run_count, 1)
        self.assertEqual(flow_count, 0)

    def test_tatoeba_loader_matches_irregular_kept_to_keep_gloss(self):
        lemma_suffix = uuid4().hex[:8].translate(str.maketrans("0123456789", "abcdefghij"))
        lemma = f"zzkeep{lemma_suffix}"
        surface_form = f"{lemma}n"
        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_id = conn.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                returning id
                """,
                (lemma, lemma, "verb"),
            ).fetchone()[0]
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (lexeme_id, surface_form, surface_form, "manual"),
            )
            conn.execute(
                """
                insert into lexicon.form_analysis (normalized_query, lexeme_id, analysis_rank, confidence, features)
                values (%s, %s, %s, %s, '{}'::jsonb)
                """,
                (surface_form, lexeme_id, 1, 1.0),
            )
            conn.execute(
                """
                insert into lexicon.lexeme_sense (lexeme_id, sense_key, gloss_en, labels, sort_order)
                values
                    (%s, %s, %s, '{}', %s),
                    (%s, %s, %s, '{}', %s)
                """,
                (
                    lexeme_id,
                    "zzkeep-sense-keep",
                    "to keep",
                    1,
                    lexeme_id,
                    "zzkeep-sense-spend",
                    "to spend",
                    2,
                ),
            )
            conn.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "fin_sentences_detailed.tsv"
            input_path.write_text(
                f"900012\tfin\t{surface_form} tämän turvassa.\ttester\t2026-05-01 00:00:00\t2026-05-01 00:00:00\n"
            )
            (Path(temp_dir) / "links.csv").write_text("900012\t800012\n")
            (Path(temp_dir) / "sentences.csv").write_text("800012\teng\tI kept this safe.\n")

            exit_code = main(["ingest-tatoeba", "--input", str(input_path)])

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            keep_count = conn.execute(
                """
                select count(*)
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                join lexicon.example e on e.id = se.example_id
                where ls.sense_key = 'zzkeep-sense-keep'
                  and e.text_fi = %s
                """,
                (f"{surface_form} tämän turvassa.",),
            ).fetchone()[0]
            spend_count = conn.execute(
                """
                select count(*)
                from lexicon.sense_example se
                join lexicon.lexeme_sense ls on ls.id = se.sense_id
                join lexicon.example e on e.id = se.example_id
                where ls.sense_key = 'zzkeep-sense-spend'
                  and e.text_fi = %s
                """,
                (f"{surface_form} tämän turvassa.",),
            ).fetchone()[0]

        self.assertEqual(keep_count, 1)
        self.assertEqual(spend_count, 0)
