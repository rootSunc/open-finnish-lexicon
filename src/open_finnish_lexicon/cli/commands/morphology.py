"""CLI command handlers for morphology and the Chinese layer."""

from __future__ import annotations

from open_finnish_lexicon.cli.parsers import OflArgumentParser
from open_finnish_lexicon.enrich.zh import rebuild_chinese_glosses, select_zh_glosses
from open_finnish_lexicon.morphology.validator import validate_forms_with_rules
from open_finnish_lexicon.quality.report import print_data_quality_report


def dispatch(argv: list[str]) -> int | None:
    if not argv:
        return None
    cmd = argv[0]

    if cmd == "select-zh-glosses":
        OflArgumentParser(
            prog="ofl select-zh-glosses",
            description="Select Chinese gloss candidates and rebuild zh_layer.zh_gloss.",
        ).parse_args(argv[1:])
        selected_count = select_zh_glosses()
        rebuild_chinese_glosses()
        print(f"selected zh glosses: {selected_count}")
        return 0

    if cmd == "validate-morphology-rules":
        OflArgumentParser(
            prog="ofl validate-morphology-rules",
            description="Run deterministic rule-based validation over lexicon.form.",
        ).parse_args(argv[1:])
        stats = validate_forms_with_rules()
        print(
            f"morphology rule pass: verified={stats.verified} "
            f"mismatch={stats.mismatch} uncertain={stats.uncertain} "
            f"total={stats.total}"
        )
        return 0

    if cmd == "report-data-quality":
        OflArgumentParser(
            prog="ofl report-data-quality",
            description="Print lexicon and Chinese-layer row counts and coverage.",
        ).parse_args(argv[1:])
        print_data_quality_report()
        return 0

    return None
