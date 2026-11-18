"""Kaikki JSONL reader, entry compaction, and projection eligibility."""

from __future__ import annotations

from collections.abc import Iterable
import gzip
import json
from pathlib import Path

from open_finnish_lexicon.normalize.lexemes import normalize_part_of_speech
from open_finnish_lexicon.sources.kaikki_forms import _clean_kaikki_forms
from open_finnish_lexicon.sources.kaikki_syllables import (
    _extract_kaikki_syllabification,
    syllabify_finnish_word,
)

def _open_kaikki_input(input_path: Path):
    if input_path.suffix == ".gz":
        return gzip.open(input_path, "rt", encoding="utf-8")
    return input_path.open(encoding="utf-8")


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_usable_sound(value: object) -> bool:
    return isinstance(value, list) and any(
        isinstance(sound, dict) and _has_text(sound.get("ipa")) for sound in value
    )


def _has_usable_derived(value: object) -> bool:
    return isinstance(value, list) and any(
        isinstance(item, dict) and _has_text(item.get("word")) for item in value
    )


def _has_usable_glosses(value: object) -> bool:
    return isinstance(value, list) and any(_has_text(gloss) for gloss in value)


def _clean_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        values.append(normalized)
    return values


def _clean_kaikki_examples(value: object) -> list[dict[str, str]]:
    """Keep usable Finnish example sentences from a Kaikki sense."""

    if not isinstance(value, list):
        return []
    examples: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        text_fi = item.get("text")
        if not isinstance(text_fi, str):
            continue
        text_fi = " ".join(text_fi.split())
        if not text_fi or text_fi in seen:
            continue
        seen.add(text_fi)
        example = {"text": text_fi}
        for key in ("english", "english_text"):
            english = item.get(key)
            if isinstance(english, str) and english.strip():
                example["english"] = english.strip()
                break
        examples.append(example)
    return examples


def _normalize_kaikki_entry(entry: object) -> dict | None:
    if not isinstance(entry, dict):
        return None
    if not _has_text(entry.get("word")) or not _has_text(entry.get("pos")):
        return None

    normalized = dict(entry)
    normalized["word"] = entry["word"].strip()
    normalized["pos"] = normalize_part_of_speech(entry["pos"])

    senses: list[dict] = []
    raw_senses = entry.get("senses")
    if isinstance(raw_senses, list):
        for raw_sense in raw_senses:
            if not isinstance(raw_sense, dict) or not _has_text(raw_sense.get("id")):
                continue
            sense = dict(raw_sense)
            sense["id"] = raw_sense["id"].strip()
            for field in ("glosses", "tags", "raw_tags", "topics"):
                sense[field] = _clean_string_list(sense.get(field))
            senses.append(sense)
    normalized["senses"] = senses

    sounds = entry.get("sounds")
    normalized["sounds"] = (
        [sound for sound in sounds if isinstance(sound, dict)] if isinstance(sounds, list) else []
    )

    derived = entry.get("derived")
    normalized["derived"] = (
        [
            {**item, "word": item["word"].strip()}
            for item in derived
            if isinstance(item, dict) and _has_text(item.get("word"))
        ]
        if isinstance(derived, list)
        else []
    )
    return normalized


