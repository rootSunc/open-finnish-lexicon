from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
import re

import psycopg

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.sources.lexeme_lookup import (
    load_sense_candidates,
    load_single_sense_ids,
    load_unique_analysis_matches,
    load_unique_form_matches,
    load_unique_lemma_matches,
)
from open_finnish_lexicon.zh_script import normalize_and_validate_zh_sentence

TOKEN_RE = re.compile(r"[^\W\d_]+(?:[-'’ʼ‐‑‒–—][^\W\d_]+)*", re.UNICODE)
CHINESE_LANGUAGE_PRIORITY = {
    "cmn": 0,
    "zh": 1,
    "yue": 2,
    "wuu": 3,
    "nan": 4,
    "hak": 5,
    "lzh": 6,
}
ENGLISH_LANGUAGE_PRIORITY = {
    "eng": 0,
    "enm": 1,
}
TATOEBA_MIN_EXAMPLE_QUALITY = 0.45

ENGLISH_STOPWORDS = {
    "a",
    "an",
    "and",
    "be",
    "i",
    "in",
    "is",
    "of",
    "or",
    "the",
    "to",
}
ENGLISH_IRREGULAR_STEMS = {
    "am": "be",
    "are": "be",
    "been": "be",
    "being": "be",
    "did": "do",
    "does": "do",
    "done": "do",
    "gone": "go",
    "kept": "keep",
    "ran": "run",
    "running": "run",
    "was": "be",
    "were": "be",
}


def _clean_direct_chinese_translation(value: object) -> str | None:
    """Convert Traditional->Simplified and keep learner-safe Mandarin sentences."""

    return normalize_and_validate_zh_sentence(value)


def _format_tatoeba_attribution(username: str | None) -> str | None:
    if not username:
        return None
    cleaned = username.strip()
    if not cleaned or cleaned == r"\N":
        return None
    return f"Tatoeba ({cleaned})"


@dataclass(frozen=True)
class TatoebaEntry:
    external_id: str
    sentence_id: str | None
    text_fi: str
    quality_score: float
    text_en: str | None = None
    text_zh: str | None = None
    sense_key: str | None = None
    username: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class TatoebaLookupCache:
    analysis_matches: dict[str, int | None]
    lemma_matches: dict[str, int | None]
    form_matches: dict[str, int | None]
    single_sense_ids: dict[int, int | None]
    sense_candidates: dict[int, list[tuple[int, str]]]


def get_tatoeba_source_kind(input_path: Path) -> str:
    with input_path.open(encoding="utf-8") as handle:
        first_line = handle.readline().strip()
    if not first_line:
        return "tsv"
    columns = first_line.split("\t")
    if len(columns) in {4, 5}:
        return "tsv"
    if len(columns) >= 6:
        return "tatoeba-detailed"
    raise ValueError("unsupported Tatoeba format")


def iter_tatoeba_entries(input_path: Path) -> Iterator[TatoebaEntry]:
    source_kind = get_tatoeba_source_kind(input_path)
    with input_path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.rstrip("\n")
            if not stripped:
                continue
            columns = stripped.split("\t")
            if source_kind == "tsv":
                if len(columns) not in {4, 5}:
                    raise ValueError("legacy Tatoeba rows must have 4 or 5 tab-separated columns")
                sense_key, text_fi, text_en, quality = columns[:4]
                text_zh = columns[4] if len(columns) == 5 and columns[4].strip() else None
                yield TatoebaEntry(
                    external_id=sense_key,
                    sentence_id=None,
                    sense_key=sense_key,
                    text_fi=text_fi,
                    text_en=text_en,
                    text_zh=text_zh,
                    quality_score=float(quality),
                )
                continue

            sentence_id, language, text_fi, username, created_at, updated_at = columns[:6]
            if language != "fin":
                continue
            yield TatoebaEntry(
                external_id=f"tatoeba:{sentence_id}",
                sentence_id=sentence_id,
                text_fi=text_fi,
                quality_score=1.0,
                username=username,
                created_at=created_at,
                updated_at=updated_at,
            )


