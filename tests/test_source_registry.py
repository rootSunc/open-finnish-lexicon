import unittest
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

from open_finnish_lexicon.sources.registry import (
    CHINESE_CANDIDATE_SOURCES,
    FIXTURE_INPUTS,
    SYNC_SOURCE_ORDER,
    refresh_runtime_views,
    run_manual_ingest,
)


class SourceRegistryTests(unittest.TestCase):
    def test_fixture_inputs_cover_all_manual_sources_in_stable_order(self):
        self.assertEqual(
            [source_name for source_name, _path in FIXTURE_INPUTS],
            [
                "omorfi",
                "kaikki",
                "finnwordnet",
                "tatoeba",
                "frequency",
                "wiktionary_zh",
                "dbnary_zh",
            ],
        )
        self.assertTrue(all(isinstance(path, Path) for _source_name, path in FIXTURE_INPUTS))

    def test_sync_order_excludes_sources_that_are_manual_only_for_now(self):
        self.assertEqual(
            SYNC_SOURCE_ORDER,
            (
                "kaikki",
                "tatoeba",
                "frequency",
                "omorfi",
                "finnwordnet",
                "dbnary_zh",
                "wiktionary_zh",
            ),
        )
        self.assertLess(
            SYNC_SOURCE_ORDER.index("tatoeba"),
            SYNC_SOURCE_ORDER.index("omorfi"),
        )
        self.assertLess(
            SYNC_SOURCE_ORDER.index("frequency"),
            SYNC_SOURCE_ORDER.index("omorfi"),
        )
        self.assertEqual(CHINESE_CANDIDATE_SOURCES, {"wiktionary_zh", "dbnary_zh"})

    def test_run_manual_ingest_routes_to_stage_and_project(self):
        input_path = Path("example.tsv")
        with (
            patch("open_finnish_lexicon.sources.registry.stage_omorfi_rows") as stage,
            patch("open_finnish_lexicon.sources.registry.project_omorfi_rows") as project,
            patch("open_finnish_lexicon.sources.registry.finalize_source_snapshot") as finalize,
            patch("open_finnish_lexicon.sources.registry.connect") as connect,
            patch(
                "open_finnish_lexicon.sources.registry.clear_retired_source_registry_documents_in_batches"
            ) as clear_retired,
        ):
            stage.return_value = 123
            staging_conn = MagicMock()
            cleanup_conn = MagicMock()
            cleanup_conn.execute.return_value.fetchone.return_value = (456,)
            connect.return_value.__enter__.side_effect = [staging_conn, cleanup_conn]
            run_manual_ingest("omorfi", input_path)

        stage.assert_called_once_with(
            input_path,
            version="manual",
            source_url=str(input_path.resolve()),
        )
        project.assert_called_once_with(input_path, source_file_id=123, connection=ANY)
        finalize.assert_called_once_with(
            "omorfi",
            input_path,
            source_file_id=123,
            cleanup_superseded_documents=False,
            connection=staging_conn,
        )
        staging_conn.commit.assert_called_once_with()
        clear_retired.assert_called_once_with(source_registry_id=456)

    def test_run_manual_ingest_rejects_fixture_path_for_real_profile(self):
        with (
            patch(
                "open_finnish_lexicon.sources.registry.get_pipeline_settings",
                return_value=type("Settings", (), {"data_profile": "real"})(),
            ),
            patch("open_finnish_lexicon.sources.registry.stage_omorfi_rows") as stage,
        ):
            with self.assertRaisesRegex(RuntimeError, "refuses fixture input"):
                run_manual_ingest(
                    "omorfi",
                    Path("tests/fixtures/omorfi.tsv"),
                )

        stage.assert_not_called()




if __name__ == "__main__":
    unittest.main()


class RefreshRuntimeViewsTests(unittest.TestCase):
    def test_refresh_runs_every_step(self):
        with (
            patch("open_finnish_lexicon.sources.registry.rebuild_collocations") as collocations,
            patch("open_finnish_lexicon.sources.registry.select_zh_glosses") as select_zh,
            patch("open_finnish_lexicon.sources.registry.rebuild_chinese_glosses") as rebuild_zh,
            patch("open_finnish_lexicon.sources.registry.validate_forms_with_rules") as validate_forms,
        ):
            refresh_runtime_views()

        collocations.assert_called_once()
        select_zh.assert_called_once()
        rebuild_zh.assert_called_once()
        validate_forms.assert_called_once()

    def test_refresh_can_skip_form_validation(self):
        with (
            patch("open_finnish_lexicon.sources.registry.rebuild_collocations"),
            patch("open_finnish_lexicon.sources.registry.select_zh_glosses"),
            patch("open_finnish_lexicon.sources.registry.rebuild_chinese_glosses"),
            patch("open_finnish_lexicon.sources.registry.validate_forms_with_rules") as validate_forms,
        ):
            refresh_runtime_views(refresh_forms=False)

        validate_forms.assert_not_called()
