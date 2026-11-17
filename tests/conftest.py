"""Point every test at the throwaway database and apply the schema once."""

import os

import pytest

from support import get_test_database_url

os.environ["OFL_PROFILE"] = "fixture"
get_test_database_url()


@pytest.fixture(autouse=True)
def _fresh_settings():
    from open_finnish_lexicon.config import get_pipeline_settings

    get_pipeline_settings.cache_clear()
    yield
    get_pipeline_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    import psycopg

    from open_finnish_lexicon.cli.ingest import init_db

    try:
        with psycopg.connect(get_test_database_url(), connect_timeout=3):
            pass
    except psycopg.OperationalError:
        pytest.skip("test database unavailable; run scripts/test-db.sh", allow_module_level=True)
    init_db()
