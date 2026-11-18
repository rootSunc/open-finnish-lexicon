# open-finnish-lexicon

Build an offline Finnish lexicon with English definitions, inflected forms,
example sentences, and an experimental Simplified Chinese gloss layer. Use the
SQLite or JSON Lines exports in dictionary apps, study tools, or NLP pipelines.

## Try the sample

From a clone, with Python 3.12+, Docker Compose and the `sqlite3` command:

```bash
python -m venv .venv
source .venv/bin/activate
pip install .
docker compose up -d --wait demo
OFL_DATABASE_URL=postgresql://ofl:ofl@127.0.0.1:54332/ofl_demo \
  OFL_PROFILE=fixture OFL_DATA_DIR=./data/demo \
  ofl build --manifest examples/source_releases.toml --output dist/demo.sqlite
sqlite3 -header -column dist/demo.sqlite < examples/lookup.sql
```

The three queries find the lemma behind `juoksen`, show both meanings of
`kuusi`, and trace a sense to its source. The sample uses three
[project-authored records](examples/mini-kaikki.jsonl) and a separate database.
It works without the upstream datasets. Stop its database with
`docker compose stop demo`. Pass `--overwrite` when rebuilding the sample.

open-finnish-lexicon downloads releases of Kaikki (Wiktionary), Omorfi, Tatoeba,
FinnWordNet and a Finnish frequency list, merges them into one PostgreSQL
schema, validates inflected forms with a rule engine, and exports the result
to SQLite or JSON Lines. An optional layer adds Chinese glosses from the
Chinese Wiktionary, DBnary, Chinese Open Wordnet (OMW), and CC-CEDICT.

The repository includes source code and small fixtures. See
[NOTICE.md](NOTICE.md) for data licenses and attribution.

## What you get

- **One schema for several sources.** Lexemes, senses, inflected forms,
  pronunciations, examples, lexical relations, derivations, collocations and
  topics, each linked to the source file it came from.
- **Traceable builds.** Every source is listed in
  [`source_releases.toml`](src/open_finnish_lexicon/source_releases.toml), and
  each completed sync records the SHA-256 of each archive and companion file.
  Several URLs are rolling, including Kaikki, Tatoeba and DBnary. Their catalog
  labels group downloads. The hashes identify the actual inputs. Re-running
  a sync activates each new source snapshot only after its projection succeeds.
- **Quality gates.** Duplicate lexemes are merged, empty shells pruned, and
  frequency imports refuse empty or sparse input. A pure-Python rule engine
  marks each inflected form `verified`, `mismatch` or `uncertain`.
- **Standalone exports.** `export-sqlite` writes one SQLite file.
  `export-jsonl` writes one JSON object per lexeme. Both can carry source
  fingerprints and provide source references for senses and translated examples.

## Install

Requires Python 3.12+ and PostgreSQL with the `unaccent` and `pg_trgm`
extensions (both ship with PostgreSQL; tested on PostgreSQL 17). From a clone:

```bash
pip install .
```

The Omorfi source and the example-morphology check use the optional
[Omorfi](https://github.com/flammie/omorfi) extra, which includes GPL-3.0 software.

```bash
pip install ".[omorfi]"
```

## Build the full lexicon

The command-line tool is called `ofl`. With Docker, one command builds the
whole lexicon:

```bash
docker compose up -d --wait db          # PostgreSQL on 127.0.0.1:54320
export OFL_DATABASE_URL=postgresql://ofl:ofl@127.0.0.1:54320/open_finnish_lexicon
ofl build --output dist/fi.sqlite
```

`ofl build` creates the schema, syncs the enabled sources, merges
duplicate lexemes, rebuilds derived tables, and exports the result. The format
follows the file name (`.sqlite`/`.db` or `.jsonl`). Next to the export it
writes `fi.sqlite.report.json` with row counts, coverage, source versions and
licenses, and the time each step took.

Allow tens of minutes and several gigabytes for a full build, including source
archives, unpacked data, PostgreSQL and the exports. An example build without
Omorfi took about 26 minutes. In that snapshot the SQLite and JSONL exports
were about 1.1 GB each before compression. The base install skips Omorfi.
Chinese sources are enabled by default. For a smaller first build, try
`--sources kaikki,frequency` on an empty database. Source filters control the
current sync, and any other active snapshots in the database still take part
in exports.

| Option | Effect |
| --- | --- |
| `--manifest <path>` | Use another `source_releases.toml` |
| `--skip-sync` | Re-export from the existing database without downloading |
| `--no-report` | Do not write the report file |
| `--overwrite` | Replace each output and report file via an atomic rename |
| `--sources <s1,s2>` | Sync only the selected sources (e.g. `kaikki,frequency`) |
| `--exclude-sources <s1,s2>` | Skip specific sources during sync (e.g. `tatoeba`) |
| `--force-download` | Re-download selected upstream archives even if cached locally |
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
ofl export-sqlite --output dist/fi.sqlite
ofl package-release --dist-dir dist/release         # export and package one validated snapshot
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

Source references are available for senses, forms, relations, and other
projected records in PostgreSQL. The export schema lists the references
available to downstream users.

## How a sync works

```text
upstream release ──fetch──► data/releases/<source>/<version>/
                 ──stage──► warehouse.source_document / source_claim
                 ──project► lexicon.* / zh_layer.* / semantic.*
                 ──refresh► collocations, Chinese gloss selection, form validation
```

A new snapshot is staged as `pending`, then projected and marked `active`
in one transaction. Retired warehouse documents are cleaned up afterwards.
Each source commits separately. Retry a failed sync to complete the remaining
sources before exporting. Use one writer per build database.

## Development

```bash
uv sync --group dev
scripts/test-db.sh                      # throwaway PostgreSQL on 127.0.0.1:54331
uv run pytest
uv run ruff check src tests
```

Tests truncate tables, so they only run against a database whose name
contains `test` (`OFL_TEST_DATABASE_URL`). The test suite also uses `zstd`
on Python 3.12 and 3.13. Set `OFL_REQUIRE_TEST_DB=1` to require PostgreSQL in
the test run. `ofl seed-fixtures` is a development command that reads
`tests/fixtures/` from the repository root with `OFL_PROFILE=fixture`.

For release steps and verification, see [docs/RELEASING.md](docs/RELEASING.md).

## License

Code: Apache-2.0 ([LICENSE](LICENSE)). Data built with this tool and the test
fixtures are covered by their sources' licenses ([NOTICE.md](NOTICE.md)).
