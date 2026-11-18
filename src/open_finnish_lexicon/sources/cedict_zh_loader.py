"""Reader and English-pivot indexer for MDBG CC-CEDICT (CC-BY-SA-4.0)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
import gzip
from pathlib import Path
import re

from open_finnish_lexicon.zh_script import normalize_and_validate_zh_gloss

_CEDICT_LINE_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]+)\]\s+/(.+)/\s*$")
_COMMON_CJK_RE = re.compile(r"^[\u4e00-\u9fff·・]+$")
_LEADING_TAGS_RE = re.compile(r"^(?:\([^)]{1,32}\)\s*)+")
_TRAILING_NOTE_RE = re.compile(
    r"\s*(?:\((?:Taiwan|also|old)\s+pr\.[^)]*\)|CL:[^/;]+)\s*$",
    re.IGNORECASE,
)
_CLEAN_EN_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9' -]{0,47}$")

_REJECT_DEF_SUBSTRINGS = (
    "(archaic)",
    "(old)",
    "(literary)",
    "(classical)",
    "(dialect)",
    "(topolect)",
    "(slang)",
    "(vulgar)",
    "(derog.)",
    "(offensive)",
    "(tw)",
    "kangxi radical",
    "japanese variant",
    "erhua variant",
    "old variant of",
    "variant of ",
)

_REJECT_DEF_PREFIXES = (
    "surname ",
    "variant of ",
    "old variant of ",
    "also written ",
    "see ",
    "see also ",
    "abbr. ",
    "abbr.",
    "short for ",
    "cl:",
    "classifier ",
    "measure word",
    "radical ",
    "used in ",
    "bound form",
    "a kind of ",
    "a type of ",
    "any of ",
    "one who ",
    "person who ",
    "pertaining to ",
    "relating to ",
)

# Classical, literary, or regional-colloquial words in CC-CEDICT that lack an
# explicit ``(literary)`` / ``(dialect)`` tag and would otherwise outrank
# everyday Standard Mandarin vocabulary on short function-word keys.
_DEMOTED_LITERARY_OR_REGIONAL_WORDS = frozenset(
    {
        "倘如",
        "倘或",
        "倘若",
        "业已",
        "业经",
        "阿谁",
        "何人",
        "何所",
        "怎生",
        "今次",
        "有够",
        "亦或",
        "仿似",
        "事事",
        "凡事",
        "时辰",
        "时节",
        "大部",
        "此际",
        "本处",
        "此地",
    }
)
_CLASSICAL_SINGLE_CHARS = frozenset(
    "叵焉彼乃尔汝吾予兮哉矣欤盍曷奚孰胡罔靡弗勿毋莫斯兹厥什"
)


def _open_cedict(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open(encoding="utf-8")


def _extract_clean_defs(raw_defs: str, *, is_proper_pinyin: bool) -> list[tuple[str, bool, int, bool]]:
    """Return ``(en_key, is_verb, def_rank, has_qualifier)`` tuples from ``/d1/d2/``."""

    results: list[tuple[str, bool, int, bool]] = []
    parts = [p.strip() for p in raw_defs.split("/") if p.strip()]
    for rank, part in enumerate(parts):
        low_full = part.lower()
        if any(bad in low_full for bad in _REJECT_DEF_SUBSTRINGS):
            continue
        cleaned_part = _TRAILING_NOTE_RE.sub("", part).strip()
        if not cleaned_part:
            continue
        stripped_tags = _LEADING_TAGS_RE.sub("", cleaned_part).strip()
        has_qualifier = stripped_tags != cleaned_part
        if not stripped_tags:
            continue

        for sub in stripped_tags.split(";"):
            clause = " ".join(sub.strip().split())
            if not clause:
                continue
            low_clause = clause.lower()
            if low_clause.startswith(_REJECT_DEF_PREFIXES):
                continue
            if "(" in clause or ")" in clause or "[" in clause or "]" in clause:
                continue

            is_verb = low_clause.startswith("to ") and len(low_clause) > 4
            if is_proper_pinyin:
                # Proper-pinyin entries (surnames, dynasties, place names) may only
                # match capitalized proper-noun English keys, never common words.
                if is_verb or not clause[0].isupper():
                    continue
                key = re.sub(
                    r",\s*(?:(?:the\s+)?capital\b|(?:a\s+)?(?:city|port|province|state|island|river)\b).*$",
                    "",
                    clause,
                    flags=re.IGNORECASE,
                ).strip()
            else:
                if is_verb:
                    verb_body = low_clause[3:].strip()
                    if not verb_body:
                        continue
                    key = f"to {verb_body}"
                else:
                    key = low_clause
                    for art in ("a ", "an "):
                        if key.startswith(art) and " " in key[len(art) :]:
                            key = key[len(art) :].strip()

            if not _CLEAN_EN_KEY_RE.match(key):
                continue
            word_count = len(key.split())
            if word_count > 5:
                continue
            results.append((key, is_verb, rank, has_qualifier))
    return results


def read_cedict_zh_entries(input_path: Path) -> Iterable[dict[str, object]]:
    """Aggregate CC-CEDICT into ranked Simplified Chinese glosses per English key."""

    # Map (en_key, is_verb) -> dict[zh_simp, best_sort_tuple]
    grouped: dict[tuple[str, bool], dict[str, tuple[int, int, int, int, int, str]]] = defaultdict(
        dict
    )

    with _open_cedict(input_path) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            m = _CEDICT_LINE_RE.match(line)
            if not m:
                continue
            _trad, raw_simp, pinyin, raw_defs = m.groups()
            if len(raw_simp) > 8:
                continue
            zh = normalize_and_validate_zh_gloss(raw_simp)
            if zh is None or not _COMMON_CJK_RE.match(zh):
                continue

            is_proper_pinyin = bool(pinyin and pinyin[0].isupper())
            extracted = _extract_clean_defs(raw_defs, is_proper_pinyin=is_proper_pinyin)
            if not extracted:
                continue

            is_literary_word = (
                zh in _DEMOTED_LITERARY_OR_REGIONAL_WORDS
                or (len(zh) == 1 and zh in _CLASSICAL_SINGLE_CHARS)
            )

            for en_key, is_verb, def_rank, has_qualifier in extracted:
                sort_key = (
                    1 if is_literary_word else 0,
                    0 if def_rank == 0 else (1 if def_rank == 1 else 2),
                    0 if not has_qualifier else 1,
                    0 if 2 <= len(zh) <= 4 else (1 if len(zh) == 1 else 2),
                    len(zh),
                    zh,
                )
                bucket = grouped[(en_key, is_verb)]
                prev = bucket.get(zh)
                if prev is None or sort_key < prev:
                    bucket[zh] = sort_key

    for (en_key, is_verb) in sorted(grouped):
        bucket = grouped[(en_key, is_verb)]
        ranked_items = sorted(bucket.items(), key=lambda kv: kv[1])
        top_words = [w for w, _sk in ranked_items[:3] if _sk[0] == 0] or [
            w for w, _sk in ranked_items[:2]
        ]
        if not top_words:
            continue
        best_sk = ranked_items[0][1]
        primary_exact = best_sk[0] == 0 and best_sk[1] == 0 and best_sk[2] == 0
        # Keep the top 2 closest non-literary equivalents for the rendered gloss string.
        rendered_words = [ranked_items[0][0]]
        if (
            len(ranked_items) > 1
            and ranked_items[1][1][0] == 0
            and ranked_items[1][1][:3] == best_sk[:3]
        ):
            rendered_words.append(ranked_items[1][0])
        kind_tag = "v" if is_verb else "n"
        yield {
            "external_id": f"cedict_zh:{kind_tag}:{en_key}",
            "en_key": en_key,
            "is_verb": is_verb,
            "gloss_zh": "；".join(rendered_words),
            "candidates_zh": top_words,
            "primary_exact": primary_exact,
        }
