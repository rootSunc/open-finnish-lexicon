"""Kaikki paradigm table parsing, possessive filtering, and form normalization."""

from __future__ import annotations

import re
import unicodedata

from open_finnish_lexicon.normalize.lexemes import normalize_part_of_speech

_KAIKKI_FORM_CASES = {
    "nominative": "nominative",
    "accusative": "accusative",
    "genitive": "genitive",
    "partitive": "partitive",
    "inessive": "inessive",
    "elative": "elative",
    "illative": "illative",
    "adessive": "adessive",
    "ablative": "ablative",
    "allative": "allative",
    "essive": "essive",
    "translative": "translative",
    "abessive": "abessive",
    "comitative": "comitative",
    "instructive": "instructive",
    # Wiktionary uses these productive/semantic cases for Finnish pronouns,
    # numerals, and adverbs as well as the canonical fifteen cases above.
    "lative": "lative",
    "prolative": "prolative",
    "distributive": "distributive",
    "superessive": "superessive",
    "delative": "delative",
    "sublative": "sublative",
    "situative": "situative",
    "multiplicative": "multiplicative",
    "causative": "causative",
    "oppositive": "oppositive",
    "separative": "separative",
    "locative": "locative",
    "temporal": "temporal",
}

# The Wiktionary ``fi-decl-pron`` template renders all six Finnish personal
# pronouns in one table. Kaikki consequently repeats the complete
# minä–sinä–hän–me–te–he paradigm under each of those entries. Keep only the
# surface family belonging to the entry being projected; the other five
# families are valid Finnish, but they are not inflections of this lemma.
_PERSONAL_PRONOUN_SURFACES = {
    "minä": frozenset(
        {
            "minä", "minun", "minua", "minut", "minussa", "minusta",
            "minuun", "minulla", "minulta", "minulle", "minuna", "minuksi", "minutta",
        }
    ),
    "sinä": frozenset(
        {
            "sinä", "sinun", "sinua", "sinut", "sinussa", "sinusta",
            "sinuun", "sinulla", "sinulta", "sinulle", "sinuna", "sinuksi", "sinutta",
        }
    ),
    "hän": frozenset(
        {
            "hän", "hänen", "häntä", "hänet", "hänessä", "hänestä",
            "häneen", "hänellä", "häneltä", "hänelle", "hänenä", "häneksi", "hänettä",
        }
    ),
    "me": frozenset(
        {
            "me", "meidän", "meitä", "meidät", "meissä", "meistä",
            "meihin", "meillä", "meiltä", "meille", "meinä", "meiksi", "meittä",
        }
    ),
    "te": frozenset(
        {
            "te", "teidän", "teitä", "teidät", "teissä", "teistä",
            "teihin", "teillä", "teiltä", "teille", "teinä", "teiksi", "teittä",
        }
    ),
    "he": frozenset(
        {
            "he", "heidän", "heitä", "heidät", "heissä", "heistä",
            "heihin", "heillä", "heiltä", "heille", "heinä", "heiksi", "heittä",
        }
    ),
}


def _belongs_to_personal_pronoun_entry(entry: dict, surface: str) -> bool:
    word = str(entry.get("word", "")).strip().casefold()
    allowed = _PERSONAL_PRONOUN_SURFACES.get(word)
    if allowed is None:
        return True
    return surface.strip().casefold() in allowed


