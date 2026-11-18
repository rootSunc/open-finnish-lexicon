"""Regression tests for data-quality, Chinese-layer, and provenance optimizations."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import psycopg
import pytest

from open_finnish_lexicon.cli import main
from open_finnish_lexicon.morphology.rules import Verdict, validate_form
from open_finnish_lexicon.normalize.collocations import rebuild_collocations
from open_finnish_lexicon.sources.cedict_zh_loader import read_cedict_zh_entries
from open_finnish_lexicon.sources.finnwordnet_project import project_finnwordnet_rows
from open_finnish_lexicon.sources.finnwordnet_stage import stage_finnwordnet_rows
from open_finnish_lexicon.sources.kaikki_loader import (
    compact_kaikki_entry,
    syllabify_finnish_word,
)
from open_finnish_lexicon.sources.omw_zh_loader import (
    normalize_wn30_synset_key,
    read_omw_zh_entries,
)
from open_finnish_lexicon.zh_script import (
    normalize_and_validate_zh_gloss,
    normalize_and_validate_zh_sentence,
    simplified_chinese_text_issue,
    to_simplified_chinese,
)
from support import get_test_database_url
from test_end_to_end import DATA_TABLES


class PurePythonOptimizationTests(unittest.TestCase):
    def test_opencc_converts_traditional_chinese_and_keeps_proper_nouns_and_units(self):
        self.assertEqual(to_simplified_chinese("跑步；運動"), "跑步；运动")
        self.assertEqual(
            normalize_and_validate_zh_sentence(
                "汤姆在 Helsinki 测试 pH 和 mRNA（100 km/h）。"
            ),
            "汤姆在 Helsinki 测试 pH 和 mRNA（100 km/h）。",
        )
        self.assertEqual(
            normalize_and_validate_zh_gloss("電腦軟體與網路"),
            "电脑软体与网路",
        )
        # Untranslated lowercase English phrases are still rejected.
        self.assertIsNotNone(simplified_chinese_text_issue("to run quickly 跑"))

    def test_kaikki_syllabification_relations_multisound_and_apostrophe_possessives(self):
        self.assertEqual(syllabify_finnish_word("juosta"), "juos·ta")
        self.assertEqual(syllabify_finnish_word("auto-onnettomuus"), "au·to-on·net·to·muus")

        compact = compact_kaikki_entry(
            {
                "word": "aa'a",
                "lang": "Finnish",
                "pos": "noun",
                "sounds": [
                    {"ipa": "/ˈɑːʔɑ/"},
                    {"ipa": "[ˈɑːʔɑ]"},
                ],
                "synonyms": [{"word": "huudahdus"}],
                "forms": [
                    {"form": "aa'a", "source": "declension", "tags": ["nominative", "singular"]},
                    {"form": "aa'aa", "source": "declension", "tags": ["partitive", "singular"]},
                    {"form": "aa’aaan", "source": "declension", "tags": ["partitive", "singular"]},
                    {"form": "aa’aani", "source": "declension", "tags": ["nominative", "singular"]},
                    {"form": "aa’aasi", "source": "declension", "tags": ["nominative", "singular"]},
                    {"form": "aa’aamme", "source": "declension", "tags": ["nominative", "singular"]},
                ],
                "senses": [{"id": "s1", "glosses": ["interjection"], "antonyms": [{"word": "hiljaisuus"}]}],
            }
        )
        self.assertEqual(compact["syllabification"], "aa'a") if "syllabification" in compact else None
        self.assertEqual(compact["sounds"], [{"ipa": "/ˈɑːʔɑ/"}, {"ipa": "[ˈɑːʔɑ]"}])
        self.assertEqual(
            compact["relations"],
            [{"word": "huudahdus", "type": "synonym"}, {"word": "hiljaisuus", "type": "antonym"}],
        )
        kept_surfaces = [item["form"] for item in compact["forms"]]
        self.assertEqual(kept_surfaces, ["aa'a", "aa'aa"])

    def test_verb_kotus_variant_and_reverse_gradation_verdicts(self):
        cases = [
            ("kirota", "kiroisin", {"mood": "conditional", "person": "1", "number": "singular", "source_class": "no gradation | 74/katketa"}, Verdict.VERIFIED),
            ("kuutioida", "kuutioitsin", {"mood": "indicative", "tense": "past", "person": "1", "number": "singular", "source_class": "no gradation | 68/tupakoida"}, Verdict.VERIFIED),
            ("kuutioida", "kuutioitsisin", {"mood": "conditional", "person": "1", "number": "singular", "source_class": "no gradation | 68/tupakoida"}, Verdict.VERIFIED),
            ("parata", "paranen", {"mood": "indicative", "tense": "present", "person": "1", "number": "singular", "source_class": "no gradation | 72/vanheta"}, Verdict.VERIFIED),
            ("karata", "karkaan", {"mood": "indicative", "tense": "present", "person": "1", "number": "singular", "source_class": "k–∅ gradation | 73*D/salata"}, Verdict.VERIFIED),
            ("tarjeta", "tarkenen", {"mood": "indicative", "tense": "present", "person": "1", "number": "singular", "source_class": "k–j gradation | 72*L/vanheta"}, Verdict.VERIFIED),
            ("siitä", "sikiän", {"mood": "indicative", "tense": "present", "person": "1", "number": "singular", "source_class": "k–∅ gradation | 75*D/selvitä"}, Verdict.VERIFIED),
            ("syöstä", "syöksen", {"mood": "indicative", "tense": "present", "person": "1", "number": "singular", "source_class": "no gradation | 70/juosta"}, Verdict.VERIFIED),
            ("seistä", "seison", {"mood": "indicative", "tense": "present", "person": "1", "number": "singular", "source_class": "no gradation | 66/rohkaista and 52/sanoa"}, Verdict.UNCERTAIN),
        ]
        for lemma, surface, features, expected in cases:
            with self.subTest(lemma=lemma, surface=surface):
                res = validate_form(
                    lemma=lemma,
                    part_of_speech="verb",
                    surface_form=surface,
                    features=features,
                )
                self.assertEqual(res.verdict, expected, msg=res.explanation)

    def test_omw_and_cedict_loaders_filter_surnames_and_normalize_synsets(self):
        self.assertEqual(normalize_wn30_synset_key("fi:s00003553"), ("00003553-a", "adj"))
        self.assertEqual(normalize_wn30_synset_key("00003553-s"), ("00003553-a", "adj"))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            omw_file = root / "omw.tab"
            omw_file.write_text(
                "# OMW test\n"
                "00003553-s\tcmn:lemma\t新興\n"
                "02084071-n\tcmn:lemma\t狗\n",
                encoding="utf-8",
            )
            omw_rows = {row["synset_id"]: row["gloss_zh"] for row in read_omw_zh_entries(omw_file)}
            self.assertEqual(omw_rows, {"00003553-a": "新兴", "02084071-n": "狗"})

            cedict_file = root / "cedict.txt"
            cedict_file.write_text(
                "宋 宋 [Song4] /Song dynasty/surname Song/\n"
                "梅 梅 [Mei2] /surname Mei/\n"
                "芬蘭 芬兰 [Fen1 lan2] /Finland/\n"
                "僅僅 仅仅 [jin3 jin3] /only; merely; barely/\n",
                encoding="utf-8",
            )
            cedict_rows = {
                (row["en_key"], row["is_verb"]): row["gloss_zh"]
                for row in read_cedict_zh_entries(cedict_file)
            }
            self.assertNotIn(("song", False), cedict_rows)
            self.assertNotIn(("surname mei", False), cedict_rows)
            self.assertEqual(cedict_rows[("Finland", False)], "芬兰")
            self.assertEqual(cedict_rows[("merely", False)], "仅仅")


@pytest.mark.db
class DatabaseOptimizationIntegrationTests(unittest.TestCase):
    def setUp(self):
        with psycopg.connect(get_test_database_url()) as conn:
            conn.execute(f"truncate {DATA_TABLES} restart identity cascade")
            conn.commit()

    def test_form_of_isolation_chinese_rescue_semrels_and_collocation_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # 1. Kaikki: canonical multi-sense lemma ``juosta`` + pure form-of shell ``juoksen``
            #    + target noun ``hölkkä`` for lexical relations.
            kaikki_path = root / "kaikki.jsonl"
            kaikki_rows = [
                {
                    "word": "juosta",
                    "lang": "Finnish",
                    "pos": "verb",
                    "sounds": [{"ipa": "/ˈjuos.tɑ/"}, {"ipa": "[ˈjuo̯s̠.tɑ]"}],
                    "synonyms": [{"word": "hölkätä"}],
                    "forms": [
                        {
                            "form": "juoksen",
                            "source": "conjugation",
                            "tags": ["first-person", "indicative", "present", "singular"],
                        }
                    ],
                    "senses": [
                        {"id": "s1", "glosses": ["to run"]},
                        {"id": "s2", "glosses": ["to flow"]},
                    ],
                },
                {
                    "word": "juoksen",
                    "lang": "Finnish",
                    "pos": "verb",
                    "senses": [
                        {
                            "id": "f1",
                            "glosses": ["first-person singular present of juosta"],
                            "tags": ["form-of"],
                        }
                    ],
                },
                {
                    "word": "hölkätä",
                    "lang": "Finnish",
                    "pos": "verb",
                    "senses": [{"id": "h1", "glosses": ["to jog"]}],
                },
                {
                    "word": "liikkua",
                    "lang": "Finnish",
                    "pos": "verb",
                    "senses": [{"id": "l1", "glosses": ["to move"]}],
                },
            ]
            kaikki_path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in kaikki_rows) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-kaikki", "--input", str(kaikki_path)]), 0)

            # 2. Frequency: surface form ``juoksen`` appears with high count; it must aggregate
            #    onto canonical ``juosta`` (is_lemma=True) instead of ``juoksen`` (is_lemma=False).
            freq_path = root / "frequency.txt"
            freq_lines = ["juoksen 5000", "liikkua 1000"] + [
                f"sana{i} {500 - i}" for i in range(120)
            ]
            freq_path.write_text("\n".join(freq_lines) + "\n", encoding="utf-8")
            self.assertEqual(main(["ingest-frequency", "--input", str(freq_path)]), 0)

            # 3. Tatoeba: 3 sentences sharing phrase ``juoksen joka aamu`` + Traditional Chinese
            #    translation + author username + 1 invalid untranslated sentence.
            tatoeba_dir = root / "tatoeba"
            tatoeba_dir.mkdir()
            fin_tsv = tatoeba_dir / "fin_sentences_detailed.tsv"
            fin_tsv.write_text(
                "101\tfin\tVarhain juoksen nopeasti.\talice\t2024-01-01\t2024-01-01\n"
                "102\tfin\tIllalla juoksen nopeasti.\tbob\t2024-01-01\t2024-01-01\n"
                "103\tfin\tUlkona juoksen nopeasti.\tcarol\t2024-01-01\t2024-01-01\n",
                encoding="utf-8",
            )
            (tatoeba_dir / "links.csv").write_text(
                "101\t201\n101\t301\n102\t201\n103\t201\n",
                encoding="utf-8",
            )
            (tatoeba_dir / "eng_sentences_detailed.tsv").write_text(
                "201\teng\tI run every morning.\tdave\t2024-01-01\t2024-01-01\n",
                encoding="utf-8",
            )
            (tatoeba_dir / "cmn_sentences_detailed.tsv").write_text(
                "301\tcmn\t我每天早上跑步運動。\teve\t2024-01-01\t2024-01-01\n"
                "302\tcmn\tuntranslated english sentence only\tfrank\t2024-01-01\t2024-01-01\n",
                encoding="utf-8",
            )
            self.assertEqual(
                main(["ingest-tatoeba", "--input", str(fin_tsv)]),
                0,
            )

            # 4. FinnWordNet: directory with fiwn-wsenses.tsv + fiwn-semrels.tsv
            #    including an unknown shell word ``tuntematon_haamu`` that must NOT create a shell
            #    when only_existing_lexemes=True.
            fiwn_dir = root / "fiwn"
            fiwn_dir.mkdir()
            (fiwn_dir / "fiwn-wsenses.tsv").write_text(
                "fi:v:001\tjuosta\n"
                "fi:v:001\ttuntematon_haamu\n"
                "fi:v:002\tliikkua\n",
                encoding="utf-8",
            )
            (fiwn_dir / "fiwn-semrels.tsv").write_text(
                "fi:v:001\tfi:v:002\t@\thypernym\n"
                "fi:v:001\tfi:v:002\t#p\tpart holonym\n",
                encoding="utf-8",
            )
            sf_id = stage_finnwordnet_rows(
                fiwn_dir,
                version="test-fiwn",
                source_url=str(fiwn_dir),
            )
            project_finnwordnet_rows(
                fiwn_dir,
                source_file_id=sf_id,
                only_existing_lexemes=True,
            )

            # 5. Chinese Wiktionary (Traditional Chinese, 1 sense vs local 2 senses!)
            #    + DBnary ZH (single-sense fallback on ``hölkätä``).
            wikt_zh_path = root / "wikt_zh.jsonl"
            wikt_zh_path.write_text(
                json.dumps(
                    {
                        "word": "juosta",
                        "lang": "芬兰语",
                        "lang_code": "fi",
                        "pos": "verb",
                        "senses": [{"id": "zh-juosta-1", "glosses": ["奔跑；運動"]}],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-wiktionary-zh", "--input", str(wikt_zh_path)]), 0)

            dbnary_path = root / "dbnary_zh.ttl"
            dbnary_path.write_text(
                "@prefix ontolex: <http://www.w3.org/ns/lemon/ontolex#> .\n"
                "@prefix lexinfo: <http://www.lexinfo.net/ontology/3.0/lexinfo#> .\n"
                "@prefix dct: <http://purl.org/dc/terms/> .\n"
                "@prefix ex: <https://example.test/dbnary/> .\n\n"
                "ex:holkata-entry a ontolex:LexicalEntry ;\n"
                '  dct:language "fi" ;\n'
                "  lexinfo:partOfSpeech lexinfo:verb ;\n"
                "  ontolex:canonicalForm ex:holkata-form ;\n"
                "  ontolex:sense ex:holkata-sense-1 .\n"
                'ex:holkata-form ontolex:writtenRep "hölkätä"@fi .\n'
                "ex:holkata-sense-1 a ontolex:LexicalSense .\n",
                encoding="utf-8",
            )
            (root / "dbnary-zh-enhancement.ttl").write_text(
                "@prefix dbnary: <http://kaiko.getalp.org/dbnary#> .\n"
                "@prefix lexvo: <http://lexvo.org/id/iso639-3/> .\n"
                "@prefix ex: <https://example.test/dbnary/> .\n\n"
                "ex:tr-holkata dbnary:isTranslationOf ex:holkata-entry ;\n"
                "  dbnary:targetLanguage lexvo:cmn ;\n"
                '  dbnary:writtenForm "慢跑" .\n',
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-dbnary-zh", "--input", str(dbnary_path)]), 0)
            with psycopg.connect(get_test_database_url()) as conn:
                ex_id = conn.execute(
                    "select id from lexicon.example order by id limit 1"
                ).fetchone()[0]
                conn.execute(
                    """
                    insert into zh_layer.zh_example_translation (
                        example_id, text_zh, generation_method, generation_version
                    )
                    values (%s, 'untranslated english sentence only', 'tatoeba', 'test')
                    """,
                    (ex_id,),
                )
                conn.commit()
            self.assertEqual(main(["refresh"]), 0)

            # Rebuild collocations explicitly with min_examples=3 to verify repeated n-gram keeps
            # ``juoksen joka`` while dropping 1-occurrence prefixes ``minä juoksen``.
            rebuild_collocations(min_examples=3)

        with psycopg.connect(get_test_database_url()) as conn:
            lexeme_flags = {
                lemma: (is_lemma, freq_rank)
                for lemma, is_lemma, freq_rank in conn.execute(
                    "select lemma, is_lemma, frequency_rank from lexicon.lexeme order by lemma"
                ).fetchall()
            }
            # ``tuntematon_haamu`` was NOT inserted as an empty shell!
            self.assertNotIn("tuntematon_haamu", lexeme_flags)
            # ``juosta`` is a canonical lemma and received rank #1 from ``juoksen``!
            self.assertEqual(lexeme_flags["juosta"], (True, 1))
            # ``juoksen`` is marked is_lemma=False and has NO frequency rank!
            self.assertEqual(lexeme_flags["juoksen"], (False, None))

            # Examples attached to ``juosta``, ZERO attached to ``form-of`` ``juoksen``!
            attached_lemmas = {
                row[0]
                for row in conn.execute(
                    """
                    select l.lemma
                    from lexicon.sense_example se
                    join lexicon.lexeme_sense s on s.id = se.sense_id
                    join lexicon.lexeme l on l.id = s.lexeme_id
                    """
                ).fetchall()
            }
            self.assertIn("juosta", attached_lemmas)
            self.assertNotIn("juoksen", attached_lemmas)

            # Tatoeba attribution preserved
            attributions = {
                row[0]
                for row in conn.execute(
                    "select attribution from lexicon.example where attribution is not null"
                ).fetchall()
            }
            self.assertIn("Tatoeba (alice)", attributions)

            # Non-destructive zh_example_translation filtering + OpenCC conversion
            zh_ex_rows = conn.execute(
                "select text_zh, is_usable from zh_layer.zh_example_translation order by id"
            ).fetchall()
            self.assertEqual(len(zh_ex_rows), 2)
            self.assertIn(("我每天早上跑步运动。", True), zh_ex_rows)
            self.assertTrue(any(not usable for _txt, usable in zh_ex_rows))

            # Both wiktionary_zh (Traditional -> Simplified, 1-vs-2 sense alignment) and
            # dbnary_zh (single-sense fallback) produced materialized zh_gloss rows!
            zh_glosses = dict(
                conn.execute(
                    """
                    select l.lemma, zg.gloss_zh
                    from zh_layer.zh_gloss zg
                    join lexicon.lexeme_sense s on s.id = zg.sense_id
                    join lexicon.lexeme l on l.id = s.lexeme_id
                    """
                ).fetchall()
            )
            self.assertEqual(zh_glosses.get("juosta"), "奔跑；运动")
            self.assertEqual(zh_glosses.get("hölkätä"), "慢跑")

            # Syllabification and multi-pronunciation IPA populated on ``juosta``
            pron_rows = conn.execute(
                """
                select p.ipa, p.syllabification
                from lexicon.pronunciation p
                join lexicon.lexeme l on l.id = p.lexeme_id
                where l.lemma = 'juosta'
                order by p.ipa
                """
            ).fetchall()
            self.assertEqual(
                pron_rows,
                [("/ˈjuos.tɑ/", "juos·ta"), ("[ˈjuo̯s̠.tɑ]", "juos·ta")],
            )

            # FinnWordNet semrels hypernym/hyponym + Kaikki synonym populated
            rels = set(
                conn.execute(
                    """
                    select src.lemma, r.relation_type, tgt.lemma
                    from lexicon.lexical_relation r
                    join lexicon.lexeme src on src.id = r.source_lexeme_id
                    join lexicon.lexeme tgt on tgt.id = r.target_lexeme_id
                    """
                ).fetchall()
            )
            self.assertIn(("juosta", "hypernym", "liikkua"), rels)
            self.assertIn(("juosta", "part holonym", "liikkua"), rels)
            self.assertIn(("juosta", "synonym", "hölkätä"), rels)

            # Collocation noise filtering: 3-example phrase kept, 1-example phrase dropped
            phrases = {
                row[0]
                for row in conn.execute("select phrase from lexicon.collocation").fetchall()
            }
            self.assertTrue(any("juoksen nopeasti" in p for p in phrases))
            self.assertFalse(any("varhain juoksen" in p for p in phrases))

    def test_omw_synset_disambiguation_cedict_consensus_and_source_priority(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            kaikki_path = root / "kaikki.jsonl"
            kaikki_rows = [
                {
                    "word": "kuusi",
                    "lang": "Finnish",
                    "pos": "noun",
                    "senses": [
                        {"id": "k1", "glosses": ["spruce (tree)"]},
                        {"id": "k2", "glosses": ["six (the number)"]},
                    ],
                },
                {
                    "word": "vain",
                    "lang": "Finnish",
                    "pos": "adv",
                    "senses": [{"id": "v1", "glosses": ["only, merely, solely"]}],
                },
                {
                    "word": "ranta",
                    "lang": "Finnish",
                    "pos": "noun",
                    "senses": [{"id": "r1", "glosses": ["bank"]}],
                },
            ]
            kaikki_path.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kaikki_rows),
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-kaikki", "--input", str(kaikki_path)]), 0)

            fiwn_dir = root / "fiwn"
            fiwn_dir.mkdir()
            (fiwn_dir / "fiwn-wsenses.tsv").write_text(
                "fi:n11653599\tkuusi\t0\nfi:n13746575\tkuusi\t0\n",
                encoding="utf-8",
            )
            (fiwn_dir / "fiwn-transls.tsv").write_text(
                "fi:n11653599\tkuusi\ten-3.0:n11653599\tspruce\tsynonym\n"
                "fi:n13746575\tkuusi\ten-3.0:n13746575\tsix\tsynonym\n",
                encoding="utf-8",
            )
            (fiwn_dir / "fiwn-lexrels.tsv").write_text("", encoding="utf-8")
            (fiwn_dir / "fiwn-semrels.tsv").write_text("", encoding="utf-8")
            sf_id = stage_finnwordnet_rows(fiwn_dir, version="test", source_url="test")
            project_finnwordnet_rows(fiwn_dir, source_file_id=sf_id, only_existing_lexemes=True)
            with psycopg.connect(get_test_database_url()) as conn:
                conn.execute(
                    "update warehouse.source_file set snapshot_state = 'active' where id = %s",
                    (sf_id,),
                )
                conn.commit()

            omw_path = root / "omw.tab"
            omw_path.write_text(
                "11653599-n\tcmn:lemma\t云杉\n"
                "13746575-n\tcmn:lemma\t六\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-omw-zh", "--input", str(omw_path)]), 0)

            cedict_path = root / "cedict.txt"
            cedict_path.write_text(
                "僅僅 仅仅 [jin3 jin3] /only; merely; barely/\n"
                "只是 只是 [zhi3 shi4] /merely; simply; only/\n"
                "銀行 银行 [yin2 hang2] /bank/\n"
                "松樹 松树 [song1 shu4] /spruce/\n",
                encoding="utf-8",
            )
            self.assertEqual(main(["ingest-cedict-zh", "--input", str(cedict_path)]), 0)
            self.assertEqual(main(["refresh"]), 0)

        with psycopg.connect(get_test_database_url()) as conn:
            rows = {
                (lemma, sense_key): (gloss_zh, method)
                for lemma, sense_key, gloss_zh, method in conn.execute(
                    """
                    select l.lemma, s.sense_key, zg.gloss_zh, zg.generation_method
                    from zh_layer.zh_gloss zg
                    join lexicon.lexeme_sense s on s.id = zg.sense_id
                    join lexicon.lexeme l on l.id = s.lexeme_id
                    """
                ).fetchall()
            }
            # OMW synset bridge disambiguated both senses of ``kuusi`` AND beat cedict_zh!
            self.assertEqual(rows[("kuusi", "k1")], ("云杉", "omw_zh-rule"))
            self.assertEqual(rows[("kuusi", "k2")], ("六", "omw_zh-rule"))
            # CC-CEDICT multi-synonym consensus matched ``vain``!
            self.assertEqual(rows[("vain", "v1")], ("仅仅；只是", "cedict_zh-rule"))
            # Ambiguous single-word ``bank`` on ``ranta`` was safely blocked!
            self.assertNotIn(("ranta", "r1"), rows)
