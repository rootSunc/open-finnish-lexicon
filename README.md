# Open Finnish Lexicon

**Look up Finnish words as they appear in text.**

Look up **`kädessä`** to find **`käsi`** (“hand”), marked as singular inessive.
Look up **`juoksen`** to find **`juosta`** (“to run”), marked as first-person
singular present indicative.

An offline Finnish–English dictionary database for readers, dictionary apps,
and data pipelines. The full dataset contains about **180,000 headwords**,
**312,000 English senses**, and **4.84 million word-form records**.

[Download the browser and SQLite sample](examples/open-finnish-lexicon-demo.zip) · [Download the full dataset](https://github.com/rootSunc/open-finnish-lexicon/releases/latest) · [Browse the export schema](docs/EXPORT_SCHEMA.md)

## Try the sample

The sample includes seven entries. Try `kädessä` for a case ending, `kuusi`
for two meanings, or `tulin` for two possible headwords.

Unzip the sample and open `index.html` in your browser. To query the same data
directly, run this from the directory containing `sample.sqlite`.

```bash
sqlite3 -readonly -header -column sample.sqlite "
  SELECT f.surface_form, l.lemma, l.primary_gloss_en
  FROM form AS f
  JOIN v_lexeme_summary AS l ON l.id = f.lexeme_id
  WHERE f.surface_form = 'kädessä' AND l.is_lemma = 1;
"
```

```text
surface_form  lemma  primary_gloss_en
------------  -----  ----------------
kädessä       käsi   hand
```

See [build the sample from source](#build-the-sample-from-source) to generate both files locally.

## What you can do with it

| Use case | Data you can use |
| --- | --- |
| Look up words as they appear in text | Inflected forms linked to headwords, with grammatical features and morphology rule-check results |
| Show a full dictionary entry | Separate meanings and parts of speech, such as `kuusi` (“six” or “spruce”), plus IPA, syllable breaks, and usage notes where available |
| Build vocabulary lists and flashcards | Frequency ranks, Finnish examples, and English translations where available |
| Explore related words | Synonyms, broader and narrower terms, derived words, collocations, and topics |
| Add Simplified Chinese glosses | Experimental glosses linked to individual meanings, with source and confidence information where available |

The build brings together Wiktionary data from Kaikki, FinnWordNet, Tatoeba,
FrequencyWords, and Chinese gloss sources. The exports preserve upstream
references for definitions and available attribution for examples. See the
[source catalog](src/open_finnish_lexicon/source_releases.toml).

## Use the full dataset

Download the files from the [latest GitHub Release](https://github.com/rootSunc/open-finnish-lexicon/releases/latest).
Python and PostgreSQL are required for [building from source](#build-the-full-dataset).

| Export | Best for |
| --- | --- |
| `fi.sqlite.zst` | Complete data with indexed headword and form lookup and FTS5 search |
| `fi-lite.sqlite.zst` | Smaller offline readers and mobile apps. It includes the forms of selected headwords. |
| `fi.jsonl.zst` | Bulk imports and NLP. It contains one entry per line after the source metadata header by default. |

Download `lookup.py` alongside the SQLite archive. The example uses Python's
standard library and opens the database read-only.

```bash
zstd -d -k fi.sqlite.zst
python3 lookup.py fi.sqlite KÄDESSÄ
python3 lookup.py fi.sqlite tulin
```

The first query finds `käsi` with singular inessive features. The second returns
both `tulla` and `tuli`. The same commands work with `fi-lite.sqlite` when a word
is included in that edition. See the [schema](docs/EXPORT_SCHEMA.md) for
parameterized queries and [benchmark instructions](docs/RELEASING.md#evaluate-and-build-the-lite-edition)
for comparing coverage.

## Data coverage and feedback

Experimental Simplified Chinese glosses cover about **19% of senses**.
Examples have a match method so apps can distinguish source-provided examples
from inferred matches. Tatoeba examples for words with multiple senses
are exposed at headword level in schema 2. Form validation records whether the
rules could confirm a word form. Use [sense references](docs/EXPORT_SCHEMA.md#save-and-restore-a-sense-reference)
to carry bookmarks across snapshots.

[Report a data issue](https://github.com/rootSunc/open-finnish-lexicon/issues/new?template=data.yml)
with the word, dataset version and expected result.

## Build the sample from source

From the repository root, use Python 3.12+, Docker Compose, and `sqlite3`.
The demo builds a SQLite file from the [included entries](examples/mini-kaikki.jsonl)
in a separate PostgreSQL database. It skips upstream data downloads.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .

docker compose up -d --wait demo
OFL_DATABASE_URL=postgresql://ofl:ofl@127.0.0.1:54332/ofl_demo \
  OFL_PROFILE=fixture OFL_DATA_DIR=./data/demo \
  ofl build --manifest examples/source_releases.toml --output dist/demo.sqlite
sqlite3 -readonly -header -column dist/demo.sqlite < examples/lookup.sql
python scripts/package-demo.py dist/demo.sqlite dist/demo-site
docker compose stop demo
```

Open `dist/demo-site/index.html` in a browser or use `dist/demo-site/sample.sqlite`
directly. Both contain the same sample.

The queries find the headword for `juoksen`, distinguish the two entries for
`kuusi`, and trace the `juosta` definition to its source. Add `--overwrite` to
the build command to replace the demo export.

## Build the full dataset

Install `ofl` with the Python setup above, then start PostgreSQL and build the export.

```bash
docker compose up -d --wait db
export OFL_DATABASE_URL=postgresql://ofl:ofl@127.0.0.1:54320/open_finnish_lexicon
ofl build --output dist/fi.sqlite
```

The build downloads sources, merges duplicate entries, checks inflected forms
against morphology rules, and writes the export and `<output>.report.json`.
Allow tens of minutes and several gigabytes of disk space.

Use `--output dist/fi.jsonl` for JSON Lines and `--skip-sync` to reuse sources
already in PostgreSQL. Install the optional Omorfi integration with
`python -m pip install '.[omorfi]'`. Run `ofl help` for all options and see
the [release guide](docs/RELEASING.md) to package both formats with checksums.

## Development and licensing

Install dev dependencies with `uv sync --group dev` and run `uv run pytest`.
For PostgreSQL tests, run `scripts/test-db.sh` and export the connection
string it prints as `OFL_TEST_DATABASE_URL`.

Code is licensed under [Apache 2.0](LICENSE). Upstream data is subject to its
source licenses. See [notices and attribution](NOTICE.md).
