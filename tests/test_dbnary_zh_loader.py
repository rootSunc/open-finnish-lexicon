import tempfile
import unittest
from pathlib import Path

from open_finnish_lexicon.sources.dbnary_zh_loader import read_dbnary_zh_candidates
from open_finnish_lexicon.sources.dbnary_zh_stage import _normalized_gloss_variants


class DbnaryZhLoaderTests(unittest.TestCase):
    def test_normalized_gloss_variants_match_one_entry_from_a_joined_gloss(self):
        self.assertEqual(
            _normalized_gloss_variants("to run; move quickly"),
            {"to run", "move quickly", "to run move quickly"},
        )

    def test_normalized_gloss_variants_preserve_finnish_words_after_removing_accents(self):
        self.assertEqual(
            _normalized_gloss_variants("pää; sää"),
            {"paa", "saa", "paa saa"},
        )
        self.assertNotEqual(_normalized_gloss_variants("pää"), _normalized_gloss_variants("p"))

    def test_read_dbnary_zh_candidates_extracts_finnish_english_gloss_and_chinese_terms(self):
        rows = list(
            read_dbnary_zh_candidates(
                Path("tests/fixtures/dbnary-zh-exolex.ttl"),
                Path("tests/fixtures/dbnary-zh-enhancement.ttl"),
            )
        )

        self.assertEqual(rows[0]["lemma"], "juosta")
        self.assertEqual(rows[0]["part_of_speech"], "verb")
        self.assertEqual(rows[0]["gloss_en"], "to run")
        self.assertEqual(rows[0]["zh_terms"], ["跑步"])

    def test_read_dbnary_zh_candidates_supports_current_finnish_dbnary_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            core_path = Path(temp_dir) / "fi_dbnary_ontolex.ttl"
            enhancement_path = Path(temp_dir) / "fi_dbnary_enhancement.ttl"
            core_path.write_text(
                """
@prefix ontolex: <http://www.w3.org/ns/lemon/ontolex#> .
@prefix lexinfo: <http://www.lexinfo.net/ontology/3.0/lexinfo#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix dbnary: <http://kaiko.getalp.org/dbnary#> .
@prefix lexvo: <http://lexvo.org/id/iso639-3/> .
@prefix fin: <https://example.test/dbnary/fin/> .

fin:kala__Substantiivi__1
  rdf:type ontolex:LexicalEntry ;
  dcterms:language lexvo:fin ;
  lexinfo:partOfSpeech lexinfo:noun ;
  ontolex:canonicalForm fin:__cf_kala__Substantiivi__1 ;
  ontolex:sense fin:__ws_1_kala__Substantiivi__1 .

fin:__cf_kala__Substantiivi__1
  rdf:type ontolex:Form ;
  ontolex:writtenRep "kala"@fi .

fin:__ws_1_kala__Substantiivi__1
  rdf:type ontolex:LexicalSense ;
  skos:definition [ rdf:value "vedessä elävä selkärankainen eläin"@fi ] .

fin:__tr_cmn_1_kala__Substantiivi__1
  rdf:type dbnary:Translation ;
  dbnary:isTranslationOf fin:kala__Substantiivi__1 ;
  dbnary:targetLanguage lexvo:cmn ;
  dbnary:writtenForm "鱼"@cmn .
""".strip()
            )
            enhancement_path.write_text(
                """
@prefix dbnary: <http://kaiko.getalp.org/dbnary#> .
@prefix fin: <https://example.test/dbnary/fin/> .

fin:__tr_cmn_1_kala__Substantiivi__1
  dbnary:isTranslationOf fin:__ws_1_kala__Substantiivi__1 .
""".strip()
            )

            rows = list(read_dbnary_zh_candidates(core_path, enhancement_path))

        self.assertEqual(rows[0]["lemma"], "kala")
        self.assertEqual(rows[0]["part_of_speech"], "noun")
        self.assertIsNone(rows[0]["gloss_en"])
        self.assertEqual(rows[0]["gloss_fi"], "vedessä elävä selkärankainen eläin")
        self.assertEqual(rows[0]["sense_index"], 0)
        self.assertEqual(rows[0]["zh_terms"], ["鱼"])
