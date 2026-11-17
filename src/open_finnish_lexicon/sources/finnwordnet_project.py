from pathlib import Path

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.sources.finnwordnet_loader import (
    FinnWordNetLexicalRelation,
    FinnWordNetWordSense,
    ingest_finnwordnet,
)
from open_finnish_lexicon.sources.warehouse import source_file_id_for_path


def project_finnwordnet_rows(
    input_path: Path, *, source_file_id: int | None = None, connection=None
) -> int:
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        source_file_id = source_file_id_for_path(
            conn,
            source_name="finnwordnet",
            local_path=input_path,
            source_file_id=source_file_id,
        )
        staged_word_senses: list[FinnWordNetWordSense] = []
        staged_relations: list[FinnWordNetLexicalRelation] = []
        for (payload,) in conn.execute(
            """
            select payload
            from warehouse.source_document
            where source_file_id = %s
            order by id
            """,
            (source_file_id,),
        ).fetchall():
            if not isinstance(payload, dict):
                continue
            if payload.get("kind") == "wsense":
                staged_word_senses.append(
                    FinnWordNetWordSense(
                        synset_id=str(payload["synset_id"]),
                        word=str(payload["word"]),
                        part_of_speech=str(payload["part_of_speech"]),
                    )
                )
            elif payload.get("kind") == "lexrel":
                staged_relations.append(
                    FinnWordNetLexicalRelation(
                        source_lemma=str(payload["source_lemma"]),
                        source_pos=str(payload["source_pos"]),
                        target_lemma=str(payload["target_lemma"]),
                        target_pos=str(payload["target_pos"]),
                        relation_type=str(payload["relation_type"]),
                    )
                )
        ingest_finnwordnet(
            input_path,
            source_file_id=source_file_id,
            word_senses=staged_word_senses,
            relations=staged_relations,
            connection=conn,
        )
        if owns_connection:
            conn.commit()
    return source_file_id
