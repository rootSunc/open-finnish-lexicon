from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.normalize.lexemes.types import normalize_part_of_speech


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
    for line in wsenses_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        synset_id, word, *_rest = line.split("\t")
        rows.append(
            FinnWordNetWordSense(
                synset_id=synset_id,
                word=word,
                part_of_speech=_map_synset_pos(synset_id),
            )
        )
    return rows


def iter_finnwordnet_relations(input_path: Path) -> Iterable[FinnWordNetLexicalRelation]:
    if input_path.is_dir():
        lexrels_path = input_path / "fiwn-lexrels.tsv"
        if not lexrels_path.exists():
            return []

        rows: list[FinnWordNetLexicalRelation] = []
        for line in lexrels_path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            (
                source_synset_id,
                source_word,
                target_synset_id,
                target_word,
                _relation_symbol,
                relation_name,
            ) = line.split("\t")
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
    for line in input_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        source_lemma, source_pos, target_lemma, target_pos, relation_type = line.split("\t")
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


def _build_synonym_relations(
    word_senses: Iterable[FinnWordNetWordSense],
) -> list[FinnWordNetLexicalRelation]:
    by_synset: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in word_senses:
        by_synset[(row.synset_id, row.part_of_speech)].append(row.word)

    relations: list[FinnWordNetLexicalRelation] = []
    for (_synset_id, part_of_speech), words in by_synset.items():
        unique_words = list(dict.fromkeys(words))
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
    return relations


def ingest_finnwordnet(
    input_path: Path,
    *,
    source_file_id: int | None = None,
    word_senses: list[FinnWordNetWordSense] | None = None,
    relations: list[FinnWordNetLexicalRelation] | None = None,
    connection=None,
) -> None:
    word_senses = (
        list(iter_finnwordnet_word_senses(input_path)) if word_senses is None else word_senses
    )
    relations = list(iter_finnwordnet_relations(input_path)) if relations is None else relations
    if word_senses:
        relations.extend(_build_synonym_relations(word_senses))

    lexeme_pairs = {(row.source_lemma, row.source_pos) for row in relations} | {
        (row.target_lemma, row.target_pos) for row in relations
    }

    owns_connection = connection is None
    with connection_scope(connection) as conn:
        if source_file_id is None:
            source_file_row = conn.execute(
                """
                select sf.id
                from warehouse.source_file sf
                join warehouse.source_registry sr on sr.id = sf.source_registry_id
                where sr.name = 'finnwordnet' and sf.local_path = %s
                order by (sf.snapshot_state = 'pending') desc, sf.imported_at desc, sf.id desc
                limit 1
                """,
                (str(input_path),),
            ).fetchone()
            source_file_id = int(source_file_row[0]) if source_file_row else None
        if source_file_id is not None:
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
                """,
            )
            conn.execute(
                """
                delete from lexicon.lexical_relation_source rls
                using warehouse.source_file sf
                join warehouse.source_registry sr on sr.id = sf.source_registry_id
                where rls.source_file_id = sf.id
                  and sr.name = 'finnwordnet'
                """,
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
            cursor.executemany(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                values (%s, %s, %s)
                on conflict (lemma, part_of_speech) do update set display_lemma = excluded.display_lemma
                """,
                [(lemma, lemma, part_of_speech) for lemma, part_of_speech in sorted(lexeme_pairs)],
            )

            lexeme_ids = {
                (lemma, part_of_speech): lexeme_id
                for lexeme_id, lemma, part_of_speech in conn.execute(
                    """
                    select id, lemma, part_of_speech
                    from lexicon.lexeme
                    where lemma = any(%s)
                    """,
                    ([lemma for lemma, _part_of_speech in lexeme_pairs],),
                ).fetchall()
            }

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
                seen = set()
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

            if source_file_id is None:
                conn.execute(
                    """
                    delete from lexicon.lexical_relation rel
                    using tmp_finnwordnet_relation tmp
                    where rel.source_lexeme_id = tmp.source_lexeme_id
                      and rel.target_lexeme_id = tmp.target_lexeme_id
                      and rel.relation_type = tmp.relation_type
                    """
                )
            inserted_relations = cursor.execute(
                """
                insert into lexicon.lexical_relation (
                    source_lexeme_id,
                    target_lexeme_id,
                    relation_type,
                    confidence
                )
                select source_lexeme_id, target_lexeme_id, relation_type, 1.0
                from tmp_finnwordnet_relation
                returning id, source_lexeme_id, target_lexeme_id, relation_type
                """
            ).fetchall()
            if source_file_id is not None and inserted_relations:
                cursor.executemany(
                    """
                    insert into lexicon.lexical_relation_source (relation_id, source_file_id)
                    values (%s, %s)
                    on conflict do nothing
                    """,
                    [(relation_id, source_file_id) for relation_id, *_rest in inserted_relations],
                )
        if owns_connection:
            conn.commit()
