"""Finnish orthographic syllabification and Kaikki hyphenation extraction."""

from __future__ import annotations

import re

_FINNISH_VOWELS = frozenset("aeiouyäö")
_FINNISH_DIPHTHONGS = frozenset(
    {
        "ai",
        "ei",
        "oi",
        "ui",
        "yi",
        "äi",
        "öi",
        "au",
        "eu",
        "iu",
        "ou",
        "ey",
        "iy",
        "äy",
        "öy",
        "ie",
        "uo",
        "yö",
    }
)
_SYLLABIFIABLE_WORD_RE = re.compile(r"^[A-Za-zÅÄÖåäö]+(?:-[A-Za-zÅÄÖåäö]+)*$")


def _syllabify_segment(segment: str) -> str:
    if len(segment) <= 2:
        return segment
    syllables: list[list[str]] = []
    current: list[str] = []
    vowel_cluster = ""

    for idx, ch in enumerate(segment):
        low = ch.lower()
        is_vowel = low in _FINNISH_VOWELS
        next_is_vowel = (
            idx + 1 < len(segment) and segment[idx + 1].lower() in _FINNISH_VOWELS
        )
        if not is_vowel:
            if vowel_cluster and next_is_vowel:
                syllables.append(current)
                current = [ch]
                vowel_cluster = ""
            else:
                current.append(ch)
                if vowel_cluster:
                    # Consonant codas close the vowel cluster; any later vowel starts a new syllable.
                    vowel_cluster = "__closed__"
        else:
            if not vowel_cluster:
                current.append(ch)
                vowel_cluster = low
            elif (
                len(vowel_cluster) == 1
                and vowel_cluster != "__closed__"
                and (vowel_cluster == low or (vowel_cluster + low) in _FINNISH_DIPHTHONGS)
            ):
                current.append(ch)
                vowel_cluster = vowel_cluster + low
            else:
                syllables.append(current)
                current = [ch]
                vowel_cluster = low

    if current:
        syllables.append(current)
    return "·".join("".join(part) for part in syllables if part)


def syllabify_finnish_word(word: str) -> str | None:
    cleaned = word.strip()
    if not cleaned or not _SYLLABIFIABLE_WORD_RE.fullmatch(cleaned):
        return None
    parts = cleaned.split("-")
    return "-".join(_syllabify_segment(part) for part in parts)


def _extract_kaikki_syllabification(entry: dict) -> str | None:
    existing = entry.get("syllabification")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()
    hyphenations = entry.get("hyphenations")
    if isinstance(hyphenations, list):
        for item in hyphenations:
            if isinstance(item, dict) and isinstance(item.get("parts"), list):
                parts = [str(p).strip() for p in item["parts"] if isinstance(p, str) and p.strip()]
                if parts:
                    return "·".join(parts)
    sounds = entry.get("sounds")
    if isinstance(sounds, list):
        for sound in sounds:
            if not isinstance(sound, dict):
                continue
            hyph = sound.get("hyphenation")
            if isinstance(hyph, str) and hyph.strip():
                return hyph.strip()
            if isinstance(hyph, list):
                parts = [str(p).strip() for p in hyph if isinstance(p, str) and p.strip()]
                if parts:
                    return "·".join(parts)
    word = entry.get("word")
    return syllabify_finnish_word(word) if isinstance(word, str) else None
