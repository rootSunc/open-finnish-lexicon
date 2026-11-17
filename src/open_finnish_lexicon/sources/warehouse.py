from pathlib import Path

from psycopg.types.json import Jsonb

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.sources.licenses import source_license


def upsert_source_registry(
    conn,
    *,
    name: str,
    source_kind: str,
    version: str,
    source_url: str,
    defer_activation: bool = False,
) -> int:
    if defer_activation:
        return conn.execute(
            """
            insert into warehouse.source_registry (name, source_kind, license)
            values (%s, %s, %s)
            on conflict (name) do update
            set source_kind = excluded.source_kind,
                license = excluded.license
            returning id
            """,
            (name, source_kind, source_license(name)),
        ).fetchone()[0]

    return conn.execute(
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
    ).fetchone()[0]


def upsert_source_release(
    conn,
    *,
    source_registry_id: int,
    version: str,
    source_url: str,
    archive_path: Path,
    unpacked_path: Path,
    checksum_sha256: str,
) -> int:
    return conn.execute(
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
    ).fetchone()[0]


def upsert_source_file(
    conn,
    *,
    source_registry_id: int,
    local_path: Path,
    checksum_sha256: str = "",
    snapshot_state: str = "active",
    source_version: str | None = None,
    source_url: str | None = None,
) -> int:
    if snapshot_state == "pending":
        return conn.execute(
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
        ).fetchone()[0]

    if snapshot_state == "active":
        # The lifecycle index allows only one active path per source registry.
        # Manual review bundles commonly arrive under a new temporary path;
        # retire the previous path before promoting the replacement so repeated
        # imports remain possible without deleting the audit row.
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
        return conn.execute(
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
        ).fetchone()[0]

    return conn.execute(
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
    ).fetchone()[0]


def source_file_id_for_path(
    conn,
    *,
    source_name: str,
    local_path: Path,
    source_file_id: int | None = None,
) -> int:
    """Resolve the exact unpublished attempt that a projection must publish.

    The id returned by staging is authoritative.  The path-only fallback is
    kept for direct project calls and older callers, but always prefers a
    pending attempt so a published file cannot accidentally be re-finalized.
    """

    filters = ["sr.name = %s", "sf.local_path = %s", "sf.snapshot_state = 'pending'"]
    params: list[object] = [source_name, str(local_path)]
    if source_file_id is not None:
        filters.append("sf.id = %s")
        params.append(source_file_id)
    row = conn.execute(
        """
        select sf.id
        from warehouse.source_file sf
        join warehouse.source_registry sr on sr.id = sf.source_registry_id
        where """
        + " and ".join(filters)
        + " order by sf.imported_at desc, sf.id desc limit 1",
        tuple(params),
    ).fetchone()
    if row is None:
        detail = f"source={source_name} path={local_path}"
        if source_file_id is not None:
            detail += f" id={source_file_id}"
        raise RuntimeError(f"pending source file is not staged: {detail}")
    return int(row[0])


def replace_source_document(
    conn,
    *,
    source_file_id: int,
    external_id: str,
    payload: dict,
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
        (source_file_id, external_id, Jsonb(payload)),
    ).fetchone()
    return row[0]


def _clear_source_documents(conn, *, source_filter: str, params: tuple[object, ...]) -> None:
    """Remove source documents selected by ``source_filter`` and their derived rows."""

    # Source documents are replaced atomically by the stage loaders. Semantic
    # candidates and alignments deliberately keep a normal foreign key to the
    # document so provenance cannot silently become invalid; clean those
    # derived rows before deleting the documents.
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
        f"""
        insert into tmp_source_document_cleanup (id)
        select id
        from warehouse.source_document
        {source_filter}
          and not exists (
              select 1
              from semantic.zh_gloss_candidate selected_candidate
              join semantic.zh_gloss_selection selected_gloss
                on selected_gloss.zh_gloss_candidate_id = selected_candidate.id
              where selected_candidate.source_document_id = warehouse.source_document.id
          )
        """,
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
        delete from semantic.zh_gloss_selection
        where zh_gloss_candidate_id in (select id from tmp_source_gloss_candidate_cleanup)
        """
    )
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


def clear_source_file_documents(conn, *, source_file_id: int) -> None:
    """Remove one source file's documents and all derived rows tied to them."""

    _clear_source_documents(
        conn,
        source_filter="where source_file_id = %s",
        params=(source_file_id,),
    )


def clear_retired_source_registry_documents(conn, *, source_registry_id: int) -> None:
    """Remove retired documents without touching the newly active snapshot."""

    _clear_source_documents(
        conn,
        source_filter="""where source_file_id in (
            select id
            from warehouse.source_file
            where source_registry_id = %s
              and snapshot_state = 'retired'
        )""",
        params=(source_registry_id,),
    )


def clear_retired_source_registry_documents_in_batches(
    *, source_registry_id: int, batch_size: int = 1, max_files: int | None = None
) -> int:
    """Remove retired documents in independently committed source-file batches.

    A full source replacement can leave millions of warehouse documents behind.
    Keeping every retired file in one transaction makes cleanup hard to cancel,
    holds locks for too long, and loses all progress when a connection dies.
    Select the retired file ids once, then clean each batch in its own
    transaction.  The active snapshot is never selected, and already committed
    batches remain gone if a later batch fails.

    ``batch_size`` counts source files rather than documents.  A value of one
    is the safest default because a single Kaikki file is already large enough
    to make a useful unit of recovery. ``max_files`` optionally bounds one
    maintenance invocation so a scheduler or operator can make incremental
    progress without holding a connection open for the entire backlog.
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if max_files is not None and max_files <= 0:
        raise ValueError("max_files must be positive when provided")

    limit_clause = ""
    lookup_params: list[object] = [source_registry_id]
    if max_files is not None:
        limit_clause = "limit %s"
        lookup_params.append(max_files)

    with connect() as lookup_conn:
        source_file_ids = [
            int(row[0])
            for row in lookup_conn.execute(
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
                """ + limit_clause,
                tuple(lookup_params),
            ).fetchall()
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


def retire_stale_pending_source_files(conn, *, older_than_hours: int) -> int:
    """Retire old unpublished attempts without touching a live sync.

    Staging commits warehouse documents before projection starts so a failed
    project can leave the previous active snapshot untouched.  Those pending
    attempts are safe to discard only after their retention window has passed
    and no parser for the same source registry is still running.  The file row
    remains as an audit record; its raw documents and dependent semantic rows
    are removed to prevent unbounded warehouse growth.
    """

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
    conn,
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
    conn, *, source_document_id: int, claims: list[tuple[str, str, str | None, dict]]
) -> None:
    conn.execute(
        "delete from warehouse.source_claim where source_document_id = %s", (source_document_id,)
    )
    for claim_type, subject_key, object_key, payload in claims:
        conn.execute(
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
            (source_document_id, claim_type, subject_key, object_key, Jsonb(payload)),
        )
