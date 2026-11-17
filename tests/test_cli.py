import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from open_finnish_lexicon.cli import main


class CliTests(unittest.TestCase):
    def test_help_lists_commands(self):
        with patch("builtins.print") as print_mock:
            exit_code = main(["help"])

        self.assertEqual(exit_code, 0)
        output = "\n".join(str(args[0]) for args, _kwargs in print_mock.call_args_list)
        for command in (
            "init-db",
            "sync-all [--manifest <path>]",
            "seed-fixtures",
            "reconcile-lexemes",
            "report-data-quality",
            "sanitize-invalid-zh-glosses [--apply]",
            "export-sqlite --output <path>",
            "export-jsonl --output <path>",
        ):
            self.assertIn(command, output)
        self.assertNotIn("llm", output)

    def test_seed_fixtures_rejects_real_profile_before_writing(self):
        with (
            patch(
                "open_finnish_lexicon.cli.ingest.get_pipeline_settings",
                return_value=SimpleNamespace(data_profile="real"),
            ),
            patch("open_finnish_lexicon.cli.ingest.run_manual_ingest") as ingest,
        ):
            with self.assertRaisesRegex(RuntimeError, "requires OFL_PROFILE=fixture"):
                main(["seed-fixtures"])

        ingest.assert_not_called()

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(SystemExit):
            main(["ingest-panlex", "--input", "x.tsv"])

    def test_reconcile_lexemes_routes(self):
        with patch("open_finnish_lexicon.cli.commands.normalize.reconcile_lexemes") as reconcile:
            exit_code = main(["reconcile-lexemes"])

        self.assertEqual(exit_code, 0)
        reconcile.assert_called_once_with()

    def test_sync_all_routes_manifest_path(self):
        with patch("open_finnish_lexicon.cli.commands.ingest.sync_all") as sync:
            sync.return_value = 0
            manifest_path = "src/open_finnish_lexicon/source_releases.toml"
            exit_code = main(["sync-all", "--manifest", manifest_path])

        self.assertEqual(exit_code, 0)
        self.assertEqual(sync.call_args, call(manifest_path=Path(manifest_path)))

    def test_archive_stale_build_runs_routes_hours(self):
        with patch("open_finnish_lexicon.cli.commands.ingest.archive_stale_build_runs") as archive:
            archive.return_value = 2
            exit_code = main(["archive-stale-build-runs", "--older-than-hours", "12"])

        self.assertEqual(exit_code, 0)
        archive.assert_called_once_with(older_than_hours=12)
