from contextlib import contextmanager

import psycopg

from open_finnish_lexicon.config import get_pipeline_settings


@contextmanager
def connect():
    with psycopg.connect(get_pipeline_settings().database_url) as conn:
        yield conn


@contextmanager
def connection_scope(connection=None):
    """Use an injected transaction or open a short standalone transaction."""

    if connection is not None:
        yield connection
        return
    with connect() as managed_connection:
        yield managed_connection
