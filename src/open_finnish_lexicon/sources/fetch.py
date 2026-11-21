from __future__ import annotations

import bz2
from dataclasses import dataclass
import gzip
from hashlib import sha256
from http.client import IncompleteRead
import json
import os
from pathlib import Path
import shutil
import tarfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen
import zipfile

from open_finnish_lexicon.sources.catalog import SourceRelease


@dataclass(frozen=True)
class SourceAsset:
    name: str
    url: str
    sha256: str


@dataclass(frozen=True)
class FetchResult:
    archive_path: Path
    unpack_dir: Path
    checksum_sha256: str
    member_paths: tuple[Path, ...]
    assets: tuple[SourceAsset, ...] = ()


USER_AGENT = "open-finnish-lexicon/1.0.0 (+https://github.com/rootSunc/open-finnish-lexicon; lexical-builder)"
DOWNLOAD_TIMEOUT_SECONDS = 60
MAX_DOWNLOAD_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5
RETRYABLE_HTTP_STATUS = frozenset({408, 429, 500, 502, 503, 504})
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
# Decompressed output may be much larger than the download (the Kaikki Finnish
# JSONL is over 2 GiB unpacked); the cap still stops decompression bombs.
MAX_EXTRACTED_BYTES = 16 * 1024 * 1024 * 1024
MIN_FREE_DISK_BYTES = 256 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024


def _ensure_disk_space(directory: Path, required_bytes: int = MIN_FREE_DISK_BYTES) -> None:
    try:
        free_bytes = shutil.disk_usage(directory).free
    except OSError:
        return
    if free_bytes < required_bytes:
        raise OSError(
            f"insufficient free disk space under {directory}: "
            f"{free_bytes} bytes free, need at least {required_bytes} bytes"
        )


def _copy_limited(source, output, *, limit: int = MAX_DOWNLOAD_BYTES, initial: int = 0) -> int:
    total = initial
    while chunk := source.read(COPY_CHUNK_BYTES):
        total += len(chunk)
        if total > limit:
            raise ValueError(f"download exceeds the {limit} byte safety limit")
        output.write(chunk)
    return total