def discover_tatoeba_companion_paths(input_path: Path) -> tuple[Path | None, list[Path]]:
    search_dirs = [input_path.parent, input_path.parent.parent]
    links_path: Path | None = None
    sentence_paths: list[Path] = []
    seen_sentence_names: set[str] = set()
    for directory in search_dirs:
        candidate = directory / "links.csv"
        if links_path is None and candidate.exists():
            links_path = candidate
        for filename in (
            "eng_sentences_detailed.tsv",
            "cmn_sentences_detailed.tsv",
            "sentences.csv",
        ):
            sent_candidate = directory / filename
            if filename not in seen_sentence_names and sent_candidate.exists():
                seen_sentence_names.add(filename)
                sentence_paths.append(sent_candidate)
    return links_path, sentence_paths


def load_tatoeba_translations(input_path: Path, sentence_ids: set[str]) -> dict[str, dict[str, str]]:
    if not sentence_ids:
        return {}

    links_path, sentence_paths = discover_tatoeba_companion_paths(input_path)
    if links_path is None or not sentence_paths:
        return {}

    direct_ids_by_sentence: dict[str, list[str]] = {}
    direct_sets_by_sentence: dict[str, set[str]] = {}
    with links_path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.rstrip("\n")
            if not stripped:
                continue
            parts = stripped.split("\t", 1)
            if len(parts) != 2:
                continue
            left_id, right_id = parts
            if left_id in sentence_ids:
                direct_set = direct_sets_by_sentence.setdefault(left_id, set())
                if right_id not in direct_set:
                    direct_set.add(right_id)
                    direct_ids_by_sentence.setdefault(left_id, []).append(right_id)
            if right_id in sentence_ids:
                direct_set = direct_sets_by_sentence.setdefault(right_id, set())
                if left_id not in direct_set:
                    direct_set.add(left_id)
                    direct_ids_by_sentence.setdefault(right_id, []).append(left_id)

    first_hop_to_sentence_ids: dict[str, list[str]] = {}
    for sentence_id, direct_ids in direct_ids_by_sentence.items():
        for linked_id in direct_ids:
            first_hop_to_sentence_ids.setdefault(linked_id, []).append(sentence_id)
    first_hop_ids = set(first_hop_to_sentence_ids)
    second_hop_ids_by_sentence: dict[str, list[str]] = {}
    second_hop_sets_by_sentence: dict[str, set[str]] = {}
    if first_hop_ids:
        with links_path.open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.rstrip("\n")
                if not stripped:
                    continue
                parts = stripped.split("\t", 1)
                if len(parts) != 2:
                    continue
                left_id, right_id = parts
                if left_id in first_hop_ids:
                    for sentence_id in first_hop_to_sentence_ids[left_id]:
                        direct_set = direct_sets_by_sentence.get(sentence_id, set())
                        second_set = second_hop_sets_by_sentence.setdefault(sentence_id, set())
                        if (
                            right_id != sentence_id
                            and right_id not in direct_set
                            and right_id not in second_set
                        ):
                            second_set.add(right_id)
                            second_hop_ids_by_sentence.setdefault(sentence_id, []).append(right_id)
                if right_id in first_hop_ids:
                    for sentence_id in first_hop_to_sentence_ids[right_id]:
                        direct_set = direct_sets_by_sentence.get(sentence_id, set())
                        second_set = second_hop_sets_by_sentence.setdefault(sentence_id, set())
                        if (
                            left_id != sentence_id
                            and left_id not in direct_set
                            and left_id not in second_set
                        ):
                            second_set.add(left_id)
                            second_hop_ids_by_sentence.setdefault(sentence_id, []).append(left_id)

    linked_ids_by_sentence = {
        sentence_id: direct_ids + second_hop_ids_by_sentence.get(sentence_id, [])
        for sentence_id, direct_ids in direct_ids_by_sentence.items()
    }
    target_ids = {
        linked_id
        for linked_ids in linked_ids_by_sentence.values()
        for linked_id in linked_ids
    }

    translated_sentences: dict[str, dict[str, tuple[int, str]]] = {}
    for sentences_path in sentence_paths:
        with sentences_path.open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.rstrip("\n")
                if not stripped:
                    continue
                parts = stripped.split("\t", 3)
                if len(parts) < 3:
                    continue
                sentence_id, language_code, text = parts[:3]
                if sentence_id not in target_ids:
                    continue
                translation_kind: str | None = None
                priority: int | None = CHINESE_LANGUAGE_PRIORITY.get(language_code)
                if priority is not None:
                    translation_kind = "zh"
                else:
                    priority = ENGLISH_LANGUAGE_PRIORITY.get(language_code)
                    if priority is not None:
                        translation_kind = "en"
                if translation_kind is None or priority is None:
                    continue

                sentence_translations = translated_sentences.setdefault(sentence_id, {})
                current = sentence_translations.get(translation_kind)
                if current is None or priority < current[0]:
                    sentence_translations[translation_kind] = (priority, text)

    translations: dict[str, dict[str, str]] = {}
    for sentence_id, linked_ids in linked_ids_by_sentence.items():
        translation_entry: dict[str, str] = {}
        for linked_id in linked_ids:
            translated = translated_sentences.get(linked_id, {})
            text_zh = translated.get("zh")
            if text_zh is not None and "zh" not in translation_entry:
                translation_entry["zh"] = text_zh[1]
            text_en = translated.get("en")
            if text_en is not None and "en" not in translation_entry:
                translation_entry["en"] = text_en[1]
            if "zh" in translation_entry and "en" in translation_entry:
                break
        if translation_entry:
            translations[sentence_id] = translation_entry
    return translations