_KAIKKI_THIRD_INFINITIVE_CASES = frozenset(
    {"inessive", "elative", "illative", "adessive", "abessive", "instructive"}
)
_KAIKKI_FORM_MORPHOLOGY_TAGS = frozenset(
    {
        *_KAIKKI_FORM_CASES,
        "singular",
        "plural",
        "first-person",
        "second-person",
        "third-person",
        "fourth-person",
        "indicative",
        "conditional",
        "imperative",
        "potential",
        "present",
        "past",
        "perfect",
        "pluperfect",
        "active",
        "passive",
        "infinitive",
        "infinitive-i",
        "infinitive-ii",
        "infinitive-iii",
        "infinitive-iv",
        "infinitive-v",
        "infinitive-i-long",
        "participle",
        "agent",
        "noun-from-verb",
        "positive",
        "comparative",
        "superlative",
    }
)
_KAIKKI_FORM_REJECT_TAGS = frozenset(
    {
        "table-tags",
        "inflection-template",
        "class",
        "rare",
        "archaic",
        "obsolete",
        "nonstandard",
        "negative",
        "possessive",
        "error-unrecognized-form",
    }
)
_POSSESSIVE_CORE_SUFFIXES = ("ni", "si", "mme", "nne", "nsa", "nsä")
_UNLABELLED_POSSESSIVE_SUFFIXES = tuple(
    dict.fromkeys(
        (
            *_POSSESSIVE_CORE_SUFFIXES,
            "an",
            "än",
            "aan",
            "ään",
            "een",
            *(
                vowel + suffix
                for vowel in "aeiouyäö"
                for suffix in _POSSESSIVE_CORE_SUFFIXES
            ),
        )
    )
)
# Wiktionary uses several Unicode hyphen and apostrophe characters inside
# legitimate Finnish loanwords and compounds (for example ``show’t`` and
# ``malli–näkymä–käsittelijä``). Keep them when they join two letter runs, but
# still reject leading/trailing stem markers such as ``-y`` and ``ala-``.
_SINGLE_FINNISH_FORM_RE = re.compile(
    r"[^\W\d_]+(?:[-'’ʼ‐‑‒–—][^\W\d_]+)*",
    re.UNICODE,
)


def _kaikki_form_features(tags: set[str]) -> dict[str, str]:
    features: dict[str, str] = {}
    for tag, case_name in _KAIKKI_FORM_CASES.items():
        if tag in tags:
            features["case"] = case_name
            break
    for number in ("singular", "plural"):
        if number in tags:
            features["number"] = number
            break
    third_infinitive = bool(
        "third-person" in tags
        and tags & _KAIKKI_THIRD_INFINITIVE_CASES
        and not tags
        & {"indicative", "conditional", "imperative", "potential", "present", "past"}
    )
    if not third_infinitive:
        for person in ("first-person", "second-person", "third-person"):
            if person in tags:
                features["person"] = {
                    "first-person": "1",
                    "second-person": "2",
                    "third-person": "3",
                }[person]
                break
    for mood in ("indicative", "conditional", "imperative", "potential"):
        if mood in tags:
            features["mood"] = mood
            break
    for tense in ("present", "past", "perfect", "pluperfect"):
        if tense in tags:
            features["tense"] = tense
            break
    if "passive" in tags:
        features["voice"] = "passive"
    elif "active" in tags:
        features["voice"] = "active"

    if "infinitive-i-long" in tags:
        features["participle"] = "past participle"
    elif "agent" in tags:
        features["participle"] = "agent participle"
    elif "participle" in tags:
        voice = "passive" if "passive" in tags else "active" if "active" in tags else ""
        if "infinitive-i-long" in tags or "past" in tags:
            tense = "past"
        else:
            tense = "present" if "present" in tags else ""
        features["participle"] = " ".join(
            value for value in (voice, tense, "participle") if value
        )
    elif "infinitive-ii" in tags:
        features["infinitive"] = "second"
    elif "infinitive-iii" in tags:
        features["infinitive"] = "third"
    elif "infinitive-iv" in tags:
        features["infinitive"] = "fourth"
    elif "infinitive-v" in tags:
        features["infinitive"] = "fifth"
    elif "noun-from-verb" in tags and "fourth-person" in tags:
        # Kaikki/Wiktionary labels Finnish -minen verbal nouns as
        # ``fourth-person`` and, due to the conjugation-table source, also
        # carries a ``negative`` tag.  The latter is not a negative surface
        # here: ``juokseminen`` is the fourth infinitive of ``juosta``.
        features["infinitive"] = "fourth"
    elif "infinitive" in tags or "infinitive-i" in tags:
        features["infinitive"] = "first"
    if third_infinitive and "infinitive" not in features:
        # Kaikki's Finnish conjugation tables encode the case-bearing forms
        # of the third infinitive as ``third-person`` rather than adding an
        # explicit ``infinitive-iii`` tag.
        features["infinitive"] = "third"

    for degree in ("positive", "comparative", "superlative"):
        if degree in tags:
            features["degree"] = degree
            break

    return features


