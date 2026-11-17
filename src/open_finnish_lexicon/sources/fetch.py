from dataclasses import dataclass
from hashlib import sha256
import bz2
import gzip
import json
from pathlib import Path
import shutil
import tarfile
from urllib.parse import urlparse
from urllib.request import urlopen
import zipfile

from open_finnish_lexicon.sources.catalog import SourceRelease


@dataclass(frozen=True)
class FetchResult:
    archive_path: Path
    unpack_dir: Path
    checksum_sha256: str
    member_paths: tuple[Path, ...]


DOWNLOAD_TIMEOUT_SECONDS = 60
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
# Decompressed output may be much larger than the download (the Kaikki Finnish
# JSONL is over 2 GiB unpacked); the cap still stops decompression bombs.
MAX_EXTRACTED_BYTES = 16 * 1024 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024


def _copy_limited(source, output, *, limit: int = MAX_DOWNLOAD_BYTES) -> int:
    total = 0
    while chunk := source.read(COPY_CHUNK_BYTES):
        total += len(chunk)
        if total > limit:
            raise ValueError(f"download exceeds the {limit} byte safety limit")
        output.write(chunk)
    return total


def _download_to_path(url: str, archive_path: Path) -> None:
    parsed = urlparse(url)
    partial_path = archive_path.with_name(f".{archive_path.name}.part")
    try:
        if parsed.scheme in {"http", "https", "file"}:
            with (
                urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response,
                partial_path.open("wb") as output,
            ):
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
                    raise ValueError(f"download exceeds the {MAX_DOWNLOAD_BYTES} byte safety limit")
                _copy_limited(response, output)
        else:
            source_path = Path(url)
            if not source_path.is_absolute():
                source_path = Path.cwd() / source_path
            with source_path.open("rb") as source, partial_path.open("wb") as output:
                _copy_limited(source, output)
        partial_path.replace(archive_path)
    finally:
        partial_path.unlink(missing_ok=True)


def _resolve_asset_source(url: str, local_path: str) -> str:
    if local_path:
        candidate = Path(local_path)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        if candidate.exists():
            return str(candidate)
    return url


def _archive_filename(name: str, url: str, archive_kind: str) -> str:
    parsed = urlparse(url)
    filename = Path(parsed.path if parsed.scheme else url).name
    return filename or f"{name}.{archive_kind}"


def _verify_checksum(name: str, checksum_sha256: str, archive_path: Path) -> str:
    digest_builder = sha256()
    with archive_path.open("rb") as archive:
        while chunk := archive.read(COPY_CHUNK_BYTES):
            digest_builder.update(chunk)
    digest = digest_builder.hexdigest()
    if checksum_sha256 and digest != checksum_sha256:
        raise ValueError(f"checksum mismatch for {name}")
    return digest