def _tokenize_text(value: str) -> list[str]:
    return [match.group(0).casefold() for match in TOKEN_RE.finditer(value)]


def _english_stem(token: str) -> str:
    irregular = ENGLISH_IRREGULAR_STEMS.get(token)
    if irregular is not None:
        return irregular
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ied"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _english_content_stems(value: str | None) -> set[str]:
    if not value:
        return set()
    stems = set()
    for token in _tokenize_text(value):
        if token in ENGLISH_STOPWORDS:
            continue
        stem = _english_stem(token)
        if len(stem) >= 3 and stem not in ENGLISH_STOPWORDS:
            stems.add(stem)
    return stems


def _resolve_sense_id_from_english(
    sense_candidates: list[tuple[int, str]],
    text_en: str | None,
) -> int | None:
    english_stems = _english_content_stems(text_en)
    if not english_stems:
        return None

    scored_candidates: list[tuple[int, int]] = []
    for sense_id, gloss_en in sense_candidates:
        gloss_stems = _english_content_stems(gloss_en)
        overlap = len(gloss_stems & english_stems)
        if overlap > 0:
            scored_candidates.append((sense_id, overlap))

    if not scored_candidates:
        return None

    scored_candidates.sort(key=lambda item: item[1], reverse=True)
    best_sense_id, best_score = scored_candidates[0]
    if best_score <= 0:
        return None
    if len(scored_candidates) > 1 and scored_candidates[1][1] == best_score:
        return None
    return best_sense_id


