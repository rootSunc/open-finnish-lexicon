"""Read-only coverage report for the lexicon and the Chinese layer."""

from __future__ import annotations

from typing import Any

from psycopg import Connection, sql

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.zh_script import simplified_chinese_text_issue

TABLE_COUNTS = (
    "lexicon.lexeme",
    "lexicon.lexeme_sense",
    "lexicon.form",
    "lexicon.example",
    "lexicon.sense_example",
    "lexicon.pronunciation",
    "lexicon.lexical_relation",
    "lexicon.derivation_relation",
    "lexicon.collocation",
    "lexicon.lexeme_topic",
    "zh_layer.zh_gloss",
    "zh_layer.zh_example_translation",
    "semantic.zh_gloss_candidate",
)


def _scalar_int(row: tuple[Any, ...] | None) -> int:
    return int(row[0]) if row and row[0] is not None else 0


def collect_data_quality_metrics(*, connection: Connection | None = None) -> dict[str, Any]:
    with connection_scope(connection) as conn:
        counts = {
            table: (
                _scalar_int(
                    conn.execute(
                        "select count(*) from zh_layer.zh_example_translation where is_usable"
                    ).fetchone()
                )
                if table == "zh_layer.zh_example_translation"
                else _scalar_int(
                    conn.execute(
                        sql.SQL("select count(*) from {}").format(
                            sql.Identifier(*table.split("."))
                        )
                    ).fetchone()
                )
            )
            for table in TABLE_COUNTS
        }
        coverage = conn.execute(
            """
            select
                (select count(*) from lexicon.lexeme l
                  where exists (select 1 from lexicon.lexeme_sense s where s.lexeme_id = l.id)),
                (select count(*) from lexicon.lexeme l
                  where exists (select 1 from lexicon.form f where f.lexeme_id = l.id)),
                (select count(*) from lexicon.lexeme where frequency_rank is not null),
                (select count(*) from lexicon.lexeme_sense s
                  where exists (select 1 from lexicon.export_example_link se
                                where se.sense_id = s.id and se.match_method <> 'inferred-headword')),
                (select count(distinct sense_id) from zh_layer.zh_gloss where gloss_zh is not null),
                (select count(*) from lexicon.lexeme where is_lemma),
                (select count(gloss_en) from lexicon.lexeme_sense),
                (select count(gloss_fi) from lexicon.lexeme_sense)
            """
        ).fetchone()
        assert coverage is not None
        verdicts = dict(
            conn.execute(
                "select verdict, count(*) from lexicon.form_validation group by verdict order by verdict"
            ).fetchall()
        )
        sources = conn.execute(
            """
            select sr.name, sf.source_version, sr.license, sf.imported_at,
                   sf.source_url, sf.checksum_sha256, sf.assets
            from warehouse.source_registry sr
            join warehouse.source_file sf
              on sf.source_registry_id = sr.id and sf.snapshot_state = 'active'
            order by sr.name, sf.imported_at
            """
        ).fetchall()
        zh_rows = conn.execute(
            "select gloss_zh from zh_layer.zh_gloss where gloss_zh is not null"
        ).fetchall()
        example_matches = dict(conn.execute("""
            select match_method, count(*) from (
                select distinct match_method, example_id,
                       case when match_method = 'inferred-headword' then lexeme_id else sense_id end as target
                from lexicon.export_example_link
            ) links
            group by match_method order by match_method
        """).fetchall())
    invalid_zh = sum(1 for (gloss,) in zh_rows if simplified_chinese_text_issue(gloss) is not None)
    return {
        "counts": counts,
        "coverage": {
            "lexemes_with_senses": coverage[0],
            "lexemes_with_forms": coverage[1],
            "lexemes_with_frequency_rank": coverage[2],
            "senses_with_examples": coverage[3],
            "senses_with_zh_gloss": coverage[4],
            "canonical_lexemes": coverage[5],
            "senses_with_english_gloss": coverage[6],
            "senses_with_finnish_gloss": coverage[7],
        },
        "form_validation": verdicts,
        "example_match_methods": example_matches,
        "invalid_zh_glosses": invalid_zh,
        "sources": [
            {
                "name": name,
                "version": version,
                "license": license_,
                "imported_at": imported_at,
                "url": url if url and url.startswith(("https://", "http://")) else None,
                "sha256": checksum or None,
                "assets": [
                    {
                        "name": asset["name"],
                        "sha256": asset["sha256"],
                        "url": asset["url"] if asset["url"].startswith(("https://", "http://")) else None,
                    }
                    for asset in assets
                ],
            }
            for name, version, license_, imported_at, url, checksum, assets in sources
        ],
    }


def _pct(part: int, whole: int) -> str:
    return f"{(100 * part / whole):.1f}%" if whole else "n/a"


def print_data_quality_report() -> None:
    metrics = collect_data_quality_metrics()
    counts = metrics["counts"]
    lexemes = counts["lexicon.lexeme"]
    senses = counts["lexicon.lexeme_sense"]
    print("open-finnish-lexicon data quality snapshot")
    print("\nrows")
    for table, value in counts.items():
        print(f"  {table:<36} {value:>10}")
    print("\ncoverage")
    for key, value in metrics["coverage"].items():
        whole = senses if key.startswith("senses") else lexemes
        print(f"  {key:<36} {value:>10}  {_pct(value, whole)}")
    print("\nform validation")
    for verdict, value in metrics["form_validation"].items():
        print(f"  {verdict:<36} {value:>10}")
    print(f"\ninvalid zh glosses: {metrics['invalid_zh_glosses']}")
    print("\nactive sources")
    for source in metrics["sources"]:
        print(
            f"  {source['name']:<16} version={source['version'] or '-'} "
            f"license={source['license'] or '-'}"
        )


__all__ = ["collect_data_quality_metrics", "print_data_quality_report"]
