"""Integration tests for ``_persist_verdict``'s LLM-precedence guard.

A re-run of the rule engine (e.g. as part of ``refresh-projections``)
must not erase an LLM verdict that was previously stored against a form.
The guard lives in the ``on conflict do update ... where`` clause of
``_persist_verdict``.
"""

import unittest

import psycopg

from open_finnish_lexicon.morphology.rules import Verdict
from open_finnish_lexicon.morphology.validator import _persist_verdict
from support import get_test_database_url


class PersistVerdictPrecedenceTests(unittest.TestCase):
    def _reset(self) -> None:
        with psycopg.connect(get_test_database_url()) as conn:
            conn.execute(
                """
                truncate lexicon.form_validation,
                         lexicon.form,
                         lexicon.lexeme
                restart identity cascade
                """
            )
            conn.commit()

    def setUp(self) -> None:
        self._reset()

    def tearDown(self) -> None:
        self._reset()

    def _seed_form(self, conn) -> int:
        lexeme_id = conn.execute(
            """
            insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
            values ('zztestlex', 'zztestlex', 'NOUN')
            returning id
            """
        ).fetchone()[0]
        return conn.execute(
            """
            insert into lexicon.form (
                lexeme_id, surface_form, normalized_form, form_kind, features
            )
            values (%s, 'zztestform', 'zztestform', 'inflected', '{}'::jsonb)
            returning id
            """,
            (lexeme_id,),
        ).fetchone()[0]

    def _current(self, conn, form_id: int) -> tuple[str, str, float, str]:
        return conn.execute(
            """
            select validator, verdict, confidence, explanation
            from lexicon.form_validation
            where form_id = %s
            """,
            (form_id,),
        ).fetchone()

    def test_rule_pass_does_not_overwrite_llm_verdict(self) -> None:
        with psycopg.connect(get_test_database_url()) as conn:
            form_id = self._seed_form(conn)
            with conn.cursor() as cursor:
                _persist_verdict(
                    cursor,
                    form_id=form_id,
                    verdict=Verdict.VERIFIED,
                    predicted_surface=None,
                    validator="llm",
                    rule=None,
                    confidence=0.95,
                    explanation="LLM said verified",
                )
                _persist_verdict(
                    cursor,
                    form_id=form_id,
                    verdict=Verdict.MISMATCH,
                    predicted_surface="zzpredicted",
                    validator="rule",
                    rule="some-rule",
                    confidence=0.6,
                    explanation="rule re-run after LLM",
                )
            conn.commit()
            validator, verdict, confidence, explanation = self._current(conn, form_id)

        self.assertEqual(validator, "llm")
        self.assertEqual(verdict, Verdict.VERIFIED.value)
        self.assertEqual(float(confidence), 0.95)
        self.assertEqual(explanation, "LLM said verified")

    def test_llm_pass_overwrites_existing_llm_verdict(self) -> None:
        with psycopg.connect(get_test_database_url()) as conn:
            form_id = self._seed_form(conn)
            with conn.cursor() as cursor:
                _persist_verdict(
                    cursor,
                    form_id=form_id,
                    verdict=Verdict.UNCERTAIN,
                    predicted_surface=None,
                    validator="llm",
                    rule=None,
                    confidence=0.4,
                    explanation="initial LLM call",
                )
                _persist_verdict(
                    cursor,
                    form_id=form_id,
                    verdict=Verdict.VERIFIED,
                    predicted_surface=None,
                    validator="llm",
                    rule=None,
                    confidence=0.92,
                    explanation="LLM re-run",
                )
            conn.commit()
            validator, verdict, confidence, explanation = self._current(conn, form_id)

        self.assertEqual(validator, "llm")
        self.assertEqual(verdict, Verdict.VERIFIED.value)
        self.assertEqual(float(confidence), 0.92)
        self.assertEqual(explanation, "LLM re-run")

    def test_rule_pass_overwrites_existing_rule_verdict(self) -> None:
        with psycopg.connect(get_test_database_url()) as conn:
            form_id = self._seed_form(conn)
            with conn.cursor() as cursor:
                _persist_verdict(
                    cursor,
                    form_id=form_id,
                    verdict=Verdict.UNCERTAIN,
                    predicted_surface=None,
                    validator="rule",
                    rule="old-rule",
                    confidence=0.5,
                    explanation="old rule output",
                )
                _persist_verdict(
                    cursor,
                    form_id=form_id,
                    verdict=Verdict.VERIFIED,
                    predicted_surface="zzpredicted",
                    validator="rule",
                    rule="new-rule",
                    confidence=0.8,
                    explanation="new rule output",
                )
            conn.commit()
            validator, verdict, confidence, explanation = self._current(conn, form_id)

        self.assertEqual(validator, "rule")
        self.assertEqual(verdict, Verdict.VERIFIED.value)
        self.assertEqual(float(confidence), 0.8)
        self.assertEqual(explanation, "new rule output")


if __name__ == "__main__":
    unittest.main()
