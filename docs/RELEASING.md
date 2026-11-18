# Preparing a release

## Source release

1. Review the new and historical fixture material against
   [the fixture inventory](../tests/fixtures/README.md). Record the origin,
   license and edits of actual excerpts. Use project-authored data wherever
   the original source cannot be verified.
2. Check that CI passes and follow the sample commands in the README from a
   clean clone. Confirm that the wheel smoke test can build, unpack and query a
   sample bundle.
3. Give the checked commit a version tag matching `pyproject.toml`. Include
   the relevant [changelog](../CHANGELOG.md) entries and any known limits in
   the release notes.

## Data release

Use a dedicated, empty PostgreSQL database, a clean upstream cache, and a
dedicated output directory.
Keep a single writer on the build database until the exports finish. Have
`zstd` installed for compression and verification.

```bash
export OFL_DATABASE_URL='postgresql://ofl:ofl@127.0.0.1:54320/open_finnish_lexicon'
export OFL_PROFILE=real
export OFL_DATA_DIR=./data/data-v0.1.0
ofl init-db
ofl sync-all --no-refresh --exclude-sources omorfi
ofl reconcile-lexemes
ofl refresh
ofl package-release --dist-dir dist/data-v0.1.0 \
  --dataset-version data-v0.1.0 --code-revision "$(git rev-parse HEAD)" \
  --remove-uncompressed
```

The example omits Omorfi. If you include it, test the actual model and review
the applicable terms for the distributed output. Run the export from the
tagged source revision. Archive the manifest and the exact verified input files
where their terms permit. For a rolling source, the catalog version is a
label and the checksums identify the bytes used. Rerun source syncs against a
fresh database to capture companion fingerprints for older installations.

Before publishing a bundle:

- Confirm that the manifest lists the intended sources, their main and
  companion SHA-256 hashes, and deliberately omitted sources. Check that
  dataset, schema, and code version fields are present and the profile is
  `real`.
- Review the recorded licenses and attribution for the exact input versions.
  Check that sample senses and translated examples trace back to the intended
  upstream entries.
- In the release directory, run `shasum -a 256 -c SHA256SUMS` and
  `zstd -t fi.sqlite.zst fi.jsonl.zst`. Unpack the files and smoke-test a
  word-form lookup and homographs such as `kuusi`. Inspect high-frequency
  Chinese entries and their source and method alongside coverage.
- Upload both archives, the report, `release-manifest.json`,
  `DATA-NOTICE.md` and `SHA256SUMS` together.

Use `--no-export` to recompress a previous bundle when its original raw files
and report are available. Use a new dataset version when the underlying
snapshot changes.
