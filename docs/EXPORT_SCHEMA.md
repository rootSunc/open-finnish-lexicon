# Export Schema Reference (`SQLite` & `JSONL`)

`open-finnish-lexicon` exports standalone files in two formats:
- **SQLite** (`.sqlite`, `.sqlite3`, `.db`) via `ofl export-sqlite` or `ofl build --output dist/fi.sqlite`
- **JSON Lines** (`.jsonl`) via `ofl export-jsonl` or `ofl build --output dist/fi.jsonl`

Both exports write via a temporary `.<filename>.part` file and atomically replace the target on completion, so a failed or interrupted run never leaves a half-written artifact. Pass `--overwrite` to replace an existing file.

---

## 1. SQLite Export Schema

### Core Tables

| Table | Primary Key | Columns | Description |
| :--- | :--- | :--- | :--- |
| `lexeme` | `id` | `id`, `lemma`, `display_lemma`, `part_of_speech`, `frequency_rank`, `is_lemma` | Headwords (`is_lemma = 1` for canonical lemmas, `0` for pure `form-of` inflection entries). |
| `sense` | `id` | `id`, `lexeme_id`, `sense_key`, `gloss_fi`, `gloss_en`, `labels` (JSON), `sort_order` | Word senses and English/Finnish definitions. |
| `form` | `id` | `id`, `lexeme_id`, `surface_form`, `form_kind`, `features` (JSON), `validation` | Inflected surface forms and rule-validator verdicts (`verified`, `mismatch`, `uncertain`). |
| `pronunciation` | `id` | `id`, `lexeme_id`, `ipa`, `syllabification` | Phonemic/phonetic IPA and middle-dot (`·`) Finnish syllabification. |
| `example` | `id` | `id`, `text_fi`, `text_en`, `source_label`, `attribution` | Example sentences with upstream attribution (e.g., Tatoeba CC-BY-2.0-FR contributor). |
| `sense_example` | — | `sense_id`, `example_id`, `sort_order` | Links senses to ranked example sentences. |
| `zh_gloss` | — | `sense_id`, `gloss_zh`, `method` | Primary Simplified Chinese glosses (normalized via OpenCC `t2s`). |
| `zh_example_translation` | — | `example_id`, `text_zh`, `method` | Usable primary Simplified Chinese translations of example sentences. |
| `relation` | — | `source_lexeme_id`, `target_lexeme_id`, `relation_type` | Semantic relations (`synonym`, `antonym`, `hypernym`, `hyponym`, `holonym`, `meronym`). |
| `derivation` | — | `parent_lexeme_id`, `child_lexeme_id`, `relation_type` | Derivational morphology links. |
| `collocation` | — | `lexeme_id`, `sense_id`, `phrase`, `score` | Statistically filtered multi-word collocations (`COUNT >= 3` + PMI). |
| `topic` | — | `lexeme_id`, `sense_id`, `topic_id`, `label_en`, `label_cn` | Subject-domain tags with English and Chinese labels. |
| `grammar_note` | `id` | `id`, `lexeme_id`, `sense_id`, `note_fi`, `note_en`, `note_kind` | Etymology, dialect qualifiers, and grammar/usage notes. |
| `usage_warning` | `id` | `id`, `lexeme_id`, `sense_id`, `warning_fi`, `warning_en`, `warning_kind` | Sense-level usage caveats and warnings. |
| `sources` | `name` | `name`, `version`, `source_url`, `license` | Upstream source versions and SPDX license expressions. |

### Built-in Views & Full-Text Search (FTS5)

- **`v_lexeme_summary`**: Convenience view (`id`, `lemma`, `display_lemma`, `part_of_speech`, `frequency_rank`, `is_lemma`, `primary_ipa`, `primary_gloss_en`, `primary_gloss_zh`).
- **`lexeme_fts`**: SQLite **FTS5** virtual table (`unicode61 remove_diacritics 2`) indexing `lemma`, `display_lemma`, `gloss_en`, and `gloss_zh` (with unindexed `lexeme_id` and `part_of_speech`).

### Example SQLite Queries

```sql
-- 1. Top 20 canonical Finnish lemmas by frequency
SELECT lemma, part_of_speech, frequency_rank, primary_gloss_en, primary_gloss_zh
FROM v_lexeme_summary
WHERE is_lemma = 1 AND frequency_rank IS NOT NULL
ORDER BY frequency_rank ASC
LIMIT 20;

-- 2. Millisecond FTS5 lookup across Finnish headwords, English glosses, and Chinese glosses
SELECT s.id, s.lemma, s.part_of_speech, s.primary_ipa, s.primary_gloss_en, s.primary_gloss_zh
FROM lexeme_fts f
JOIN v_lexeme_summary s ON s.id = f.lexeme_id
WHERE lexeme_fts MATCH 'juosta OR 奔跑'
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
```

---

## 2. JSON Lines (`.jsonl`) Export Schema

By default, line 1 contains `{"_sources": [...]}` for standalone license attribution, followed by one JSON object per lexeme.

For strict homogeneous JSONL pipelines (DuckDB, Polars, Spark, HuggingFace `datasets`), pass `--pure-jsonl` (or `--no-sources-header`) so every line is a lexeme object; source metadata remains available in `<output>.report.json`.

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
  "topics": [{"id": "sports", "label_en": "Sports", "confidence": 0.7, "sense_id": 1}]
}
```
