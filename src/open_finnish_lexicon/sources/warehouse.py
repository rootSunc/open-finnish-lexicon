from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.sources.licenses import source_license


def upsert_source_registry(
    conn: psycopg.Connection,
    *,
    name: str,
    source_kind: str,
    version: str,
    source_url: str,
    defer_activation: bool = False,
) -> int:
    if defer_activation:
        row = conn.execute(
            """
            insert into warehouse.source_registry (name, source_kind, license)
            values (%s, %s, %s)
            on conflict (name) do update
            set source_kind = excluded.source_kind,
                license = excluded.license
            returning id
            """,
            (name, source_kind, source_license(name)),
        ).fetchone()
        assert row is not None
        return int(row[0])

    row = conn.execute(
        """
        insert into warehouse.source_registry (name, source_kind, version, source_url, license)
        values (%s, %s, %s, %s, %s)
        on conflict (name) do update
        set source_kind = excluded.source_kind,
            version = excluded.version,
            source_url = excluded.source_url,
            license = excluded.license
        returning id
        """,
        (name, source_kind, version, source_url, source_license(name)),
    ).fetchone()
    assert row is not None
    return int(row[0])


def upsert_source_release(
    conn: psycopg.Connection,
    *,
    source_registry_id: int,
    version: str,
    source_url: str,
    archive_path: Path,
    unpacked_path: Path,
    checksum_sha256: str,
) -> int:
    row = conn.execute(
        """
        insert into warehouse.source_release (
            source_registry_id,
            version,
            source_url,
            archive_path,
            unpacked_path,
            checksum_sha256
        )
        values (%s, %s, %s, %s, %s, %s)
        on conflict (source_registry_id, version) do update
        set source_url = excluded.source_url,
            archive_path = excluded.archive_path,
            unpacked_path = excluded.unpacked_path,
            checksum_sha256 = excluded.checksum_sha256
        returning id
        """,
        (
            source_registry_id,
            version,
            source_url,
            str(archive_path),
            str(unpacked_path),
            checksum_sha256,
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])


