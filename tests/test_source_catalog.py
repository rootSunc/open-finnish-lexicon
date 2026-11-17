import unittest
from pathlib import Path

from open_finnish_lexicon.sources.catalog import load_source_catalog


class SourceCatalogTests(unittest.TestCase):
    def test_load_source_catalog_reads_pinned_sources(self):
        catalog = load_source_catalog(Path("tests/fixtures/releases/test_source_releases.toml"))

        self.assertEqual(catalog["omorfi"].version, "fixture-1")
        self.assertEqual(catalog["kaikki"].archive_kind, "gz")
        self.assertEqual(catalog["frequency"].source_kind, "csv")
        self.assertEqual(catalog["wiktionary_zh"].members, ("wiktionary-zh-fixture.jsonl",))
        self.assertEqual(catalog["dbnary_zh"].companions[0].name, "enhancement")
