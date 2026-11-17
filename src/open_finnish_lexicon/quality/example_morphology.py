"""Run the Finnish word recognizer over ``lexicon.example`` and store verdicts.

The recognizer itself lives in :mod:`open_finnish_lexicon.morphology.sentence`;
this module is the batch job around it. It is keyset-paginated and resumable:
by default it only visits examples with no verdict yet, so an interrupted run
continues where it stopped, and ``--revalidate`` is the explicit way to re-score
everything after a recognition rule changes.

The analyser is required, not optional. Without the HFST model the remaining
layers still return an answer, but a much weaker one, and storing it under the
same ``recognizer_version`` would make the two indistinguishable later.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from open_finnish_lexicon.config import get_pipeline_settings
from open_finnish_lexicon.db import connect
from open_finnish_lexicon.morphology.sentence import (
    FinnishWordRecognizer,
    RECOGNIZER_VERSION,
    VERDICT_EMPTY,
    VERDICT_UNKNOWN_TOKENS,
    VERDICT_VALID,
    find_omorfi_recased_analyser,
    load_omorfi_analyse,
    load_project_lexicon,
)

DEFAULT_BATCH_SIZE = 5000
TOP_UNKNOWN_TOKEN_COUNT = 25

_SELECT_BATCH_SQL = """
select e.id, e.text_fi
from lexicon.example e
where e.id > %(after_id)s
  and (
      %(source_family)s::text is null
      or split_part(e.source_label, ':', 1) = %(source_family)s
  )
  and (
      %(revalidate)s
      or not exists (
          select 1
          from lexicon.example_morphology_validation v
          where v.example_id = e.id
      )
  )
order by e.id
limit %(batch_size)s
"""

_UPSERT_SQL = """
insert into lexicon.example_morphology_validation (
    example_id,
    verdict,
    token_count,
    unknown_count,
    unknown_tokens,
    name_like_count,
    name_like_tokens,
    recognizer_version,
    validated_at
)
values (%s, %s, %s, %s, %s, %s, %s, %s, now())
on conflict (example_id) do update set
    verdict = excluded.verdict,
    token_count = excluded.token_count,
    unknown_count = excluded.unknown_count,
    unknown_tokens = excluded.unknown_tokens,
    name_like_count = excluded.name_like_count,
    name_like_tokens = excluded.name_like_tokens,
    recognizer_version = excluded.recognizer_version,
    validated_at = excluded.validated_at
"""

_SUMMARY_SQL = """
select source_family, examples, validated, valid, unknown_tokens, empty, unknown_pct
from lexicon.example_morphology_summary
"""


@dataclass(frozen=True)
class ExampleMorphologyStats:
    examined: int = 0
    valid: int = 0
    unknown_tokens: int = 0
    empty: int = 0
    persisted: int = 0
    unknown_token_instances: int = 0
    name_like_instances: int = 0
    top_unknown_tokens: tuple[tuple[str, int], ...] = ()
    summary_rows: tuple[tuple, ...] = field(default=())
    dry_run: bool = False

    @property
    def unknown_pct(self) -> float:
        return 100.0 * self.unknown_tokens / self.examined if self.examined else 0.0


def _resolve_analyse():
    settings = get_pipeline_settings()
    analyser_path = find_omorfi_recased_analyser(settings.data_dir)
    if analyser_path is None:
        raise SystemExit(
            "Omorfi recased analyser not found under "
            f"{settings.data_dir}/releases/omorfi/*/unpacked/omorfi_recased.analyse.hfst. "
            "Run `ofl sync-all` with the [omorfi] extra installed, then retry."
        )
    return load_omorfi_analyse(analyser_path)


def validate_example_morphology(
    *,
    limit: int | None = None,
    source_family: str | None = None,
    revalidate: bool = False,
    dry_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ExampleMorphologyStats:
    analyse = _resolve_analyse()

    examined = 0
    verdict_counts: Counter[str] = Counter()
    unknown_counter: Counter[str] = Counter()
    unknown_instances = 0
    name_like_instances = 0
    persisted = 0

    with connect() as conn:
        forms, lemmas = load_project_lexicon(conn)
        recognizer = FinnishWordRecognizer(analyse=analyse, forms=forms, lemmas=lemmas)

        after_id = 0
        while limit is None or examined < limit:
            remaining = batch_size if limit is None else min(batch_size, limit - examined)
            rows = conn.execute(
                _SELECT_BATCH_SQL,
                {
                    "after_id": after_id,
                    "source_family": source_family,
                    "revalidate": revalidate,
                    "batch_size": remaining,
                },
            ).fetchall()
            if not rows:
                break

            payload = []
            for example_id, text_fi in rows:
                result = recognizer.validate_sentence(text_fi)
                verdict_counts[result.verdict] += 1
                unknown_counter.update(result.unknown_tokens)
                unknown_instances += result.unknown_count
                name_like_instances += result.name_like_count
                payload.append(
                    (
                        example_id,
                        result.verdict,
                        result.token_count,
                        result.unknown_count,
                        list(result.unknown_tokens),
                        result.name_like_count,
                        list(result.name_like_tokens),
                        RECOGNIZER_VERSION,
                    )
                )

            examined += len(rows)
            after_id = rows[-1][0]

            if not dry_run:
                with conn.cursor() as cursor:
                    cursor.executemany(_UPSERT_SQL, payload)
                conn.commit()
                persisted += len(payload)

        summary_rows = tuple(tuple(row) for row in conn.execute(_SUMMARY_SQL).fetchall())

    return ExampleMorphologyStats(
        examined=examined,
        valid=verdict_counts[VERDICT_VALID],
        unknown_tokens=verdict_counts[VERDICT_UNKNOWN_TOKENS],
        empty=verdict_counts[VERDICT_EMPTY],
        persisted=persisted,
        unknown_token_instances=unknown_instances,
        name_like_instances=name_like_instances,
        top_unknown_tokens=tuple(unknown_counter.most_common(TOP_UNKNOWN_TOKEN_COUNT)),
        summary_rows=summary_rows,
        dry_run=dry_run,
    )


def render_example_morphology_stats(stats: ExampleMorphologyStats) -> str:
    lines = [
        "example morphology validation" + (" (dry run, nothing stored)" if stats.dry_run else ""),
        f"  examined={stats.examined} valid={stats.valid} "
        f"unknown_tokens={stats.unknown_tokens} ({stats.unknown_pct:.2f}%) "
        f"empty={stats.empty} persisted={stats.persisted}",
        f"  unrecognized words summed over sentences={stats.unknown_token_instances} "
        f"(plus {stats.name_like_instances} name-like, not counted as defects)",
    ]

    if stats.top_unknown_tokens:
        lines.append("  most repeated unrecognized words:")
        lines.extend(f"    {count:>6}  {token}" for token, count in stats.top_unknown_tokens)

    if stats.summary_rows:
        lines.append("  by source family (whole table, not just this run):")
        lines.append(
            f"    {'family':<32}{'examples':>10}{'validated':>11}{'unknown':>9}{'unknown %':>11}"
        )
        for family, examples, validated, _valid, unknown, _empty, unknown_pct in stats.summary_rows:
            pct = "-" if unknown_pct is None else f"{unknown_pct:.2f}"
            lines.append(
                f"    {family or '(none)':<32}{examples:>10}{validated:>11}{unknown:>9}{pct:>11}"
            )

    return "\n".join(lines)


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "ExampleMorphologyStats",
    "render_example_morphology_stats",
    "validate_example_morphology",
]
