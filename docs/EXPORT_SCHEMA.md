# Export Schema Reference (`SQLite` & `JSONL`)

`open-finnish-lexicon` exports standalone files in two formats:
- **SQLite** (`.sqlite`, `.sqlite3`, `.db`) via `ofl export-sqlite` or `ofl build --output dist/fi.sqlite`
- **JSON Lines** (`.jsonl`) via `ofl export-jsonl` or `ofl build --output dist/fi.jsonl`

Both exports write via a temporary `.<filename>.part` file and atomically replace the target on completion, so a failed or interrupted run never leaves a half-written artifact. Pass `--overwrite` to replace an existing file.

The initial SQLite schema version is `1` in `PRAGMA user_version`. Release
manifests identify the schema version of both formats. Treat numeric lexeme,
sense, and form IDs as identifiers within one snapshot. Rebuilds can assign
different IDs. For a lookup across snapshots, start with the lemma and part of
speech, then compare the senses or upstream references.

---

## 1. SQLite Export Schema

### Core Tables

| Table | Primary Key | Columns | Description |
| :--- | :--- | :--- | :--- |
| `lexeme` | `id` | `id`, `lemma`, `display_lemma`, `part_of_speech`, `frequency_rank`, `is_lemma` | Headwords (`is_lemma = 1` for canonical lemmas, `0` for pure `form-of` inflection entries). |
| `sense` | `id` | `id`, `lexeme_id`, `sense_key`, `gloss_fi`, `gloss_en`, `labels` (JSON), `sort_order` | Word senses and English/Finnish definitions. |
| `form` | `id` | `id`, `lexeme_id`, `surface_form`, `form_kind`, `features` (JSON), `validation` | Inflected surface forms and rule-validator verdicts (`verified`, `mismatch`, `uncertain`). |
| `pronunciation` | `id` | `id`, `lexeme_id`, `ipa`, `syllabification` | Phonemic/phonetic IPA and middle-dot (`·`) Finnish syllabification. |
| `example` | `id` | `id`, `text_fi`, `text_en`, `source_label`, `attribution`, `provenance` (JSON) | Example sentences and available original sentence references keyed by language. |
| `sense_example` | — | `sense_id`, `example_id`, `sort_order` | Links senses to ranked example sentences. |
| `sense_source` | — | `sense_id`, `source_name`, `source_entry` | Active sources of the base sense and its upstream entry label. |
| `zh_gloss` | — | `sense_id`, `gloss_zh`, `method`, `source_name`, `source_entry`, `confidence` | Primary Simplified Chinese glosses and available alignment evidence. |
| `zh_example_translation` | — | `example_id`, `text_zh`, `method` | Usable primary Simplified Chinese translations of example sentences. |
| `relation` | — | `source_lexeme_id`, `target_lexeme_id`, `relation_type` | Semantic relations (`synonym`, `antonym`, `hypernym`, `hyponym`, `holonym`, `meronym`). |
| `derivation` | — | `parent_lexeme_id`, `child_lexeme_id`, `relation_type` | Derivational morphology links. |
| `collocation` | — | `lexeme_id`, `sense_id`, `phrase`, `score` | Statistically filtered multi-word collocations (`COUNT >= 3` + PMI). |
| `topic` | — | `lexeme_id`, `sense_id`, `topic_id`, `label_en`, `label_cn` | Subject-domain tags with English and Chinese labels. |
| `grammar_note` | `id` | `id`, `lexeme_id`, `sense_id`, `note_fi`, `note_en`, `note_kind` | Etymology, dialect qualifiers, and grammar/usage notes. |
| `usage_warning` | `id` | `id`, `lexeme_id`, `sense_id`, `warning_fi`, `warning_en`, `warning_kind` | Sense-level usage caveats and warnings. |
| `sources` | `name` | `name`, `version`, `source_url`, `license`, `sha256` | Active upstream source labels, licenses, and available input archive fingerprints. |
| `export_metadata` | — | `build_id` | Identifies the snapshot in a distribution bundle. |

### Built-in Views & Full-Text Search (FTS5)

- **`v_lexeme_summary`** contains `id`, `lemma`, `display_lemma`, `part_of_speech`, `frequency_rank`, `is_lemma`, `primary_ipa`, `primary_gloss_en` and `primary_gloss_zh`. Both gloss columns come from the same sense.
- **`lexeme_fts`** uses SQLite FTS5 (`unicode61 remove_diacritics 2`) for token search on headwords and glosses. Use the regular indexes for exact form lookups. For Chinese substring matching, use the query below. An export made with SQLite compiled without FTS5 issues a warning and contains the regular indexes.

### Example SQLite Queries

