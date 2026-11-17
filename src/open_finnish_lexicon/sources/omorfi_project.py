from pathlib import Path

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.normalize.forms import upsert_omorfi_rows
from open_finnish_lexicon.sources.omorfi_loader import OmorfiRow
from open_finnish_lexicon.sources.warehouse import source_file_id_for_path


def _omorfi_source_file_id(
    input_path: Path, source_file_id: int | None = None, connection=None
) -> int:
    with connection_scope(connection) as conn:
        return source_file_id_for_path(
            conn,
            source_name="omorfi",
            local_path=input_path,
            source_file_id=source_file_id,
        )


def project_omorfi_rows(
    input_path: Path, *, source_file_id: int | None = None, connection=None
) -> int:
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        source_file_id = _omorfi_source_file_id(input_path, source_file_id, conn)
        payload_rows = conn.execute(
            """
            select d.payload
            from warehouse.source_document d
            where d.source_file_id = %s
            order by d.id
            """,
            (source_file_id,),
        ).fetchall()

        upsert_omorfi_rows(
            [
                OmorfiRow(
                    surface_form=payload["surface_form"],
                    lemma=payload["lemma"],
                    part_of_speech=payload["part_of_speech"],
                    features=payload["features"],
                    analysis_rank=int(payload.get("analysis_rank", 1)),
                    confidence=float(payload.get("confidence", 1.0)),
                )
                for (payload,) in payload_rows
                if isinstance(payload, dict)
            ],
            source_file_id=source_file_id,
            replace_snapshot=True,
            connection=conn,
        )
        if owns_connection:
            conn.commit()
    return source_file_id
