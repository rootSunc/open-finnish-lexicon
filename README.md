# open-finnish-lexicon

Build a Finnish lexical database from open sources, with provenance for every row.

open-finnish-lexicon downloads releases of Kaikki (Wiktionary), Omorfi, Tatoeba,
FinnWordNet and a Finnish frequency list, merges them into one PostgreSQL
schema, validates inflected forms with a rule engine, and exports the result
to SQLite or JSON Lines. An optional layer adds Chinese glosses from the
Chinese Wiktionary, DBnary, Chinese Open Wordnet (OMW), and CC-CEDICT.

The project ships code only. The data you build keeps the licenses of its
sources; see [NOTICE.md](NOTICE.md).

## What you get

- **One schema for several sources.** Lexemes, senses, inflected forms,
  pronunciations, examples, lexical relations, derivations, collocations and
  topics, each linked to the source file it came from.
- **Traceable builds.** Every source is listed in
  [`source_releases.toml`](src/open_finnish_lexicon/source_releases.toml), and
  each build records the SHA-256 of every file it downloaded. Omorfi is pinned
  by checksum; Kaikki, Tatoeba and DBnary only publish a rolling "latest" URL,
  so two builds on different days can differ. Re-running a sync replaces a
  source's snapshot cleanly and never publishes a half-loaded one.
- **Quality gates.** Duplicate lexemes are merged, empty shells pruned, and
  frequency imports refuse empty or sparse input. A pure-Python rule engine
  marks each inflected form `verified`, `mismatch` or `uncertain`.
- **Exports that need no database.** `export-sqlite` writes one SQLite file;
  `export-jsonl` writes one JSON object per lexeme. Both include each source's
  version and license.

## Install

Requires Python 3.12+ and PostgreSQL with the `unaccent` and `pg_trgm`
extensions (both ship with PostgreSQL; tested on PostgreSQL 17). From a clone:

```bash
pip install .
```

The Omorfi source and the example-morphology check use
[Omorfi](https://github.com/flammie/omorfi), which is GPL-3.0. They are an
optional extra so the base install stays Apache-2.0 only:

```bash
pip install ".[omorfi]"
```

## Quick start

The command-line tool is called `ofl`. With Docker, one command builds the
whole lexicon:

```bash
docker compose up -d                    # PostgreSQL on 127.0.0.1:54320
export OFL_DATABASE_URL=postgresql://ofl:ofl@127.0.0.1:54320/open_finnish_lexicon
ofl build --output dist/fi.sqlite
```

`ofl build` creates the schema, downloads and ingests every source, merges
duplicate lexemes, rebuilds derived tables, and exports the result. The format
follows the file name (`.sqlite`/`.db` or `.jsonl`). Next to the export it
writes `fi.sqlite.report.json` with row counts, coverage, source versions and
licenses, and the time each step took.

| Option | Effect |
| --- | --- |
| `--manifest <path>` | Use another `source_releases.toml` |
| `--skip-sync` | Re-export from the existing database without downloading |
| `--no-report` | Do not write the report file |
| `--overwrite` | Atomically replace an existing output (and `.report.json`) file |
| `--sources <s1,s2>` | Sync only the selected sources (e.g. `kaikki,frequency`) |
| `--exclude-sources <s1,s2>` | Skip specific sources during sync (e.g. `tatoeba`) |
| `--force-download` | Re-download rolling upstream archives even if cached locally |
| `--pure-jsonl` | Omit the leading `_sources` metadata row when exporting `.jsonl` |

Exports write to a temporary `.part` file and atomically rename on completion.
SQLite exports include foreign-key indexes, a `v_lexeme_summary` convenience
view, and a `lexeme_fts` FTS5 full-text index; see
[`docs/EXPORT_SCHEMA.md`](docs/EXPORT_SCHEMA.md) for table definitions and
example queries.

### Step by step

The same steps are available on their own:

```bash
ofl init-db                      # create the schema
ofl sync-all                     # download and ingest every source
ofl reconcile-lexemes            # merge duplicates and prune shells
ofl refresh                      # collocations, Chinese layer, form checks
ofl report-data-quality
ofl export-sqlite --output fi.sqlite
```

To ingest one local file instead, use `ingest-<source> --input <path>`
(sources: `kaikki`, `omorfi`, `tatoeba`, `frequency`, `finnwordnet`,
`omw-zh`, `cedict-zh`, `wiktionary-zh`, `dbnary-zh`). Run `ofl help` for every command.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `OFL_DATABASE_URL` | required | PostgreSQL connection string |
| `OFL_DATA_DIR` | `./data` | Download and unpack directory |
| `OFL_PROFILE` | `real` | `real` refuses fixture input; `fixture` is for tests |
| `OFL_SOURCE_MANIFEST` | bundled | Alternative `source_releases.toml` |

## Schema

| Schema | Contents |
| --- | --- |
| `warehouse` | Source registry (with license), source files, raw documents and claims, build runs |
| `lexicon` | Lexemes, senses, forms, form analyses and validation, pronunciations, examples, relations, derivations, collocations, topics, frequency signals |
| `zh_layer` | Chinese glosses and example translations |
| `semantic` | Chinese gloss candidates, selections and sense alignment |

Every content table has a `*_source` table or a source column, so you can tell
which upstream file each row came from.

## How a sync works

```text
upstream release ──fetch──► data/releases/<source>/<version>/
                 ──stage──► warehouse.source_document / source_claim
                 ──project► lexicon.* / zh_layer.* / semantic.*
                 ──refresh► collocations, Chinese gloss selection, form validation
```

A new snapshot is staged as `pending`, projected, and only then marked
`active`; the previous snapshot's rows are retired afterwards in small batches.

## Development

```bash
uv sync --group dev
scripts/test-db.sh                      # throwaway PostgreSQL on 127.0.0.1:54331
uv run pytest
uv run ruff check src tests
```

Tests truncate tables, so they only run against a database whose name
contains `test` (`OFL_TEST_DATABASE_URL`).

## License

Code: Apache-2.0 ([LICENSE](LICENSE)). Data built with this tool and the test
fixtures are covered by their sources' licenses ([NOTICE.md](NOTICE.md)).
