from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import psycopg

from open_finnish_lexicon.config import get_pipeline_settings


@contextmanager
def connect(*, keepalive: bool = False) -> Generator[psycopg.Connection, None, None]:
    database_url = get_pipeline_settings().database_url
    if keepalive:
        with psycopg.connect(
            database_url,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
        ) as conn:
            yield conn
        return
    with psycopg.connect(database_url) as conn:
        yield conn


@contextmanager
def connection_scope(
    connection: psycopg.Connection | None = None,
) -> Generator[psycopg.Connection, None, None]:
    """Use an injected transaction or open a short standalone transaction."""

    if connection is not None:
        yield connection
        return
    with connect() as managed_connection:
        yield managed_connection
