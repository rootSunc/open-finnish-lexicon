# Notices

## Code

The open-finnish-lexicon source code is licensed under the Apache License 2.0
([LICENSE](LICENSE)). The license does not extend to upstream data.

## Upstream data

`ofl` does not redistribute upstream releases; it downloads them when you
run a sync. A database or export you build contains material from these
sources and stays under their terms. Each source's license is also stored in
`warehouse.source_registry.license` and copied into every export.

| Source | Used for | License | Attribution |
| --- | --- | --- | --- |
| [Kaikki.org](https://kaikki.org/) / Wiktextract extraction of the English Wiktionary | Lemmas, parts of speech, senses, glosses, examples, pronunciations, paradigm forms, relations, topics | Wiktionary text: CC BY-SA 4.0 and GFDL (dual-licensed). Wiktextract code: MIT. | "Contains content from Wiktionary (https://www.wiktionary.org/), CC BY-SA 4.0, extracted by Kaikki.org / Wiktextract." |
| Chinese Wiktionary via Kaikki | Chinese gloss candidates | CC BY-SA 4.0 and GFDL | As above, naming zh.wiktionary.org |
| [DBnary](https://kaiko.getalp.org/about-dbnary/) | Chinese gloss candidates | CC BY-SA 3.0 Unported | "DBnary, Gilles Sérasset, CC BY-SA 3.0." |
| [Tatoeba](https://tatoeba.org/) | Example sentences and translations | CC BY 2.0 FR; some sentences CC0 1.0 | "Sentences from Tatoeba (https://tatoeba.org), CC BY 2.0 FR, attributed to sentence contributors in `example.attribution` where provided." |
| [Omorfi](https://github.com/flammie/omorfi) | Inflected forms and analyses (optional extra) | GPL-3.0 | "Omorfi, Tommi A. Pirinen et al., GPL-3.0." The pipeline runs Omorfi's analyser and generator models; it does not redistribute them. |
| [FrequencyWords](https://github.com/hermitdave/FrequencyWords) | Frequency rank | Data: CC BY-SA 4.0. Code: MIT. | "FrequencyWords by Hermit Dave, CC BY-SA 4.0." |
| [FinnWordNet](https://www.kielipankki.fi/corpora/finnwordnet/) | Lexical and semantic relations | Princeton WordNet License AND CC BY 3.0 | "FinnWordNet 2.0, University of Helsinki (FIN-CLARIN / Kielipankki), CC BY 3.0; derived from Princeton WordNet 3.0 (Copyright 2006 by Princeton University)." |

Share-alike sources (CC BY-SA) mean that a database or export that reproduces
their text must be shared under the same license, with attribution.

### Princeton WordNet 3.0 Notice (required for FinnWordNet derivatives)

> WordNet Release 3.0. This software and database is being provided to you,
> the LICENSEE, by Princeton University under the following license. By
> obtaining, using and/or copying this software and database, you agree that
> you have read, understood, and will comply with these terms and conditions:
> Permission to use, copy, modify and distribute this software and database and
> its documentation for any purpose and without fee or royalty is hereby
> granted, provided that you agree to comply with the following copyright
> notice and statements, including the disclaimer, and that the same appear on
> ALL copies of the software, database and documentation, including
> modifications that you make for internal use or for distribution.
>
> WordNet 3.0 Copyright 2006 by Princeton University. All rights reserved.
> THIS SOFTWARE AND DATABASE IS PROVIDED "AS IS" AND PRINCETON UNIVERSITY MAKES
> NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR IMPLIED. BY WAY OF EXAMPLE, BUT
> NOT LIMITATION, PRINCETON UNIVERSITY MAKES NO REPRESENTATIONS OR WARRANTIES
> OF MERCHANTABILITY OR FITNESS FOR ANY PARTICULAR PURPOSE OR THAT THE USE OF
> THE LICENSED SOFTWARE, DATABASE OR DOCUMENTATION WILL NOT INFRINGE ANY THIRD
> PARTY PATENTS, COPYRIGHTS, TRADEMARKS OR OTHER RIGHTS. The name of Princeton
> University or Princeton may not be used in advertising or publicity
> pertaining to distribution of the software and/or database. Title to
> copyright in this software, database and any associated documentation shall
> at all times remain with Princeton University and LICENSEE agrees to preserve
> same.

## Test fixtures

`tests/fixtures/` holds small excerpts of the sources above, used only by the
test suite. Each excerpt keeps its source's license and attribution as listed
in the table.

## Disclaimer

This is not legal advice. Check each source's current terms before you
publish or sell data built with open-finnish-lexicon.
