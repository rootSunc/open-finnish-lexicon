from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
import csv
from dataclasses import dataclass
from pathlib import Path

import psycopg

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.normalize.lexemes import normalize_part_of_speech
from open_finnish_lexicon.sources.lexeme_lookup import (
    load_unique_analysis_matches,
    load_unique_form_matches,
    load_unique_lemma_matches,
)

FREQUENCY_SOURCE_NAME = "frequency"
LEGACY_FREQUENCY_SOURCE_NAMES = ("frequency", "frequency-csv", "frequency-words")
LARGE_FREQUENCY_INPUT_ROWS = 1_000
MIN_LARGE_INPUT_RESOLVED_ROWS = 100
MIN_REPLACEMENT_RATIO = 0.10


@dataclass(frozen=True)
class FrequencyEntry:
    term: str
    raw_count: int
    lemma: str | None = None
    pos: str | None = None
    normalized_score: float | None = None


def get_frequency_source_kind(input_path: Path) -> str:
    with input_path.open(encoding="utf-8") as handle:
        first_line = handle.readline().strip()
    if first_line.startswith("lemma,pos,raw_count,normalized_score"):
        return "csv"
    return "txt"


def iter_frequency_entries(input_path: Path) -> Iterable[FrequencyEntry]:
    source_kind = get_frequency_source_kind(input_path)
    with input_path.open(encoding="utf-8") as handle:
        if source_kind == "csv":
            reader = csv.DictReader(handle)
            for row in reader:
                if not row:
                    continue
                yield FrequencyEntry(
                    term=row["lemma"],
                    lemma=row["lemma"],
                    pos=normalize_part_of_speech(row["pos"]),
                    raw_count=int(row["raw_count"]),
                    normalized_score=float(row["normalized_score"]),
                )
            return

        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.rsplit(maxsplit=1)
            if len(parts) != 2:
                raise ValueError(f"malformed frequency line {input_path}:{line_no}: {stripped!r}")
            term, raw_count = parts
            yield FrequencyEntry(term=term, raw_count=int(raw_count))


def _load_exact_lexeme_matches(
    conn: psycopg.Connection, entries: list[FrequencyEntry]
) -> dict[tuple[str, str], int]:
    exact_rows = [entry for entry in entries if entry.lemma and entry.pos]
    if not exact_rows:
        return {}

    lemmas = sorted({entry.lemma for entry in exact_rows if entry.lemma})
    rows = conn.execute(
        """
        select id, lemma, part_of_speech
        from lexicon.lexeme
        where lemma = any(%s)
        """,
        (lemmas,),
    ).fetchall()
    return {
        (str(lemma), str(part_of_speech)): int(lexeme_id)
        for lexeme_id, lemma, part_of_speech in rows
    }


_CLOSED_CLASS_LEMMA_POS = {
    "ei": "verb",
    "olla": "verb",
}
_FUNCTION_WORD_POS = frozenset({"pron", "conj", "aux", "adp"})


def _load_preferred_lemma_matches(
    conn: psycopg.Connection, entries: list[FrequencyEntry]
) -> dict[str, int]:
    lemma_rows = [entry for entry in entries if not entry.lemma and entry.term]
    if not lemma_rows:
        return {}

    lemmas = sorted({entry.term for entry in lemma_rows})
    rows = conn.execute(
        """
        select
            l.id,
            l.lemma,
            l.part_of_speech,
            (
                select count(*)
                from lexicon.lexeme_sense ls
                where ls.lexeme_id = l.id
                  and not ('form-of' = any(ls.labels))
            ) as sense_count,
            (
                select count(*)
                from lexicon.form f
                where f.lexeme_id = l.id
            ) as form_count
        from lexicon.lexeme l
        where l.lemma = any(%s)
          and l.is_lemma = true
        """,
        (lemmas,),
    ).fetchall()

    grouped: dict[str, list[tuple[int, str, int, int]]] = defaultdict(list)
    for lexeme_id, lemma, part_of_speech, sense_count, form_count in rows:
        grouped[str(lemma)].append(
            (int(lexeme_id), str(part_of_speech), int(sense_count), int(form_count))
        )

    preferred_matches: dict[str, int] = {}
    for lemma, candidates in grouped.items():
        sense_bearing = [candidate for candidate in candidates if candidate[2] > 0]
        if len(sense_bearing) == 1:
            preferred_matches[lemma] = sense_bearing[0][0]
        elif len(sense_bearing) > 1:
            # Prefer closed-class/function-word lemmas over metalinguistic noun
            # homographs (e.g. ``ei`` verb over ``ei`` noun "a no", ``minä`` pron
            # over ``minä`` noun "the ego"), then disambiguate by richness.
            best = max(
                sense_bearing,
                key=lambda c: (
                    1 if _CLOSED_CLASS_LEMMA_POS.get(lemma) == c[1] else 0,
                    1 if c[1] in _FUNCTION_WORD_POS else 0,
                    c[2],
                    c[3],
                    -c[0],
                ),
            )
            preferred_matches[lemma] = best[0]
    return preferred_matches


