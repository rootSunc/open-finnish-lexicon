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
release_tag=v1.0.0
git worktree add --detach "../open-finnish-lexicon-${release_tag}" "$release_tag"
cd "../open-finnish-lexicon-${release_tag}"
code_revision=$(git rev-parse "refs/tags/${release_tag}^{commit}")
test "$(git rev-parse HEAD)" = "$code_revision" || exit 1
uv sync --locked
export OFL_DATABASE_URL='postgresql://ofl:ofl@127.0.0.1:54320/open_finnish_lexicon'
export OFL_PROFILE=real
export OFL_DATA_DIR="./data/${release_tag}"
uv run --locked ofl init-db
uv run --locked ofl sync-all --no-refresh --exclude-sources omorfi
uv run --locked ofl reconcile-lexemes
uv run --locked ofl refresh
uv run --locked ofl package-release --dist-dir "dist/${release_tag}" \
  --dataset-version "$release_tag" --code-revision "$code_revision" \
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

## Public launch

1. Build the sample using the README, then use
   `python -m zipfile -c examples/open-finnish-lexicon-demo.zip dist/demo-site/*`
   to refresh the small downloadable ZIP. Unzip a fresh copy and check that it
   opens offline. The ZIP can also be attached to the Release. For a browser
   link, serve the contents of `dist/demo-site` on a static host.
2. Publish the verified data bundle to the tagged GitHub Release. Use the
   changelog for release notes and link the README's dataset section to the
   published release. Keep the archive, checksums and notices together.
3. Use “Offline Finnish–English dictionary database with inflected-form
   lookup” for the repository description. Suggested topics are `finnish`,
   `dictionary`, `sqlite`, `nlp`, and `open-data`.
4. Ask Finnish reader, dictionary, and NLP developers to try a lookup or
   integrate a sample. For learners, demonstrate `kädessä` finding `käsi`.
   For resource cataloguing, use the [Language Bank of Finland contact
   page](https://www.kielipankki.fi/support/contact-us/).
5. Check download counts and follow up on successful integrations and
   specific data issues.

## Replay a release from archived inputs

This repository includes the historical [v1.0.0 input lock](releases/v1.0.0.sources.toml).
With the original catalog and a release manifest, generate a lock for any release
whose input hashes are recorded.

```bash
python scripts/lock-sources.py src/open_finnish_lexicon/source_releases.toml \
  dist/v1.0.0/release-manifest.json > locked-sources.toml
```

Restore the original archives into the cache under
`$OFL_DATA_DIR/releases/<source>/<source-version>/<archive-filename>`.
Include companions such as Tatoeba sentence and link archives. Use a fresh
PostgreSQL database. Offline mode checks each hash before extraction, fails on
missing or different inputs, and leaves an archive in place on failure.

```bash
OFL_OFFLINE=1 ofl build --manifest locked-sources.toml --output dist/replayed.sqlite
```

The lock makes the original *inputs* reproducible. Export timestamps and build
IDs vary across runs. Keep archived bytes where upstream terms permit. If a
rolling URL no longer serves the original bytes, the lock alone cannot recover them.

## Evaluate and build the lite edition

The bundled [evaluation sample](../evaluation/fi-sample.json) contains project-authored
passages, reviewed form and Chinese gloss cases, and two attested example-link
regressions. Report results as counts on this particular sample. The passages
cover several everyday contexts and are too small to estimate general Finnish
coverage or translation accuracy.

```bash
python scripts/evaluate-lookup.py dist/fi.sqlite --strict
python scripts/export-lite.py dist/fi.sqlite dist/fi-lite.sqlite --max-rank 5000
python scripts/evaluate-lookup.py dist/fi-lite.sqlite
zstd -k dist/fi-lite.sqlite
```

Compare full and lite token coverage, curated results, and file size before
choosing the cutoff. Lite includes ranked canonical headwords up to the cutoff,
their forms and senses, and the linked examples. Words without a frequency rank
remain in the full edition. The lite database preserves source attribution and
uses the same schema, including a `distribution_metadata` table identifying the
edition and cutoff.
