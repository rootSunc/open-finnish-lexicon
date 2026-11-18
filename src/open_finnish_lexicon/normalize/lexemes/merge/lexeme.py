"""Top-level lexeme merge orchestration."""

from open_finnish_lexicon.normalize.lexemes.merge.forms import (
    _merge_form_analysis_rows,
    _merge_form_rows,
    _merge_pronunciations,
)
from open_finnish_lexicon.normalize.lexemes.merge.refs import _merge_direct_lexeme_refs
from open_finnish_lexicon.normalize.lexemes.merge.senses import _merge_sense_rows

def _merge_lexeme_metadata(conn, source_lexeme_id: int, target_lexeme_id: int) -> None:
    source_row = conn.execute(
        "select frequency_rank, is_lemma from lexicon.lexeme where id = %s",
        (source_lexeme_id,),
    ).fetchone()
    if source_row is None:
        return
    source_rank, source_is_lemma = source_row
    conn.execute(
        """
        update lexicon.lexeme
        set frequency_rank = case
                when %s::integer is null then frequency_rank
                when frequency_rank is null then %s
                else least(frequency_rank, %s)
            end,
            is_lemma = is_lemma or coalesce(%s, false)
        where id = %s
        """,
        (source_rank, source_rank, source_rank, source_is_lemma, target_lexeme_id),
    )


def _merge_lexeme_into(conn, source_lexeme_id: int, target_lexeme_id: int) -> None:
    _merge_lexeme_metadata(conn, source_lexeme_id, target_lexeme_id)
    _merge_form_rows(conn, source_lexeme_id, target_lexeme_id)
    _merge_form_analysis_rows(conn, source_lexeme_id, target_lexeme_id)
    _merge_pronunciations(conn, source_lexeme_id, target_lexeme_id)
    _merge_sense_rows(conn, source_lexeme_id, target_lexeme_id)
    _merge_direct_lexeme_refs(conn, source_lexeme_id, target_lexeme_id)
    conn.execute("delete from lexicon.lexeme where id = %s", (source_lexeme_id,))
