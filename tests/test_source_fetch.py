import gzip
import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from open_finnish_lexicon.sources.catalog import SourceCompanion, SourceRelease
from open_finnish_lexicon.sources.fetch import fetch_release


class SourceFetchTests(unittest.TestCase):
    def test_fetch_release_rejects_archive_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            archive_path = tmp_path / "malicious.tar.gz"
            payload = b"should never be extracted\n"
            with tarfile.open(archive_path, "w:gz") as archive:
                member = tarfile.TarInfo("../outside.txt")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))

            release = SourceRelease(
                name="malicious",
                version="fixture-1",
                source_kind="text",
                url=str(archive_path),
                local_path="",
                archive_kind="tar.gz",
                checksum_sha256="",
                members=("../outside.txt",),
                companions=(),
            )

            with self.assertRaisesRegex(ValueError, "escapes unpack directory"):
                fetch_release(release, tmp_path)

            self.assertFalse((tmp_path / "outside.txt").exists())

    def test_fetch_release_unpacks_fixture_archive_and_writes_receipt(self):
        archive_path = Path(
            "tests/fixtures/releases/omorfi-fixture.tar.gz"
        ).resolve()
        checksum_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()

        with tempfile.TemporaryDirectory() as tmpdir:
            release = SourceRelease(
                name="omorfi",
                version="fixture-1",
                source_kind="tsv",
                url=str(archive_path),
                local_path="",
                archive_kind="tar.gz",
                checksum_sha256=checksum_sha256,
                members=("omorfi.tsv",),
                companions=(),
            )

            result = fetch_release(release, Path(tmpdir))

            self.assertTrue(result.archive_path.exists())
            self.assertTrue(result.unpack_dir.exists())
            self.assertTrue((result.unpack_dir / "omorfi.tsv").exists())
            self.assertTrue((result.unpack_dir / "receipt.json").exists())

    def test_fetch_release_downloads_companion_assets_into_same_unpack_dir(self):
        archive_path = Path(
            "tests/fixtures/releases/tatoeba-fixture.tar.bz2"
        ).resolve()
        links_path = Path(
            "tests/fixtures/releases/tatoeba-links-fixture.csv"
        ).resolve()
        sentences_path = Path(
            "tests/fixtures/releases/tatoeba-sentences-fixture.csv"
        ).resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            release = SourceRelease(
                name="tatoeba",
                version="fixture-1",
                source_kind="tsv",
                url=str(archive_path),
                local_path="",
                archive_kind="tar.bz2",
                checksum_sha256="",
                members=("tatoeba.tsv",),
                companions=(
                    SourceCompanion(
                        name="links",
                        url=str(links_path),
                        local_path="",
                        archive_kind="plain",
                        checksum_sha256="",
                        members=("links.csv",),
                    ),
                    SourceCompanion(
                        name="sentences",
                        url=str(sentences_path),
                        local_path="",
                        archive_kind="plain",
                        checksum_sha256="",
                        members=("sentences.csv",),
                    ),
                ),
            )

            result = fetch_release(release, Path(tmpdir))

            self.assertTrue((result.unpack_dir / "tatoeba.tsv").exists())
            self.assertTrue((result.unpack_dir / "links.csv").exists())
            self.assertTrue((result.unpack_dir / "sentences.csv").exists())
            self.assertEqual(result.member_paths[0].name, "tatoeba.tsv")
            self.assertIn(result.unpack_dir / "links.csv", result.member_paths)

    def test_fetch_release_reuses_existing_extracted_single_file_members(self):
        archive_path = Path(
            "tests/fixtures/releases/kaikki-fixture.jsonl.gz"
        ).resolve()
        checksum_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()

        with tempfile.TemporaryDirectory() as tmpdir:
            release = SourceRelease(
                name="kaikki",
                version="fixture-1",
                source_kind="jsonl",
                url=str(archive_path),
                local_path="",
                archive_kind="gz",
                checksum_sha256=checksum_sha256,
                members=("kaikki-juosta.jsonl",),
                companions=(),
            )

            result = fetch_release(release, Path(tmpdir))
            extracted_path = result.unpack_dir / "kaikki-juosta.jsonl"
            sentinel = '{"word":"cached"}\n'
            extracted_path.write_text(sentinel, encoding="utf-8")

            result = fetch_release(release, Path(tmpdir))

            self.assertEqual(extracted_path.read_text(encoding="utf-8"), sentinel)
            self.assertEqual(result.member_paths, (extracted_path,))

    def test_fetch_release_skips_archive_extraction_when_no_members_requested(self):
        archive_path = Path(
            "tests/fixtures/releases/finnwordnet-fixture.zip"
        ).resolve()
        checksum_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()

        with tempfile.TemporaryDirectory() as tmpdir:
            release = SourceRelease(
                name="panlex",
                version="fixture-zip",
                source_kind="tsv",
                url=str(archive_path),
                local_path="",
                archive_kind="zip",
                checksum_sha256=checksum_sha256,
                members=(),
                companions=(),
            )

            result = fetch_release(release, Path(tmpdir))

            self.assertTrue(result.archive_path.exists())
            self.assertEqual(result.member_paths, ())

    def test_fetch_release_prefers_existing_local_path_over_network_url(self):
        archive_path = Path(
            "tests/fixtures/releases/finnwordnet-fixture.zip"
        ).resolve()
        checksum_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()

        with tempfile.TemporaryDirectory() as tmpdir:
            release = SourceRelease(
                name="panlex",
                version="fixture-local",
                source_kind="tsv",
                url="https://example.test/panlex.zip",
                local_path=str(archive_path),
                archive_kind="zip",
                checksum_sha256=checksum_sha256,
                members=(),
                companions=(),
            )

            result = fetch_release(release, Path(tmpdir))

            self.assertTrue(result.archive_path.exists())
            self.assertEqual(result.archive_path.name, archive_path.name)

    def test_fetch_release_downloads_dbnary_companion_into_same_unpack_dir(self):
        core_path = Path("tests/fixtures/releases/dbnary-zh-exolex.ttl").resolve()
        enhancement_path = Path(
            "tests/fixtures/releases/dbnary-zh-enhancement.ttl"
        ).resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            release = SourceRelease(
                name="dbnary_zh",
                version="fixture-1",
                source_kind="ttl",
                url=str(core_path),
                local_path="",
                archive_kind="plain",
                checksum_sha256="",
                members=("dbnary-zh-exolex.ttl",),
                companions=(
                    SourceCompanion(
                        name="enhancement",
                        url=str(enhancement_path),
                        local_path="",
                        archive_kind="plain",
                        checksum_sha256="",
                        members=("dbnary-zh-enhancement.ttl",),
                    ),
                ),
            )

            result = fetch_release(release, Path(tmpdir))

            self.assertIn(result.unpack_dir / "dbnary-zh-exolex.ttl", result.member_paths)
            self.assertIn(result.unpack_dir / "dbnary-zh-enhancement.ttl", result.member_paths)


