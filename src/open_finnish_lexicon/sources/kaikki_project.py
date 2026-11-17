from pathlib import Path

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.sources.kaikki_bulk import upsert_staged_kaikki_entries
from open_finnish_lexicon.normalize.senses import (
    clear_kaikki_stale_data_for_non_projection_entries,
    upsert_kaikki_entries,
)
from open_finnish_lexicon.sources.kaikki_loader import compact_kaikki_entry, has_kaikki_projection_data
from open_finnish_lexicon.sources.warehouse import source_file_id_for_path


def _kaikki_source_file_id(
    input_path: Path, source_file_id: int | None = None, connection=None
) -> int:
    with connection_scope(connection) as conn:
        return source_file_id_for_path(
            conn,
            source_name="kaikki",
            local_path=input_path,
            source_file_id=source_file_id,
        )


def _has_active_same_path(source_file_id: int, input_path: Path, connection=None) -> bool:
    """Detect a retry of a path that already has a published snapshot."""

    with connection_scope(connection) as conn:
        return bool(
            conn.execute(
                """
                select exists (
                    select 1
                    from warehouse.source_file pending
                    join warehouse.source_file active
                      on active.source_registry_id = pending.source_registry_id
                     and active.local_path = pending.local_path
                     and active.snapshot_state = 'active'
                     and active.id <> pending.id
                    where pending.id = %s
                      and pending.local_path = %s
                      and pending.snapshot_state = 'pending'
                )
                """,
                (source_file_id, str(input_path)),
            ).fetchone()[0]
        )


def _iter_staged_kaikki_entries(conn, source_file_id: int):
    """Yield staged payloads for compatibility with direct projector callers."""

    last_document_id = 0
    while True:
        rows = conn.execute(
            """
            select id, payload
            from warehouse.source_document
            where source_file_id = %s
              and id > %s
            order by id
            limit 1000
            """,
            (source_file_id, last_document_id),
        ).fetchall()
        if not rows:
            return
        for document_id, payload in rows:
            last_document_id = int(document_id)
            if isinstance(payload, dict):
                yield payload


_DEFAULT_STAGED_READER = _iter_staged_kaikki_entries


def project_kaikki_entries(
    input_path: Path,
    *,
    replace_snapshot: bool = False,
    source_file_id: int | None = None,
    connection=None,
) -> int:
    source_file_id = _kaikki_source_file_id(input_path, source_file_id, connection)
    retrying_published_path = _has_active_same_path(source_file_id, input_path, connection)
    replace_snapshot = replace_snapshot or retrying_published_path
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        if _iter_staged_kaikki_entries is _DEFAULT_STAGED_READER:
            upsert_staged_kaikki_entries(
                conn,
                source_file_id=source_file_id,
                replace_snapshot=replace_snapshot,
                allow_empty_snapshot=retrying_published_path,
            )
        else:
            # Keep the injectable reader contract used by callers that test a
            # mid-project parser failure.  Normal production projects use the
            # set-based path above.
            upsert_kaikki_entries(
                (
                    compact_kaikki_entry(entry)
                    for entry in _iter_staged_kaikki_entries(conn, source_file_id)
                    if has_kaikki_projection_data(entry)
                ),
                source_file_id=source_file_id,
                replace_snapshot=replace_snapshot,
                allow_empty_snapshot=retrying_published_path,
                connection=conn,
            )
        if not replace_snapshot:
            clear_kaikki_stale_data_for_non_projection_entries(
                source_file_id=source_file_id,
                connection=conn,
            )
        if owns_connection:
            conn.commit()
    return source_file_id
