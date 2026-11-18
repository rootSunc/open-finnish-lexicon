from open_finnish_lexicon.config import get_pipeline_settings
from open_finnish_lexicon.db import connect

_EDGE_STOP_WORDS = [
    "ja",
    "tai",
    "mutta",
    "sekä",
    "että",
    "jos",
    "kun",
    "koska",
    "kuin",
    "vai",
    "eli",
    "vaikka",
    "jotta",
    "niin",
    "siis",
    "nyt",
    "jo",
    "vielä",
    "myös",
    "vain",
    "ehkä",
    "kai",
    "aina",
    "usein",
    "hyvin",
    "erittäin",
    "aika",
    "melko",
    "liian",
    "noin",
    "tänään",
    "eilen",
    "huomenna",
    "täällä",
    "siellä",
    "tuolla",
    "tässä",
    "siinä",
    "tuossa",
    "tähän",
    "siihen",
    "tuohon",
    "minä",
    "sinä",
    "hän",
    "me",
    "te",
    "he",
    "mä",
    "sä",
    "minun",
    "sinun",
    "hänen",
    "meidän",
    "teidän",
    "heidän",
    "minut",
    "sinut",
    "hänet",
    "minua",
    "sinua",
    "häntä",
    "se",
    "sen",
    "sitä",
    "ne",
    "niiden",
    "niitä",
    "tämä",
    "tämän",
    "tätä",
    "nämä",
    "tuo",
    "tuon",
    "tuota",
    "nuo",
    "joka",
    "jonka",
    "jota",
    "jotka",
    "mikä",
    "minkä",
    "mitä",
    "kuka",
    "kenen",
    "ketä",
    "kaikki",
    "jokainen",
    "moni",
    "muu",
    "sama",
    "oma",
    "eri",
    "koko",
    "itse",
    "yksi",
    "kaksi",
    "kolme",
    "on",
    "oli",
    "ovat",
    "olivat",
    "ole",
    "ollut",
    "olla",
    "ei",
    "en",
    "et",
    "emme",
    "ette",
    "eivät",
    "älä",
    "älkää",
    "voi",
    "voisi",
    "täytyy",
    "pitää",
]

_TOKEN_PATTERN = r"([[:alnum:]ÅÄÖåäö]+(?:-[[:alnum:]ÅÄÖåäö]+)*)"
_ALPHA_TOKEN_PATTERN = r"^[[:alpha:]ÅÄÖåäö-]+$"
_DIGIT_PATTERN = r"[[:digit:]]"


