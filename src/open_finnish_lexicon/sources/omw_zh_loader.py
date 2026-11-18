"""Reader for Open Multilingual Wordnet (Chinese Open Wordnet ``cmn``) synsets."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
import gzip
from pathlib import Path
import re

from open_finnish_lexicon.zh_script import normalize_and_validate_zh_gloss

_COMMON_CJK_RE = re.compile(r"^[\u4e00-\u9fff·・，、]+$")
_WN_OFFSET_RE = re.compile(r"^(\d{8})-([nvasr])$")
_FIWN_SYNSET_RE = re.compile(r"^(?:fi|en-[0-9.]+):([nvasr])(\d{8})$")

_POS_MAP = {
    "n": ("n", "noun"),
    "v": ("v", "verb"),
    "a": ("a", "adj"),
    "s": ("a", "adj"),
    "r": ("r", "adv"),
}


def normalize_wn30_synset_key(raw: str) -> tuple[str, str] | None:
    """Normalize OMW (``02084071-n``) or FinnWordNet (``fi:n02084071``) synset IDs
    to ``('<8-digit-offset>-<n|v|a|r>', '<lexicon_pos>')``."""

    token = raw.strip()
    if not token:
        return None
    m = _WN_OFFSET_RE.match(token)
    if m:
        offset, raw_pos = m.group(1), m.group(2)
        wn_pos, lex_pos = _POS_MAP[raw_pos]
        return f"{offset}-{wn_pos}", lex_pos
    m2 = _FIWN_SYNSET_RE.match(token)
    if m2:
        raw_pos, offset = m2.group(1), m2.group(2)
        wn_pos, lex_pos = _POS_MAP[raw_pos]
        return f"{offset}-{wn_pos}", lex_pos
    return None


def _open_tab(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open(encoding="utf-8")


def _clean_cmn_lemma(raw: str) -> str | None:
    cleaned = raw.strip().replace("_", "").replace("+", "")
    if not cleaned or len(cleaned) > 12:
        return None
    return normalize_and_validate_zh_gloss(cleaned)


def _rank_cmn_lemmas(lemmas: list[str]) -> list[str]:
    unique = list(dict.fromkeys(lemmas))
    unique.sort(
        key=lambda w: (
            0 if _COMMON_CJK_RE.match(w) else 1,
            0 if 2 <= len(w) <= 4 else (1 if len(w) == 1 else 2),
            len(w),
        )
    )
    # If standard BMP CJK lemmas exist, drop rare Extension-A single-char archaisms.
    common = [w for w in unique if _COMMON_CJK_RE.match(w)]
    chosen = common if common else unique
    return chosen[:3]


def read_omw_zh_entries(input_path: Path) -> Iterable[dict[str, object]]:
    """Parse OMW ``wn-data-cmn.tab`` into one normalized record per synset."""

    cmn_by_synset: dict[str, list[str]] = defaultdict(list)
    pos_by_synset: dict[str, str] = {}
    fin_by_synset: dict[str, list[str]] = defaultdict(list)
    eng_by_synset: dict[str, list[str]] = defaultdict(list)
    def_by_synset: dict[str, str] = {}

    with _open_tab(input_path) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            parsed = normalize_wn30_synset_key(parts[0])
            if parsed is None:
                continue
            synset_id, lex_pos = parsed
            pos_by_synset[synset_id] = lex_pos

            if len(parts) == 2:
                field, value = "cmn:lemma", parts[1]
            else:
                field, value = parts[1].strip().lower(), parts[2].strip()

            if field in {"cmn:lemma", "zho:lemma", "lemma"}:
                zh = _clean_cmn_lemma(value)
                if zh is not None:
                    cmn_by_synset[synset_id].append(zh)
            elif field in {"fin:lemma", "fi:lemma"} and value:
                fin_by_synset[synset_id].append(value)
            elif field in {"eng:lemma", "en:lemma"} and value:
                eng_by_synset[synset_id].append(value.lower())
            elif field in {"eng:def", "def"} and value and synset_id not in def_by_synset:
                def_by_synset[synset_id] = value

    for synset_id in sorted(cmn_by_synset):
        ranked = _rank_cmn_lemmas(cmn_by_synset[synset_id])
        if not ranked:
            continue
        gloss_zh = "；".join(ranked)
        payload: dict[str, object] = {
            "external_id": f"omw_zh:{synset_id}",
            "synset_id": synset_id,
            "part_of_speech": pos_by_synset[synset_id],
            "gloss_zh": gloss_zh,
            "lemmas_zh": ranked,
        }
        if fin_by_synset.get(synset_id):
            payload["fin_lemmas"] = list(dict.fromkeys(fin_by_synset[synset_id]))
        if eng_by_synset.get(synset_id):
            payload["eng_lemmas"] = list(dict.fromkeys(eng_by_synset[synset_id]))
        if def_by_synset.get(synset_id):
            payload["eng_def"] = def_by_synset[synset_id]
        yield payload
