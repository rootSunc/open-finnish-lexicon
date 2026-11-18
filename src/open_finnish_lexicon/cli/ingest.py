"""Database setup, fixture seeding and refresh helpers."""

from __future__ import annotations

from importlib import resources

from open_finnish_lexicon.config import get_pipeline_settings
from open_finnish_lexicon.db import connect
from open_finnish_lexicon.sources.registry import FIXTURE_INPUTS, refresh_runtime_views, run_manual_ingest


def _migrations() -> list[tuple[str, str]]:
    folder = resources.files("open_finnish_lexicon") / "migrations"
    files = sorted(
        (entry for entry in folder.iterdir() if entry.name.endswith(".sql")),
        key=lambda entry: entry.name,
    )
    return [(entry.name, entry.read_text(encoding="utf-8")) for entry in files]


def init_db() -> int:
    """Apply bundled migrations that have not run yet."""

    applied: list[str] = []
    with connect() as conn:
        conn.execute(
            """
            create table if not exists public.ofl_migration (
                name text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )
        done = {row[0] for row in conn.execute("select name from public.ofl_migration")}
        for name, migration_sql in _migrations():
            if name in done:
                continue
            conn.execute(migration_sql.encode("utf-8"))
            conn.execute("insert into public.ofl_migration (name) values (%s)", (name,))
            applied.append(name)
        conn.commit()
    print(f"init-db: applied={len(applied)}" + (f" ({', '.join(applied)})" if applied else ""))
    return 0


def seed_fixtures() -> int:
    if get_pipeline_settings().data_profile != "fixture":
        raise RuntimeError("seed-fixtures requires OFL_PROFILE=fixture")
    if not all(input_path.is_file() for _, input_path in FIXTURE_INPUTS):
        raise SystemExit("seed-fixtures requires the repository root with tests/fixtures/")
    for source_name, input_path in FIXTURE_INPUTS:
        run_manual_ingest(source_name, input_path)
    refresh_runtime_views()
    return 0


def refresh_projections() -> int:
    refresh_runtime_views()
    return 0