def _kaikki_primary_form_items(entry: dict) -> list[object]:
    """Select the first complete declension block when Wiktionary repeats it.

    A few entries contain multiple unlabelled templates for competing
    paradigms (for example ``nälkä`` has both ``k~∅`` and ``k~j`` blocks).
    The raw JSON does not attach a template id to each cell, but each block
    starts with a ``table-tags`` marker. Prefer the first block that contains
    the lemma's nominative singular and leave the raw document untouched.
    """

    raw_forms = entry.get("forms")
    lemma = entry.get("word")
    if not isinstance(raw_forms, list) or not isinstance(lemma, str):
        return []

    block_starts: list[int] = []
    for index, item in enumerate(raw_forms):
        if not isinstance(item, dict):
            continue
        tags = item.get("tags")
        if isinstance(tags, list) and "table-tags" in {
            str(tag).strip().casefold() for tag in tags if isinstance(tag, str)
        }:
            block_starts.append(index)
    if not block_starts:
        return raw_forms

    for block_index, start in enumerate(block_starts):
        end = (
            block_starts[block_index + 1]
            if block_index + 1 < len(block_starts)
            else len(raw_forms)
        )
        block = raw_forms[start:end]
        for item in block:
            raw_item_form = item.get("form") if isinstance(item, dict) else None
            if not isinstance(raw_item_form, str) or _fold_apostrophes(
                raw_item_form.strip()
            ) != _fold_apostrophes(lemma):
                continue
            tags = {
                str(tag).strip().casefold()
                for tag in item.get("tags", [])
                if isinstance(tag, str)
            }
            if (
                {"nominative", "singular"}.issubset(tags)
                or {"infinitive", "infinitive-i"}.issubset(tags)
            ):
                return block
    return raw_forms


def _fold_apostrophes(value: str) -> str:
    return (
        unicodedata.normalize("NFC", value)
        .replace("’", "'")
        .replace("ʼ", "'")
    )


def _kaikki_form_candidates(entry: dict) -> list[tuple[str, set[str]]]:
    """Return source morphology cells after the basic shape filters."""

    raw_forms = _kaikki_primary_form_items(entry)
    if not isinstance(raw_forms, list):
        return []

    candidates: list[tuple[str, set[str]]] = []
    for item in raw_forms:
        if not isinstance(item, dict):
            continue
        surface = item.get("form")
        if not isinstance(surface, str):
            continue
        surface = unicodedata.normalize("NFC", surface.strip())
        if not surface or not _SINGLE_FINNISH_FORM_RE.fullmatch(surface):
            continue
        raw_tags = item.get("tags")
        if not isinstance(raw_tags, list):
            continue
        tags = {
            str(tag).strip().casefold()
            for tag in raw_tags
            if isinstance(tag, str) and tag.strip()
        }
        if not tags:
            continue
        reject_tags = tags & _KAIKKI_FORM_REJECT_TAGS
        if reject_tags == {"negative"} and {
            "fourth-person",
            "noun-from-verb",
        }.issubset(tags):
            # Kaikki marks the fourth infinitive with ``negative`` in this
            # table, but the surface is still a valid positive form.
            reject_tags = set()
        if reject_tags:
            continue
        source = item.get("source")
        degree_only_form = source is None and tags <= {"comparative", "superlative"}
        if source not in {"declension", "conjugation", "inflection"} and not degree_only_form:
            continue
        if not tags & _KAIKKI_FORM_MORPHOLOGY_TAGS:
            continue
        candidates.append((surface, tags))
    return candidates


def _kaikki_source_class(raw_forms: list[object]) -> str | None:
    """Return the declension/conjugation class declared by the table.

    Kaikki puts class labels next to the inflection-template marker instead
    of repeating them on every cell. Preserve the compact, human-readable
    labels so downstream validation can distinguish explicit source rules
    such as ``no gradation`` from the productive default.
    """

    classes: list[str] = []
    seen: set[str] = set()
    for item in raw_forms:
        if not isinstance(item, dict):
            continue
        tags = item.get("tags")
        if not isinstance(tags, list) or "class" not in tags:
            continue
        value = item.get("form")
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value.casefold() == "class":
            continue
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            classes.append(value)
    return " | ".join(classes) or None