def upsert_source_file(
    conn: psycopg.Connection,
    *,
    source_registry_id: int,
    local_path: Path,
    checksum_sha256: str = "",
    snapshot_state: str = "active",
    source_version: str | None = None,
    source_url: str | None = None,
) -> int:
    if snapshot_state == "pending":
        row = conn.execute(
            """
            insert into warehouse.source_file (
                source_registry_id,
                local_path,
                checksum_sha256,
                snapshot_state,
                source_version,
                source_url
            )
            values (%s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                source_registry_id,
                str(local_path),
                checksum_sha256,
                snapshot_state,
                source_version,
                source_url,
            ),
        ).fetchone()
        assert row is not None
        return int(row[0])

    if snapshot_state == "active":
        conn.execute(
            """
            update warehouse.source_file
            set snapshot_state = 'retired',
                retired_at = now(),
                retire_reason = 'superseded by newer active source file'
            where source_registry_id = %s
                and snapshot_state = 'active'
                and local_path <> %s
            """,
            (source_registry_id, str(local_path)),
        )

    existing = conn.execute(
        """
        select id
        from warehouse.source_file
        where source_registry_id = %s
          and local_path = %s
        order by (snapshot_state = 'active') desc, imported_at desc, id desc
        limit 1
        """,
        (source_registry_id, str(local_path)),
    ).fetchone()
    if existing is not None:
        updated = conn.execute(
            """
            update warehouse.source_file
            set checksum_sha256 = %s,
                imported_at = now(),
                snapshot_state = %s,
                source_version = coalesce(%s, source_version),
                source_url = coalesce(%s, source_url),
                retired_at = null,
                retire_reason = null
            where id = %s
            returning id
            """,
            (checksum_sha256, snapshot_state, source_version, source_url, existing[0]),
        ).fetchone()
        assert updated is not None
        return int(updated[0])

    inserted = conn.execute(
        """
        insert into warehouse.source_file (
            source_registry_id,
            local_path,
            checksum_sha256,
            snapshot_state,
            source_version,
            source_url
        )
        values (%s, %s, %s, %s, %s, %s)
        returning id
        """,
        (
            source_registry_id,
            str(local_path),
            checksum_sha256,
            snapshot_state,
            source_version,
            source_url,
        ),
    ).fetchone()
    assert inserted is not None
    return int(inserted[0])


def prepare_pending_source_snapshot(
    conn: psycopg.Connection,
    *,
    name: str,
    source_kind: str,
    version: str,
    source_url: str,
    input_path: Path,
    archive_path: Path | None = None,
    unpacked_path: Path | None = None,
    checksum_sha256: str = "",
) -> int:
    """Register a source release and return a fresh pending ``source_file`` id."""

    source_registry_id = upsert_source_registry(
        conn,
        name=name,
        source_kind=source_kind,
        version=version,
        source_url=source_url,
        defer_activation=True,
    )
    upsert_source_release(
        conn,
        source_registry_id=source_registry_id,
        version=version,
        source_url=source_url,
        archive_path=archive_path or input_path,
        unpacked_path=unpacked_path or input_path.parent,
        checksum_sha256=checksum_sha256,
    )
    return upsert_source_file(
        conn,
        source_registry_id=source_registry_id,
        local_path=input_path,
        checksum_sha256=checksum_sha256,
        snapshot_state="pending",
        source_version=version,
        source_url=source_url,
    )


def source_file_id_for_path(
    conn: psycopg.Connection,
    *,
    source_name: str,
    local_path: Path,
    source_file_id: int | None = None,
    allow_active: bool = False,
) -> int:
    """Resolve the exact unpublished attempt that a projection must publish."""

    allowed_states = ("pending", "active") if allow_active else ("pending",)
    conditions = [
        sql.SQL("sr.name = %s"),
        sql.SQL("sf.local_path = %s"),
        sql.SQL("sf.snapshot_state = any(%s)"),
    ]
    params: list[object] = [source_name, str(local_path), list(allowed_states)]
    if source_file_id is not None:
        conditions.append(sql.SQL("sf.id = %s"))
        params.append(source_file_id)
    query = sql.SQL(
        """
        select sf.id
        from warehouse.source_file sf
        join warehouse.source_registry sr on sr.id = sf.source_registry_id
        where {where_clause}
        order by (sf.snapshot_state = 'pending') desc, sf.imported_at desc, sf.id desc
        limit 1
        """
    ).format(where_clause=sql.SQL(" and ").join(conditions))
    row = conn.execute(query, tuple(params)).fetchone()
    if row is None:
        detail = f"source={source_name} path={local_path}"
        if source_file_id is not None:
            detail += f" id={source_file_id}"
        raise RuntimeError(f"pending source file is not staged: {detail}")
    return int(row[0])


def active_source_file_for_name(
    conn: psycopg.Connection,
    *,
    source_name: str,
) -> tuple[int, Path] | None:
    """Return ``(source_file_id, local_path)`` for an active source snapshot if one exists."""

    row = conn.execute(
        """
        select sf.id, sf.local_path
        from warehouse.source_file sf
        join warehouse.source_registry sr on sr.id = sf.source_registry_id
        where sr.name = %s
          and sf.snapshot_state = 'active'
        order by sf.imported_at desc, sf.id desc
        limit 1
        """,
        (source_name,),
    ).fetchone()
    if row is None:
        return None
    return int(row[0]), Path(str(row[1]))


def replace_source_document(
    conn: psycopg.Connection,
    *,
    source_file_id: int,
    external_id: str,
    payload: Mapping[str, Any],
) -> int:
    row = conn.execute(
        """
        insert into warehouse.source_document (source_file_id, external_id, payload)
        values (%s, %s, %s)
        on conflict (source_file_id, external_id) do update
        set payload = excluded.payload,
            imported_at = now()
        returning id
        """,
        (source_file_id, external_id, Jsonb(dict(payload))),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _clear_source_documents(
    conn: psycopg.Connection,
    *,
    source_filter: sql.Composable,
    params: tuple[object, ...],
) -> None:
    """Remove source documents selected by ``source_filter`` and their derived rows."""

    conn.execute("drop table if exists tmp_source_gloss_candidate_cleanup")
    conn.execute("drop table if exists tmp_source_document_cleanup")
    conn.execute(
        """
        create temporary table tmp_source_document_cleanup (
            id bigint primary key
        ) on commit drop
        """
    )
    conn.execute(
        sql.SQL(
            """
            insert into tmp_source_document_cleanup (id)
            select id
            from warehouse.source_document
            where {source_filter}
              and not exists (
                  select 1
                  from semantic.zh_gloss_candidate selected_candidate
                  join semantic.zh_gloss_selection selected_gloss
                    on selected_gloss.zh_gloss_candidate_id = selected_candidate.id
                  where selected_candidate.source_document_id = warehouse.source_document.id
              )
            """
        ).format(source_filter=source_filter),
        params,
    )
    conn.execute("analyze tmp_source_document_cleanup")
    conn.execute(
        """
        create temporary table tmp_source_gloss_candidate_cleanup (
            id bigint primary key
        ) on commit drop
        """
    )
    conn.execute(
        """
        insert into tmp_source_gloss_candidate_cleanup (id)
        select id
        from semantic.zh_gloss_candidate
        where source_document_id in (select id from tmp_source_document_cleanup)
        """
    )
    conn.execute("analyze tmp_source_gloss_candidate_cleanup")
    conn.execute(
        """
        delete from semantic.zh_gloss_candidate
        where id in (select id from tmp_source_gloss_candidate_cleanup)
        """
    )
    conn.execute(
        """
        delete from semantic.sense_alignment
        where source_document_id in (select id from tmp_source_document_cleanup)
        """
    )
    conn.execute(
        """
        delete from semantic.sense_alignment_candidate
        where source_document_id in (select id from tmp_source_document_cleanup)
        """
    )
    conn.execute(
        """
        delete from warehouse.source_claim
        where source_document_id in (select id from tmp_source_document_cleanup)
        """
    )
    conn.execute(
        """
        delete from warehouse.source_document
        where id in (select id from tmp_source_document_cleanup)
        """
    )


def clear_source_file_documents(conn: psycopg.Connection, *, source_file_id: int) -> None:
    """Remove one source file's documents and all derived rows tied to them."""

    _clear_source_documents(
        conn,
        source_filter=sql.SQL("source_file_id = %s"),
        params=(source_file_id,),
    )


def clear_retired_source_registry_documents(
    conn: psycopg.Connection, *, source_registry_id: int
) -> None:
    """Remove retired documents without touching the newly active snapshot."""

    _clear_source_documents(
        conn,
        source_filter=sql.SQL(
            """source_file_id in (
                select id
                from warehouse.source_file
                where source_registry_id = %s
                  and snapshot_state = 'retired'
            )"""
        ),
        params=(source_registry_id,),
    )


def clear_retired_source_registry_documents_in_batches(
    *, source_registry_id: int, batch_size: int = 1, max_files: int | None = None
) -> int:
    """Remove retired documents in independently committed source-file batches."""

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if max_files is not None and max_files <= 0:
        raise ValueError("max_files must be positive when provided")

    limit_sql = sql.SQL(" limit %s") if max_files is not None else sql.SQL("")
    lookup_params: list[object] = [source_registry_id]
    if max_files is not None:
        lookup_params.append(max_files)

    query = sql.SQL(
        """
        select sf.id
        from warehouse.source_file sf
        where sf.source_registry_id = %s
          and sf.snapshot_state = 'retired'
          and exists (
              select 1
              from warehouse.source_document d
              where d.source_file_id = sf.id
                and not exists (
                    select 1
                    from semantic.zh_gloss_candidate selected_candidate
                    join semantic.zh_gloss_selection selected_gloss
                      on selected_gloss.zh_gloss_candidate_id = selected_candidate.id
                    where selected_candidate.source_document_id = d.id
                )
          )
        order by sf.id
        """
    ) + limit_sql

    with connect() as lookup_conn:
        source_file_ids = [
            int(row[0])
            for row in lookup_conn.execute(query, tuple(lookup_params)).fetchall()
        ]

    cleaned_files = 0
    for offset in range(0, len(source_file_ids), batch_size):
        batch = source_file_ids[offset : offset + batch_size]
        with connect() as conn:
            for source_file_id in batch:
                clear_source_file_documents(conn, source_file_id=source_file_id)
            conn.commit()
        cleaned_files += len(batch)
    return cleaned_files


def retire_stale_pending_source_files(conn: psycopg.Connection, *, older_than_hours: int) -> int:
    """Retire old unpublished attempts without touching a live sync."""

    if older_than_hours <= 0:
        raise ValueError("older_than_hours must be positive")
    stale_rows = conn.execute(
        """
        select sf.id
        from warehouse.source_file sf
        where sf.snapshot_state = 'pending'
          and sf.imported_at < now() - (%s::text || ' hours')::interval
          and not exists (
              select 1
              from warehouse.parser_run pr
              join warehouse.build_run br on br.id = pr.build_run_id
              where pr.source_registry_id = sf.source_registry_id
                and pr.status = 'running'
                and br.status = 'running'
          )
        order by sf.id
        """,
        (older_than_hours,),
    ).fetchall()
    source_file_ids = [int(row[0]) for row in stale_rows]
    for source_file_id in source_file_ids:
        clear_source_file_documents(conn, source_file_id=source_file_id)
    if not source_file_ids:
        return 0

    retired_count = conn.execute(
        """
        update warehouse.source_file
        set snapshot_state = 'retired',
            retired_at = now(),
            retire_reason = 'stale-pending-attempt'
        where id = any(%s)
          and snapshot_state = 'pending'
        """,
        (source_file_ids,),
    ).rowcount
    return int(retired_count or 0)


def finalize_source_registry_snapshot(
    conn: psycopg.Connection,
    *,
    source_registry_id: int,
    active_source_file_id: int,
    cleanup_superseded_documents: bool = True,
) -> None:
    """Activate one projected file and retire/remove superseded source files."""

    conn.execute(
        """
        update warehouse.source_file
        set snapshot_state = 'retired',
            retired_at = coalesce(retired_at, now()),
            retire_reason = coalesce(retire_reason, 'superseded-by-newer-snapshot')
        where source_registry_id = %s
          and id <> %s
        """,
        (source_registry_id, active_source_file_id),
    )
    conn.execute(
        """
        update warehouse.source_file
        set snapshot_state = 'active',
            retired_at = null,
            retire_reason = null
        where id = %s
          and source_registry_id = %s
        """,
        (active_source_file_id, source_registry_id),
    )
    conn.execute(
        """
        update warehouse.source_registry sr
        set version = sf.source_version,
            source_url = sf.source_url
        from warehouse.source_file sf
        where sr.id = %s
          and sf.id = %s
          and sf.source_version is not null
        """,
        (source_registry_id, active_source_file_id),
    )

    if cleanup_superseded_documents:
        clear_retired_source_registry_documents(
            conn,
            source_registry_id=source_registry_id,
        )


def replace_source_claims(
    conn: psycopg.Connection,
    *,
    source_document_id: int,
    claims: Sequence[tuple[str, str, str | None, Mapping[str, Any]]],
) -> None:
    conn.execute(
        "delete from warehouse.source_claim where source_document_id = %s", (source_document_id,)
    )
    if not claims:
        return
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            insert into warehouse.source_claim (
                source_document_id,
                claim_type,
                subject_key,
                object_key,
                payload
            )
            values (%s, %s, %s, %s, %s)
            """,
            [
                (source_document_id, claim_type, subject_key, object_key, Jsonb(dict(payload)))
                for claim_type, subject_key, object_key, payload in claims
            ],
        )
