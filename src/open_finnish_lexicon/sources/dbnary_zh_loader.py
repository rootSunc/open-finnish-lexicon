from collections.abc import Iterable, Iterator
from pathlib import Path
import re


TYPE_DECL_RE = re.compile(
    r"^(?P<subject>\S+)\s+(?:a|rdf:type)\s+(?P<types>.*?)(?:\s*;|\s*\.)",
    re.DOTALL,
)
POS_ALIASES = {
    "adjective": "adj",
    "adverb": "adv",
    "conjunction": "conj",
    "determiner": "det",
    "interjection": "intj",
    "noun": "noun",
    "numeral": "num",
    "postposition": "postp",
    "preposition": "prep",
    "pronoun": "pron",
    "propernoun": "name",
    "proper_noun": "name",
    "verb": "verb",
}


def _iter_turtle_statements(path: Path) -> Iterator[str]:
    statement_lines: list[str] = []
    bracket_depth = 0
    in_string = False
    escaped = False

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not statement_lines and stripped.startswith("@prefix"):
                continue

            statement_lines.append(raw_line.rstrip("\n"))

            for character in raw_line:
                if in_string:
                    if escaped:
                        escaped = False
                        continue
                    if character == "\\":
                        escaped = True
                        continue
                    if character == '"':
                        in_string = False
                    continue

                if character == '"':
                    in_string = True
                elif character == "[":
                    bracket_depth += 1
                elif character == "]" and bracket_depth > 0:
                    bracket_depth -= 1

            if not in_string and bracket_depth == 0 and stripped.endswith("."):
                yield " ".join(line.strip() for line in statement_lines)
                statement_lines.clear()

    if statement_lines:
        yield " ".join(line.strip() for line in statement_lines)


def _extract_predicate_object(statement: str, predicate: str) -> str | None:
    match = re.search(rf"\b{re.escape(predicate)}\s+(.*?)(?=(?:\s*;\s+\S+\s)|\s*\.$)", statement, re.DOTALL)
    if not match:
        return None
    return match.group(1).strip()


def _extract_literal_value(statement: str, predicate: str) -> str | None:
    literal = _extract_literal(statement, predicate)
    return literal[0] if literal is not None else None


def _extract_literal(statement: str, predicate: str) -> tuple[str, str | None] | None:
    value = _extract_predicate_object(statement, predicate)
    if value is None:
        return None
    match = re.match(r"\"(?P<literal>(?:[^\"\\]|\\.)*)\"(?:@(?P<lang>[\w-]+))?", value, re.DOTALL)
    if not match:
        return None
    return match.group("literal"), match.group("lang")


def _statement_subject(statement: str) -> str | None:
    match = re.match(r"^(?P<subject>\S+)\s+", statement)
    return match.group("subject") if match else None


def _type_subject(statement: str, type_name: str) -> str | None:
    match = TYPE_DECL_RE.match(statement)
    if match is None:
        return None
    return match.group("subject") if type_name in match.group("types") else None


def _extract_language_code(statement: str) -> str | None:
    for predicate in ("dct:language", "dcterms:language"):
        literal = _extract_literal_value(statement, predicate)
        if literal:
            return literal.casefold()

        value = _extract_predicate_object(statement, predicate)
        if not value:
            continue
        normalized = value.strip().strip("<>").casefold()
        if normalized.startswith("lexvo:"):
            return normalized.split(":", 1)[1]
        if normalized.startswith("http://lexvo.org/id/iso639-3/"):
            return normalized.rsplit("/", 1)[-1]
        return normalized
    return None


def _is_finnish_language(language_code: str | None) -> bool:
    return language_code in {"fi", "fin"}


def _normalize_part_of_speech(value: str) -> str:
    normalized = value.strip().strip("<>").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    normalized = normalized.rsplit(":", 1)[-1].replace("-", "_").casefold()
    return POS_ALIASES.get(normalized, normalized)