def rebuild_collocations(*, min_examples: int | None = None) -> int:
    """Extract statistically recurring multi-word collocations from sense examples.

    Materializing tokenized examples once into an indexed temporary table keeps
    the multi-window n-gram joins linear in example count instead of repeatedly
    scanning ``sense_example x example``.
    """

    if min_examples is None:
        min_examples = 3 if get_pipeline_settings().data_profile == "real" else 2
    if min_examples < 1:
        raise ValueError("min_examples must be >= 1")

    with connect() as conn:
        conn.execute(
            """
            create temporary table if not exists tmp_collocation_active_sense (
                sense_id bigint primary key,
                lexeme_id bigint not null,
                part_of_speech text not null
            ) on commit drop
            """
        )
        conn.execute("truncate tmp_collocation_active_sense")
        conn.execute(
            """
            insert into tmp_collocation_active_sense (sense_id, lexeme_id, part_of_speech)
            select ls.id, ls.lexeme_id, l.part_of_speech
            from lexicon.lexeme_sense ls
            join lexicon.lexeme l on l.id = ls.lexeme_id
            where l.is_lemma = true
              and not ('form-of' = any(ls.labels))
              and exists (
                  select 1
                  from lexicon.sense_example se
                  where se.sense_id = ls.id
              )
            """
        )
        conn.execute(
            """
            create index if not exists idx_tmp_collocation_sense_lexeme
            on tmp_collocation_active_sense (lexeme_id)
            """
        )
        conn.execute("analyze tmp_collocation_active_sense")

        conn.execute(
            """
            create temporary table if not exists tmp_collocation_example_token (
                example_id bigint not null,
                token_index integer not null,
                normalized_token text not null,
                has_digit boolean not null,
                can_edge boolean not null,
                primary key (example_id, token_index)
            ) on commit drop
            """
        )
        conn.execute("truncate tmp_collocation_example_token")
        conn.execute(
            """
            insert into tmp_collocation_example_token (
                example_id, token_index, normalized_token, has_digit, can_edge
            )
            with eligible_examples as (
                select distinct e.id, e.text_fi
                from tmp_collocation_active_sense ts
                join lexicon.sense_example se on se.sense_id = ts.sense_id
                join lexicon.example e on e.id = se.example_id
                where e.quality_score >= 0.70
                  and char_length(e.text_fi) <= 240
            )
            select
                ex.id,
                token_row.ordinality::integer,
                lower((token_row.match)[1]),
                (token_row.match)[1] ~ %s,
                char_length((token_row.match)[1]) > 1
                  and (token_row.match)[1] !~ %s
                  and lower((token_row.match)[1]) <> all(%s::text[])
            from eligible_examples ex
            cross join lateral regexp_matches(ex.text_fi, %s, 'g')
                with ordinality as token_row(match, ordinality)
            """,
            (_DIGIT_PATTERN, _DIGIT_PATTERN, _EDGE_STOP_WORDS, _TOKEN_PATTERN),
        )
        conn.execute(
            """
            create index if not exists idx_tmp_collocation_token_norm
            on tmp_collocation_example_token (normalized_token)
            """
        )
        conn.execute("analyze tmp_collocation_example_token")

        conn.execute(
            """
            create temporary table if not exists tmp_collocation_lexeme_form (
                lexeme_id bigint not null,
                form text not null,
                primary key (lexeme_id, form)
            ) on commit drop
            """
        )
        conn.execute("truncate tmp_collocation_lexeme_form")
        conn.execute(
            """
            insert into tmp_collocation_lexeme_form (lexeme_id, form)
            select distinct
                al.lexeme_id,
                lower(f.normalized_form)
            from (select distinct lexeme_id from tmp_collocation_active_sense) al
            join lexicon.form f on f.lexeme_id = al.lexeme_id
            where char_length(f.normalized_form) between 2 and 40
              and f.normalized_form ~ %s
              and f.normalized_form !~ %s
            """,
            (_ALPHA_TOKEN_PATTERN, _DIGIT_PATTERN),
        )
        conn.execute("analyze tmp_collocation_lexeme_form")

        conn.execute(
            """
            create temporary table if not exists tmp_collocation_hit (
                lexeme_id bigint not null,
                sense_id bigint not null,
                part_of_speech text not null,
                example_id bigint not null,
                token_index integer not null,
                normalized_token text not null
            ) on commit drop
            """
        )
        conn.execute("truncate tmp_collocation_hit")
        conn.execute(
            """
            insert into tmp_collocation_hit (
                lexeme_id, sense_id, part_of_speech, example_id, token_index, normalized_token
            )
            select
                s.lexeme_id,
                s.sense_id,
                s.part_of_speech,
                se.example_id,
                t.token_index,
                t.normalized_token
            from tmp_collocation_active_sense s
            join lexicon.sense_example se on se.sense_id = s.sense_id
            join tmp_collocation_example_token t
              on t.example_id = se.example_id
             and t.has_digit = false
            join tmp_collocation_lexeme_form tf
              on tf.lexeme_id = s.lexeme_id
             and tf.form = t.normalized_token
            """
        )
        conn.execute("analyze tmp_collocation_hit")

        conn.execute("delete from lexicon.collocation where source_label = 'example-window'")
        inserted = conn.execute(
            """
            insert into lexicon.collocation (lexeme_id, sense_id, phrase, score, source_label)
            with token_doc_freq as (
                select normalized_token, count(distinct example_id)::double precision as doc_freq
                from tmp_collocation_example_token
                group by normalized_token
            ),
            corpus_stats as (
                select greatest(count(distinct example_id), 1)::double precision as total_examples
                from tmp_collocation_example_token
            ),
            candidates as (
                select
                    h.lexeme_id,
                    h.sense_id,
                    h.example_id,
                    concat_ws(' ', p1.normalized_token, h.normalized_token) as phrase,
                    p1.normalized_token as collocate_token,
                    3.0::double precision as base_weight
                from tmp_collocation_hit h
                join tmp_collocation_example_token p1
                  on p1.example_id = h.example_id
                 and p1.token_index = h.token_index - 1
                where p1.can_edge
                union all
                select
                    h.lexeme_id,
                    h.sense_id,
                    h.example_id,
                    concat_ws(' ', h.normalized_token, n1.normalized_token) as phrase,
                    n1.normalized_token as collocate_token,
                    2.5::double precision as base_weight
                from tmp_collocation_hit h
                join tmp_collocation_example_token n1
                  on n1.example_id = h.example_id
                 and n1.token_index = h.token_index + 1
                where n1.can_edge
                  and h.part_of_speech in ('verb', 'adv')
                union all
                select
                    h.lexeme_id,
                    h.sense_id,
                    h.example_id,
                    concat_ws(' ', p2.normalized_token, p1.normalized_token, h.normalized_token) as phrase,
                    p1.normalized_token as collocate_token,
                    1.5::double precision as base_weight
                from tmp_collocation_hit h
                join tmp_collocation_example_token p1
                  on p1.example_id = h.example_id
                 and p1.token_index = h.token_index - 1
                join tmp_collocation_example_token p2
                  on p2.example_id = h.example_id
                 and p2.token_index = h.token_index - 2
                where p1.can_edge and p2.can_edge
                union all
                select
                    h.lexeme_id,
                    h.sense_id,
                    h.example_id,
                    concat_ws(' ', h.normalized_token, n1.normalized_token, n2.normalized_token) as phrase,
                    n1.normalized_token as collocate_token,
                    1.2::double precision as base_weight
                from tmp_collocation_hit h
                join tmp_collocation_example_token n1
                  on n1.example_id = h.example_id
                 and n1.token_index = h.token_index + 1
                join tmp_collocation_example_token n2
                  on n2.example_id = h.example_id
                 and n2.token_index = h.token_index + 2
                where n1.can_edge and n2.can_edge
                  and h.part_of_speech in ('verb', 'adv')
            ),
            aggregated as (
                select
                    c.lexeme_id,
                    c.sense_id,
                    c.phrase,
                    count(distinct c.example_id) as example_hits,
                    sum(c.base_weight) as weight_sum,
                    max(coalesce(tdf.doc_freq, 1.0)) as collocate_df
                from candidates c
                left join token_doc_freq tdf on tdf.normalized_token = c.collocate_token
                where char_length(c.phrase) between 4 and 80
                group by c.lexeme_id, c.sense_id, c.phrase
                having count(distinct c.example_id) >= %s
            )
            select
                a.lexeme_id,
                a.sense_id,
                a.phrase,
                least(
                    round(
                        (
                            a.weight_sum
                            * greatest(
                                1.0,
                                ln((cs.total_examples * a.example_hits) / greatest(a.collocate_df, 1.0))
                            )
                        )::numeric,
                        5
                    ),
                    999.0
                ),
                'example-window'
            from aggregated a
            cross join corpus_stats cs
            """,
            (min_examples,),
        ).rowcount
        conn.commit()
    return int(inserted or 0)