```sql
-- 1. Top 20 canonical Finnish lemmas by frequency
SELECT lemma, part_of_speech, frequency_rank, primary_gloss_en, primary_gloss_zh
FROM v_lexeme_summary
WHERE is_lemma = 1 AND frequency_rank IS NOT NULL
ORDER BY frequency_rank ASC
LIMIT 20;

-- 2. FTS5 token lookup on headwords and glosses
SELECT s.id, s.lemma, s.part_of_speech, s.primary_ipa, s.primary_gloss_en, s.primary_gloss_zh
FROM lexeme_fts f
JOIN v_lexeme_summary s ON s.id = f.lexeme_id
WHERE lexeme_fts MATCH 'juosta'
ORDER BY rank
LIMIT 10;

-- 3. Fetch senses, Chinese glosses, and attributed examples for one lemma
SELECT sn.sort_order, sn.gloss_en, zg.gloss_zh, ex.text_fi, ex.text_en, zet.text_zh, ex.attribution
FROM lexeme l
JOIN sense sn ON sn.lexeme_id = l.id
LEFT JOIN zh_gloss zg ON zg.sense_id = sn.id
LEFT JOIN sense_example se ON se.sense_id = sn.id
LEFT JOIN example ex ON ex.id = se.example_id
LEFT JOIN zh_example_translation zet ON zet.example_id = ex.id
WHERE l.lemma = 'juosta' AND l.part_of_speech = 'verb'
ORDER BY sn.sort_order, se.sort_order;

-- 4. Chinese substring lookup without a tokenizer
SELECT l.lemma, l.part_of_speech, s.gloss_en, g.gloss_zh, g.source_name
FROM zh_gloss g
JOIN sense s ON s.id = g.sense_id
JOIN lexeme l ON l.id = s.lexeme_id
WHERE instr(g.gloss_zh, '银行') > 0
ORDER BY l.frequency_rank IS NULL, l.frequency_rank, l.lemma;
```

`verified` means the rule engine predicts that form for the recorded features.
`mismatch` means its prediction differed. `uncertain` means the rules could
not reach a verdict. Chinese alignment scores are heuristic, and the
experimental Chinese layer has incomplete coverage.

---

## 2. JSON Lines (`.jsonl`) Export Schema

By default, line 1 contains `{"_sources": [...]}` for standalone license attribution, followed by one JSON object per lexeme.

Use `--pure-jsonl` (or `--no-sources-header`) to write a lexeme object on every
line. `ofl build` writes a source report by default. `ofl package-release` also
includes source metadata in its report and manifest. The standalone
`export-jsonl` command writes only the JSONL file.

Packaged JSONL with a header includes `_export` with the build ID and schema
version. In pure mode the report binds the JSONL file to its snapshot by its
SHA-256. Sense objects include `sources` and `gloss_zh_source`. Example objects
include `provenance` when upstream identifiers are available. Tatoeba provenance
lists each language's sentence ID, source URL, contributor where available,
and whether a translation was linked through a pivot. Re-ingest older
snapshots to populate these fields.

### Lexeme Object Structure

```json
{
  "id": 1,
  "lemma": "juosta",
  "display_lemma": "juosta",
  "pos": "verb",
  "is_lemma": true,
  "frequency_rank": 124,
  "etymology": "Inherited from Proto-Finnic.",
  "ipa": ["/ˈjuos.tɑ/"],
  "pronunciations": [
    {"ipa": "/ˈjuos.tɑ/", "syllabification": "juos·ta"}
  ],
  "senses": [
    {
      "id": 1,
      "sense_key": "sense-1",
      "gloss_en": "to run",
      "gloss_fi": null,
      "gloss_zh": "奔跑；跑",
      "gloss_zh_method": "wiktionary_zh-rule",
      "labels": ["literal"],
      "notes": ["Often used for physical running."],
      "warnings": [],
      "examples": [
        {
          "fi": "Hän juoksee joka aamu.",
          "en": "He runs every morning.",
          "zh": "他每天早上跑步。",
          "source": "tatoeba",
          "attribution": "Tatoeba contributor: ..."
        }
      ]
    }
  ],
  "forms": [
    {
      "form": "juoksen",
      "form_kind": "kaikki",
      "features": {"mood": "indicative", "number": "singular", "person": "1", "tense": "present"},
      "validation": "verified"
    }
  ],
  "relations": [{"target_lexeme_id": 42, "target_lemma": "liikkua", "type": "hypernym"}],
  "derivations": [{"child_lexeme_id": 99, "child_lemma": "juoksija", "type": "derived-term"}],
  "collocations": [{"phrase": "juosta pakoon", "score": 8.42, "sense_id": null}],
  "topics": [{"topic_id": "sports", "label_en": "Sports", "label_cn": "体育", "sense_id": 1}]
}
```

---

## 3. Compressed Release Bundles (`.zst` & `SHA256SUMS`)

`ofl package-release --dist-dir dist/release` reads one PostgreSQL snapshot
to produce the bundle. It checks core row counts, SQLite integrity and foreign
keys and the build IDs before publishing the staged files. A new destination
directory appears after the entire bundle is ready. With `--overwrite`,
existing files are replaced individually and `SHA256SUMS` is written last.

| Artifact | Description |
| :--- | :--- |
| `fi.sqlite.zst` | Zstandard-compressed standalone SQLite database (with FTS5 and `v_lexeme_summary`). |
| `fi.jsonl.zst` | Zstandard-compressed JSON Lines export. |
| `fi.sqlite.report.json` | Counts, coverage, source references, and the snapshot ID and raw file hashes. |
| `release-manifest.json` | File hashes and sizes, dataset version, schema version, build ID, code revision when supplied, and input fingerprints. |
| `DATA-NOTICE.md` | Upstream attribution and applicable license notices. |
| `SHA256SUMS` | Standard checksum manifest verifiable via `shasum -a 256 -c SHA256SUMS` or `sha256sum -c SHA256SUMS`. |

### Verifying & Unpacking Downstream

```bash
cd dist/release
shasum -a 256 -c SHA256SUMS
zstd -d -k fi.sqlite.zst -o fi.sqlite
zstd -d -k fi.jsonl.zst -o fi.jsonl
```

`--no-export` repackages the matching raw files and report from an earlier
`package-release` run. It can run without PostgreSQL. Use a fresh export for
files from other workflows or older bundle formats. For release preparation,
see [RELEASING.md](RELEASING.md).
