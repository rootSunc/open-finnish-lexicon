"""Batch delete helpers for lexeme merge."""

from open_finnish_lexicon.normalize.lexemes.types import LEXEME_DELETE_BATCH_SIZE

def _batched(values: list[int], batch_size: int = LEXEME_DELETE_BATCH_SIZE):
    for index in range(0, len(values), batch_size):
        yield values[index : index + batch_size]


def _delete_lexeme_ids_in_batches(conn, lexeme_ids: list[int]) -> None:
    for batch in _batched(lexeme_ids):
        conn.execute("delete from lexicon.lexeme where id = any(%s)", (batch,))
