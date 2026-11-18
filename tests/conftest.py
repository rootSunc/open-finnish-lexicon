"""Point DB-backed tests at the throwaway database while allowing pure-Python
unit tests to run without PostgreSQL."""

from __future__ import annotations

import os

import psycopg
import pytest

from support import get_test_database_url

os.environ["OFL_PROFILE"] = "fixture"
get_test_database_url()

_REAL_PSYCOPG_CONNECT = psycopg.connect


@pytest.fixture(autouse=True)
def _fresh_settings():
    from open_finnish_lexicon.config import get_pipeline_settings

    get_pipeline_settings.cache_clear()
    yield
    get_pipeline_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _db_session_setup():
    from open_finnish_lexicon.cli.ingest import init_db

    try:
        with _REAL_PSYCOPG_CONNECT(get_test_database_url(), connect_timeout=2):
            pass
    except psycopg.OperationalError as exc:
        if os.environ.get("OFL_REQUIRE_TEST_DB") == "1":
            pytest.exit(f"PostgreSQL test database is required: {exc}", returncode=1)
        mp = pytest.MonkeyPatch()

        def _skip_on_db_connect(*_args, **_kwargs):
            pytest.skip("test database unavailable; run scripts/test-db.sh")

        mp.setattr(psycopg, "connect", _skip_on_db_connect)
        try:
            yield False
        finally:
            mp.undo()
        return

    init_db()
    yield True
