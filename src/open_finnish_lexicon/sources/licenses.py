"""License of each upstream source, stored in ``warehouse.source_registry``.

Values are SPDX identifiers where one exists. Data built from a source keeps
that source's license; see NOTICE.md for attribution text.
"""

SOURCE_LICENSES: dict[str, str] = {
    # Wiktionary text is dual-licensed; reusers may pick CC BY-SA.
    "kaikki": "CC-BY-SA-4.0 OR GFDL-1.3-or-later",
    "wiktionary_zh": "CC-BY-SA-4.0 OR GFDL-1.3-or-later",
    "dbnary_zh": "CC-BY-SA-3.0",
    "omw_zh": "WordNet",
    "cedict_zh": "CC-BY-SA-4.0",
    # Default Tatoeba license; some sentences are released as CC0-1.0.
    "tatoeba": "CC-BY-2.0-FR",
    "omorfi": "GPL-3.0-only",
    "frequency": "CC-BY-SA-4.0",
    "finnwordnet": "WordNet AND CC-BY-3.0",
}


def source_license(name: str) -> str | None:
    return SOURCE_LICENSES.get(name)
