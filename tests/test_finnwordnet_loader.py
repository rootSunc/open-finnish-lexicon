import unittest
import tempfile
from pathlib import Path

import psycopg

from open_finnish_lexicon.cli import main
from open_finnish_lexicon.sources.finnwordnet_loader import iter_finnwordnet_relations
from support import get_test_database_url


class FinnWordNetLoaderTests(unittest.TestCase):
    def test_plain_finnwordnet_rows_normalize_part_of_speech(self):
        rows = list(
            iter_finnwordnet_relations(Path("tests/fixtures/finnwordnet.tsv"))
        )

        self.assertTrue(rows)
        self.assertEqual({row.source_pos for row in rows}, {"verb"})
        self.assertEqual({row.target_pos for row in rows}, {"verb"})

    def test_finnwordnet_loader_supports_real_rels_directory(self):
        self.assertEqual(
            main(["ingest-omorfi", "--input", "tests/fixtures/omorfi.tsv"]), 0
        )

        exit_code = main(
            ["ingest-finnwordnet", "--input", "tests/fixtures/finnwordnet-rels"]
        )

        self.assertEqual(exit_code, 0)

        with psycopg.connect(get_test_database_url()) as conn:
            relation_rows = conn.execute(
                """
                select source.display_lemma, rel.relation_type, target.display_lemma
                from lexicon.lexical_relation rel
                join lexicon.lexeme source on source.id = rel.source_lexeme_id
                join lexicon.lexeme target on target.id = rel.target_lexeme_id
                where source.display_lemma in ('juosta', 'pinkoa', 'nopea')
                order by source.display_lemma, rel.relation_type, target.display_lemma
                """
            ).fetchall()
            document_count = conn.execute(
                """
                select count(*)
                from warehouse.source_document
                where external_id like 'finnwordnet:%%'
                """
            ).fetchone()[0]

        self.assertIn(("juosta", "synonym", "pinkoa"), relation_rows)
        self.assertIn(("juosta", "synonym", "kirmata"), relation_rows)
        self.assertIn(("juosta", "verb group", "kävellä"), relation_rows)
        self.assertIn(("nopea", "antonym", "hidas"), relation_rows)
        self.assertGreaterEqual(document_count, 9)

    def test_finnwordnet_loader_removes_relations_missing_from_a_later_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir)
            wsenses_path = input_dir / "fiwn-wsenses.tsv"
            lexrels_path = input_dir / "fiwn-lexrels.tsv"
            wsenses_path.write_text(
                "fi:v00000001\tzzfwnrun\t0\n"
                "fi:v00000001\tzzfwnjog\t0\n",
                encoding="utf-8",
            )
            lexrels_path.write_text(
                "fi:v00000001\tzzfwnrun\tfi:v00000002\tzzfwnwalk\t$\tverb group\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-finnwordnet", "--input", str(input_dir)]), 0)

            wsenses_path.write_text("fi:v00000003\tzzfwnunrelated\t0\n", encoding="utf-8")
            lexrels_path.write_text("", encoding="utf-8")
            self.assertEqual(main(["ingest-finnwordnet", "--input", str(input_dir)]), 0)

            with psycopg.connect(get_test_database_url()) as conn:
                relation_count = conn.execute(
                    """
                    select count(*)
                    from lexicon.lexical_relation rel
                    join lexicon.lexeme source on source.id = rel.source_lexeme_id
                    join lexicon.lexeme target on target.id = rel.target_lexeme_id
                    where source.lemma = any(%s) or target.lemma = any(%s)
                    """,
                    (
                        ["zzfwnrun", "zzfwnjog", "zzfwnwalk"],
                        ["zzfwnrun", "zzfwnjog", "zzfwnwalk"],
                    ),
                ).fetchone()[0]
                ownership_count = conn.execute(
                    """
                    select count(*)
                    from lexicon.lexical_relation_source rls
                    join warehouse.source_file sf on sf.id = rls.source_file_id
                    join warehouse.source_registry sr on sr.id = sf.source_registry_id
                    where sr.name = 'finnwordnet' and sf.local_path = %s
                    """,
                    (str(input_dir),),
                ).fetchone()[0]
                self.assertEqual(relation_count, 0)
                self.assertEqual(ownership_count, 0)
                lexeme_ids = [
                    row[0]
                    for row in conn.execute(
                        "select id from lexicon.lexeme where lemma = any(%s)",
                        (["zzfwnrun", "zzfwnjog", "zzfwnwalk"],),
                    ).fetchall()
                ]
                if lexeme_ids:
                    conn.execute(
                        "delete from lexicon.lexical_relation where source_lexeme_id = any(%s) or target_lexeme_id = any(%s)",
                        (lexeme_ids, lexeme_ids),
                    )
                    conn.execute("delete from lexicon.lexeme where id = any(%s)", (lexeme_ids,))
