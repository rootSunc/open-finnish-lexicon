import importlib.util
from contextlib import contextmanager
from pathlib import Path
import sys
import time

from psycopg.types.json import Jsonb

from open_finnish_lexicon.config import get_pipeline_settings
from open_finnish_lexicon.db import connect
from open_finnish_lexicon.sources.catalog import SourceRelease, load_source_catalog
from open_finnish_lexicon.sources.fetch import FetchResult, fetch_release
from open_finnish_lexicon.sources.registry import (
    SYNC_SOURCE_ORDER,
    finalize_source_snapshot,
    get_source_pipeline,
    refresh_runtime_views,
)
from open_finnish_lexicon.sources.warehouse import (
    clear_retired_source_registry_documents_in_batches,
    retire_stale_pending_source_files,
)


def _log(message: str) -> None:
    print(f"[sync-all] {message}", flush=True, file=sys.stderr)


LOCK_ID = 741_202_605
STALE_BUILD_RUN_HOURS = 6


def _resolve_input_path(release: SourceRelease, fetch_result: FetchResult) -> Path:
    if release.source_kind == "jsonl" and release.archive_kind == "gz":
        return fetch_result.archive_path
    return fetch_result.member_paths[0]


def _fixture_release_detail(release: SourceRelease) -> str | None:
    """Return a reason when a catalog entry is clearly fixture-only."""

    version = release.version.strip().casefold()
    metadata = " ".join(
        value.strip().casefold() for value in (release.url, release.local_path) if value
    )
    if version.startswith("fixture"):
        return f"version={release.version!r}"
    if "tests/fixtures" in metadata or "fixture://" in metadata:
        return f"source={release.url or release.local_path!r}"
    return None


def _validate_catalog_for_profile(
    catalog: dict[str, SourceRelease],
    *,
    data_profile: str,
) -> None:
    """Reject an obviously wrong source manifest before fetching or writing."""

    if data_profile != "real":
        return
    fixture_releases = [
        f"{source_name} ({detail})"
        for source_name, release in catalog.items()
        if (detail := _fixture_release_detail(release)) is not None
    ]
    if fixture_releases:
        raise RuntimeError(
            "real profile refuses fixture source manifest entries: "
            + ", ".join(sorted(fixture_releases))
        )


def _create_build_run() -> int:
    settings = get_pipeline_settings()
    with connect() as conn:
        build_run_id = conn.execute(
            """
            insert into warehouse.build_run (build_kind, status, metadata)
            values (%s, %s, %s)
            returning id
            """,
            ("sync-all", "running", Jsonb({"data_profile": settings.data_profile})),
        ).fetchone()[0]
        conn.commit()
        return build_run_id


