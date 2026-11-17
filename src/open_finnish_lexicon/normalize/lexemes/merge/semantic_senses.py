"""Merge semantic-layer rows when two senses collapse."""

from psycopg.types.json import Jsonb

def _merge_semantic_sense_rows(conn, source_sense_id: int, target_sense_id: int) -> None:
    alignment_candidate_rows = conn.execute(
        """
        select source_name, source_document_id, candidate_kind, confidence_score, match_payload
        from semantic.sense_alignment_candidate
        where target_sense_id = %s
        order by id
        """,
        (source_sense_id,),
    ).fetchall()
    for source_name, source_document_id, candidate_kind, confidence_score, match_payload in alignment_candidate_rows:
        conn.execute(
            """
            insert into semantic.sense_alignment_candidate (
                source_name,
                source_document_id,
                target_sense_id,
                candidate_kind,
                confidence_score,
                match_payload
            )
            values (%s, %s, %s, %s, %s, %s)
            on conflict (source_name, source_document_id, target_sense_id, candidate_kind)
            do update set
                confidence_score = greatest(
                    semantic.sense_alignment_candidate.confidence_score,
                    excluded.confidence_score
                ),
                match_payload = excluded.match_payload
            """,
            (
                source_name,
                source_document_id,
                target_sense_id,
                candidate_kind,
                confidence_score,
                Jsonb(match_payload),
            ),
        )
    conn.execute(
        "delete from semantic.sense_alignment_candidate where target_sense_id = %s",
        (source_sense_id,),
    )

    alignment_rows = conn.execute(
        """
        select source_name, source_document_id, status, confidence_score, selection_reason
        from semantic.sense_alignment
        where target_sense_id = %s
        order by id
        """,
        (source_sense_id,),
    ).fetchall()
    for source_name, source_document_id, status, confidence_score, selection_reason in alignment_rows:
        conn.execute(
            """
            insert into semantic.sense_alignment (
                source_name,
                source_document_id,
                target_sense_id,
                status,
                confidence_score,
                selection_reason
            )
            values (%s, %s, %s, %s, %s, %s)
            on conflict (source_name, source_document_id, target_sense_id)
            do update set
                status = excluded.status,
                confidence_score = greatest(
                    semantic.sense_alignment.confidence_score,
                    excluded.confidence_score
                ),
                selection_reason = excluded.selection_reason
            """,
            (
                source_name,
                source_document_id,
                target_sense_id,
                status,
                confidence_score,
                selection_reason,
            ),
        )
    conn.execute(
        "delete from semantic.sense_alignment where target_sense_id = %s",
        (source_sense_id,),
    )

    source_candidate_rows = conn.execute(
        """
        select id, source_name, source_document_id, gloss_zh, confidence_score, candidate_payload
        from semantic.zh_gloss_candidate
        where target_sense_id = %s
        order by id
        """,
        (source_sense_id,),
    ).fetchall()
    candidate_id_map: dict[int, int] = {}
    for candidate_id, source_name, source_document_id, gloss_zh, confidence_score, candidate_payload in source_candidate_rows:
        target_candidate_id = conn.execute(
            """
            insert into semantic.zh_gloss_candidate (
                target_sense_id,
                source_name,
                source_document_id,
                gloss_zh,
                confidence_score,
                candidate_payload
            )
            values (%s, %s, %s, %s, %s, %s)
            on conflict (target_sense_id, source_name, source_document_id, gloss_zh)
            do update set
                confidence_score = greatest(
                    semantic.zh_gloss_candidate.confidence_score,
                    excluded.confidence_score
                ),
                candidate_payload = excluded.candidate_payload
            returning id
            """,
            (
                target_sense_id,
                source_name,
                source_document_id,
                gloss_zh,
                confidence_score,
                Jsonb(candidate_payload),
            ),
        ).fetchone()[0]
        candidate_id_map[int(candidate_id)] = int(target_candidate_id)

    selection_row = conn.execute(
        """
        select zh_gloss_candidate_id, gloss_zh, selected_by, confidence_score, selection_reason
        from semantic.zh_gloss_selection
        where target_sense_id = %s
        """,
        (source_sense_id,),
    ).fetchone()
    if selection_row is not None:
        (
            source_candidate_id,
            gloss_zh,
            selected_by,
            confidence_score,
            selection_reason,
        ) = selection_row
        mapped_candidate_id = candidate_id_map.get(int(source_candidate_id), int(source_candidate_id))
        existing_target_selection = conn.execute(
            """
            select confidence_score
            from semantic.zh_gloss_selection
            where target_sense_id = %s
            """,
            (target_sense_id,),
        ).fetchone()
        target_confidence = (
            float(existing_target_selection[0])
            if existing_target_selection is not None and existing_target_selection[0] is not None
            else None
        )
        if target_confidence is None or float(confidence_score) > target_confidence:
            conn.execute(
                """
                insert into semantic.zh_gloss_selection (
                    target_sense_id,
                    zh_gloss_candidate_id,
                    gloss_zh,
                    selected_by,
                    confidence_score,
                    selection_reason
                )
                values (%s, %s, %s, %s, %s, %s)
                on conflict (target_sense_id) do update
                set zh_gloss_candidate_id = excluded.zh_gloss_candidate_id,
                    gloss_zh = excluded.gloss_zh,
                    selected_by = excluded.selected_by,
                    confidence_score = excluded.confidence_score,
                    selection_reason = excluded.selection_reason,
                    selected_at = now()
                """,
                (
                    target_sense_id,
                    mapped_candidate_id,
                    gloss_zh,
                    selected_by,
                    confidence_score,
                    selection_reason,
                ),
            )
    conn.execute(
        "delete from semantic.zh_gloss_selection where target_sense_id = %s",
        (source_sense_id,),
    )


    if source_candidate_rows:
        conn.execute(
            "delete from semantic.zh_gloss_candidate where target_sense_id = %s",
            (source_sense_id,),
        )
