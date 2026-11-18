"""CLI command handlers for exports."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from subprocess import CalledProcessError

from open_finnish_lexicon.cli.parsers import OflArgumentParser, non_empty_str, positive_int
from open_finnish_lexicon.export import export_jsonl, export_sqlite
from open_finnish_lexicon.release import package_release


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

    if cmd == "package-release":
        parser = OflArgumentParser(
            prog="ofl package-release",
            description=(
                "Package .sqlite.zst and .jsonl.zst distribution archives with "
                "release-manifest.json and SHA256SUMS."
            ),
        )
        parser.add_argument(
            "--dist-dir",
            type=non_empty_str,
            default="dist",
            help="Directory for release artifacts (default: dist)",
        )
        parser.add_argument(
            "--prefix",
            type=non_empty_str,
            default="fi",
            help="Base filename stem (default: fi)",
        )
        parser.add_argument(
            "--level",
            type=positive_int,
            default=19,
            help="Zstandard compression level 1..22 (default: 19)",
        )
        parser.add_argument(
            "--no-export",
            action="store_true",
            help="Repackage the verified raw files and report from a previous package-release run",
        )
        parser.add_argument(
            "--pure-jsonl",
            "--no-sources-header",
            dest="pure_jsonl",
            action="store_true",
            help="Omit the leading _sources metadata line in the fresh JSONL export",
        )
        parser.add_argument(
            "--remove-uncompressed",
            action="store_true",
            help="Remove uncompressed .sqlite and .jsonl after verifying .zst archives",
        )
        parser.add_argument(
            "--overwrite",
            "--force",
            dest="overwrite",
            action="store_true",
            help="Replace existing release outputs",
        )
        parser.add_argument(
            "--code-revision",
            type=non_empty_str,
            help="Git commit used for the fresh export",
        )
        parser.add_argument(
            "--dataset-version",
            type=non_empty_str,
            help="Version label for the fresh dataset snapshot",
        )
        ns = parser.parse_args(argv[1:])
        try:
            bundle = package_release(
                Path(ns.dist_dir),
                prefix=ns.prefix,
                level=ns.level,
                export_missing=not ns.no_export,
                pure_jsonl=ns.pure_jsonl,
                keep_uncompressed=not ns.remove_uncompressed,
                overwrite=ns.overwrite,
                code_revision=ns.code_revision,
                dataset_version=ns.dataset_version,
            )
        except (CalledProcessError, OSError, ValueError, sqlite3.DatabaseError) as exc:
            parser.error(str(exc))
        print(
            f"package release: sqlite_zst={bundle.sqlite_zst} "
            f"jsonl_zst={bundle.jsonl_zst} checksums={bundle.checksums_path}"
        )
        return 0

    return None
