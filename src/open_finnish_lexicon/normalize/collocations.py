from open_finnish_lexicon.db import connect


_TOKEN_PATTERN = r"[[:alpha:]ÅÄÖåäö]+(?:[-'][[:alpha:]ÅÄÖåäö]+)*|[0-9]+"
_ALPHA_TOKEN_PATTERN = r"^[[:alpha:]ÅÄÖåäö]+(?:[-'][[:alpha:]ÅÄÖåäö]+)*$"
_DIGIT_PATTERN = r"[0-9]"
_EDGE_STOP_WORDS = [
    "aika",
    "aina",
    "eli",
    "en",
    "ennen",
    "että",
    "ette",
    "eivät",
    "ei",
    "emme",
    "hän",
    "he",
    "ja",
    "joka",
    "jotka",
    "jos",
    "jotta",
    "koska",
    "kuin",
    "kun",
    "alice",
    "betty",
    "bill",
    "bob",
    "jack",
    "jane",
    "john",
    "ken",
    "mary",
    "mike",
    "minä",
    "me",
    "mutta",
    "ne",
    "nämä",
    "niin",
    "nuo",
    "nyt",
    "oli",
    "olin",
    "olit",
    "olivat",
    "olimme",
    "olitte",
    "ole",
    "olen",
    "olet",
    "olemme",
    "olette",
    "on",
    "ovat",
    "se",
    "sekä",
    "sitten",
    "sinä",
    "tai",
    "te",
    "tom",
    "tuo",
    "tämä",
    "vaikka",
    "vain",
]


def rebuild_collocations() -> None:
    with connect() as conn:
        conn.execute("delete from lexicon.collocation where source_label = 'example-window'")
        conn.execute(
            """
            insert into lexicon.collocation (lexeme_id, sense_id, phrase, score, source_label)
            with target_forms as (
                select distinct
                    ls.lexeme_id,
                    ls.id as sense_id,
                    l.part_of_speech,
                    lower(f.normalized_form) as form
                from lexicon.lexeme_sense ls
                join lexicon.lexeme l on l.id = ls.lexeme_id
                join lexicon.form f on f.lexeme_id = ls.lexeme_id
                where char_length(f.normalized_form) between 2 and 40
                  and f.normalized_form ~ %s
                  and f.normalized_form !~ %s
            ),
            tokens as (
                select
                    ls.lexeme_id,
                    ls.id as sense_id,
                    e.id as example_id,
                    token_row.ordinality::integer as token_index,
                    lower((token_row.match)[1]) as normalized_token,
                    (token_row.match)[1] ~ %s as has_digit,
                    char_length((token_row.match)[1]) > 1
                      and (token_row.match)[1] !~ %s
                      and lower((token_row.match)[1]) <> all(%s::text[]) as can_edge
                from lexicon.lexeme_sense ls
                join lexicon.sense_example se on se.sense_id = ls.id
                join lexicon.example e on e.id = se.example_id
                cross join lateral regexp_matches(e.text_fi, %s, 'g') with ordinality as token_row(match, ordinality)
                where e.quality_score >= 0.70
                  and char_length(e.text_fi) <= 240
                  and e.source_label not like 'external-completion-example:%%'
            ),
            hits as (
                select t.*, tf.part_of_speech
                from tokens t
                join target_forms tf
                  on tf.lexeme_id = t.lexeme_id
                 and tf.sense_id = t.sense_id
                 and tf.form = t.normalized_token
                where t.has_digit = false
            ),
            candidates as (
                select
                    h.lexeme_id,
                    h.sense_id,
                    concat_ws(' ', p1.normalized_token, h.normalized_token) as phrase,
                    3.0::double precision as weight
                from hits h
                join tokens p1
                  on p1.lexeme_id = h.lexeme_id
                 and p1.sense_id = h.sense_id
                 and p1.example_id = h.example_id
                 and p1.token_index = h.token_index - 1
                where p1.can_edge
                union all
                select
                    h.lexeme_id,
                    h.sense_id,
                    concat_ws(' ', h.normalized_token, n1.normalized_token) as phrase,
                    2.5::double precision as weight
                from hits h
                join tokens n1
                  on n1.lexeme_id = h.lexeme_id
                 and n1.sense_id = h.sense_id
                 and n1.example_id = h.example_id
                 and n1.token_index = h.token_index + 1
                where n1.can_edge
                  and h.part_of_speech in ('verb', 'adv')
                union all
                select
                    h.lexeme_id,
                    h.sense_id,
                    concat_ws(' ', p2.normalized_token, p1.normalized_token, h.normalized_token) as phrase,
                    1.2::double precision as weight
                from hits h
                join tokens p1
                  on p1.lexeme_id = h.lexeme_id
                 and p1.sense_id = h.sense_id
                 and p1.example_id = h.example_id
                 and p1.token_index = h.token_index - 1
                join tokens p2
                  on p2.lexeme_id = h.lexeme_id
                 and p2.sense_id = h.sense_id
                 and p2.example_id = h.example_id
                 and p2.token_index = h.token_index - 2
                where p1.can_edge and p2.can_edge
                union all
                select
                    h.lexeme_id,
                    h.sense_id,
                    concat_ws(' ', h.normalized_token, n1.normalized_token, n2.normalized_token) as phrase,
                    1.0::double precision as weight
                from hits h
                join tokens n1
                  on n1.lexeme_id = h.lexeme_id
                 and n1.sense_id = h.sense_id
                 and n1.example_id = h.example_id
                 and n1.token_index = h.token_index + 1
                join tokens n2
                  on n2.lexeme_id = h.lexeme_id
                 and n2.sense_id = h.sense_id
                 and n2.example_id = h.example_id
                 and n2.token_index = h.token_index + 2
                where n1.can_edge and n2.can_edge
                  and h.part_of_speech in ('verb', 'adv')
            )
            select
                lexeme_id,
                sense_id,
                phrase,
                least(sum(weight), 999.0)::double precision,
                'example-window'
            from candidates
            where char_length(phrase) between 4 and 80
            group by lexeme_id, sense_id, phrase
            """,
            (
                _ALPHA_TOKEN_PATTERN,
                _DIGIT_PATTERN,
                _DIGIT_PATTERN,
                _DIGIT_PATTERN,
                _EDGE_STOP_WORDS,
                _TOKEN_PATTERN,
            ),
        )
        conn.commit()
