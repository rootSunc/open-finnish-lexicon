from itertools import chain
from pathlib import Path
import re
import unicodedata

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.semantic.candidates import (
    upsert_sense_alignment_candidate,
    upsert_zh_gloss_candidate,
)
from open_finnish_lexicon.sources.dbnary_zh_loader import read_dbnary_zh_candidates
from open_finnish_lexicon.sources.warehouse import (
    clear_source_file_documents,
    replace_source_claims,
    replace_source_document,
    upsert_source_file,
    upsert_source_registry,
    upsert_source_release,
)


def _normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    normalized = "".join(char if char.isalnum() else " " for char in without_marks)
    return re.sub(r"\s+", " ", normalized).strip()


def _normalized_gloss_variants(value: object) -> set[str]:
    if not isinstance(value, str):
        return set()
    variants = [value, *re.split(r"\s*;\s*", value)]
    return {normalized for variant in variants if (normalized := _normalize_text(variant))}


def _find_enhancement_path(base_dir: Path) -> Path:
    for candidate in (
        "fi_dbnary_enhancement.ttl",
        "en_dbnary_enhancement.ttl",
        "dbnary-zh-enhancement.ttl",
    ):
        path = base_dir / candidate
        if path.exists():
            return path
    raise FileNotFoundError("dbnary enhancement TTL not found")


def stage_dbnary_zh_rows(
    input_path: Path,
    *,
    version: str,
    source_url: str,
    archive_path: Path | None = None,
    unpacked_path: Path | None = None,
    checksum_sha256: str = "",
) -> int:
    base_dir = unpacked_path or input_path.parent
    enhancement_path = _find_enhancement_path(base_dir)
    with connect() as conn:
        source_registry_id = upsert_source_registry(
            conn,
            name="dbnary_zh",
            source_kind="ttl",
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
            unpacked_path=base_dir,
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
        entries = iter(read_dbnary_zh_candidates(input_path, enhancement_path))
        first_entry = next(entries, None)
        if first_entry is None:
            raise ValueError(
                "DBnary-zh input contains no valid Chinese candidates; refusing to replace existing data"
            )
        clear_source_file_documents(conn, source_file_id=source_file_id)

        for entry in chain((first_entry,), entries):
            source_document_id = replace_source_document(
                conn,
                source_file_id=source_file_id,
                external_id=entry["external_id"],
                payload=entry,
            )
            claims = [("dbnary_zh_entry", entry["lemma"], None, entry)]

            candidate_senses = conn.execute(
                """
                select ls.id, ls.sense_key, ls.gloss_en, ls.gloss_fi
                from lexicon.lexeme lx
                join lexicon.lexeme_sense ls on ls.lexeme_id = lx.id
                where lx.lemma = %s and lx.part_of_speech = %s
                order by ls.sort_order, ls.id
                """,
                (entry["lemma"], entry["part_of_speech"]),
            ).fetchall()
            source_gloss_en = entry.get("gloss_en")
            source_gloss_fi = entry.get("gloss_fi")
            source_en_variants = _normalized_gloss_variants(source_gloss_en)
            source_fi_variants = _normalized_gloss_variants(source_gloss_fi)
            matching = [
                (sense_id, sense_key)
                for sense_id, sense_key, gloss_en, gloss_fi in candidate_senses
                if (
                    source_en_variants and source_en_variants & _normalized_gloss_variants(gloss_en)
                )
                or (
                    source_fi_variants and source_fi_variants & _normalized_gloss_variants(gloss_fi)
                )
            ]
            candidate_kind = "exact_gloss"
            confidence_score = 0.70
            if len(matching) != 1:
                sense_index = int(entry.get("sense_index", -1))
                source_sense_count = int(entry.get("source_sense_count", -1))
                if source_sense_count == len(candidate_senses) and 0 <= sense_index < len(
                    candidate_senses
                ):
                    sense_id, sense_key, _gloss_en, _gloss_fi = candidate_senses[sense_index]
                    matching = [(sense_id, sense_key)]
                    candidate_kind = "ordered_sense"
                    confidence_score = 0.62
                else:
                    replace_source_claims(
                        conn, source_document_id=source_document_id, claims=claims
                    )
                    continue
            if len(matching) != 1:
                replace_source_claims(conn, source_document_id=source_document_id, claims=claims)
                continue

            sense_id, sense_key = matching[0]
            gloss_zh = "；".join(entry["zh_terms"])
            upsert_sense_alignment_candidate(
                conn,
                source_name="dbnary_zh",
                source_document_id=source_document_id,
                target_sense_id=sense_id,
                candidate_kind=candidate_kind,
                confidence_score=confidence_score,
                match_payload={
                    "sense_key": sense_key,
                    "lemma": entry["lemma"],
                    "part_of_speech": entry["part_of_speech"],
                    "source_gloss_en": source_gloss_en,
                    "source_gloss_fi": source_gloss_fi,
                    "source_gloss_language": entry.get("source_gloss_language"),
                    "source_gloss": entry.get("source_gloss"),
                    "sense_index": entry.get("sense_index"),
                    "match_kind": candidate_kind,
                },
            )
            candidate_id = upsert_zh_gloss_candidate(
                conn,
                target_sense_id=sense_id,
                source_name="dbnary_zh",
                source_document_id=source_document_id,
                gloss_zh=gloss_zh,
                confidence_score=confidence_score,
                candidate_payload={
                    "sense_key": sense_key,
                    "lemma": entry["lemma"],
                    "part_of_speech": entry["part_of_speech"],
                    "source_gloss_en": source_gloss_en,
                    "source_gloss_fi": source_gloss_fi,
                    "source_gloss_language": entry.get("source_gloss_language"),
                    "source_gloss": entry.get("source_gloss"),
                    "sense_index": entry.get("sense_index"),
                    "match_kind": candidate_kind,
                    "requires_llm_review": candidate_kind != "exact_gloss",
                },
            )
            claims.append(
                (
                    "zh_gloss_candidate",
                    sense_key,
                    None,
                    {"candidate_id": candidate_id, "gloss_zh": gloss_zh},
                )
            )
            replace_source_claims(conn, source_document_id=source_document_id, claims=claims)
        conn.commit()
    return source_file_id