def has_kaikki_projection_data(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    raw_forms = entry.get("forms")
    has_precleaned_forms = bool(
        isinstance(raw_forms, list)
        and any(
            isinstance(item, dict)
            and isinstance(item.get("form"), str)
            and item["form"].strip()
            and isinstance(item.get("features"), dict)
            and bool(item["features"])
            for item in raw_forms
        )
    )
    if (
        _has_usable_sound(entry.get("sounds"))
        or _has_text(entry.get("etymology_text"))
        or _has_usable_derived(entry.get("derived"))
        or has_precleaned_forms
        or bool(_clean_kaikki_forms(entry))
    ):
        return True
    senses = entry.get("senses")
    if not isinstance(senses, list):
        return False
    for sense in senses:
        if isinstance(sense, dict) and _has_usable_glosses(sense.get("glosses")):
            return True
    return False


_KAIKKI_RELATION_FIELDS: tuple[tuple[str, str], ...] = (
    ("synonyms", "synonym"),
    ("antonyms", "antonym"),
    ("hypernyms", "hypernym"),
    ("hyponyms", "hyponym"),
)


def _extract_kaikki_relations(entry: dict) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    relations: list[dict[str, str]] = []
    lemma = str(entry.get("word", "")).strip()
    existing_rels = entry.get("relations")
    if isinstance(existing_rels, list):
        for item in existing_rels:
            if not isinstance(item, dict):
                continue
            word_val = item.get("word")
            type_val = item.get("type")
            if isinstance(word_val, str) and isinstance(type_val, str):
                cleaned_word = word_val.strip()
                cleaned_type = type_val.strip()
                if cleaned_word and cleaned_type and cleaned_word != lemma:
                    key = (cleaned_word, cleaned_type)
                    if key not in seen:
                        seen.add(key)
                        relations.append({"word": cleaned_word, "type": cleaned_type})

    def _collect(container: dict) -> None:
        for field_name, rel_type in _KAIKKI_RELATION_FIELDS:
            items = container.get(field_name)
            if not isinstance(items, list):
                continue
            for item in items:
                target = item.get("word") if isinstance(item, dict) else None
                if not isinstance(target, str):
                    continue
                cleaned = target.strip()
                if not cleaned or cleaned == lemma:
                    continue
                key = (cleaned, rel_type)
                if key not in seen:
                    seen.add(key)
                    relations.append({"word": cleaned, "type": rel_type})

    _collect(entry)
    for sense in entry.get("senses", []):
        if isinstance(sense, dict):
            _collect(sense)
    return relations


def compact_kaikki_entry(entry: dict) -> dict:
    raw_forms = entry.get("forms")
    if (
        isinstance(raw_forms, list)
        and raw_forms
        and all(
            isinstance(item, dict)
            and isinstance(item.get("form"), str)
            and isinstance(item.get("features"), dict)
            for item in raw_forms
        )
    ):
        cleaned_forms = [
            {
                "form": item["form"].strip(),
                "features": dict(item["features"]),
                "tags": list(item.get("tags", [])) if isinstance(item.get("tags"), list) else [],
            }
            for item in raw_forms
            if item["form"].strip()
        ]
    else:
        cleaned_forms = _clean_kaikki_forms(entry)

    compact: dict[str, object] = {
        "word": str(entry["word"]).strip(),
        "pos": normalize_part_of_speech(str(entry["pos"])),
        "senses": [],
        "forms": cleaned_forms,
        "derived": [
            {"word": item["word"]}
            for item in entry.get("derived", [])
            if isinstance(item, dict) and item.get("word")
        ],
    }

    syllabification = _extract_kaikki_syllabification(entry)
    if syllabification:
        compact["syllabification"] = syllabification

    relations = _extract_kaikki_relations(entry)
    if relations:
        compact["relations"] = relations

    sounds = entry.get("sounds")
    if isinstance(sounds, list):
        compact_sounds: list[dict[str, str]] = []
        seen_ipas: set[str] = set()
        for sound in sounds:
            if not isinstance(sound, dict):
                continue
            ipa = sound.get("ipa")
            if isinstance(ipa, str) and ipa.strip():
                cleaned_ipa = ipa.strip()
                has_variant_context = bool(
                    cleaned_ipa.startswith("[")
                    or sound.get("tags")
                    or sound.get("raw_tags")
                    or sound.get("note")
                )
                if compact_sounds and not has_variant_context:
                    continue
                if cleaned_ipa not in seen_ipas:
                    seen_ipas.add(cleaned_ipa)
                    compact_sounds.append({"ipa": cleaned_ipa})
        if compact_sounds:
            compact["sounds"] = compact_sounds

    etymology_text = entry.get("etymology_text")
    if isinstance(etymology_text, str) and etymology_text.strip():
        compact["etymology_text"] = etymology_text.strip()

    compact_senses: list[dict[str, object]] = []
    for sense in entry.get("senses", []):
        if not isinstance(sense, dict) or not _has_text(sense.get("id")):
            continue
        compact_sense: dict[str, object] = {
            "id": sense["id"],
            "glosses": _clean_string_list(sense.get("glosses")),
            "tags": _clean_string_list(sense.get("tags")),
        }
        for field in ("qualifier", "note", "warning"):
            value = sense.get(field)
            if _has_text(value):
                compact_sense[field] = value.strip()
        raw_tags = _clean_string_list(sense.get("raw_tags"))
        if raw_tags:
            compact_sense["raw_tags"] = raw_tags
        topics = _clean_string_list(sense.get("topics"))
        if topics:
            compact_sense["topics"] = topics
        examples = _clean_kaikki_examples(sense.get("examples"))
        if examples:
            compact_sense["examples"] = examples
        compact_senses.append(compact_sense)
    compact["senses"] = compact_senses

    return compact


def read_kaikki_entries(
    input_path: Path,
    *,
    include_non_projection_entries: bool = False,
    reject_corrupt_stream: bool = False,
) -> Iterable[dict]:
    valid_lines = 0
    corrupt_lines = 0
    with _open_kaikki_input(input_path) as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                corrupt_lines += 1
                continue
            valid_lines += 1
            entry = _normalize_kaikki_entry(entry)
            if entry is None:
                continue
            if entry.get("lang") not in (None, "Finnish"):
                continue
            if not include_non_projection_entries and not has_kaikki_projection_data(entry):
                continue
            yield entry
    if reject_corrupt_stream and corrupt_lines > 100 and corrupt_lines > valid_lines * 0.05:
        raise ValueError(
            f"Kaikki input {input_path} appears corrupted: "
            f"{corrupt_lines} malformed JSON lines vs {valid_lines} valid lines"
        )

__all__ = [
    "_clean_kaikki_forms",
    "_open_kaikki_input",
    "compact_kaikki_entry",
    "has_kaikki_projection_data",
    "read_kaikki_entries",
    "syllabify_finnish_word",
]
