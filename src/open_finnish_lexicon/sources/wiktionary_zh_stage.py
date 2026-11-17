from itertools import chain
from pathlib import Path

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.semantic.candidates import (
    upsert_sense_alignment_candidate,
    upsert_zh_gloss_candidate,
)
from open_finnish_lexicon.sources.wiktionary_zh_loader import read_wiktionary_zh_entries
from open_finnish_lexicon.sources.warehouse import (
    clear_source_file_documents,
    replace_source_claims,
    replace_source_document,
    upsert_source_file,
    upsert_source_registry,
    upsert_source_release,
)


def stage_wiktionary_zh_rows(
    input_path: Path,
    *,
    version: str,
    source_url: str,
    archive_path: Path | None = None,
    unpacked_path: Path | None = None,
    checksum_sha256: str = "",
) -> int:
    with connect() as conn:
        source_registry_id = upsert_source_registry(
            conn,
            name="wiktionary_zh",
            source_kind="jsonl",
            version=version,
            source_url=source_url,
            defer_activation=True,
        )
        upsert_source_release(
            conn,
            source_registry_id=source_registry_id,
            version=version,
            source_url=source_url,
            archive_path=archive_path or input_path,
            unpacked_path=unpacked_path or input_path.parent,
            checksum_sha256=checksum_sha256,
        )
        source_file_id = upsert_source_file(
            conn,
            source_registry_id=source_registry_id,
            local_path=input_path,
            checksum_sha256=checksum_sha256,
            snapshot_state="pending",
            source_version=version,
            source_url=source_url,
        )
        entries = iter(read_wiktionary_zh_entries(input_path))
        first_entry = next(entries, None)
        if first_entry is None:
            raise ValueError(
                "Wiktionary-zh input contains no valid Finnish entries; refusing to replace existing data"
            )
        clear_source_file_documents(conn, source_file_id=source_file_id)

        for entry in chain((first_entry,), entries):
            source_document_id = replace_source_document(
                conn,
                source_file_id=source_file_id,
                external_id=entry["external_id"],
                payload=entry,
            )
            claims = [("wiktionary_zh_entry", entry["lemma"], None, entry)]

            local_senses = conn.execute(
                """
                select ls.id, ls.sense_key
                from lexicon.lexeme lx
                join lexicon.lexeme_sense ls on ls.lexeme_id = lx.id
                where lx.lemma = %s and lx.part_of_speech = %s
                order by ls.id
                """,
                (entry["lemma"], entry["part_of_speech"]),
            ).fetchall()
            if len(local_senses) != len(entry["sense_glosses"]):
                replace_source_claims(conn, source_document_id=source_document_id, claims=claims)
                continue

            for index, (sense_id, sense_key) in enumerate(local_senses):
                gloss_zh = "；".join(entry["sense_glosses"][index])
                confidence_score = 0.95 if len(local_senses) == 1 else 0.80
                upsert_sense_alignment_candidate(
                    conn,
                    source_name="wiktionary_zh",
                    source_document_id=source_document_id,
                    target_sense_id=sense_id,
                    candidate_kind="ordered_sense",
                    confidence_score=confidence_score,
                    match_payload={
                        "sense_key": sense_key,
                        "lemma": entry["lemma"],
                        "part_of_speech": entry["part_of_speech"],
                        "sense_index": index,
                    },
                )
                candidate_id = upsert_zh_gloss_candidate(
                    conn,
                    target_sense_id=sense_id,
                    source_name="wiktionary_zh",
                    source_document_id=source_document_id,
                    gloss_zh=gloss_zh,
                    confidence_score=confidence_score,
                    candidate_payload={
                        "sense_key": sense_key,
                        "lemma": entry["lemma"],
                        "part_of_speech": entry["part_of_speech"],
                        "sense_index": index,
                    },
                )
                claims.append(
                    ("zh_gloss_candidate", sense_key, None, {"candidate_id": candidate_id, "gloss_zh": gloss_zh})
                )
            replace_source_claims(conn, source_document_id=source_document_id, claims=claims)
        conn.commit()
    return source_file_id
