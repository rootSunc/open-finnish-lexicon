import unittest
import tempfile
from pathlib import Path

from open_finnish_lexicon.sources.wiktionary_zh_loader import read_wiktionary_zh_entries


class WiktionaryZhLoaderTests(unittest.TestCase):
    def test_read_wiktionary_zh_entries_skips_malformed_rows_and_gloss_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "wiktionary-zh-malformed.jsonl"
            input_path.write_text(
                "not-json\n"
                "[]\n"
                '{"lang_code":"fi","word":"bad-senses","pos":"noun","senses":"bad"}\n'
                '{"lang_code":"fi","word":"bad-glosses","pos":"noun","senses":[{"glosses":"abc"}]}\n'
                '{"lang_code":"fi","word":"good","pos":"NOUN","senses":[null,{"glosses":["  书  ",1,""]}]}\n',
                encoding="utf-8",
            )

            rows = list(read_wiktionary_zh_entries(input_path))

        self.assertEqual(
            rows,
            [
                {
                    "lemma": "good",
                    "part_of_speech": "noun",
                    "sense_glosses": [["书"]],
                    "external_id": "wiktionary_zh:good:noun",
                }
            ],
        )

    def test_read_wiktionary_zh_entries_keeps_finnish_gloss_order(self):
        rows = list(
            read_wiktionary_zh_entries(
                Path("tests/fixtures/wiktionary-zh-fixture.jsonl")
            )
        )

        self.assertEqual(rows[0]["lemma"], "juosta")
        self.assertEqual(rows[0]["part_of_speech"], "verb")
        self.assertEqual(rows[0]["sense_glosses"], [["跑", "奔跑"], ["流动"]])
