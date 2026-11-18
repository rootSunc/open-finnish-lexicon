"""Run the rule-based morphology validator over every ``lexicon.form`` row.

:func:`validate_forms_with_rules` runs the deterministic rule engine in a
single transaction and stores one verdict per form. It is idempotent:
re-running it updates verdicts in place. Rows whose ``validator`` is ``'llm'``
(written by an external review tool) are never overwritten by the rule pass.
"""

from __future__ import annotations

from dataclasses import dataclass


from open_finnish_lexicon.db import connect
from open_finnish_lexicon.morphology.rules import RuleVerdict, Verdict, validate_form


@dataclass(frozen=True)
class ValidationStats:
    verified: int
    mismatch: int
    uncertain: int

    @property
    def total(self) -> int:
        return self.verified + self.mismatch + self.uncertain


def _persist_verdict(
    cursor,
    *,
    form_id: int,
    verdict: Verdict,
    predicted_surface: str | None,
    validator: str,
    rule: str | None,
    confidence: float,
    explanation: str,
) -> None:
    cursor.execute(
        """
        insert into lexicon.form_validation (
            form_id, verdict, predicted_surface, validator, rule, confidence, explanation, updated_at
        )
        values (%s, %s, %s, %s, %s, %s, %s, now())
        on conflict (form_id) do update set
            verdict = excluded.verdict,
            predicted_surface = excluded.predicted_surface,
            validator = excluded.validator,
            rule = excluded.rule,
            confidence = excluded.confidence,
            explanation = excluded.explanation,
            updated_at = excluded.updated_at
        where excluded.validator = 'llm'
           or lexicon.form_validation.validator <> 'llm'
        """,
        (
            form_id,
            verdict.value,
            predicted_surface,
            validator,
            rule,
            confidence,
            explanation,
        ),
    )


def validate_forms_with_rules() -> ValidationStats:
    """Walk every ``lexicon.form`` row and persist a rule-engine verdict."""

    verified = 0
    mismatch = 0
    uncertain = 0

    with connect() as conn:
        # The rule engine is cheap, but issuing one INSERT/UPSERT round-trip per
        # form is not.  Real Kaikki snapshots contain tens of millions of forms,
        # so stream verdicts through COPY and merge them in one set-based write.
        conn.execute(
            """
            create temporary table tmp_form_validation (
                form_id bigint not null,
                verdict text not null,
                predicted_surface text,
                validator text not null,
                rule text,
                confidence numeric(6, 5) not null,
                explanation text not null
            ) on commit drop
            """
        )
        # COPY occupies its connection until the stream finishes. Keep the
        # source cursor on a separate connection so reading and writing can
        # progress independently at large snapshot sizes.
        with connect() as source_conn:
            source_cursor = source_conn.cursor(name="form-validation-source")
            source_cursor.itersize = 10_000
            source_cursor.execute(
                """
                select
                    f.id,
                    l.lemma,
                    l.part_of_speech,
                    f.surface_form,
                    f.features,
                    f.form_kind
                from lexicon.form f
                join lexicon.lexeme l on l.id = f.lexeme_id
                order by f.id
                """
            )
            try:
                with conn.cursor().copy(
                    """
                    copy tmp_form_validation (
                        form_id,
                        verdict,
                        predicted_surface,
                        validator,
                        rule,
                        confidence,
                        explanation
                    ) from stdin
                    """
                ) as copy:
                    for form_id, lemma, part_of_speech, surface_form, features, form_kind in source_cursor:
                        rule_verdict: RuleVerdict = validate_form(
                            lemma=lemma,
                            part_of_speech=part_of_speech,
                            surface_form=surface_form,
                            features=features or {},
                            form_kind=form_kind,
                        )
                        if rule_verdict.verdict is Verdict.VERIFIED:
                            verified += 1
                        elif rule_verdict.verdict is Verdict.MISMATCH:
                            mismatch += 1
                        else:
                            uncertain += 1
                        copy.write_row(
                            (
                                form_id,
                                rule_verdict.verdict.value,
                                rule_verdict.predicted_surface,
                                "rule",
                                rule_verdict.rule,
                                rule_verdict.confidence,
                                rule_verdict.explanation,
                            )
                        )
            finally:
                source_cursor.close()
        conn.execute(
            """
            insert into lexicon.form_validation (
                form_id,
                verdict,
                predicted_surface,
                validator,
                rule,
                confidence,
                explanation,
                updated_at
            )
            select
                form_id,
                verdict,
                predicted_surface,
                validator,
                rule,
                confidence,
                explanation,
                now()
            from tmp_form_validation
            on conflict (form_id) do update set
                verdict = excluded.verdict,
                predicted_surface = excluded.predicted_surface,
                validator = excluded.validator,
                rule = excluded.rule,
                confidence = excluded.confidence,
                explanation = excluded.explanation,
                updated_at = excluded.updated_at
            where excluded.validator = 'llm'
               or lexicon.form_validation.validator <> 'llm'
            """
        )
        conn.commit()

    return ValidationStats(verified=verified, mismatch=mismatch, uncertain=uncertain)


__all__ = ["ValidationStats", "validate_forms_with_rules"]
