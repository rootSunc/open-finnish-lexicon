# Changelog

## Unreleased

- Build an offline Finnish lexicon from Kaikki, FinnWordNet, Tatoeba,
  FrequencyWords and optional Omorfi. Export SQLite or JSON Lines.
- Export the experimental Simplified Chinese gloss layer with alignment
  sources and heuristic confidence scores.
- Package and verify both export formats from a single PostgreSQL snapshot.
  Bundles carry input checksums, snapshot metadata and upstream notices.
- Run the three-record demo in a separate PostgreSQL database and use the
  included queries to look up a word form, homograph and source.
