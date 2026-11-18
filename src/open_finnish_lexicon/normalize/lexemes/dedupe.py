from open_finnish_lexicon.db import connect
from open_finnish_lexicon.normalize.lexemes.merge import (
    _cleanup_relation_duplicates,
    _merge_lexeme_into,
    _merge_no_sense_lexemes_bulk,
)


def normalize_lexemes() -> int:
    merged_count = 0
    with connect() as conn:
        duplicate_rows = conn.execute(
            """
            with duplicate_keys as (
                select
                    l.lemma,
                    lower(btrim(l.part_of_speech)) as normalized_pos
                from lexicon.lexeme l
                group by l.lemma, lower(btrim(l.part_of_speech))
                having count(*) > 1
            ),
            candidates as (
                select
                    l.id,
                    l.lemma,
                    l.part_of_speech,
                    dk.normalized_pos
                from lexicon.lexeme l
                join duplicate_keys dk
                  on dk.lemma = l.lemma
                 and dk.normalized_pos = lower(btrim(l.part_of_speech))
            ),
            sense_counts as (
                select ls.lexeme_id, count(*) as sense_count
                from lexicon.lexeme_sense ls
                where ls.lexeme_id in (select id from candidates)
                group by ls.lexeme_id
            ),
            form_counts as (
                select f.lexeme_id, count(*) as form_count
                from lexicon.form f
                where f.lexeme_id in (select id from candidates)
                group by f.lexeme_id
            ),
            scored as (
                select
                    c.id,
                    c.lemma,
                    c.normalized_pos,
                    coalesce(sc.sense_count, 0) as sense_count,
                    row_number() over (
                        partition by c.lemma, c.normalized_pos
                        order by
                            (c.part_of_speech = c.normalized_pos) desc,
                            coalesce(sc.sense_count, 0) desc,
                            coalesce(fc.form_count, 0) desc,
                            c.id asc
                    ) as preferred_rank
                from candidates c
                left join sense_counts sc on sc.lexeme_id = c.id
                left join form_counts fc on fc.lexeme_id = c.id
            )
            select id, lemma, normalized_pos, preferred_rank, sense_count
            from scored
            order by lemma, normalized_pos, preferred_rank, id
            """
        ).fetchall()

        grouped: dict[tuple[str, str], list[tuple[int, int, int]]] = {}
        for lexeme_id, lemma, normalized_pos, preferred_rank, sense_count in duplicate_rows:
            grouped.setdefault((lemma, normalized_pos), []).append(
                (int(lexeme_id), int(preferred_rank), int(sense_count))
            )

        no_sense_pairs: list[tuple[int, int]] = []
        sense_bearing_pairs: list[tuple[int, int]] = []
        target_pos_updates: list[tuple[str, int]] = []

        for (_lemma, normalized_pos), rows in grouped.items():
            target_id = next(
                lexeme_id for lexeme_id, preferred_rank, _sc in rows if preferred_rank == 1
            )
            target_pos_updates.append((normalized_pos, target_id))
            for source_id, _preferred_rank, sense_count in rows:
                if source_id == target_id:
                    continue
                if sense_count == 0:
                    no_sense_pairs.append((source_id, target_id))
                else:
                    sense_bearing_pairs.append((source_id, target_id))

        if target_pos_updates:
            with conn.cursor() as cursor:
                cursor.executemany(
                    "update lexicon.lexeme set part_of_speech = %s where id = %s and part_of_speech <> %s",
                    [(pos, tid, pos) for pos, tid in target_pos_updates],
                )

        if no_sense_pairs:
            _merge_no_sense_lexemes_bulk(conn, no_sense_pairs)
            merged_count += len(no_sense_pairs)

        for source_id, target_id in sense_bearing_pairs:
            _merge_lexeme_into(conn, source_id, target_id)
            merged_count += 1

        conn.execute(
            """
            update lexicon.lexeme l
            set part_of_speech = lower(btrim(l.part_of_speech))
            where l.part_of_speech <> lower(btrim(l.part_of_speech))
              and not exists (
                  select 1
                  from lexicon.lexeme other
                  where other.id <> l.id
                    and other.lemma = l.lemma
                    and other.part_of_speech = lower(btrim(l.part_of_speech))
              )
            """
        )
        _cleanup_relation_duplicates(conn)
        conn.commit()
    return merged_count