def _extract_single_file(raw_path: Path, output_path: Path, opener) -> None:
    """Decompress to a temporary name and rename, so a failed run leaves no
    truncated file that a later run would mistake for a finished one."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = output_path.with_name(f".{output_path.name}.part")
    try:
        with opener(raw_path, "rb") as compressed, partial_path.open("wb") as output:
            _copy_limited(compressed, output, limit=MAX_EXTRACTED_BYTES)
        partial_path.replace(output_path)
    finally:
        partial_path.unlink(missing_ok=True)


def _safe_member_path(unpack_dir: Path, member_name: str) -> Path:
    root = unpack_dir.resolve()
    destination = (unpack_dir / member_name).resolve()
    if destination == root or root not in destination.parents:
        raise ValueError(f"archive member escapes unpack directory: {member_name}")
    return destination


def _extract_release(
    name: str, archive_kind: str, members: tuple[str, ...], archive_path: Path, unpack_dir: Path
) -> tuple[Path, ...]:
    if not members:
        return ()

    member_paths = tuple(_safe_member_path(unpack_dir, member) for member in members)
    # Reuse earlier output only if that extraction finished; an interrupted
    # run can leave members on disk without the marker.
    marker = unpack_dir / f".{archive_path.name}.extracted"
    if marker.exists() and all(path.exists() for path in member_paths):
        return member_paths

    if archive_kind == "plain":
        destination = _safe_member_path(unpack_dir, members[0] if members else archive_path.name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive_path, destination)
    elif archive_kind == "gz":
        destination = _safe_member_path(unpack_dir, members[0])
        _extract_single_file(archive_path, destination, gzip.open)
    elif archive_kind == "bz2":
        destination = _safe_member_path(unpack_dir, members[0])
        _extract_single_file(archive_path, destination, bz2.open)
    elif archive_kind in {"tar.gz", "tar.bz2", "tar.xz"}:
        with tarfile.open(archive_path, "r:*") as tar:
            extracted_bytes = 0
            for member in tar.getmembers():
                _safe_member_path(unpack_dir, member.name)
                if member.issym() or member.islnk():
                    raise ValueError(f"archive links are not allowed: {member.name}")
                if member.isfile():
                    extracted_bytes += member.size
                    if extracted_bytes > MAX_EXTRACTED_BYTES:
                        raise ValueError(
                            f"extracted archive contents exceed the {MAX_EXTRACTED_BYTES} byte safety limit"
                        )
                tar.extract(member, unpack_dir, filter="data")
    elif archive_kind == "zip":
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                destination = _safe_member_path(unpack_dir, member.filename)
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if member.file_size > MAX_EXTRACTED_BYTES:
                    raise ValueError(
                        f"archive member exceeds the {MAX_EXTRACTED_BYTES} byte safety limit"
                    )
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as output:
                    _copy_limited(source, output, limit=MAX_EXTRACTED_BYTES)
    else:
        raise ValueError(f"unsupported archive kind: {archive_kind}")

    missing = [str(path) for path in member_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing extracted members for {name}: {', '.join(missing)}")
    marker.touch()
    return member_paths


def _fetch_asset(
    name: str,
    url: str,
    local_path: str,
    archive_kind: str,
    checksum_sha256: str,
    members: tuple[str, ...],
    target_dir: Path,
    unpack_dir: Path,
) -> tuple[Path, str, tuple[Path, ...]]:
    asset_source = _resolve_asset_source(url, local_path)
    archive_path = target_dir / _archive_filename(name, asset_source, archive_kind)
    if not archive_path.exists():
        _download_to_path(asset_source, archive_path)

    checksum = _verify_checksum(name, checksum_sha256, archive_path)
    member_paths = _extract_release(name, archive_kind, members, archive_path, unpack_dir)
    return archive_path, checksum, member_paths


def fetch_release(release: SourceRelease, data_dir: Path) -> FetchResult:
    target_dir = (data_dir / "releases" / release.name / release.version).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    unpack_dir = (target_dir / "unpacked").resolve()
    unpack_dir.mkdir(parents=True, exist_ok=True)

    archive_path, checksum, member_paths = _fetch_asset(
        release.name,
        release.url,
        release.local_path,
        release.archive_kind,
        release.checksum_sha256,
        release.members,
        target_dir,
        unpack_dir,
    )
    all_member_paths = list(member_paths)
    companion_receipts = []
    for companion in release.companions:
        companion_archive_path, companion_checksum, companion_member_paths = _fetch_asset(
            companion.name,
            companion.url,
            companion.local_path,
            companion.archive_kind,
            companion.checksum_sha256,
            companion.members,
            target_dir,
            unpack_dir,
        )
        all_member_paths.extend(companion_member_paths)
        companion_receipts.append(
            {
                "name": companion.name,
                "url": companion.url,
                "archive_path": str(companion_archive_path.relative_to(target_dir)),
                "checksum_sha256": companion_checksum,
                "archive_kind": companion.archive_kind,
                "members": [str(path.relative_to(unpack_dir)) for path in companion_member_paths],
            }
        )

    receipt_path = unpack_dir / "receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "name": release.name,
                "version": release.version,
                "url": release.url,
                "checksum_sha256": checksum,
                "archive_kind": release.archive_kind,
                "members": [str(path.relative_to(unpack_dir)) for path in member_paths],
                "companions": companion_receipts,
            }
        )
    )

    return FetchResult(
        archive_path=archive_path,
        unpack_dir=unpack_dir,
        checksum_sha256=checksum,
        member_paths=tuple(all_member_paths),
    )