def _resolve_frequency_rows(
    conn: psycopg.Connection, entries: list[FrequencyEntry]
) -> list[tuple[int, int, float]]:
    exact_matches = _load_exact_lexeme_matches(conn, entries)
    preferred_lemma_matches = _load_preferred_lemma_matches(conn, entries)
    normalized_terms = {entry.term.casefold() for entry in entries if not entry.lemma and entry.term}
    lemma_terms = {entry.term for entry in entries if not entry.lemma and entry.term}
    analysis_matches = load_unique_analysis_matches(conn, normalized_terms)
    lemma_matches = load_unique_lemma_matches(conn, lemma_terms)
    form_matches = load_unique_form_matches(conn, normalized_terms)

    raw_counts_by_lexeme: dict[int, int] = defaultdict(int)
    provided_scores_by_lexeme: dict[int, float] = {}
    has_provided_scores = False

    for entry in entries:
        lexeme_id = None
        if entry.lemma and entry.pos:
            lexeme_id = exact_matches.get((entry.lemma, entry.pos))
            has_provided_scores = True
        else:
            lexeme_id = analysis_matches.get(entry.term.casefold())
            if lexeme_id is None:
                lexeme_id = lemma_matches.get(entry.term)
            if lexeme_id is None:
                lexeme_id = preferred_lemma_matches.get(entry.term)
            if lexeme_id is None:
                lexeme_id = form_matches.get(entry.term.casefold())

        if lexeme_id is None:
            continue

        raw_counts_by_lexeme[lexeme_id] += entry.raw_count
        if entry.normalized_score is not None:
            previous = provided_scores_by_lexeme.get(lexeme_id, 0.0)
            provided_scores_by_lexeme[lexeme_id] = max(previous, entry.normalized_score)

    if not raw_counts_by_lexeme:
        return []

    if has_provided_scores:
        return [
            (lexeme_id, raw_count, provided_scores_by_lexeme[lexeme_id])
            for lexeme_id, raw_count in raw_counts_by_lexeme.items()
            if lexeme_id in provided_scores_by_lexeme
        ]

    max_raw_count = max(raw_counts_by_lexeme.values())
    return [
        (lexeme_id, raw_count, raw_count / max_raw_count)
        for lexeme_id, raw_count in raw_counts_by_lexeme.items()
    ]


def _validate_frequency_replacement(
    conn,
    *,
    input_row_count: int,
    resolved_rows: list[tuple[int, int, float]],
) -> None:
    """Reject an implausibly sparse full-source replacement before mutating data."""

    resolved_count = len(resolved_rows)
    if input_row_count == 0:
        raise ValueError("frequency input contains no rows; refusing to replace existing data")
    if resolved_count == 0:
        raise ValueError(
            f"frequency input has {input_row_count} rows but matched no lexemes; "
            "refusing to replace existing data"
        )

    existing_row = conn.execute(
        """
        select count(distinct lexeme_id)
        from lexicon.frequency_signal
        where source_name = any(%s)
        """,
        (list(LEGACY_FREQUENCY_SOURCE_NAMES),),
    ).fetchone()
    existing_count = int(existing_row[0] or 0) if existing_row else 0

    if (
        input_row_count >= LARGE_FREQUENCY_INPUT_ROWS
        and resolved_count < MIN_LARGE_INPUT_RESOLVED_ROWS
    ):
        raise ValueError(
            f"frequency input has {input_row_count} rows but matched only {resolved_count} lexemes; "
            "refusing a likely source/schema mismatch"
        )
    if existing_count and resolved_count < existing_count * MIN_REPLACEMENT_RATIO:
        raise ValueError(
            f"frequency replacement would shrink matched lexemes from {existing_count} "
            f"to {resolved_count}; provide a complete source or use frequency review import"
        )


def ingest_frequency(
    input_path: Path,
    *,
    entries: list[FrequencyEntry] | None = None,
    connection: psycopg.Connection | None = None,
) -> None:
    entries = list(iter_frequency_entries(input_path)) if entries is None else entries
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        resolved_rows = _resolve_frequency_rows(conn, entries)
        _validate_frequency_replacement(
            conn,
            input_row_count=len(entries),
            resolved_rows=resolved_rows,
        )

        conn.execute(
            """
            delete from lexicon.frequency_signal
            where source_name = any(%s)
            """,
            (list(LEGACY_FREQUENCY_SOURCE_NAMES),),
        )
        conn.execute("update lexicon.lexeme set frequency_rank = null where frequency_rank is not null")

        ranked_rows = sorted(resolved_rows, key=lambda row: (-row[1], row[0]))

        conn.execute("drop table if exists tmp_frequency_resolved")
        conn.execute(
            """
            create temporary table tmp_frequency_resolved (
                rank integer not null,
                lexeme_id bigint primary key,
                raw_count bigint not null,
                normalized_score numeric(8, 5) not null
            ) on commit drop
            """
        )
        with conn.cursor() as cursor:
            with cursor.copy(
                """
                copy tmp_frequency_resolved (rank, lexeme_id, raw_count, normalized_score)
                from stdin
                """
            ) as copy:
                for rank, (lexeme_id, raw_count, normalized_score) in enumerate(
                    ranked_rows, start=1
                ):
                    copy.write_row((rank, lexeme_id, raw_count, round(normalized_score, 5)))

            cursor.execute(
                """
                insert into lexicon.frequency_signal (
                    lexeme_id, source_name, raw_count, normalized_score
                )
                select lexeme_id, %s, raw_count, normalized_score
                from tmp_frequency_resolved
                order by rank
                """,
                (FREQUENCY_SOURCE_NAME,),
            )
            cursor.execute(
                """
                update lexicon.lexeme l
                set frequency_rank = t.rank
                from tmp_frequency_resolved t
                where l.id = t.lexeme_id
                """
            )
        if owns_connection:
            conn.commit()
