import unittest

import psycopg

from open_finnish_lexicon.cli import main
from support import get_test_database_url


class SemanticSourceTests(unittest.TestCase):
    def test_semantic_sources_populate_relations_examples_frequency_and_chinese_gloss_sources(self):
        self.assertEqual(main(["ingest-omorfi", "--input", "tests/fixtures/omorfi.tsv"]), 0)
        self.assertEqual(main(["ingest-kaikki", "--input", "tests/fixtures/kaikki-juosta.jsonl"]), 0)
        self.assertEqual(main(["ingest-finnwordnet", "--input", "tests/fixtures/finnwordnet.tsv"]), 0)
        self.assertEqual(main(["ingest-tatoeba", "--input", "tests/fixtures/tatoeba.tsv"]), 0)
        self.assertEqual(main(["ingest-frequency", "--input", "tests/fixtures/frequency.csv"]), 0)
        self.assertEqual(
            main(["ingest-wiktionary-zh", "--input", "tests/fixtures/wiktionary-zh-fixture.jsonl"]),
            0,
        )
        self.assertEqual(
            main(["ingest-dbnary-zh", "--input", "tests/fixtures/dbnary-zh-exolex.ttl"]),
            0,
        )

        with psycopg.connect(get_test_database_url()) as conn:
            relation_count = conn.execute("select count(*) from lexicon.lexical_relation").fetchone()[0]
            example_count = conn.execute("select count(*) from lexicon.example").fetchone()[0]
            frequency_count = conn.execute("select count(*) from lexicon.frequency_signal").fetchone()[0]
            zh_candidate_count = conn.execute("select count(*) from semantic.zh_gloss_candidate").fetchone()[0]

        self.assertGreaterEqual(relation_count, 1)
        self.assertGreaterEqual(example_count, 1)
        self.assertGreaterEqual(frequency_count, 1)
        self.assertGreaterEqual(zh_candidate_count, 2)