class InterruptedExtractionTests(unittest.TestCase):
    def test_interrupted_extraction_is_redone_on_next_run(self):
        archive_path = Path("tests/fixtures/releases/kaikki-fixture.jsonl.gz").resolve()
        release = SourceRelease(
            name="kaikki",
            version="fixture-1",
            source_kind="jsonl",
            url=str(archive_path),
            local_path="",
            archive_kind="gz",
            checksum_sha256="",
            members=("kaikki-juosta.jsonl",),
            companions=(),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            unpack_dir = (Path(tmpdir) / "releases/kaikki/fixture-1/unpacked").resolve()
            unpack_dir.mkdir(parents=True)
            # A truncated member from an interrupted run, with no completion marker.
            (unpack_dir / "kaikki-juosta.jsonl").write_text('{"word": "trunc', encoding="utf-8")

            result = fetch_release(release, Path(tmpdir))

            with gzip.open(archive_path, "rt", encoding="utf-8") as source:
                expected = source.read()
            self.assertEqual(result.member_paths[0].read_text(encoding="utf-8"), expected)
            self.assertFalse(list(unpack_dir.glob(".*.part")))

    def test_bad_checksum_deletes_corrupted_cached_archive(self):
        archive_path = Path("tests/fixtures/releases/omorfi-fixture.tar.gz").resolve()
        with tempfile.TemporaryDirectory() as tmpdir:
            release = SourceRelease(
                name="omorfi",
                version="fixture-bad-sum",
                source_kind="tsv",
                url=str(archive_path),
                local_path="",
                archive_kind="tar.gz",
                checksum_sha256="0" * 64,
                members=(),
                companions=(),
            )
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                fetch_release(release, Path(tmpdir))
            cached_dir = Path(tmpdir) / "releases/omorfi/fixture-bad-sum"
            self.assertFalse((cached_dir / archive_path.name).exists())

    def test_offline_requires_existing_verified_archive_and_never_removes_it(self):
        content = b"archived data"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            release = SourceRelease(
                name="fixture",
                version="locked",
                source_kind="tsv",
                url="https://example.invalid/archive.tsv",
                local_path="",
                archive_kind="plain",
                checksum_sha256=hashlib.sha256(content).hexdigest(),
                members=(),
                companions=(),
            )
            with self.assertRaisesRegex(FileNotFoundError, "missing offline archive"):
                fetch_release(release, root, offline=True)
            cached = root / "releases/fixture/locked/archive.tsv"
            cached.write_bytes(b"different data")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                fetch_release(release, root, offline=True)
            self.assertEqual(cached.read_bytes(), b"different data")
            cached.write_bytes(content)
            with self.assertRaisesRegex(ValueError, "cannot force downloads"):
                fetch_release(release, root, offline=True, force_download=True)
            result = fetch_release(release, root, offline=True)
            self.assertEqual(result.archive_path, cached.resolve())

    def test_zip_cumulative_unpacked_bytes_limit_is_enforced(self):
        import zipfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "bomb.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("a.txt", "x" * 600)
                zf.writestr("b.txt", "y" * 600)
            release = SourceRelease(
                name="bomb",
                version="v1",
                source_kind="text",
                url=str(zip_path),
                local_path="",
                archive_kind="zip",
                checksum_sha256="",
                members=("a.txt", "b.txt"),
                companions=(),
            )
            with patch("open_finnish_lexicon.sources.fetch.MAX_EXTRACTED_BYTES", 1000):
                with self.assertRaisesRegex(ValueError, "exceeds the 1000 byte safety limit"):
                    fetch_release(release, Path(tmpdir))

    def test_download_retries_and_rejects_truncated_content_length(self):
        from http.client import IncompleteRead
        from unittest.mock import patch
        from urllib.error import URLError
        from open_finnish_lexicon.sources.fetch import _download_to_path

        class _FakeResponse(io.BytesIO):
            def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None):
                super().__init__(body)
                self.status = status
                self.headers = headers or {}

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                self.close()

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "sample.bin"
            attempts = {"n": 0}

            def _flaky_urlopen(_req, timeout=0):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise URLError("temporary reset")
                return _FakeResponse(b"hello world", headers={"Content-Length": "11"})

            with (
                patch("open_finnish_lexicon.sources.fetch.urlopen", side_effect=_flaky_urlopen),
                patch("open_finnish_lexicon.sources.fetch.time.sleep"),
            ):
                _download_to_path("https://example.test/sample.bin", dest)
            self.assertEqual(dest.read_bytes(), b"hello world")

            truncated_dest = Path(tmpdir) / "truncated.bin"
            with (
                patch(
                    "open_finnish_lexicon.sources.fetch.urlopen",
                    side_effect=lambda _req, timeout=0: _FakeResponse(
                        b"short", headers={"Content-Length": "100"}
                    ),
                ),
                patch("open_finnish_lexicon.sources.fetch.time.sleep"),
            ):
                with self.assertRaises(IncompleteRead):
                    _download_to_path("https://example.test/truncated.bin", truncated_dest)
