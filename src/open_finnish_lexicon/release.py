"""Build Zstandard-compressed distribution bundles and SHA-256 manifests."""

from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
import hashlib
import importlib
from importlib import resources
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from open_finnish_lexicon.config import get_pipeline_settings
from open_finnish_lexicon.db import connect
from open_finnish_lexicon.export import EXPORT_SCHEMA_VERSION, export_jsonl, export_sqlite
from open_finnish_lexicon.quality.report import collect_data_quality_metrics
from open_finnish_lexicon.sources.registry import SYNC_SOURCE_ORDER


@dataclass(frozen=True)
class ArtifactEntry:
    filename: str
    sha256: str
    size_bytes: int
    uncompressed_filename: str | None = None
    uncompressed_size_bytes: int | None = None
    compression_ratio: float | None = None


@dataclass(frozen=True)
class ReleaseBundle:
    dist_dir: Path
    sqlite_zst: Path
    jsonl_zst: Path
    report_path: Path
    manifest_path: Path
    checksums_path: Path
    artifacts: tuple[ArtifactEntry, ...]


def _package_version() -> str:
    try:
        return version("open-finnish-lexicon")
    except PackageNotFoundError:
        return "0.1.0"


def sha256_file(path: Path) -> str:
    """Compute the hex SHA-256 digest of ``path`` using streamed reads."""

    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.part")
    temp_path.unlink(missing_ok=True)
    try:
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def compress_zstd(
    input_path: Path,
    output_path: Path | None = None,
    *,
    level: int = 19,
    overwrite: bool = False,
) -> Path:
    """Compress ``input_path`` into a ``.zst`` file via an atomic ``.part`` swap."""

    if not 1 <= level <= 22:
        raise ValueError(f"zstd compression level must be between 1 and 22, got {level}")
    if not input_path.is_file():
        raise FileNotFoundError(f"input file does not exist: {input_path}")

    target = output_path or input_path.with_name(input_path.name + ".zst")
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.part")
    temp_path.unlink(missing_ok=True)

    zstd_bin = shutil.which("zstd")
    try:
        if zstd_bin is not None:
            subprocess.run(
                [
                    zstd_bin,
                    "-T0",
                    *(["--ultra"] if level > 19 else []),
                    f"-{level}",
                    "-q",
                    "-f",
                    str(input_path),
                    "-o",
                    str(temp_path),
                ],
                check=True,
            )
            subprocess.run([zstd_bin, "-q", "-t", str(temp_path)], check=True)
        else:
            try:
                zstd_mod = importlib.import_module("compression.zstd")
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "zstd compression requires the 'zstd' CLI binary or Python 3.14+ compression.zstd"
                ) from exc
            with input_path.open("rb") as src, zstd_mod.open(temp_path, "wb", level=level) as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            with zstd_mod.open(temp_path, "rb") as restored:
                if hashlib.file_digest(restored, "sha256").hexdigest() != sha256_file(input_path):
                    raise ValueError("compressed archive does not match its input")
        temp_path.replace(target)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return target


def _export_snapshot(
    sqlite_path: Path,
    jsonl_path: Path,
    report_path: Path,
    *,
    pure_jsonl: bool,
    code_revision: str | None,
    dataset_version: str | None,
) -> None:
    build_id = uuid4().hex
    with connect() as conn:
        conn.execute("set transaction isolation level repeatable read read only")
        metrics = collect_data_quality_metrics(connection=conn)
        if not metrics["counts"]["lexicon.lexeme"] or not metrics["counts"]["lexicon.lexeme_sense"]:
            raise ValueError("cannot package an empty lexicon; populate the database first")
        export_sqlite(sqlite_path, connection=conn, build_id=build_id)
        export_jsonl(
            jsonl_path,
            connection=conn,
            build_id=build_id,
            include_sources_header=not pure_jsonl,
        )
    metrics["snapshot"] = {
        "build_id": build_id,
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "package_version": _package_version(),
        "code_revision": code_revision,
        "dataset_version": dataset_version,
        "profile": get_pipeline_settings().data_profile,
        "jsonl_sources_header": not pure_jsonl,
        "raw_sha256": {path.name: sha256_file(path) for path in (sqlite_path, jsonl_path)},
    }
    active_sources = {source["name"] for source in metrics["sources"]}
    metrics["skipped_sources"] = [name for name in SYNC_SOURCE_ORDER if name not in active_sources]
    _write_text_atomic(report_path, json.dumps(metrics, ensure_ascii=False, indent=2, default=str) + "\n")


