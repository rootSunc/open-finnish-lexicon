import os
import tempfile
import unittest
from pathlib import Path

import psycopg

from open_finnish_lexicon.cli import main
from open_finnish_lexicon.sources.catalog import SourceRelease
from open_finnish_lexicon.sources.fetch import FetchResult
from open_finnish_lexicon.sync_all import (
    LOCK_ID,
    _resolve_input_path,
    _validate_catalog_for_profile,
    archive_stale_build_runs,
)
from open_finnish_lexicon.sources.warehouse import retire_stale_pending_source_files
from support import get_test_database_url


class SyncAllTests(unittest.TestCase):
    def test_real_profile_rejects_fixture_manifest_before_fetching(self):
        release = SourceRelease(
            name="frequency",
            version="fixture-1",
            source_kind="csv",
            url="tests/fixtures/releases/frequency-fixture.csv",
            local_path="",
            archive_kind="plain",
            checksum_sha256="",
            members=("frequency.csv",),
            companions=(),
        )

        with self.assertRaisesRegex(RuntimeError, "refuses fixture source manifest"):
            _validate_catalog_for_profile({"frequency": release}, data_profile="real")

    def test_real_profile_accepts_catalogued_source_release(self):
        release = SourceRelease(
            name="frequency",
            version="2018-fi-50k",
            source_kind="txt",
            url="https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/fi/fi_50k.txt",
            local_path="",
            archive_kind="plain",
            checksum_sha256="",
            members=("fi_50k.txt",),
            companions=(),
        )

        _validate_catalog_for_profile({"frequency": release}, data_profile="real")

    def test_resolve_input_path_prefers_gz_archive_for_jsonl_sources(self):
        release = SourceRelease(
            name="kaikki",
            version="fixture-1",
            source_kind="jsonl",
            url="https://example.test/kaikki.jsonl.gz",
            local_path="",
            archive_kind="gz",
            checksum_sha256="",
            members=("kaikki.jsonl",),
            companions=(),
        )
        fetch_result = FetchResult(
            archive_path=Path("/tmp/kaikki.jsonl.gz"),
            unpack_dir=Path("/tmp/unpacked"),
            checksum_sha256="",
            member_paths=(Path("/tmp/unpacked/kaikki.jsonl"),),
        )

        self.assertEqual(_resolve_input_path(release, fetch_result), fetch_result.archive_path)


    def test_resolve_input_path_prefers_plain_jsonl_member_for_wiktionary_zh(self):
        release = SourceRelease(
            name="wiktionary_zh",
            version="fixture-1",
            source_kind="jsonl",
            url="https://example.test/wiktionary-zh.jsonl",
            local_path="",
            archive_kind="plain",
            checksum_sha256="",
            members=("wiktionary-zh-fixture.jsonl",),
            companions=(),
        )
        fetch_result = FetchResult(
            archive_path=Path("/tmp/wiktionary-zh.jsonl"),
            unpack_dir=Path("/tmp/unpacked"),
            checksum_sha256="",
            member_paths=(Path("/tmp/unpacked/wiktionary-zh-fixture.jsonl"),),
        )

        self.assertEqual(_resolve_input_path(release, fetch_result), fetch_result.member_paths[0])

    def test_sync_all_imports_all_sources_from_manifest(self):
        manifest_path = "tests/fixtures/releases/test_source_releases.toml"
        with tempfile.TemporaryDirectory() as data_dir:
            os.environ["OFL_DATA_DIR"] = data_dir

            exit_code = main(["sync-all", "--manifest", manifest_path])

            self.assertEqual(exit_code, 0)

            with psycopg.connect(get_test_database_url()) as conn:
                source_names = {
                    row[0]
                    for row in conn.execute(
                        "select name from warehouse.source_registry order by name"
                    ).fetchall()
                }
                self.assertTrue(
                    {
                        "dbnary_zh",
                        "frequency",
                        "finnwordnet",
                        "kaikki",
                        "omorfi",
                        "tatoeba",
                        "wiktionary_zh",
                    }.issubset(source_names),
                )

    def test_archive_stale_build_runs_marks_old_running_rows_failed(self):
        with psycopg.connect(get_test_database_url()) as conn:
            build_run_id = conn.execute(
                """
                insert into warehouse.build_run (build_kind, status, started_at, metadata)
                values ('sync-all', 'running', now() - interval '2 hours', '{}'::jsonb)
                returning id
                """
            ).fetchone()[0]
            parser_run_id = conn.execute(
                """
                insert into warehouse.parser_run (build_run_id, parser_name, status, started_at)
                values (%s, 'fixture-sync', 'running', now() - interval '2 hours')
                returning id
                """,
                (build_run_id,),
            ).fetchone()[0]
            conn.commit()

        archived = archive_stale_build_runs(older_than_hours=1)

        self.assertGreaterEqual(archived, 1)
        with psycopg.connect(get_test_database_url()) as conn:
            build_status, metadata = conn.execute(
                "select status, metadata from warehouse.build_run where id = %s",
                (build_run_id,),
            ).fetchone()
            parser_status, message = conn.execute(
                "select status, message from warehouse.parser_run where id = %s",
                (parser_run_id,),
            ).fetchone()

        self.assertEqual(build_status, "failed")
        self.assertTrue(metadata["archived_as_stale"])
        self.assertEqual(parser_status, "failed")
        self.assertIn("stale", message)

    def test_stale_pending_cleanup_keeps_attempt_owned_by_running_parser(self):
        with psycopg.connect(get_test_database_url()) as conn:
            source_registry_id = conn.execute(
                """
                insert into warehouse.source_registry (name, source_kind)
                values ('stale-running-source-test', 'fixture')
                returning id
                """
            ).fetchone()[0]
            source_file_id = conn.execute(
                """
                insert into warehouse.source_file (
                    source_registry_id, local_path, snapshot_state, imported_at
                )
                values (%s, '/tmp/stale-running-source-test', 'pending', now() - interval '2 hours')
                returning id
                """,
                (source_registry_id,),
            ).fetchone()[0]
            conn.execute(
                """
                insert into warehouse.source_document (source_file_id, external_id, payload)
                values (%s, 'stale-running-source-test:1', '{}'::jsonb)
                """,
                (source_file_id,),
            )
            build_run_id = conn.execute(
                """
                insert into warehouse.build_run (build_kind, status)
                values ('sync-all', 'running')
                returning id
                """
            ).fetchone()[0]
            parser_run_id = conn.execute(
                """
                insert into warehouse.parser_run (
                    build_run_id, source_registry_id, parser_name, status
                )
                values (%s, %s, 'stale-running-source-test', 'running')
                returning id
                """,
                (build_run_id, source_registry_id),
            ).fetchone()[0]
            conn.commit()

        try:
            with psycopg.connect(get_test_database_url()) as conn:
                retired_count = retire_stale_pending_source_files(
                    conn, older_than_hours=1
                )
                conn.commit()
                state, document_count = conn.execute(
                    """
                    select sf.snapshot_state,
                           (select count(*) from warehouse.source_document d
                            where d.source_file_id = sf.id)
                    from warehouse.source_file sf
                    where sf.id = %s
                    """,
                    (source_file_id,),
                ).fetchone()
        finally:
            with psycopg.connect(get_test_database_url()) as conn:
                conn.execute("delete from warehouse.parser_run where id = %s", (parser_run_id,))
                conn.execute("delete from warehouse.build_run where id = %s", (build_run_id,))
                conn.execute(
                    "delete from warehouse.source_document where source_file_id = %s",
                    (source_file_id,),
                )
                conn.execute("delete from warehouse.source_file where id = %s", (source_file_id,))
                conn.execute(
                    "delete from warehouse.source_registry where id = %s",
                    (source_registry_id,),
                )
                conn.commit()

        self.assertEqual(retired_count, 0)
        self.assertEqual(state, "pending")
        self.assertEqual(document_count, 1)

    def test_sync_all_does_not_create_build_run_when_lock_is_held(self):
        manifest_path = "tests/fixtures/releases/test_source_releases.toml"
        database_url = get_test_database_url()
        with psycopg.connect(database_url) as lock_conn:
            self.assertTrue(
                lock_conn.execute("select pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()[0]
            )
            lock_conn.commit()
            with psycopg.connect(database_url) as check_conn:
                before = check_conn.execute("select count(*) from warehouse.build_run").fetchone()[
                    0
                ]

            with self.assertRaisesRegex(RuntimeError, "sync-all already running"):
                main(["sync-all", "--manifest", manifest_path])

            with psycopg.connect(database_url) as check_conn:
                after = check_conn.execute("select count(*) from warehouse.build_run").fetchone()[0]

            lock_conn.execute("select pg_advisory_unlock(%s)", (LOCK_ID,))
            lock_conn.commit()

        self.assertEqual(after, before)