def _delete_existing_tatoeba_rows(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        delete from lexicon.sense_example
        where example_id in (
            select id
            from lexicon.example
            where source_label = 'tatoeba'
        )
        """
    )
    conn.execute(
        """
        delete from zh_layer.zh_example_translation
        where example_id in (
            select id
            from lexicon.example
            where source_label = 'tatoeba'
        )
        """
    )
    conn.execute("delete from lexicon.example where source_label = 'tatoeba'")


def _resolve_legacy_sense_id(conn: psycopg.Connection, entry: TatoebaEntry) -> int | None:
    exact_sentence_senses = conn.execute(
        """
        select distinct se.sense_id
        from lexicon.sense_example se
        join lexicon.example e on e.id = se.example_id
        where e.text_fi = %s
        order by se.sense_id
        """,
        (entry.text_fi,),
    ).fetchall()
    if len(exact_sentence_senses) == 1:
        return int(exact_sentence_senses[0][0])

    candidates = conn.execute(
        """
        select id, coalesce(gloss_en, '')
        from lexicon.lexeme_sense
        where sense_key = %s
        order by id
        """,
        (entry.sense_key,),
    ).fetchall()
    if not candidates:
        return None
    resolved = _resolve_sense_id_from_english(
        [(int(sense_id), str(gloss_en)) for sense_id, gloss_en in candidates],
        entry.text_en,
    )
    if resolved is not None:
        return resolved
    if len(candidates) == 1 and not _english_content_stems(entry.text_en):
        return int(candidates[0][0])
    return None


def _ingest_legacy_tatoeba(
    input_path: Path,
    *,
    entries: Iterable[TatoebaEntry] | None = None,
    connection: psycopg.Connection | None = None,
) -> None:
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        _delete_existing_tatoeba_rows(conn)
        for entry in entries if entries is not None else iter_tatoeba_entries(input_path):
            if entry.sense_key is None:
                continue
            sense_id = _resolve_legacy_sense_id(conn, entry)
            if sense_id is None:
                continue
            row = conn.execute(
                """
                insert into lexicon.example (
                    text_fi, text_en, source_label, quality_score, attribution
                )
                values (%s, %s, %s, %s, %s)
                returning id
                """,
                (
                    entry.text_fi,
                    entry.text_en,
                    "tatoeba",
                    entry.quality_score,
                    _format_tatoeba_attribution(entry.username),
                ),
            ).fetchone()
            assert row is not None
            example_id = int(row[0])
            text_zh = _clean_direct_chinese_translation(entry.text_zh)
            if text_zh:
                conn.execute(
                    """
                    insert into zh_layer.zh_example_translation (
                        example_id,
                        text_zh,
                        generation_method,
                        generation_version,
                        is_primary,
                        is_usable
                    )
                    values (%s, %s, %s, %s, %s, true)
                    """,
                    (example_id, text_zh, "tatoeba-direct-zh", "v1", True),
                )
            conn.execute(
                """
                insert into lexicon.sense_example (sense_id, example_id, is_core, sort_order)
                values (%s, %s, %s, %s)
                on conflict (sense_id, example_id) do update
                set is_core = excluded.is_core,
                    sort_order = excluded.sort_order
                """,
                (sense_id, example_id, True, 1),
            )
        if owns_connection:
            conn.commit()


def _upsert_tatoeba_chunk_with_cache(
    conn: psycopg.Connection,
    entries: list[TatoebaEntry],
    cache: TatoebaLookupCache,
    translations_by_sentence_id: dict[str, dict[str, str]],
) -> None:
    if not entries:
        return

    normalized_terms = {
        token
        for entry in entries
        for token in _tokenize_text(entry.text_fi)
    }
    unresolved_analysis_terms = normalized_terms - cache.analysis_matches.keys()
    unresolved_lemma_terms = normalized_terms - cache.lemma_matches.keys()
    unresolved_form_terms = normalized_terms - cache.form_matches.keys()

    resolved_analysis_matches = load_unique_analysis_matches(conn, unresolved_analysis_terms)
    resolved_lemma_matches = load_unique_lemma_matches(conn, unresolved_lemma_terms)
    resolved_form_matches = load_unique_form_matches(conn, unresolved_form_terms)

    for token in unresolved_analysis_terms:
        cache.analysis_matches[token] = resolved_analysis_matches.get(token)
    for token in unresolved_lemma_terms:
        cache.lemma_matches[token] = resolved_lemma_matches.get(token)
    for token in unresolved_form_terms:
        cache.form_matches[token] = resolved_form_matches.get(token)

    candidate_lexeme_ids = {
        lexeme_id
        for lexeme_id in (
            [cache.analysis_matches[token] for token in normalized_terms]
            + [cache.lemma_matches[token] for token in normalized_terms]
            + [cache.form_matches[token] for token in normalized_terms]
        )
        if lexeme_id is not None
    }
    unresolved_single_sense_ids = candidate_lexeme_ids - cache.single_sense_ids.keys()
    resolved_single_sense_ids = load_single_sense_ids(conn, unresolved_single_sense_ids)
    for lexeme_id in unresolved_single_sense_ids:
        cache.single_sense_ids[lexeme_id] = resolved_single_sense_ids.get(lexeme_id)

    unresolved_sense_candidates = {
        lexeme_id
        for lexeme_id in candidate_lexeme_ids
        if lexeme_id not in cache.sense_candidates and cache.single_sense_ids.get(lexeme_id) is None
    }
    resolved_sense_candidates = load_sense_candidates(conn, unresolved_sense_candidates)
    for lexeme_id in unresolved_sense_candidates:
        cache.sense_candidates[lexeme_id] = resolved_sense_candidates.get(lexeme_id, [])

    example_rows: dict[str, tuple[str | None, float, str | None, str | None]] = {}
    link_rows: list[tuple[str, int, int]] = []
    for entry in entries:
        if entry.quality_score < TATOEBA_MIN_EXAMPLE_QUALITY:
            continue
        existing = example_rows.get(entry.text_fi)
        translation_entry = translations_by_sentence_id.get(entry.sentence_id or "", {})
        text_zh = _clean_direct_chinese_translation(
            entry.text_zh or translation_entry.get("zh")
        )
        text_en = entry.text_en or translation_entry.get("en")
        attribution = _format_tatoeba_attribution(entry.username)
        if existing is None or entry.quality_score > existing[1]:
            example_rows[entry.text_fi] = (text_en, entry.quality_score, text_zh, attribution)
        else:
            merged_en = existing[0] or text_en
            merged_zh = existing[2] or text_zh
            merged_attr = existing[3] or attribution
            example_rows[entry.text_fi] = (merged_en, existing[1], merged_zh, merged_attr)

        seen_sense_ids: set[int] = set()
        sort_order = 1
        for token in dict.fromkeys(_tokenize_text(entry.text_fi)):
            lexeme_id = cache.analysis_matches.get(token)
            if lexeme_id is None:
                lexeme_id = cache.lemma_matches.get(token)
            if lexeme_id is None:
                lexeme_id = cache.form_matches.get(token)
            sense_id = cache.single_sense_ids.get(lexeme_id) if lexeme_id is not None else None
            if sense_id is None and lexeme_id is not None:
                sense_id = _resolve_sense_id_from_english(
                    cache.sense_candidates.get(lexeme_id, []),
                    text_en,
                )
            if sense_id is None or sense_id in seen_sense_ids:
                continue
            seen_sense_ids.add(sense_id)
            link_rows.append((entry.text_fi, sense_id, sort_order))
            sort_order += 1

    with conn.cursor() as cursor:
        cursor.execute(
            """
            create temporary table if not exists tmp_tatoeba_example (
                text_fi text primary key,
                text_en text,
                quality_score numeric(6, 5) not null,
                text_zh text,
                attribution text
            ) on commit drop
            """
        )
        cursor.execute(
            """
            create temporary table if not exists tmp_tatoeba_link (
                text_fi text not null,
                sense_id bigint not null,
                sort_order integer not null,
                primary key (text_fi, sense_id)
            ) on commit drop
            """
        )
        cursor.execute(
            """
            create temporary table if not exists tmp_tatoeba_example_chunk (
                text_fi text not null,
                text_en text,
                quality_score numeric(6, 5) not null,
                text_zh text,
                attribution text
            ) on commit drop
            """
        )
        cursor.execute(
            """
            create temporary table if not exists tmp_tatoeba_link_chunk (
                text_fi text not null,
                sense_id bigint not null,
                sort_order integer not null
            ) on commit drop
            """
        )
        cursor.execute("truncate tmp_tatoeba_example_chunk")
        cursor.execute("truncate tmp_tatoeba_link_chunk")

        with cursor.copy(
            """
            copy tmp_tatoeba_example_chunk (text_fi, text_en, quality_score, text_zh, attribution)
            from stdin
            """
        ) as copy:
            for text_fi, (text_en, quality_score, text_zh, attribution) in example_rows.items():
                copy.write_row((text_fi, text_en, quality_score, text_zh, attribution))

        cursor.execute(
            """
            insert into tmp_tatoeba_example (text_fi, text_en, quality_score, text_zh, attribution)
            select text_fi, text_en, quality_score, text_zh, attribution
            from tmp_tatoeba_example_chunk
            on conflict (text_fi) do update
            set text_en = coalesce(excluded.text_en, tmp_tatoeba_example.text_en),
                quality_score = greatest(tmp_tatoeba_example.quality_score, excluded.quality_score),
                text_zh = coalesce(excluded.text_zh, tmp_tatoeba_example.text_zh),
                attribution = coalesce(excluded.attribution, tmp_tatoeba_example.attribution)
            """
        )

        with cursor.copy(
            """
            copy tmp_tatoeba_link_chunk (text_fi, sense_id, sort_order)
            from stdin
            """
        ) as copy:
            for row in link_rows:
                copy.write_row(row)

        cursor.execute(
            """
            insert into tmp_tatoeba_link (text_fi, sense_id, sort_order)
            select text_fi, sense_id, min(sort_order)
            from tmp_tatoeba_link_chunk
            group by text_fi, sense_id
            on conflict (text_fi, sense_id) do update
            set sort_order = least(tmp_tatoeba_link.sort_order, excluded.sort_order)
            """
        )


def _ingest_real_tatoeba(
    input_path: Path,
    *,
    entries: list[TatoebaEntry] | None = None,
    translations_by_sentence_id: dict[str, dict[str, str]] | None = None,
    connection: psycopg.Connection | None = None,
) -> None:
    source_entries = list(iter_tatoeba_entries(input_path)) if entries is None else entries
    chunk: list[TatoebaEntry] = []
    lookup_cache = TatoebaLookupCache(
        analysis_matches={},
        lemma_matches={},
        form_matches={},
        single_sense_ids={},
        sense_candidates={},
    )
    if translations_by_sentence_id is None:
        sentence_ids = {
            entry.sentence_id
            for entry in source_entries
            if entry.sentence_id is not None
        }
        translations_by_sentence_id = load_tatoeba_translations(input_path, sentence_ids)
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        _delete_existing_tatoeba_rows(conn)
        conn.execute("drop table if exists tmp_tatoeba_example")
        conn.execute("drop table if exists tmp_tatoeba_link")
        for entry in source_entries:
            chunk.append(entry)
            if len(chunk) >= 5_000:
                _upsert_tatoeba_chunk_with_cache(
                    conn, chunk, lookup_cache, translations_by_sentence_id
                )
                chunk.clear()
        if chunk:
            _upsert_tatoeba_chunk_with_cache(
                conn, chunk, lookup_cache, translations_by_sentence_id
            )

        conn.execute(
            """
            insert into lexicon.example (
                text_fi, text_en, source_label, quality_score, attribution
            )
            select text_fi, text_en, 'tatoeba', quality_score, attribution
            from tmp_tatoeba_example
            where exists (
                select 1
                from tmp_tatoeba_link link
                where link.text_fi = tmp_tatoeba_example.text_fi
            )
            """
        )
        conn.execute(
            """
            insert into lexicon.sense_example (sense_id, example_id, is_core, sort_order)
            select link.sense_id, example.id, true, link.sort_order
            from tmp_tatoeba_link link
            join lexicon.example example
              on example.source_label = 'tatoeba'
             and example.text_fi = link.text_fi
            on conflict (sense_id, example_id) do update
            set is_core = excluded.is_core,
                sort_order = excluded.sort_order
            """
        )
        conn.execute(
            """
            insert into zh_layer.zh_example_translation (
                example_id,
                text_zh,
                generation_method,
                generation_version,
                is_primary,
                is_usable
            )
            select example.id, tmp.text_zh, 'tatoeba-direct-zh', 'v1', true, true
            from tmp_tatoeba_example tmp
            join lexicon.example example
              on example.source_label = 'tatoeba'
             and example.text_fi = tmp.text_fi
            where tmp.text_zh is not null and tmp.text_zh <> ''
              and exists (
                  select 1
                  from tmp_tatoeba_link link
                  where link.text_fi = tmp.text_fi
              )
            """
        )
        if owns_connection:
            conn.commit()


def ingest_tatoeba(
    input_path: Path,
    *,
    entries: Iterable[TatoebaEntry] | None = None,
    connection: psycopg.Connection | None = None,
) -> None:
    staged_entries = list(iter_tatoeba_entries(input_path)) if entries is None else list(entries)
    if not staged_entries:
        raise ValueError(
            "Tatoeba input contains no valid Finnish entries; refusing to replace existing examples"
        )
    if entries is None and get_tatoeba_source_kind(input_path) == "tsv":
        _ingest_legacy_tatoeba(input_path, entries=staged_entries, connection=connection)
        return
    if entries is not None and not any(entry.sentence_id is not None for entry in staged_entries):
        _ingest_legacy_tatoeba(input_path, entries=staged_entries, connection=connection)
        return
    _ingest_real_tatoeba(
        input_path,
        entries=staged_entries,
        translations_by_sentence_id={} if entries is not None else None,
        connection=connection,
    )
