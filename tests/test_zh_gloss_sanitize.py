import unittest
from unittest.mock import MagicMock, patch

from open_finnish_lexicon.quality.zh_gloss_sanitize import sanitize_invalid_zh_glosses


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, object]] = []
        self.committed = False
        self.rolled_back = False

    def execute(self, query: str, params=None):
        self.executed.append((query, params))
        if "from zh_layer.zh_gloss" in query and query.lstrip().startswith("select"):
            return MagicMock(fetchall=lambda: [(1, "跑"), (2, "punkki的属格单数")])
        if "from semantic.zh_gloss_selection" in query and query.lstrip().startswith("select"):
            return MagicMock(fetchall=lambda: [(10, "去 go"), (11, "学习")])
        return MagicMock()

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class ZhGlossSanitizeTests(unittest.TestCase):
    def _connect_context(self, conn: _FakeConnection) -> MagicMock:
        context = MagicMock()
        context.__enter__.return_value = conn
        return context

    def test_defaults_to_read_only_and_reports_invalid_rows(self) -> None:
        conn = _FakeConnection()
        with patch(
            "open_finnish_lexicon.quality.zh_gloss_sanitize.connect",
            return_value=self._connect_context(conn),
        ):
            stats = sanitize_invalid_zh_glosses()

        self.assertEqual(stats.invalid_materialized, 1)
        self.assertEqual(stats.invalid_selected, 1)
        self.assertEqual(stats.materialized_by_issue, {"dictionary_metadata": 1})
        self.assertEqual(stats.selected_by_issue, {"latin_residue": 1})
        self.assertFalse(stats.applied)
        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.committed)
        self.assertFalse(any(q.lstrip().startswith("delete") for q, _ in conn.executed))

    def test_apply_deletes_invalid_rows_but_leaves_candidates(self) -> None:
        conn = _FakeConnection()
        with patch(
            "open_finnish_lexicon.quality.zh_gloss_sanitize.connect",
            return_value=self._connect_context(conn),
        ):
            stats = sanitize_invalid_zh_glosses(apply=True)

        self.assertTrue(stats.applied)
        self.assertTrue(conn.committed)
        deletes = [q for q, _ in conn.executed if q.lstrip().startswith("delete")]
        self.assertEqual(len(deletes), 2)
        self.assertFalse(any("zh_gloss_candidate" in q for q in deletes))


if __name__ == "__main__":
    unittest.main()