def _set_build_run_status(build_run_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            update warehouse.build_run
            set status = %s,
                finished_at = now()
            where id = %s
            """,
            (status, build_run_id),
        )
        conn.commit()


def archive_stale_build_runs(*, older_than_hours: int = STALE_BUILD_RUN_HOURS) -> int:
    """Mark abandoned sync runs as failed once no active sync lock exists."""

    if older_than_hours <= 0:
        raise ValueError("older_than_hours must be positive")
    with connect() as conn:
        parser_rows = conn.execute(
            """
            update warehouse.parser_run pr
            set status = 'failed',
                message = coalesce(pr.message, 'abandoned sync-all run archived as stale'),
                finished_at = coalesce(pr.finished_at, now())
            from warehouse.build_run br
            where pr.build_run_id = br.id
              and br.status = 'running'
              and br.started_at < now() - (%s::text || ' hours')::interval
              and pr.status = 'running'
            """,
            (older_than_hours,),
        ).rowcount
        build_rows = conn.execute(
            """
            update warehouse.build_run
            set status = 'failed',
                finished_at = coalesce(finished_at, now()),
                metadata = metadata
                    || jsonb_build_object(
                        'archived_as_stale', true,
                        'stale_after_hours', %s,
                        'archived_at', to_jsonb(now())
                    )
            where status = 'running'
              and started_at < now() - (%s::text || ' hours')::interval
            """,
            (older_than_hours, older_than_hours),
        ).rowcount
        pending_rows = retire_stale_pending_source_files(
            conn, older_than_hours=older_than_hours
        )
        conn.commit()
    if build_rows or pending_rows:
        _log(
            "archived stale sync state: "
            f"build_runs={build_rows} parser_runs={parser_rows} pending_files={pending_rows}"
        )
    return int(build_rows or 0)


def _create_parser_run(build_run_id: int, source_registry_name: str, parser_name: str) -> int:
    with connect() as conn:
        source_registry_id = conn.execute(
            "select id from warehouse.source_registry where name = %s",
            (source_registry_name,),
        ).fetchone()
        parser_run_id = conn.execute(
            """
            insert into warehouse.parser_run (build_run_id, source_registry_id, parser_name, status)
            values (%s, %s, %s, %s)
            returning id
            """,
            (
                build_run_id,
                source_registry_id[0] if source_registry_id else None,
                parser_name,
                "running",
            ),
        ).fetchone()[0]
        conn.commit()
        return parser_run_id


def _finish_parser_run(parser_run_id: int, status: str, message: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            """
            update warehouse.parser_run
            set status = %s,
                message = %s,
                finished_at = now()
            where id = %s
            """,
            (status, message, parser_run_id),
        )
        conn.commit()


@contextmanager
def _sync_lock():
    with connect() as conn:
        acquired = conn.execute("select pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()[0]
        conn.commit()
        if not acquired:
            raise RuntimeError("sync-all already running")
        try:
            yield
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (LOCK_ID,))
            conn.commit()


def _run_source(build_run_id: int, release: SourceRelease, fetch_result: FetchResult) -> None:
    pipeline = get_source_pipeline(release.name)
    parser_run_id = _create_parser_run(build_run_id, release.name, f"{release.name}-sync")
    input_path = _resolve_input_path(release, fetch_result)
    source_file_id: int | None = None
    try:
        stage_started = time.monotonic()
        _log(f"{release.name}: stage starting (input={input_path.name})")
        stage_kwargs: dict[str, object] = {
            "version": release.version,
            "source_url": release.url,
            "archive_path": fetch_result.archive_path,
            "unpacked_path": fetch_result.unpack_dir,
            "checksum_sha256": fetch_result.checksum_sha256,
        }
        if release.name == "kaikki" and get_pipeline_settings().data_profile == "real":
            stage_kwargs["reject_empty_snapshot"] = True
        source_file_id = pipeline.stage(input_path, **stage_kwargs)
        _log(
            f"{release.name}: stage done in {time.monotonic() - stage_started:.1f}s; project starting"
        )
        project_started = time.monotonic()
        with connect() as conn:
            if release.name == "kaikki" and get_pipeline_settings().data_profile == "real":
                pipeline.project(
                    input_path,
                    replace_snapshot=True,
                    source_file_id=source_file_id,
                    connection=conn,
                )
            else:
                pipeline.project(input_path, source_file_id=source_file_id, connection=conn)
            finalize_source_snapshot(
                release.name,
                input_path,
                source_file_id=source_file_id,
                cleanup_superseded_documents=False,
                connection=conn,
            )
            conn.commit()
        # Publish first, then clean retired warehouse documents in a separate
        # transaction. A cleanup failure must not roll back a valid snapshot.
        try:
            with connect() as cleanup_conn:
                source_registry_id = cleanup_conn.execute(
                    "select id from warehouse.source_registry where name = %s",
                    (release.name,),
                ).fetchone()[0]
            cleaned_files = clear_retired_source_registry_documents_in_batches(
                source_registry_id=source_registry_id,
            )
            if cleaned_files:
                _log(f"{release.name}: retired warehouse files cleaned={cleaned_files}")
        except Exception as exc:
            _log(f"{release.name}: retired warehouse cleanup deferred: {exc}")
        _log(f"{release.name}: project done in {time.monotonic() - project_started:.1f}s")
    except BaseException as exc:
        message = str(exc) or f"{type(exc).__name__} interrupted source sync"
        _finish_parser_run(parser_run_id, "failed", message)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)) and source_file_id is not None:
            with connect() as conn:
                conn.execute(
                    """
                    update warehouse.source_file
                    set snapshot_state = 'retired',
                        retired_at = now(),
                        retire_reason = 'sync-interrupted'
                    where id = %s
                      and snapshot_state = 'pending'
                    """,
                    (source_file_id,),
                )
                conn.commit()
        raise
    _finish_parser_run(parser_run_id, "succeeded")


def sync_all(*, manifest_path: Path | None = None, refresh: bool = True) -> int:
    get_pipeline_settings.cache_clear()
    settings = get_pipeline_settings()
    manifest_file = manifest_path or (
        Path(settings.source_manifest_path)
        if settings.source_manifest_path
        else Path(__file__).with_name("source_releases.toml")
    )
    catalog = load_source_catalog(manifest_file)
    _validate_catalog_for_profile(catalog, data_profile=settings.data_profile)
    with _sync_lock():
        archive_stale_build_runs()
        build_run_id = _create_build_run()
        overall_started = time.monotonic()
        try:
            _log(f"build_run_id={build_run_id} starting profile={settings.data_profile}")
            for source_name in SYNC_SOURCE_ORDER:
                release = catalog[source_name]
                if release.source_kind == "hfst" and importlib.util.find_spec("omorfi") is None:
                    _log(f"{source_name}: skipped; install the [omorfi] extra to include it")
                    continue
                fetch_started = time.monotonic()
                _log(f"{source_name}: fetch starting (version={release.version})")
                fetch_result = fetch_release(release, Path(settings.data_dir))
                _log(f"{source_name}: fetch done in {time.monotonic() - fetch_started:.1f}s")
                _run_source(build_run_id, release, fetch_result)
            if refresh:
                _log("all sources processed; refreshing runtime views")
                refresh_started = time.monotonic()
                refresh_runtime_views()
                _log(f"refresh_runtime_views done in {time.monotonic() - refresh_started:.1f}s")
        except BaseException:
            _set_build_run_status(build_run_id, "failed")
            raise
        _set_build_run_status(build_run_id, "succeeded")
        _log(f"sync-all finished in {time.monotonic() - overall_started:.1f}s total")
    return 0
