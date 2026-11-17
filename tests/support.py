"""Test database helpers.

Integration tests truncate lexicon tables, so they only run against the
database named by ``OFL_TEST_DATABASE_URL``. The default points at the
throwaway container started by ``scripts/test-db.sh``.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

DEFAULT_TEST_DATABASE_URL = "postgresql://fi:fi@127.0.0.1:54331/ofl_test"


def get_test_database_url() -> str:
    url = os.environ.get("OFL_TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL
    name = urlsplit(url).path.lstrip("/")
    if "test" not in name:
        raise RuntimeError(
            f"refusing to run destructive tests against {name!r}; "
            "OFL_TEST_DATABASE_URL must name a database containing 'test'"
        )
    os.environ["OFL_DATABASE_URL"] = url
    os.environ.setdefault("OFL_PROFILE", "fixture")
    return url
