# Fixture inventory

These files exercise the source parsers and snapshot replacement. Some fixtures
use reduced or rewritten records. The upstream source entries below identify
the relevant licenses and attribution, with license texts in
[DATA-NOTICE.md](../../src/open_finnish_lexicon/DATA-NOTICE.md).

| Files | Source represented |
| --- | --- |
| `kaikki-juosta.jsonl`, `releases/kaikki-*` | English Wiktionary through Kaikki |
| `wiktionary-zh-*`, `releases/wiktionary-zh-*` | Chinese Wiktionary through Kaikki |
| `omorfi.tsv`, `releases/omorfi-*` | Omorfi |
| `tatoeba.tsv`, `releases/tatoeba-*` | Tatoeba |
| `finnwordnet.tsv`, `finnwordnet-rels/`, `releases/finnwordnet-*` | FinnWordNet and Princeton WordNet |
| `frequency.csv`, `releases/frequency-*` | FrequencyWords |
| `dbnary-zh-*`, `releases/dbnary-zh-*` | DBnary |
| `omw-zh-*`, `releases/omw-zh-*` | Chinese Open Wordnet |
| `cedict-zh-*`, `releases/cedict-zh-*` | CC-CEDICT |

`minimal-source.jsonl` is a project test record. The manifest under
`releases/` points to the repository's test archives and files. The original
upstream snapshot has yet to be recorded for some older fixtures.