def _validate_snapshot(sqlite_path: Path, jsonl_path: Path, report_path: Path) -> dict[str, Any]:
    for path in (sqlite_path, jsonl_path, report_path):
        if not path.is_file():
            raise FileNotFoundError(f"missing release input {path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    snapshot = report.get("snapshot", {}) if isinstance(report, dict) else {}
    if not snapshot.get("build_id") or snapshot.get("schema_version") != EXPORT_SCHEMA_VERSION:
        raise ValueError("inputs must come from one package-release snapshot; regenerate without --no-export")
    for path in (sqlite_path, jsonl_path):
        if sha256_file(path) != snapshot.get("raw_sha256", {}).get(path.name):
            raise ValueError(f"{path.name} does not match the release report; regenerate without --no-export")

    counts = report.get("counts", {})
    expected = tuple(counts.get(f"lexicon.{table}") for table in ("lexeme", "lexeme_sense", "form"))
    if not expected[0] or not expected[1]:
        raise ValueError("cannot package an empty lexicon")
    with closing(sqlite3.connect(sqlite_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("pragma user_version").fetchone() != (EXPORT_SCHEMA_VERSION,):
            raise ValueError("SQLite schema version does not match the release report")
        if db.execute("select build_id from export_metadata").fetchall() != [(snapshot["build_id"],)]:
            raise ValueError("SQLite build ID does not match the release report")
        if db.execute("pragma quick_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite failed quick_check")
        if db.execute("pragma foreign_key_check").fetchone() is not None:
            raise ValueError("SQLite has broken foreign keys")
        actual = db.execute(
            "select (select count(*) from lexeme), (select count(*) from sense), (select count(*) from form)"
        ).fetchone()
        if actual != expected:
            raise ValueError("SQLite core counts do not match the release report")

    lexemes = senses = forms = 0
    with jsonl_path.open(encoding="utf-8") as handle:
        if snapshot.get("jsonl_sources_header"):
            header = json.loads(next(handle, "{}"))
            if header.get("_export") != {
                "build_id": snapshot["build_id"],
                "schema_version": EXPORT_SCHEMA_VERSION,
            }:
                raise ValueError("JSONL build ID or schema version does not match the release report")
        for line in handle:
            row = json.loads(line)
            lexemes += 1
            senses += len(row["senses"])
            forms += len(row["forms"])
    if (lexemes, senses, forms) != expected:
        raise ValueError("JSONL core counts do not match the release report")
    return report

def _compress_artifact(path: Path, target: Path, *, level: int) -> ArtifactEntry:
    compress_zstd(path, target, level=level)
    raw_size = path.stat().st_size
    size = target.stat().st_size
    return ArtifactEntry(
        filename=target.name,
        sha256=sha256_file(target),
        size_bytes=size,
        uncompressed_filename=path.name,
        uncompressed_size_bytes=raw_size,
        compression_ratio=round(size / raw_size, 4),
    )


def _assemble_release(
    dist_dir: Path,
    sqlite_path: Path,
    jsonl_path: Path,
    report_path: Path,
    *,
    level: int,
) -> ReleaseBundle:
    report_payload = _validate_snapshot(sqlite_path, jsonl_path, report_path)
    sqlite_zst = dist_dir / f"{sqlite_path.name}.zst"
    jsonl_zst = dist_dir / f"{jsonl_path.name}.zst"
    manifest_path = dist_dir / "release-manifest.json"
    checksums_path = dist_dir / "SHA256SUMS"
    notice_path = dist_dir / "DATA-NOTICE.md"
    notice_path.write_text(
        resources.files("open_finnish_lexicon").joinpath(notice_path.name).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    artifacts = (
        _compress_artifact(sqlite_path, sqlite_zst, level=level),
        _compress_artifact(jsonl_path, jsonl_zst, level=level),
        ArtifactEntry(report_path.name, sha256_file(report_path), report_path.stat().st_size),
        ArtifactEntry(notice_path.name, sha256_file(notice_path), notice_path.stat().st_size),
    )
    manifest_payload = {
        "package": "open-finnish-lexicon",
        "package_version": _package_version(),
        "generated_at": datetime.now(UTC).isoformat(),
        "snapshot": report_payload["snapshot"],
        "compression": {
            "algorithm": "zstd",
            "level": level,
        },
        "artifacts": [
            {key: value for key, value in asdict(item).items() if value is not None}
            for item in artifacts
        ],
        "summary": {
            "counts": report_payload.get("counts", {}),
            "coverage": report_payload.get("coverage", {}),
            "form_validation": report_payload.get("form_validation", {}),
            "invalid_zh_glosses": report_payload.get("invalid_zh_glosses", 0),
            "sources": report_payload.get("sources", []),
            "skipped_sources": report_payload.get("skipped_sources", []),
        },
    }
    _write_text_atomic(
        manifest_path,
        json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n",
    )

    checksum_items = [
        *(
            (item.sha256, item.filename)
            for item in artifacts
        ),
        (sha256_file(manifest_path), manifest_path.name),
    ]
    checksum_items.sort(key=lambda pair: pair[1])
    checksum_lines = "".join(f"{digest}  {name}\n" for digest, name in checksum_items)
    _write_text_atomic(checksums_path, checksum_lines)

    return ReleaseBundle(
        dist_dir=dist_dir,
        sqlite_zst=sqlite_zst,
        jsonl_zst=jsonl_zst,
        report_path=report_path,
        manifest_path=manifest_path,
        checksums_path=checksums_path,
        artifacts=artifacts,
    )


def package_release(
    dist_dir: Path,
    *,
    prefix: str = "fi",
    level: int = 19,
    export_missing: bool = True,
    pure_jsonl: bool = False,
    keep_uncompressed: bool = True,
    overwrite: bool = False,
    code_revision: str | None = None,
    dataset_version: str | None = None,
) -> ReleaseBundle:
    """Export one database snapshot, or package a verified previous export offline."""

    if not prefix or not prefix.replace("-", "").replace("_", "").isalnum():
        raise ValueError("release prefix must contain only letters, numbers, hyphens or underscores")
    if not 1 <= level <= 22:
        raise ValueError("zstd compression level must be between 1 and 22")
    if not export_missing and (pure_jsonl or code_revision is not None or dataset_version is not None):
        raise ValueError("--pure-jsonl, --code-revision and --dataset-version require a fresh export")

    new_directory = not dist_dir.exists()
    stage_parent = dist_dir.parent if new_directory else dist_dir
    stage_parent.mkdir(parents=True, exist_ok=True)
    raw_names = (f"{prefix}.sqlite", f"{prefix}.jsonl")
    report_name = f"{prefix}.sqlite.report.json"
    outputs = [
        *(f"{name}.zst" for name in raw_names), "DATA-NOTICE.md", "release-manifest.json", "SHA256SUMS",
    ]
    if export_missing:
        outputs[:0] = [*raw_names, report_name] if keep_uncompressed else [report_name]
    if not overwrite:
        checked_names = [*outputs, *raw_names] if export_missing and not keep_uncompressed else outputs
        for name in checked_names:
            if (dist_dir / name).exists():
                raise FileExistsError(f"{dist_dir / name} already exists; pass --overwrite to replace")

    with TemporaryDirectory(prefix=".ofl-release-", dir=stage_parent) as temp_dir:
        stage = Path(temp_dir)
        inputs = stage if export_missing else dist_dir
        sqlite_path, jsonl_path = (inputs / name for name in raw_names)
        report_path = inputs / report_name
        if export_missing:
            _export_snapshot(
                sqlite_path, jsonl_path, report_path,
                pure_jsonl=pure_jsonl, code_revision=code_revision, dataset_version=dataset_version,
            )
        bundle = _assemble_release(stage, sqlite_path, jsonl_path, report_path, level=level)
        if new_directory:
            if not keep_uncompressed:
                sqlite_path.unlink()
                jsonl_path.unlink()
            stage.rename(dist_dir)
        else:
            # Keep SHA256SUMS last so readers can verify a complete set after replacement.
            for name in outputs:
                (stage / name).replace(dist_dir / name)
            if not keep_uncompressed:
                for name in raw_names:
                    (dist_dir / name).unlink(missing_ok=True)
    return replace(
        bundle,
        dist_dir=dist_dir,
        sqlite_zst=dist_dir / bundle.sqlite_zst.name,
        jsonl_zst=dist_dir / bundle.jsonl_zst.name,
        report_path=dist_dir / report_name,
        manifest_path=dist_dir / bundle.manifest_path.name,
        checksums_path=dist_dir / bundle.checksums_path.name,
    )


__all__ = [
    "ArtifactEntry",
    "ReleaseBundle",
    "compress_zstd",
    "package_release",
    "sha256_file",
]
