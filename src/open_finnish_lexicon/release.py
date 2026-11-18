"""Build Zstandard-compressed distribution bundles and SHA-256 manifests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import importlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import shutil
import subprocess

from open_finnish_lexicon.export import export_jsonl, export_sqlite
from open_finnish_lexicon.quality.report import collect_data_quality_metrics


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
                    f"-{level}",
                    "-q",
                    "-f",
                    str(input_path),
                    "-o",
                    str(temp_path),
                ],
                check=True,
            )
        else:
            try:
                zstd_mod = importlib.import_module("compression.zstd")
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "zstd compression requires the 'zstd' CLI binary or Python 3.14+ compression.zstd"
                ) from exc
            with input_path.open("rb") as src, zstd_mod.open(temp_path, "wb", level=level) as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        temp_path.replace(target)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return target


def package_release(
    dist_dir: Path,
    *,
    prefix: str = "fi",
    level: int = 19,
    export_missing: bool = True,
    pure_jsonl: bool = False,
    keep_uncompressed: bool = True,
    overwrite: bool = False,
) -> ReleaseBundle:
    """Create ``<prefix>.sqlite.zst``, ``<prefix>.jsonl.zst``, ``release-manifest.json``,
    and ``SHA256SUMS`` inside ``dist_dir``."""

    dist_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = dist_dir / f"{prefix}.sqlite"
    jsonl_path = dist_dir / f"{prefix}.jsonl"
    report_path = dist_dir / f"{prefix}.sqlite.report.json"
    sqlite_zst = dist_dir / f"{prefix}.sqlite.zst"
    jsonl_zst = dist_dir / f"{prefix}.jsonl.zst"
    manifest_path = dist_dir / "release-manifest.json"
    checksums_path = dist_dir / "SHA256SUMS"

    if not overwrite:
        for out in (sqlite_zst, jsonl_zst, manifest_path, checksums_path):
            if out.exists():
                raise FileExistsError(f"{out} already exists; pass --overwrite to replace")

    if not sqlite_path.is_file():
        if not export_missing:
            raise FileNotFoundError(f"missing {sqlite_path} (--no-export was specified)")
        export_sqlite(sqlite_path, overwrite=True)

    if not jsonl_path.is_file():
        if not export_missing:
            raise FileNotFoundError(f"missing {jsonl_path} (--no-export was specified)")
        export_jsonl(
            jsonl_path,
            overwrite=True,
            include_sources_header=not pure_jsonl,
        )

    if not report_path.is_file():
        if not export_missing:
            raise FileNotFoundError(f"missing {report_path} (--no-export was specified)")
        metrics = collect_data_quality_metrics()
        _write_text_atomic(
            report_path,
            json.dumps(metrics, ensure_ascii=False, indent=2, default=str) + "\n",
        )

    sqlite_raw_size = sqlite_path.stat().st_size
    jsonl_raw_size = jsonl_path.stat().st_size

    compress_zstd(sqlite_path, sqlite_zst, level=level, overwrite=overwrite)
    compress_zstd(jsonl_path, jsonl_zst, level=level, overwrite=overwrite)

    sqlite_zst_size = sqlite_zst.stat().st_size
    jsonl_zst_size = jsonl_zst.stat().st_size
    report_size = report_path.stat().st_size

    artifacts = (
        ArtifactEntry(
            filename=sqlite_zst.name,
            sha256=sha256_file(sqlite_zst),
            size_bytes=sqlite_zst_size,
            uncompressed_filename=sqlite_path.name,
            uncompressed_size_bytes=sqlite_raw_size,
            compression_ratio=round(sqlite_zst_size / max(sqlite_raw_size, 1), 4),
        ),
        ArtifactEntry(
            filename=jsonl_zst.name,
            sha256=sha256_file(jsonl_zst),
            size_bytes=jsonl_zst_size,
            uncompressed_filename=jsonl_path.name,
            uncompressed_size_bytes=jsonl_raw_size,
            compression_ratio=round(jsonl_zst_size / max(jsonl_raw_size, 1), 4),
        ),
        ArtifactEntry(
            filename=report_path.name,
            sha256=sha256_file(report_path),
            size_bytes=report_size,
        ),
    )

    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    manifest_payload = {
        "package": "open-finnish-lexicon",
        "package_version": _package_version(),
        "generated_at": datetime.now(UTC).isoformat(),
        "compression": {
            "algorithm": "zstd",
            "level": level,
        },
        "artifacts": [
            {
                key: value
                for key, value in {
                    "filename": item.filename,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                    "uncompressed_filename": item.uncompressed_filename,
                    "uncompressed_size_bytes": item.uncompressed_size_bytes,
                    "compression_ratio": item.compression_ratio,
                }.items()
                if value is not None
            }
            for item in artifacts
        ],
        "summary": {
            "counts": report_payload.get("counts", {}),
            "coverage": report_payload.get("coverage", {}),
            "form_validation": report_payload.get("form_validation", {}),
            "invalid_zh_glosses": report_payload.get("invalid_zh_glosses", 0),
            "sources": report_payload.get("sources", []),
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

    if not keep_uncompressed:
        sqlite_path.unlink(missing_ok=True)
        jsonl_path.unlink(missing_ok=True)

    return ReleaseBundle(
        dist_dir=dist_dir,
        sqlite_zst=sqlite_zst,
        jsonl_zst=jsonl_zst,
        report_path=report_path,
        manifest_path=manifest_path,
        checksums_path=checksums_path,
        artifacts=artifacts,
    )


__all__ = [
    "ArtifactEntry",
    "ReleaseBundle",
    "compress_zstd",
    "package_release",
    "sha256_file",
]
