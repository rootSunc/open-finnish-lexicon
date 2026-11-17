"""CLI usage text."""

USAGE = """usage: ofl <command> [options]

build
  build --output <file.sqlite|file.jsonl> [--manifest <path>] [--skip-sync] [--no-report]
                                 init-db, sync-all, reconcile, refresh and export in one go;
                                 also writes <output>.report.json

database
  init-db                        apply schema migrations

sources
  sync-all [--manifest <path>]   download pinned releases and ingest them all
  ingest-<source> --input <path> ingest one local file
                                 sources: kaikki, omorfi, tatoeba, frequency,
                                 finnwordnet, wiktionary-zh, dbnary-zh
  seed-fixtures                  ingest the bundled fixtures (OFL_PROFILE=fixture)
  archive-stale-build-runs [--older-than-hours <n>]

normalize
  normalize-lexemes              merge duplicate lexemes
  reconcile-lexemes              normalize, align surface forms, prune shells
  prune-empty-lexemes            merge or drop lexemes without senses
  refresh                        rebuild collocations, Chinese layer, form validation

checks
  validate-morphology-rules
  validate-example-morphology [--limit <n>] [--source <family>] [--revalidate] [--dry-run]
  select-zh-glosses
  sanitize-invalid-zh-glosses [--apply]
  report-data-quality

export
  export-sqlite --output <path>  write lexicon and Chinese layer to one SQLite file
  export-jsonl --output <path>   write one JSON object per lexeme
"""
