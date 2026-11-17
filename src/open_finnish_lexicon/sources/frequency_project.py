from pathlib import Path

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.sources.frequency_loader import FrequencyEntry, ingest_frequency
from open_finnish_lexicon.sources.warehouse import source_file_id_for_path


def project_frequency_rows(
    input_path: Path, *, source_file_id: int | None = None, connection=None
) -> int:
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        source_file_id = source_file_id_for_path(
            conn,
            source_name="frequency",
            local_path=input_path,
            source_file_id=source_file_id,
        )
        payload_rows = conn.execute(
            """
            select payload
            from warehouse.source_document
            where source_file_id = %s
            order by id
            """,
            (source_file_id,),
        ).fetchall()
        staged_entries = [
            FrequencyEntry(
                term=payload["term"],
                raw_count=int(payload["raw_count"]),
                lemma=payload.get("lemma"),
                pos=payload.get("pos"),
                normalized_score=(
                    float(payload["normalized_score"])
                    if payload.get("normalized_score") is not None
                    else None
                ),
            )
            for (payload,) in payload_rows
            if isinstance(payload, dict)
        ]
        ingest_frequency(input_path, entries=staged_entries, connection=conn)
        if owns_connection:
            conn.commit()
    return source_file_id
