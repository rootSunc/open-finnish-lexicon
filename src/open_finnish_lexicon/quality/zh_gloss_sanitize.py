"""Remove invalid Chinese glosses without touching source candidates."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from open_finnish_lexicon.db import connect
from open_finnish_lexicon.zh_script import simplified_chinese_text_issue


@dataclass(frozen=True)
class ZhGlossSanitizeStats:
    invalid_materialized: int = 0
    invalid_selected: int = 0
    materialized_by_issue: dict[str, int] | None = None
    selected_by_issue: dict[str, int] | None = None
    applied: bool = False


def _issue_category(value: object) -> str:
    issue = simplified_chinese_text_issue(value)
    if issue is None:
        return "usable"
    if "dictionary metadata" in issue:
        return "dictionary_metadata"
    if issue.startswith("traditional Chinese"):
        return "traditional_chinese"
    if issue.startswith("untranslated Latin"):
        return "latin_residue"
    if issue == "Chinese text has no Han characters":
        return "no_han_characters"
    return "other"


def sanitize_invalid_zh_glosses(*, apply: bool = False) -> ZhGlossSanitizeStats:
    """Delete invalid glosses and selections; ``apply=False`` only counts them.

    ``semantic.zh_gloss_candidate`` keeps every source row, so a later run with
    better rules can still use them.
    """

    with connect() as conn:
        materialized_rows = conn.execute(
            "select id, gloss_zh from zh_layer.zh_gloss where gloss_zh is not null order by id"
        ).fetchall()
        selected_rows = conn.execute(
            "select target_sense_id, gloss_zh from semantic.zh_gloss_selection order by target_sense_id"
        ).fetchall()
        invalid_materialized = [
            (int(row_id), gloss_zh)
            for row_id, gloss_zh in materialized_rows
            if simplified_chinese_text_issue(gloss_zh) is not None
        ]
        invalid_selected = [
            (int(sense_id), gloss_zh)
            for sense_id, gloss_zh in selected_rows
            if simplified_chinese_text_issue(gloss_zh) is not None
        ]
        stats = dict(
            invalid_materialized=len(invalid_materialized),
            invalid_selected=len(invalid_selected),
            materialized_by_issue=dict(Counter(_issue_category(g) for _, g in invalid_materialized)),
            selected_by_issue=dict(Counter(_issue_category(g) for _, g in invalid_selected)),
        )
        if not apply:
            conn.rollback()
            return ZhGlossSanitizeStats(**stats)

        if invalid_materialized:
            conn.execute(
                "delete from zh_layer.zh_gloss where id = any(%s)",
                ([row_id for row_id, _ in invalid_materialized],),
            )
        if invalid_selected:
            conn.execute(
                "delete from semantic.zh_gloss_selection where target_sense_id = any(%s)",
                ([sense_id for sense_id, _ in invalid_selected],),
            )
        conn.commit()
    return ZhGlossSanitizeStats(**stats, applied=True)


def render_zh_gloss_sanitize_stats(stats: ZhGlossSanitizeStats) -> str:
    mode = "applied" if stats.applied else "dry run"
    return (
        f"invalid zh gloss sanitize ({mode}): "
        f"materialized={stats.invalid_materialized} "
        f"selected={stats.invalid_selected} "
        f"materialized_by_issue={stats.materialized_by_issue or {}} "
        f"selected_by_issue={stats.selected_by_issue or {}}"
    )


__all__ = [
    "ZhGlossSanitizeStats",
    "render_zh_gloss_sanitize_stats",
    "sanitize_invalid_zh_glosses",
]
