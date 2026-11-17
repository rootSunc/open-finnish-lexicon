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
