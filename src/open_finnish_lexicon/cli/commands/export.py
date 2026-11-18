"""CLI command handlers for exports."""

from __future__ import annotations

from pathlib import Path

from open_finnish_lexicon.cli.parsers import OflArgumentParser, non_empty_str
from open_finnish_lexicon.export import export_jsonl, export_sqlite


def dispatch(argv: list[str]) -> int | None:
    if not argv:
        return None
    cmd = argv[0]

    if cmd == "export-sqlite":
        parser = OflArgumentParser(
            prog="ofl export-sqlite",
            description="Export the lexicon and Chinese layer into a standalone SQLite database.",
        )
        parser.add_argument(
            "--output",
            required=True,
            type=non_empty_str,
            help="Output SQLite file path",
        )
        parser.add_argument(
            "--overwrite",
            "--force",
            dest="overwrite",
            action="store_true",
            help="Replace an existing SQLite file atomically",
        )
        ns = parser.parse_args(argv[1:])
        counts = (
            export_sqlite(Path(ns.output), overwrite=True)
            if ns.overwrite
            else export_sqlite(Path(ns.output))
        )
        print("export sqlite: " + " ".join(f"{table}={n}" for table, n in counts.items()))
        return 0

    if cmd == "export-jsonl":
        parser = OflArgumentParser(
            prog="ofl export-jsonl",
            description="Export one JSON object per lexeme to JSON Lines.",
        )
        parser.add_argument(
            "--output",
            required=True,
            type=non_empty_str,
            help="Output JSONL file path",
        )
        parser.add_argument(
            "--overwrite",
            "--force",
            dest="overwrite",
            action="store_true",
            help="Replace an existing JSONL file atomically",
        )
        parser.add_argument(
            "--pure-jsonl",
            "--no-sources-header",
            dest="pure_jsonl",
            action="store_true",
            help="Omit the leading _sources metadata line so every line is a homogeneous lexeme record",
        )
        ns = parser.parse_args(argv[1:])
        if ns.overwrite or ns.pure_jsonl:
            written = export_jsonl(
                Path(ns.output),
                overwrite=ns.overwrite,
                include_sources_header=not ns.pure_jsonl,
            )
        else:
            written = export_jsonl(Path(ns.output))
        print(f"export jsonl: lexemes={written}")
        return 0

    return None
