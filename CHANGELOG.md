# Changelog

## 1.1.0

- Add Unicode-normalized SQLite lookup keys and a read-only lookup example.
- Export evidence labels for examples. Tatoeba examples linked to a polysemous
  word appear at headword level in both formats.
- Add a smaller SQLite edition based on frequency rank, with lookup coverage
  measured on the bundled Finnish sample.
- Add an input catalog lock and offline replay from verified archives.
- Add a sense reference format for restoring bookmarks across data snapshots.

The exports use schema version 2. See the export schema for query changes
and the v1 compatibility path.

## 1.0.0

- Build an offline Finnish lexicon from Kaikki, FinnWordNet, Tatoeba,
  FrequencyWords and optional Omorfi. Export SQLite or JSON Lines.
- Export the experimental Simplified Chinese gloss layer with alignment
  sources and heuristic confidence scores.
- Package and verify both export formats from a single PostgreSQL snapshot.
  Bundles carry input checksums, snapshot metadata and upstream notices.
- Try word-form lookup and homographs in the downloadable browser and SQLite
  sample.

The full data snapshot contains about 180,000 headwords, 312,000 English
senses and 4.84 million word-form records. Simplified Chinese glosses cover
about 19% of senses. About 10% of senses link to examples, and some links
attach examples to the wrong sense. The bundled snapshot omits Omorfi.
