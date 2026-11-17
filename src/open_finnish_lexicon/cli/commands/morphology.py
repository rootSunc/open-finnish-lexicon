"""CLI command handlers for morphology and the Chinese layer."""

from __future__ import annotations

from open_finnish_lexicon.enrich.zh import rebuild_chinese_glosses, select_zh_glosses
from open_finnish_lexicon.morphology.validator import validate_forms_with_rules
from open_finnish_lexicon.quality.report import print_data_quality_report


def dispatch(argv: list[str]) -> int | None:
    if len(argv) == 1 and argv[0] == "select-zh-glosses":
        selected_count = select_zh_glosses()
        rebuild_chinese_glosses()
        print(f"selected zh glosses: {selected_count}")
        return 0
    if len(argv) == 1 and argv[0] == "validate-morphology-rules":
        stats = validate_forms_with_rules()
        print(
            f"morphology rule pass: verified={stats.verified} "
            f"mismatch={stats.mismatch} uncertain={stats.uncertain} "
            f"total={stats.total}"
        )
        return 0
    if len(argv) == 1 and argv[0] == "report-data-quality":
        print_data_quality_report()
        return 0
    return None
