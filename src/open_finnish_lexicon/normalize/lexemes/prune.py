from open_finnish_lexicon.db import connect
from open_finnish_lexicon.normalize.lexemes.merge import (
    _cleanup_relation_duplicates,
    _delete_lexeme_ids_in_batches,
    _merge_no_sense_lexemes_bulk,
)

def _prune_relation_only_empty_lexemes(conn) -> int:
    conn.execute(
        """
        create temporary table tmp_relation_only_empty_lexeme (
            lexeme_id bigint primary key
        ) on commit drop
        """
    )
    conn.execute("truncate tmp_relation_only_empty_lexeme")
    conn.execute(
        """
        insert into tmp_relation_only_empty_lexeme (lexeme_id)
        select l.id
        from lexicon.lexeme l
        where not exists (
                select 1
                from lexicon.lexeme_sense s
                where s.lexeme_id = l.id
            )
          and not exists (
                select 1
                from lexicon.form f
                where f.lexeme_id = l.id
            )
          and not exists (
                select 1
                from lexicon.form_analysis fa
                where fa.lexeme_id = l.id
            )
          and not exists (
                select 1
                from lexicon.frequency_signal fs
                where fs.lexeme_id = l.id
            )
          and not exists (
                select 1
                from lexicon.pronunciation p
                where p.lexeme_id = l.id
            )
          and not exists (
                select 1
                from lexicon.derivation_relation d
                where d.parent_lexeme_id = l.id
                   or d.child_lexeme_id = l.id
            )
          and not exists (
                select 1
                from lexicon.grammar_note gn
                where gn.lexeme_id = l.id
            )
          and not exists (
                select 1
                from lexicon.usage_warning uw
                where uw.lexeme_id = l.id
            )
          and exists (
                select 1
                from lexicon.lexical_relation r
                where r.source_lexeme_id = l.id
                   or r.target_lexeme_id = l.id
            )
        """
    )
    doomed_ids = [
        row[0]
        for row in conn.execute(
            "select lexeme_id from tmp_relation_only_empty_lexeme order by lexeme_id"
        ).fetchall()
    ]
    if not doomed_ids:
        return 0

    conn.execute(
        """
        delete from lexicon.lexical_relation r
        where exists (
            select 1
            from tmp_relation_only_empty_lexeme doomed
            where doomed.lexeme_id = r.source_lexeme_id
               or doomed.lexeme_id = r.target_lexeme_id
        )
        """
    )
    _delete_lexeme_ids_in_batches(conn, doomed_ids)
    return len(doomed_ids)


def prune_empty_lexemes() -> int:
    with connect() as conn:
        relation_only_pruned_count = _prune_relation_only_empty_lexemes(conn)
        prune_rows = conn.execute(
                """
                with no_sense as (
                    select l.id, l.lemma
                    from lexicon.lexeme l
                    where not exists (
                        select 1
                        from lexicon.lexeme_sense s
                        where s.lexeme_id = l.id
                    )
                ),
                form_counts as (
                    select lexeme_id, count(*) as form_count
                    from lexicon.form
                    where lexeme_id in (select id from no_sense)
                    group by lexeme_id
                ),
                analysis_ids as (
                    select distinct lexeme_id
                    from lexicon.form_analysis
                    where lexeme_id in (select id from no_sense)
                ),
                pronunciation_ids as (
                    select distinct lexeme_id
                    from lexicon.pronunciation
                    where lexeme_id in (select id from no_sense)
                ),
                derivation_ids as (
                    select distinct lexeme_id
                    from (
                        select parent_lexeme_id as lexeme_id
                        from lexicon.derivation_relation
                        where parent_lexeme_id in (select id from no_sense)
                        union
                        select child_lexeme_id as lexeme_id
                        from lexicon.derivation_relation
                        where child_lexeme_id in (select id from no_sense)
                    ) unioned
                ),
                relation_ids as (
                    select distinct lexeme_id
                    from (
                        select source_lexeme_id as lexeme_id
                        from lexicon.lexical_relation
                        where source_lexeme_id in (select id from no_sense)
                        union
                        select target_lexeme_id as lexeme_id
                        from lexicon.lexical_relation
                        where target_lexeme_id in (select id from no_sense)
                    ) unioned
                ),
                frequency_ids as (
                    select distinct lexeme_id
                    from lexicon.frequency_signal
                    where lexeme_id in (select id from no_sense)
                ),
                note_ids as (
                    select distinct lexeme_id
                    from lexicon.grammar_note
                    where lexeme_id in (select id from no_sense)
                ),
                warning_ids as (
                    select distinct lexeme_id
                    from lexicon.usage_warning
                    where lexeme_id in (select id from no_sense)
                ),
                sense_counts as (
                    select lexeme_id, count(*) as sense_count
                    from lexicon.lexeme_sense
                    group by lexeme_id
                ),
                merge_targets as (
                    select
                        n.id as source_id,
                        sibling.id as target_id,
                        row_number() over (
                            partition by n.id
                            order by
                                coalesce(sc.sense_count, 0) desc,
                                sibling.id asc
                        ) as preferred_rank
                    from no_sense n
                    join lexicon.lexeme sibling
                      on sibling.lemma = n.lemma
                     and sibling.id <> n.id
                    join sense_counts sc on sc.lexeme_id = sibling.id
                )
                select n.id, mt.target_id
                from no_sense n
                left join form_counts f on f.lexeme_id = n.id
                left join analysis_ids fa on fa.lexeme_id = n.id
                left join pronunciation_ids p on p.lexeme_id = n.id
                left join derivation_ids d on d.lexeme_id = n.id
                left join relation_ids r on r.lexeme_id = n.id
                left join frequency_ids fs on fs.lexeme_id = n.id
                left join note_ids gn on gn.lexeme_id = n.id
                left join warning_ids uw on uw.lexeme_id = n.id
                left join merge_targets mt
                  on mt.source_id = n.id
                 and mt.preferred_rank = 1
                where p.lexeme_id is null
                  and r.lexeme_id is null
                  and (
                      (
                          mt.target_id is not null
                      )
                      or (
                          coalesce(f.form_count, 0) <= 1
                          and fa.lexeme_id is null
                          and d.lexeme_id is null
                          and fs.lexeme_id is null
                          and gn.lexeme_id is null
                          and uw.lexeme_id is null
                      )
                  )
                """
        ).fetchall()
        doomed_ids = [row[0] for row in prune_rows if row[1] is None]
        merge_pairs = [(row[0], row[1]) for row in prune_rows if row[1] is not None]

        _merge_no_sense_lexemes_bulk(conn, merge_pairs)

        if not doomed_ids:
            if merge_pairs:
                _cleanup_relation_duplicates(conn)
                conn.commit()
            elif relation_only_pruned_count:
                conn.commit()
            return relation_only_pruned_count + len(merge_pairs)

        conn.execute("delete from lexicon.form where lexeme_id = any(%s)", (doomed_ids,))
        _delete_lexeme_ids_in_batches(conn, doomed_ids)
        _cleanup_relation_duplicates(conn)
        conn.commit()
        return relation_only_pruned_count + len(doomed_ids) + len(merge_pairs)
