from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import psycopg

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.normalize.lexemes.types import normalize_part_of_speech

SEMANTIC_RELATION_TYPES = frozenset(
    {
        "hypernym",
        "instance hypernym",
        "member holonym",
        "part holonym",
        "substance holonym",
        "similar to",
    }
)
MAX_SEMREL_SYNSET_WORDS = 4


@dataclass(frozen=True)
class FinnWordNetLexicalRelation:
    source_lemma: str
    source_pos: str
    target_lemma: str
    target_pos: str
    relation_type: str


@dataclass(frozen=True)
class FinnWordNetWordSense:
    synset_id: str
    word: str
    part_of_speech: str


@dataclass(frozen=True)
class FinnWordNetSemanticRelation:
    source_synset_id: str
    target_synset_id: str
    relation_type: str


def _map_synset_pos(synset_id: str) -> str:
    synset_code = synset_id.split(":", 1)[1][0]
    return {
        "n": "noun",
        "v": "verb",
        "a": "adj",
        "s": "adj",
        "r": "adv",
    }[synset_code]


def iter_finnwordnet_word_senses(input_path: Path) -> Iterable[FinnWordNetWordSense]:
    if not input_path.is_dir():
        return []

    wsenses_path = input_path / "fiwn-wsenses.tsv"
    if not wsenses_path.exists():
        return []

    rows: list[FinnWordNetWordSense] = []
    with wsenses_path.open(encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                raise ValueError(f"malformed FinnWordNet wsense at {wsenses_path}:{line_no}")
            synset_id, word = parts[0], parts[1]
            rows.append(
                FinnWordNetWordSense(
                    synset_id=synset_id,
                    word=word,
                    part_of_speech=_map_synset_pos(synset_id),
                )
            )
    return rows


def iter_finnwordnet_semantic_relations(input_path: Path) -> Iterable[FinnWordNetSemanticRelation]:
    if not input_path.is_dir():
        return []

    semrels_path = input_path / "fiwn-semrels.tsv"
    if not semrels_path.exists():
        return []

    rows: list[FinnWordNetSemanticRelation] = []
    with semrels_path.open(encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                raise ValueError(f"malformed FinnWordNet semrel at {semrels_path}:{line_no}")
            source_synset_id, target_synset_id, _symbol, relation_name = parts[:4]
            if relation_name not in SEMANTIC_RELATION_TYPES:
                continue
            rows.append(
                FinnWordNetSemanticRelation(
                    source_synset_id=source_synset_id,
                    target_synset_id=target_synset_id,
                    relation_type=relation_name,
                )
            )
    return rows


def iter_finnwordnet_relations(input_path: Path) -> Iterable[FinnWordNetLexicalRelation]:
    if input_path.is_dir():
        lexrels_path = input_path / "fiwn-lexrels.tsv"
        if not lexrels_path.exists():
            return []

        rows: list[FinnWordNetLexicalRelation] = []
        with lexrels_path.open(encoding="utf-8") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                line = raw_line.rstrip("\n")
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 6:
                    raise ValueError(f"malformed FinnWordNet lexrel at {lexrels_path}:{line_no}")
                (
                    source_synset_id,
                    source_word,
                    target_synset_id,
                    target_word,
                    _relation_symbol,
                    relation_name,
                ) = parts[:6]
                rows.append(
                    FinnWordNetLexicalRelation(
                        source_lemma=source_word,
                        source_pos=_map_synset_pos(source_synset_id),
                        target_lemma=target_word,
                        target_pos=_map_synset_pos(target_synset_id),
                        relation_type=relation_name,
                    )
                )
        return rows

    rows = []
    with input_path.open(encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 5:
                raise ValueError(f"malformed FinnWordNet TSV row at {input_path}:{line_no}")
            source_lemma, source_pos, target_lemma, target_pos, relation_type = parts
            rows.append(
                FinnWordNetLexicalRelation(
                    source_lemma=source_lemma,
                    source_pos=normalize_part_of_speech(source_pos),
                    target_lemma=target_lemma,
                    target_pos=normalize_part_of_speech(target_pos),
                    relation_type=relation_type,
                )
            )
    return rows


def _build_synset_relations(
    word_senses: Iterable[FinnWordNetWordSense],
    semantic_relations: Iterable[FinnWordNetSemanticRelation] = (),
) -> list[FinnWordNetLexicalRelation]:
    by_synset: dict[str, tuple[str, list[str]]] = {}
    raw_words: dict[str, list[str]] = defaultdict(list)
    synset_pos: dict[str, str] = {}
    for row in word_senses:
        synset_pos[row.synset_id] = row.part_of_speech
        raw_words[row.synset_id].append(row.word)

    for synset_id, words in raw_words.items():
        by_synset[synset_id] = (synset_pos[synset_id], list(dict.fromkeys(words)))

    relations: list[FinnWordNetLexicalRelation] = []
    for _synset_id, (part_of_speech, unique_words) in by_synset.items():
        for source_word in unique_words:
            for target_word in unique_words:
                if source_word == target_word:
                    continue
                relations.append(
                    FinnWordNetLexicalRelation(
                        source_lemma=source_word,
                        source_pos=part_of_speech,
                        target_lemma=target_word,
                        target_pos=part_of_speech,
                        relation_type="synonym",
                    )
                )

    for semrel in semantic_relations:
        src_entry = by_synset.get(semrel.source_synset_id)
        tgt_entry = by_synset.get(semrel.target_synset_id)
        if src_entry is None or tgt_entry is None:
            continue
        src_pos, src_words = src_entry
        tgt_pos, tgt_words = tgt_entry
        for source_word in src_words[:MAX_SEMREL_SYNSET_WORDS]:
            for target_word in tgt_words[:MAX_SEMREL_SYNSET_WORDS]:
                if source_word == target_word and src_pos == tgt_pos:
                    continue
                relations.append(
                    FinnWordNetLexicalRelation(
                        source_lemma=source_word,
                        source_pos=src_pos,
                        target_lemma=target_word,
                        target_pos=tgt_pos,
                        relation_type=semrel.relation_type,
                    )
                )
    return relations


def ingest_finnwordnet(
    input_path: Path,
    *,
    source_file_id: int | None = None,
    word_senses: list[FinnWordNetWordSense] | None = None,
    relations: list[FinnWordNetLexicalRelation] | None = None,
    semantic_relations: list[FinnWordNetSemanticRelation] | None = None,
    only_existing_lexemes: bool = False,
    connection: psycopg.Connection | None = None,
) -> None:
    word_senses = (
        list(iter_finnwordnet_word_senses(input_path)) if word_senses is None else word_senses
    )
    relations = list(iter_finnwordnet_relations(input_path)) if relations is None else relations
    semantic_relations = (
        list(iter_finnwordnet_semantic_relations(input_path))
        if semantic_relations is None
        else semantic_relations
    )
    if word_senses:
        relations.extend(_build_synset_relations(word_senses, semantic_relations))

    lexeme_pairs = {(row.source_lemma, row.source_pos) for row in relations} | {
        (row.target_lemma, row.target_pos) for row in relations
    }

    owns_connection = connection is None
    with connection_scope(connection) as conn:
        if source_file_id is not None:
            conn.execute("drop table if exists tmp_finnwordnet_relation_cleanup")
            conn.execute(
                """
                create temporary table tmp_finnwordnet_relation_cleanup (
                    relation_id bigint primary key
                ) on commit drop
                """
            )
            conn.execute(
                """
                insert into tmp_finnwordnet_relation_cleanup (relation_id)
                select distinct rls.relation_id
                from lexicon.lexical_relation_source rls
                join warehouse.source_file sf on sf.id = rls.source_file_id
                join warehouse.source_registry sr on sr.id = sf.source_registry_id
                where sr.name = 'finnwordnet'
                """
            )
            conn.execute(
                """
                delete from lexicon.lexical_relation_source rls
                using warehouse.source_file sf
                join warehouse.source_registry sr on sr.id = sf.source_registry_id
                where rls.source_file_id = sf.id
                  and sr.name = 'finnwordnet'
                """
            )
            conn.execute(
                """
                delete from lexicon.lexical_relation rel
                using tmp_finnwordnet_relation_cleanup cleanup
                where rel.id = cleanup.relation_id
                  and not exists (
                      select 1
                      from lexicon.lexical_relation_source ownership
                      where ownership.relation_id = rel.id
                  )
                """
            )

        with conn.cursor() as cursor:
            if not only_existing_lexemes and lexeme_pairs:
                conn.execute("drop table if exists tmp_finnwordnet_lexeme")
                conn.execute(
                    """
                    create temporary table tmp_finnwordnet_lexeme (
                        lemma text not null,
                        part_of_speech text not null
                    ) on commit drop
                    """
                )
                with cursor.copy(
                    "copy tmp_finnwordnet_lexeme (lemma, part_of_speech) from stdin"
                ) as copy:
                    for lemma, part_of_speech in sorted(lexeme_pairs):
                        copy.write_row((lemma, part_of_speech))
                cursor.execute(
                    """
                    insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                    select lemma, lemma, part_of_speech
                    from tmp_finnwordnet_lexeme
                    on conflict (lemma, part_of_speech) do update
                    set display_lemma = excluded.display_lemma
                    """
                )

            lexeme_query = (
                """
                select id, lemma, part_of_speech
                from lexicon.lexeme
                where lemma = any(%s)
                  and is_lemma = true
                """
                if only_existing_lexemes
                else """
                select id, lemma, part_of_speech
                from lexicon.lexeme
                where lemma = any(%s)
                """
            )
            lexeme_ids = {
                (str(lemma), str(part_of_speech)): int(lexeme_id)
                for lexeme_id, lemma, part_of_speech in conn.execute(
                    lexeme_query,
                    (sorted({lemma for lemma, _part_of_speech in lexeme_pairs}),),
                ).fetchall()
            }

            conn.execute("drop table if exists tmp_finnwordnet_relation")
            conn.execute(
                """
                create temporary table tmp_finnwordnet_relation (
                    source_lexeme_id bigint not null,
                    target_lexeme_id bigint not null,
                    relation_type text not null
                ) on commit drop
                """
            )
            with cursor.copy(
                """
                copy tmp_finnwordnet_relation (source_lexeme_id, target_lexeme_id, relation_type)
                from stdin
                """
            ) as copy:
                seen: set[tuple[int, int, str]] = set()
                for row in relations:
                    source_id = lexeme_ids.get((row.source_lemma, row.source_pos))
                    target_id = lexeme_ids.get((row.target_lemma, row.target_pos))
                    if source_id is None or target_id is None:
                        continue
                    key = (source_id, target_id, row.relation_type)
                    if key in seen:
                        continue
                    seen.add(key)
                    copy.write_row(key)

            if source_file_id is not None:
                cursor.execute(
                    """
                    with inserted as (
                        insert into lexicon.lexical_relation (
                            source_lexeme_id,
                            target_lexeme_id,
                            relation_type,
                            confidence
                        )
                        select source_lexeme_id, target_lexeme_id, relation_type, 1.0
                        from tmp_finnwordnet_relation
                        returning id
                    )
                    insert into lexicon.lexical_relation_source (relation_id, source_file_id)
                    select id, %s
                    from inserted
                    on conflict do nothing
                    """,
                    (source_file_id,),
                )
            else:
                cursor.execute(
                    """
                    insert into lexicon.lexical_relation (
                        source_lexeme_id,
                        target_lexeme_id,
                        relation_type,
                        confidence
                    )
                    select source_lexeme_id, target_lexeme_id, relation_type, 1.0
                    from tmp_finnwordnet_relation
                    """
                )
        if owns_connection:
            conn.commit()