def _split_object_list(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _load_finnish_entry_metadata(core_path: Path) -> tuple[dict[str, tuple[str, str, int, int]], set[str]]:
    entry_by_sense: dict[str, tuple[str, str, int, int]] = {}
    needed_form_ids: set[str] = set()
    lemma_by_form_id: dict[str, str] = {}
    pending_entries: list[tuple[str, str, list[str]]] = []

    for statement in _iter_turtle_statements(core_path):
        entry_subject = _type_subject(statement, "ontolex:LexicalEntry")
        if entry_subject is not None:
            language = _extract_language_code(statement)
            if not _is_finnish_language(language):
                continue

            part_of_speech = _extract_predicate_object(statement, "lexinfo:partOfSpeech")
            canonical_form = _extract_predicate_object(statement, "ontolex:canonicalForm")
            sense_ids = _split_object_list(_extract_predicate_object(statement, "ontolex:sense"))
            if not part_of_speech or not canonical_form or not sense_ids:
                continue

            pending_entries.append((canonical_form, _normalize_part_of_speech(part_of_speech), sense_ids))
            needed_form_ids.add(canonical_form)
            continue

        subject = _statement_subject(statement)
        if subject not in needed_form_ids:
            continue
        written_rep = _extract_literal(statement, "ontolex:writtenRep")
        if written_rep is None:
            continue
        written_value, written_lang = written_rep
        if written_lang is not None and not _is_finnish_language(written_lang.casefold()):
            continue
        lemma_by_form_id[subject] = written_value.strip()

    for form_id, part_of_speech, sense_ids in pending_entries:
        lemma = lemma_by_form_id.get(form_id)
        if not lemma:
            continue
        sense_count = len(sense_ids)
        for sense_index, sense_id in enumerate(sense_ids):
            entry_by_sense[sense_id] = (lemma, part_of_speech, sense_index, sense_count)

    return entry_by_sense, set(entry_by_sense)


def _load_finnish_sense_glosses(core_path: Path, needed_sense_ids: set[str]) -> dict[str, tuple[str, str | None]]:
    gloss_by_sense: dict[str, tuple[str, str | None]] = {}
    for statement in _iter_turtle_statements(core_path):
        sense_id = _type_subject(statement, "ontolex:LexicalSense")
        if sense_id is None:
            continue

        if sense_id not in needed_sense_ids:
            continue

        gloss_match = re.search(
            r"skos:definition\s+\[\s*rdf:value\s+\"(?P<value>(?:[^\"\\]|\\.)*)\"(?:@(?P<lang>[\w-]+))?",
            statement,
            re.DOTALL,
        )
        if gloss_match is None:
            continue
        gloss_by_sense[sense_id] = (gloss_match.group("value").strip(), gloss_match.group("lang"))
    return gloss_by_sense


def _load_translation_sense_links(path: Path, needed_sense_ids: set[str]) -> dict[str, str]:
    sense_id_by_translation_id: dict[str, str] = {}
    for statement in _iter_turtle_statements(path):
        subject = _statement_subject(statement)
        if subject is None:
            continue

        sense_id = _extract_predicate_object(statement, "dbnary:isTranslationOf")
        if sense_id and sense_id in needed_sense_ids:
            sense_id_by_translation_id[subject] = sense_id
    return sense_id_by_translation_id


def _load_chinese_terms(
    path: Path,
    needed_sense_ids: set[str],
    *,
    sense_id_by_translation_id: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    chinese_terms_by_sense: dict[str, list[str]] = {}
    for statement in _iter_turtle_statements(path):
        subject = _statement_subject(statement)
        sense_id = _extract_predicate_object(statement, "dbnary:isTranslationOf")
        if sense_id not in needed_sense_ids:
            sense_id = (sense_id_by_translation_id or {}).get(subject or "")
        if not sense_id or sense_id not in needed_sense_ids:
            continue

        target_language = _extract_predicate_object(statement, "dbnary:targetLanguage")
        if target_language not in {"lexvo:cmn", "lexvo:zho"}:
            continue

        written_form = _extract_literal_value(statement, "dbnary:writtenForm")
        if not written_form:
            continue

        chinese_terms_by_sense.setdefault(sense_id, [])
        if written_form not in chinese_terms_by_sense[sense_id]:
            chinese_terms_by_sense[sense_id].append(written_form)
    return chinese_terms_by_sense


def read_dbnary_zh_candidates(core_path: Path, enhancement_path: Path) -> Iterable[dict]:
    entry_by_sense, needed_sense_ids = _load_finnish_entry_metadata(core_path)
    gloss_by_sense = _load_finnish_sense_glosses(core_path, needed_sense_ids)
    sense_id_by_translation_id = _load_translation_sense_links(enhancement_path, needed_sense_ids)
    chinese_terms_by_sense = _load_chinese_terms(enhancement_path, needed_sense_ids)
    for sense_id, terms in _load_chinese_terms(
        core_path,
        needed_sense_ids,
        sense_id_by_translation_id=sense_id_by_translation_id,
    ).items():
        chinese_terms_by_sense.setdefault(sense_id, [])
        for term in terms:
            if term not in chinese_terms_by_sense[sense_id]:
                chinese_terms_by_sense[sense_id].append(term)

    grouped: dict[tuple[str, str, str, str | None, int, int], list[str]] = {}
    for sense_id in sorted(needed_sense_ids):
        entry = entry_by_sense.get(sense_id)
        gloss = gloss_by_sense.get(sense_id)
        zh_terms = chinese_terms_by_sense.get(sense_id)
        if entry is None or gloss is None or not zh_terms:
            continue

        lemma, part_of_speech, sense_index, source_sense_count = entry
        gloss_text, gloss_language = gloss
        key = (lemma, part_of_speech, gloss_text, gloss_language, sense_index, source_sense_count)
        grouped.setdefault(key, [])
        for value in zh_terms:
            if value and value not in grouped[key]:
                grouped[key].append(value)

    for (
        lemma,
        part_of_speech,
        gloss_text,
        gloss_language,
        sense_index,
        source_sense_count,
    ), zh_terms in grouped.items():
        normalized_gloss_language = (gloss_language or "").casefold()
        gloss_en = gloss_text if normalized_gloss_language == "en" else None
        gloss_fi = gloss_text if _is_finnish_language(normalized_gloss_language) else None
        yield {
            "lemma": lemma,
            "part_of_speech": part_of_speech,
            "gloss_en": gloss_en,
            "gloss_fi": gloss_fi,
            "source_gloss": gloss_text,
            "source_gloss_language": gloss_language,
            "sense_index": sense_index,
            "source_sense_count": source_sense_count,
            "zh_terms": zh_terms,
            "external_id": f"dbnary_zh:{lemma}:{part_of_speech}:{sense_index}:{gloss_text}",
        }