def _kaikki_source_possessive(entry: dict) -> str | None:
    """Return a possessive parameter declared by a Wiktionary template.

    A few entries such as ``hänenlaisensa`` are generated from a
    ``fi-decl-nainen`` template with ``poss=3s``. The expanded cells do not
    repeat a ``possessive`` tag, so keep this source fact on each compact form
    instead of mistaking the generated paradigm for an ordinary ``-nen``
    lemma.
    """

    templates = entry.get("inflection_templates")
    if not isinstance(templates, list):
        return None
    for template in templates:
        if not isinstance(template, dict):
            continue
        args = template.get("args")
        if not isinstance(args, dict):
            continue
        possessive = args.get("poss")
        if isinstance(possessive, str) and possessive.strip():
            return possessive.strip()
    return None


def _kaikki_source_variant(entry: dict) -> str | None:
    """Identify entries with an explicit alternate first infinitive.

    A small set of Finnish slang/variant entries is headed by a present-like
    ``-aa/-ää`` form while the same Wiktionary conjugation table also gives a
    ``-ta/-tä`` first infinitive (for example ``bamlaa`` / ``bamlata``).
    These are source-declared variants, not ordinary lemma paradigms. Keep
    the distinction in compact form metadata so morphology validation does
    not turn the explicit table into a false mismatch.
    """

    if normalize_part_of_speech(str(entry.get("pos", ""))) != "verb":
        return None
    word = entry.get("word")
    if not isinstance(word, str):
        return None
    word = word.strip()
    if not _SINGLE_FINNISH_FORM_RE.fullmatch(word) or word.casefold()[-2:] not in {
        "aa",
        "ää",
    }:
        return None
    raw_forms = entry.get("forms")
    if not isinstance(raw_forms, list):
        return None
    first_infinitives: set[str] = set()
    for item in raw_forms:
        if not isinstance(item, dict) or not isinstance(item.get("form"), str):
            continue
        tags = {
            str(tag).strip().casefold()
            for tag in item.get("tags", [])
            if isinstance(tag, str) and tag.strip()
        }
        if {"infinitive", "infinitive-i"}.issubset(tags):
            first_infinitives.add(item["form"].strip())
    word_folded = word.casefold()
    first_infinitive_folds = {value.casefold() for value in first_infinitives}
    if word_folded not in first_infinitive_folds:
        usable_first_infinitives = {
            value
            for value in first_infinitives
            if _SINGLE_FINNISH_FORM_RE.fullmatch(value)
        }
        # A few Wiktionary entries are intentionally headed by a defective
        # present-like form (for example ``kutiaa``) while their manual table
        # declares a different -ta/-tä first infinitive (``kutista``). Keep
        # that source fact instead of treating the explicit source form as a
        # rule mismatch. Require one unambiguous, Finnish-looking infinitive
        # so a missing/placeholder cell cannot bless arbitrary data.
        if len(usable_first_infinitives) == 1 and next(
            iter(usable_first_infinitives)
        ).casefold()[-2:] in {"ta", "tä"}:
            return "defective-first-infinitive"
        return None
    if any(
        value.casefold() != word_folded
        and value.casefold()[-2:] in {"ta", "tä"}
        and _SINGLE_FINNISH_FORM_RE.fullmatch(value)
        for value in first_infinitives
    ):
        return "alternate-first-infinitive"
    return None