def _download_http_with_retries(url: str, partial_path: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(1, MAX_DOWNLOAD_RETRIES + 1):
        resume_offset = partial_path.stat().st_size if partial_path.exists() else 0
        headers = {"User-Agent": USER_AGENT}
        if resume_offset > 0:
            headers["Range"] = f"bytes={resume_offset}-"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", 200) or 200
                content_length_raw = response.headers.get("Content-Length")
                expected_chunk = int(content_length_raw) if content_length_raw else None
                if status == 206 and resume_offset > 0:
                    mode = "ab"
                    initial = resume_offset
                else:
                    mode = "wb"
                    initial = 0
                if expected_chunk is not None and initial + expected_chunk > MAX_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"download exceeds the {MAX_DOWNLOAD_BYTES} byte safety limit"
                    )
                with partial_path.open(mode) as output:
                    total = _copy_limited(
                        response, output, limit=MAX_DOWNLOAD_BYTES, initial=initial
                    )
                if expected_chunk is not None and (total - initial) != expected_chunk:
                    raise IncompleteRead(b"", expected_chunk - (total - initial))
                return
        except HTTPError as exc:
            if exc.code == 416 and partial_path.exists():
                # Range not satisfiable: discard stale partial file and retry cleanly.
                partial_path.unlink(missing_ok=True)
                last_error = exc
            elif exc.code in RETRYABLE_HTTP_STATUS and attempt < MAX_DOWNLOAD_RETRIES:
                last_error = exc
            else:
                raise
        except (URLError, TimeoutError, IncompleteRead, ConnectionError) as exc:
            last_error = exc
            if attempt >= MAX_DOWNLOAD_RETRIES:
                raise
        time.sleep(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
    if last_error is not None:
        raise last_error


def _download_to_path(url: str, archive_path: Path) -> None:
    parsed = urlparse(url)
    _ensure_disk_space(archive_path.parent)
    partial_path = archive_path.with_name(f".{archive_path.name}.part")
    try:
        if parsed.scheme in {"http", "https"}:
            _download_http_with_retries(url, partial_path)
        elif parsed.scheme == "file":
            with (
                urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response,
                partial_path.open("wb") as output,
            ):
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
    raw_path = unquote(parsed.path) if parsed.scheme else url
    filename = Path(raw_path).name
    return filename or f"{name}.{archive_kind}"


def _verify_checksum(
    name: str, checksum_sha256: str, archive_path: Path, *, remove_invalid: bool = True,
) -> str:
    digest_builder = sha256()
    with archive_path.open("rb") as archive:
        while chunk := archive.read(COPY_CHUNK_BYTES):
            digest_builder.update(chunk)
    digest = digest_builder.hexdigest()
    if checksum_sha256 and digest != checksum_sha256:
        # Remove the corrupted archive so a retry can re-download cleanly.
        if remove_invalid:
            archive_path.unlink(missing_ok=True)
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


def _link_or_copy_plain_file(archive_path: Path, destination: Path) -> None:
    """Expose a plain file in ``unpacked/`` via hardlink when possible to avoid
    duplicating multi-hundred-MB files on disk, falling back to an atomic copy."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial_path = destination.with_name(f".{destination.name}.part")
    partial_path.unlink(missing_ok=True)
    try:
        os.link(archive_path, partial_path)
        partial_path.replace(destination)
        return
    except OSError:
        partial_path.unlink(missing_ok=True)
    try:
        with archive_path.open("rb") as source, partial_path.open("wb") as output:
            _copy_limited(source, output, limit=MAX_EXTRACTED_BYTES)
        partial_path.replace(destination)
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
    marker = unpack_dir / f".{archive_path.name}.extracted"
    if marker.exists() and all(path.exists() for path in member_paths):
        return member_paths

    _ensure_disk_space(unpack_dir)

    if archive_kind == "plain":
        destination = _safe_member_path(unpack_dir, members[0] if members else archive_path.name)
        _link_or_copy_plain_file(archive_path, destination)
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
                destination = _safe_member_path(unpack_dir, member.name)
                if member.issym() or member.islnk():
                    raise ValueError(f"archive links are not allowed: {member.name}")
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if member.isfile():
                    if extracted_bytes + member.size > MAX_EXTRACTED_BYTES:
                        raise ValueError(
                            f"extracted archive contents exceed the {MAX_EXTRACTED_BYTES} byte safety limit"
                        )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    partial_path = destination.with_name(f".{destination.name}.part")
                    try:
                        extracted_stream = tar.extractfile(member)
                        if extracted_stream is None:
                            continue
                        with extracted_stream as source, partial_path.open("wb") as output:
                            extracted_bytes = _copy_limited(
                                source,
                                output,
                                limit=MAX_EXTRACTED_BYTES,
                                initial=extracted_bytes,
                            )
                        partial_path.replace(destination)
                    finally:
                        partial_path.unlink(missing_ok=True)
    elif archive_kind == "zip":
        with zipfile.ZipFile(archive_path) as archive:
            extracted_bytes = 0
            for member in archive.infolist():
                destination = _safe_member_path(unpack_dir, member.filename)
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if extracted_bytes + member.file_size > MAX_EXTRACTED_BYTES:
                    raise ValueError(
                        f"archive member exceeds the {MAX_EXTRACTED_BYTES} byte safety limit"
                    )
                destination.parent.mkdir(parents=True, exist_ok=True)
                partial_path = destination.with_name(f".{destination.name}.part")
                try:
                    with archive.open(member) as source, partial_path.open("wb") as output:
                        extracted_bytes = _copy_limited(
                            source,
                            output,
                            limit=MAX_EXTRACTED_BYTES,
                            initial=extracted_bytes,
                        )
                    partial_path.replace(destination)
                finally:
                    partial_path.unlink(missing_ok=True)
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
    *,
    force_download: bool = False,
    offline: bool = False,
) -> tuple[Path, str, tuple[Path, ...]]:
    asset_source = _resolve_asset_source(url, local_path)
    archive_path = target_dir / _archive_filename(name, asset_source, archive_kind)
    marker = unpack_dir / f".{archive_path.name}.extracted"
    if force_download and archive_path.exists():
        archive_path.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
    if not archive_path.exists():
        if offline:
            raise FileNotFoundError(f"missing offline archive for {name}: {archive_path}")
        marker.unlink(missing_ok=True)
        _download_to_path(asset_source, archive_path)

    if offline:
        if not checksum_sha256:
            raise ValueError(f"offline replay requires a checksum for {name}")
        # Verify the archive in place without deleting a historical input on error.
        checksum = _verify_checksum(name, checksum_sha256, archive_path, remove_invalid=False)
    else:
        checksum = _verify_checksum(name, checksum_sha256, archive_path)
    member_paths = _extract_release(name, archive_kind, members, archive_path, unpack_dir)
    return archive_path, checksum, member_paths


def fetch_release(
    release: SourceRelease,
    data_dir: Path,
    *,
    force_download: bool = False,
    offline: bool = False,
) -> FetchResult:
    if offline and force_download:
        raise ValueError("offline replay cannot force downloads")
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
        force_download=force_download,
        offline=offline,
    )
    all_member_paths = list(member_paths)
    assets = [SourceAsset(release.name, release.url, checksum)]
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
            force_download=force_download,
            offline=offline,
        )
        all_member_paths.extend(companion_member_paths)
        assets.append(SourceAsset(companion.name, companion.url, companion_checksum))
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
        ),
        encoding="utf-8",
    )

    return FetchResult(
        archive_path=archive_path,
        unpack_dir=unpack_dir,
        checksum_sha256=checksum,
        member_paths=tuple(all_member_paths),
        assets=tuple(assets),
    )
