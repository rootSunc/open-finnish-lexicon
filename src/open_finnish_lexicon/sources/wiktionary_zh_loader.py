import json
from collections.abc import Iterable
from pathlib import Path


def _normalize_pos(value: str) -> str:
    return value.strip().lower()


def read_wiktionary_zh_entries(input_path: Path) -> Iterable[dict]:
    with input_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get("lang_code") != "fi":
                continue
            word = entry.get("word")
            pos = entry.get("pos")
            if not isinstance(word, str) or not word.strip():
                continue
            if not isinstance(pos, str) or not pos.strip():
                continue
            sense_glosses = []
            senses = entry.get("senses")
            if not isinstance(senses, list):
                continue
            for sense in senses:
                if not isinstance(sense, dict):
                    continue
                raw_glosses = sense.get("glosses")
                if not isinstance(raw_glosses, list):
                    continue
                glosses = [
                    gloss.strip()
                    for gloss in raw_glosses
                    if isinstance(gloss, str) and gloss.strip()
                ]
                if glosses:
                    sense_glosses.append(glosses)
            if not sense_glosses:
                continue
            lemma = word.strip()
            part_of_speech = _normalize_pos(pos)
            yield {
                "lemma": lemma,
                "part_of_speech": part_of_speech,
                "sense_glosses": sense_glosses,
                "external_id": f"wiktionary_zh:{lemma}:{part_of_speech}",
            }
