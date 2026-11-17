from open_finnish_lexicon.db import connect
from open_finnish_lexicon.normalize.lexemes.merge import (
    _cleanup_relation_duplicates,
    _merge_lexeme_into,
)

def normalize_lexemes() -> int:
    merged_count = 0
    with connect() as conn:
        duplicate_rows = conn.execute(
            """
            with scored as (
                select
                    l.id,
                    l.lemma,
                    lower(l.part_of_speech) as normalized_pos,
                    l.part_of_speech,
                    (
                        select count(*)
                        from lexicon.lexeme_sense ls
                        where ls.lexeme_id = l.id
                    ) as sense_count,
                    (
                        select count(*)
                        from lexicon.form f
                        where f.lexeme_id = l.id
                    ) as form_count,
                    row_number() over (
                        partition by l.lemma, lower(l.part_of_speech)
                        order by
                            (l.part_of_speech = lower(l.part_of_speech)) desc,
                            (
                                select count(*)
                                from lexicon.lexeme_sense ls
                                where ls.lexeme_id = l.id
                            ) desc,
                            (
                                select count(*)
                                from lexicon.form f
                                where f.lexeme_id = l.id
                            ) desc,
                            l.id asc
                    ) as preferred_rank
                from lexicon.lexeme l
            )
            select id, lemma, normalized_pos, preferred_rank
            from scored
            where exists (
                select 1
                from scored siblings
                where siblings.lemma = scored.lemma
                  and siblings.normalized_pos = scored.normalized_pos
                  and siblings.id <> scored.id
            )
            order by lemma, normalized_pos, preferred_rank, id
            """
        ).fetchall()

        grouped: dict[tuple[str, str], list[tuple[int, int]]] = {}
        for lexeme_id, lemma, normalized_pos, preferred_rank in duplicate_rows:
            grouped.setdefault((lemma, normalized_pos), []).append((lexeme_id, preferred_rank))

        for (lemma, normalized_pos), rows in grouped.items():
            target_id = next(lexeme_id for lexeme_id, preferred_rank in rows if preferred_rank == 1)
            conn.execute(
                """
                update lexicon.lexeme
                set part_of_speech = %s
                where id = %s
                """,
                (normalized_pos, target_id),
            )
            for source_id, preferred_rank in rows:
                if source_id == target_id:
                    continue
                _merge_lexeme_into(conn, source_id, target_id)
                merged_count += 1

        conn.execute(
            """
            update lexicon.lexeme l
            set part_of_speech = lower(l.part_of_speech)
            where l.part_of_speech <> lower(l.part_of_speech)
              and not exists (
                  select 1
                  from lexicon.lexeme other
                  where other.id <> l.id
                    and other.lemma = l.lemma
                    and other.part_of_speech = lower(l.part_of_speech)
              )
            """
        )
        _cleanup_relation_duplicates(conn)
        conn.commit()
    return merged_count