def _unlabelled_possessive_forms(
    candidates: list[tuple[str, set[str]]],
    *,
    lemma: str | None = None,
) -> set[tuple[frozenset[str], str]]:
    """Find possessive families that Kaikki omitted from its tags.

    Some Finnish declension tables repeat the same case cell with ``-ni``,
    ``-si``, ``-mme``, ``-nne`` and ``-nsa`` endings, but omit the
    ``possessive`` tag.  The suffix can be attached after a case vowel or
    replace a final ``n``/``i`` in illative/translative cells.  Grouping
    several distinct suffix-bearing siblings by their stripped stem handles
    all of these table variants without needing a complete declension model.
    """

    # The Wiktionary table repeats one possessive cell under both singular
    # and plural (and under accusative+nominative combinations).  Number is
    # therefore not a reliable family key for this cleanup.
    lemma_folded = _fold_apostrophes(lemma) if isinstance(lemma, str) and lemma else None
    surfaces_by_family: dict[frozenset[str], set[str]] = {}
    surfaces_by_stem: dict[tuple[frozenset[str], str], set[str]] = {}
    for surface, tags in candidates:
        family_key = frozenset(tags - {"singular", "plural"})
        surfaces_by_family.setdefault(family_key, set()).add(_fold_apostrophes(surface))
        for suffix in _UNLABELLED_POSSESSIVE_SUFFIXES:
            if not surface.endswith(suffix) or len(surface) <= len(suffix) + 1:
                continue
            stem = surface[: -len(suffix)]
            stem_folded = _fold_apostrophes(stem)
            # A base illative such as ``herraan`` also ends in ``-aan``. It
            # is not part of a possessive family when the stripped stem is
            # the lemma itself; possessive case forms have an additional
            # case stem (``herrassaan``, ``herrallaan`` ...).
            if suffix in {"aan", "ään"} and lemma_folded and stem_folded == lemma_folded:
                continue
            # The ordinary Finnish comitative plural often ends in ``-een``
            # (``herroineen``), so that ending is ambiguous with the
            # possessive allomorph in other case cells.
            if suffix == "een" and "comitative" in family_key:
                continue
            surfaces_by_stem.setdefault((family_key, stem_folded), set()).add(surface)

    possessive_forms = {
        (family_key, surface)
        for (family_key, _stem), surfaces in surfaces_by_stem.items()
        if len(surfaces) >= 3
        for surface in surfaces
    }
    # A table may expose only the 3rd-person possessive for a cell.  The
    # ``-aan``/``-ään`` allomorph is still safe to remove when its stripped
    # case form is explicitly present in the same cell (``juttua`` /
    # ``juttuaan``), while a canonical illative such as ``herraan`` has no
    # same-cell ``herra`` sibling and is retained.
    for surface, tags in candidates:
        family_key = frozenset(tags - {"singular", "plural"})
        for suffix in ("an", "än", "aan", "ään"):
            if not surface.endswith(suffix):
                continue
            stem = surface[: -len(suffix)]
            if _fold_apostrophes(stem) in surfaces_by_family.get(family_key, set()):
                possessive_forms.add((family_key, surface))
    return possessive_forms


def _clean_kaikki_forms(entry: dict) -> list[dict]:
    """Keep single-token, non-possessive Wiktionary morphology cells.

    Kaikki includes table labels, conjugation metadata, negative auxiliary
    phrases, possessive tables, and source-less degree forms in the same
    ``forms`` array.  Only cells with a usable Finnish surface and explicit
    morphology are copied into the lexical model; the raw source document
    still keeps the original array for auditability.
    """

    forms: list[dict] = []
    raw_forms = _kaikki_primary_form_items(entry)
    candidates = _kaikki_form_candidates(entry)
    source_class = _kaikki_source_class(raw_forms)
    source_possessive = _kaikki_source_possessive(entry)
    source_variant = _kaikki_source_variant(entry)
    possessive_forms = _unlabelled_possessive_forms(candidates, lemma=entry.get("word"))
    for surface, tags in candidates:
        if entry.get("pos") == "pron" and not _belongs_to_personal_pronoun_entry(
            entry, surface
        ):
            continue
        family_key = frozenset(tags - {"singular", "plural"})
        if (family_key, surface) in possessive_forms:
            continue
        features = _kaikki_form_features(tags)
        if not features:
            continue
        if source_class is not None:
            features["source_class"] = source_class
        if source_possessive is not None:
            features["source_possessive"] = source_possessive
        if source_variant is not None:
            features["source_variant"] = source_variant
        forms.append({"form": surface, "features": features, "tags": sorted(tags)})
    return forms
