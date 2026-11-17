from pathlib import Path

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.sources.warehouse import source_file_id_for_path


def project_dbnary_zh_rows(
    input_path: Path, *, source_file_id: int | None = None, connection=None
) -> int:
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        source_file_id = source_file_id_for_path(
            conn,
            source_name="dbnary_zh",
            local_path=input_path,
            source_file_id=source_file_id,
        )
        if owns_connection:
            conn.commit()
    return source_file_id
