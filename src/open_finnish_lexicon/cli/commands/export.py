"""CLI command handlers for exports."""

from __future__ import annotations

from pathlib import Path

from open_finnish_lexicon.export import export_jsonl, export_sqlite


def dispatch(argv: list[str]) -> int | None:
    if len(argv) == 3 and argv[0] == "export-sqlite" and argv[1] == "--output":
        counts = export_sqlite(Path(argv[2]))
        print("export sqlite: " + " ".join(f"{table}={n}" for table, n in counts.items()))
        return 0
    if len(argv) == 3 and argv[0] == "export-jsonl" and argv[1] == "--output":
        print(f"export jsonl: lexemes={export_jsonl(Path(argv[2]))}")
        return 0
    return None
