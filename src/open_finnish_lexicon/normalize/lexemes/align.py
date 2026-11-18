from open_finnish_lexicon.db import connect
from open_finnish_lexicon.normalize.lexemes.merge import (
    _cleanup_relation_duplicates,
    _merge_no_sense_lexemes_bulk,
)


def align_surface_forms_to_sense_lexemes() -> int:
    with connect() as conn:
        singleton_merge_rows = [
            (int(source_id), int(target_id))
            for source_id, target_id in conn.execute(
                """
                with unique_sense_targets as (
                    select
                        lower(l.lemma) as normalized_lemma,
                        min(l.id) as target_id
                    from lexicon.lexeme l
                    where exists (
                        select 1
                        from lexicon.lexeme_sense s
                        where s.lexeme_id = l.id
                    )
                    group by lower(l.lemma)
                    having count(*) = 1
                ),
                form_only_stats as (
                    select
                        l.id as source_id,
                        min(f.normalized_form) as normalized_form,
                        count(distinct f.normalized_form) as normalized_form_count
                    from lexicon.lexeme l
                    join lexicon.form f on f.lexeme_id = l.id
                    where not exists (
                        select 1
                        from lexicon.lexeme_sense s
                        where s.lexeme_id = l.id
                    )
                    group by l.id
                )
                select source_id, target_id
                from form_only_stats fs
                join unique_sense_targets st on st.normalized_lemma = fs.normalized_form
                where fs.normalized_form_count = 1
                  and fs.source_id <> st.target_id
                order by source_id
                """
            ).fetchall()
        ]

        singleton_merge_count = len(singleton_merge_rows)
        if singleton_merge_rows:
            _merge_no_sense_lexemes_bulk(conn, singleton_merge_rows)

        conn.execute(
            """
            create temporary table if not exists tmp_form_row_alignment (
                form_id bigint primary key,
                source_id bigint not null,
                target_id bigint not null,
                normalized_form text not null
            ) on commit drop
            """
        )
        conn.execute("truncate tmp_form_row_alignment")
        conn.execute(
            """
            insert into tmp_form_row_alignment (form_id, source_id, target_id, normalized_form)
            with unique_sense_targets as (
                select
                    lower(l.lemma) as normalized_lemma,
                    min(l.id) as target_id
                from lexicon.lexeme l
                where exists (
                    select 1
                    from lexicon.lexeme_sense s
                    where s.lexeme_id = l.id
                )
                group by lower(l.lemma)
                having count(*) = 1
            ),
            multi_form_sources as (
                select
                    l.id as source_id,
                    count(distinct f.normalized_form) as normalized_form_count,
                    count(distinct fs.id) as frequency_signal_count
                from lexicon.lexeme l
                join lexicon.form f on f.lexeme_id = l.id
                left join lexicon.frequency_signal fs on fs.lexeme_id = l.id
                where not exists (
                    select 1
                    from lexicon.lexeme_sense s
                    where s.lexeme_id = l.id
                )
                group by l.id
            )
            select
                f.id,
                f.lexeme_id,
                st.target_id,
                f.normalized_form
            from lexicon.form f
            join multi_form_sources ms on ms.source_id = f.lexeme_id
            join unique_sense_targets st on st.normalized_lemma = f.normalized_form
            where ms.normalized_form_count > 1
              and ms.frequency_signal_count = 0
              and f.lexeme_id <> st.target_id
            """
        )

        count_row = conn.execute("select count(*) from tmp_form_row_alignment").fetchone()
        moved_form_count = int(count_row[0]) if count_row else 0
        if moved_form_count:
            conn.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                select
                    a.target_id,
                    f.surface_form,
                    f.normalized_form,
                    f.form_kind,
                    f.features
                from tmp_form_row_alignment a
                join lexicon.form f on f.id = a.form_id
                on conflict do nothing
                """
            )
            conn.execute(
                """
                insert into lexicon.form_source (form_id, source_file_id)
                select distinct target.id, ownership.source_file_id
                from tmp_form_row_alignment a
                join lexicon.form source on source.id = a.form_id
                join lexicon.form_source ownership on ownership.form_id = source.id
                join lexicon.form target
                  on target.lexeme_id = a.target_id
                 and target.surface_form = source.surface_form
                 and target.normalized_form = source.normalized_form
                 and target.form_kind = source.form_kind
                 and target.features = source.features
                on conflict do nothing
                """
            )
            conn.execute(
                """
                insert into lexicon.form_analysis (
                    normalized_query,
                    lexeme_id,
                    analysis_rank,
                    confidence,
                    features
                )
                select distinct
                    fa.normalized_query,
                    a.target_id,
                    fa.analysis_rank,
                    fa.confidence,
                    fa.features
                from tmp_form_row_alignment a
                join lexicon.form_analysis fa
                  on fa.lexeme_id = a.source_id
                 and fa.normalized_query = a.normalized_form
                where not exists (
                    select 1
                    from lexicon.form_analysis existing
                    where existing.lexeme_id = a.target_id
                      and existing.normalized_query = fa.normalized_query
                      and existing.analysis_rank = fa.analysis_rank
                      and existing.confidence = fa.confidence
                      and existing.features = fa.features
                )
                """
            )
            conn.execute(
                """
                delete from lexicon.form_analysis fa
                using tmp_form_row_alignment a
                where fa.lexeme_id = a.source_id
                  and fa.normalized_query = a.normalized_form
                """
            )
            conn.execute(
                """
                delete from lexicon.form f
                using tmp_form_row_alignment a
                where f.id = a.form_id
                """
            )

        _cleanup_relation_duplicates(conn)
        conn.commit()
        return singleton_merge_count + moved_form_count
