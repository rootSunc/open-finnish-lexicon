"""Project CC-CEDICT Chinese candidates onto Finnish ``lexicon.lexeme_sense``."""

from __future__ import annotations

import json
from pathlib import Path
import re

import psycopg

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.sources.warehouse import source_file_id_for_path

_PAREN_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_CLEAN_CLAUSE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9' -]{0,47}$")

_META_GLOSS_PREFIXES = (
    "alternative form of ",
    "alternative spelling of ",
    "misspelling of ",
    "archaic form of ",
    "obsolete form of ",
    "dated form of ",
    "rare form of ",
    "eye dialect ",
    "abbreviation of ",
    "initialism of ",
    "acronym of ",
    "inflection of ",
    "plural of ",
    "genitive of ",
    "partitive of ",
    "synonym of ",
    "short for ",
    "diminutive of ",
    "female given name",
    "male given name",
    "a surname",
    "surname",
    "used together with ",
)

# High-polysemy single English words where an unguided 1-word pivot risks
# picking the wrong homograph unless corroborated by a second synonym or OMW.
_AMBIGUOUS_SINGLE_ENGLISH_WORDS = frozenset(
    {
        "about",
        "account",
        "act",
        "air",
        "back",
        "band",
        "bank",
        "bar",
        "bark",
        "base",
        "bat",
        "bear",
        "beat",
        "bill",
        "block",
        "board",
        "bond",
        "bow",
        "box",
        "break",
        "cabinet",
        "call",
        "can",
        "capital",
        "card",
        "case",
        "cast",
        "cell",
        "charge",
        "check",
        "chest",
        "class",
        "clear",
        "club",
        "coat",
        "code",
        "cold",
        "company",
        "compound",
        "cool",
        "count",
        "court",
        "cover",
        " crane",
        "crane",
        "cross",
        "current",
        "cut",
        "date",
        "deal",
        "degree",
        "draft",
        "draw",
        "drive",
        "drop",
        "even",
        "express",
        "face",
        "fair",
        "fall",
        "fan",
        "fast",
        "field",
        "figure",
        "file",
        "fine",
        "firm",
        "flat",
        "flight",
        "fly",
        "fold",
        "foot",
        "force",
        "form",
        "frame",
        "free",
        "game",
        "grade",
        "grave",
        "ground",
        "hand",
        "hard",
        "head",
        "hold",
        "host",
        "iron",
        "issue",
        "jam",
        "just",
        "key",
        "kind",
        "land",
        "last",
        "lead",
        "leave",
        "leaves",
        "left",
        "letter",
        "lie",
        "lift",
        "light",
        "like",
        "line",
        "link",
        "list",
        "live",
        "load",
        "lock",
        "log",
        "long",
        "lot",
        "major",
        "mark",
        "mass",
        "match",
        "matter",
        "may",
        "mean",
        "measure",
        "medium",
        "might",
        "mine",
        "minor",
        "mint",
        "miss",
        "model",
        "mole",
        "mount",
        "move",
        "nail",
        "net",
        "note",
        "novel",
        "object",
        "odd",
        "off",
        "open",
        "order",
        "organ",
        "over",
        "pack",
        "page",
        "palm",
        "park",
        "part",
        "party",
        "pass",
        "patch",
        "patient",
        "pen",
        "period",
        "pick",
        "piece",
        "pipe",
        "pitch",
        "place",
        "plain",
        "plane",
        "plant",
        "plate",
        "play",
        "plot",
        "point",
        "pole",
        "pool",
        "port",
        "post",
        "pound",
        "power",
        "present",
        "press",
        "prime",
        "project",
        "pupil",
        "quarter",
        "race",
        "rack",
        "range",
        "rank",
        "rate",
        "raw",
        "record",
        "rest",
        "return",
        "right",
        "ring",
        "rise",
        "rock",
        "roll",
        "root",
        "rose",
        "round",
        "row",
        "rule",
        "run",
        "safe",
        "sail",
        "saw",
        "scale",
        "school",
        "score",
        "screen",
        "seal",
        "season",
        "second",
        "sense",
        "sentence",
        "serve",
        "set",
        "settled",
        "shade",
        "shaft",
        "shape",
        "share",
        "sharp",
        "sheet",
        "shift",
        "shoot",
        "shop",
        "short",
        "shot",
        "show",
        "side",
        "sign",
        "single",
        "sink",
        "slip",
        "sole",
        "sound",
        "space",
        "spare",
        "spell",
        "spirit",
        "split",
        "spot",
        "spring",
        "square",
        "stable",
        "staff",
        "stage",
        "stake",
        "stall",
        "stamp",
        "stand",
        "star",
        "state",
        "step",
        "stern",
        "stick",
        "still",
        "stock",
        "store",
        "story",
        "strain",
        "strand",
        "stream",
        "strike",
        "string",
        "strip",
        "stroke",
        "study",
        "subject",
        "suit",
        "swallow",
        "switch",
        "table",
        "tack",
        "tag",
        "take",
        "tank",
        "tap",
        "temple",
        "tender",
        "term",
        "tick",
        "tie",
        "till",
        "tip",
        "title",
        "toast",
        "toll",
        "top",
        "touch",
        "track",
        "train",
        "trap",
        "treat",
        "trip",
        "trunk",
        "tube",
        "turn",
        "type",
        "value",
        "vault",
        "vessel",
        "view",
        "volume",
        "wake",
        "watch",
        "wave",
        "way",
        "well",
        "will",
        "wind",
        "wing",
        "work",
        "yard",
    }
)

# High-frequency Finnish closed-class function words where the English Wiktionary
# gloss uses grammatical metalanguage rather than a bare lexical equivalent.
_CLOSED_CLASS_DIRECT_ZH: dict[tuple[str, str], str] = {
    ("olla", "verb"): "是；有；在",
    ("ei", "verb"): "不；没有",
    ("eikä", "verb"): "也不；而且不",
    ("älä", "intj"): "别；不要",
    ("se", "pron"): "它；那",
    ("se", "det"): "那；那个",
    ("tämä", "pron"): "这；这个",
    ("tuo", "pron"): "那；那个",
    ("te", "pron"): "你们；您",
    ("mikä", "pron"): "什么；哪一个",
    ("kuka", "pron"): "谁",
    ("joka", "pron"): "（关系代词）……的",
    ("joka", "det"): "每个；每一",
    ("kaikki", "pron"): "一切；所有人",
    ("että", "conj"): "（引导从句）",
    ("jos", "conj"): "如果；假如",
    ("kun", "conj"): "当……时；因为",
    ("tai", "conj"): "或者；还是",
    ("kuin", "conj"): "比；如同",
    ("kanssa", "postp"): "与……一起；和",
    ("ilman", "prep"): "没有；无",
    ("ilman", "postp"): "没有；无",
    ("kyllä", "adv"): "是的；确实",
    ("hyvin", "adv"): "很；非常；好",
    ("paljon", "adv"): "很多；非常",
    ("vähän", "adv"): "一点儿；稍微",
    ("jo", "adv"): "已经",
    ("missä", "adv"): "在哪里；哪里",
    ("miten", "adv"): "怎么；如何",
    ("voida", "verb"): "能；可以；能够",
    ("täytyä", "verb"): "必须；得",
    ("hyvä", "adj"): "好；好的",
    ("sanoa", "verb"): "说；讲",
    ("tulla", "verb"): "来；成为",
    ("mennä", "verb"): "去；前往",
    ("tehdä", "verb"): "做；制作",
    ("niin", "conj"): "那么；如此",
    ("niin", "adv"): "那么；这么；如此",
    ("nyt", "adv"): "现在",
    ("sitten", "adv"): "然后；后来",
    ("täällä", "adv"): "这里；在这儿",
    ("mitä", "adv"): "越……（越……）；多么",
    ("suomi", "noun"): "芬兰语",
}
_CLOSED_CLASS_OVERRIDES: dict[tuple[str, str], tuple[str, bool]] = {
    ("ei", "verb"): ("not", False),
}


def _extract_lookup_keys(lemma: str, pos: str, gloss_en: str) -> list[tuple[str, bool]]:
    raw = gloss_en.strip()
    if not raw or raw.lower().startswith(_META_GLOSS_PREFIXES):
        return []

    stripped = _PAREN_RE.sub(" ", raw)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if not stripped:
        return []

    is_verb_pos = pos in {"verb", "aux"}
    is_proper_pos = pos in {"propn", "name"}
    raw_clauses = [c.strip(" .:!?'\"“”‘’") for c in re.split(r"[,;/]", stripped)]
    clauses = [c for c in raw_clauses if c and not c.lower().startswith(("etc", "e.g.", "i.e."))]
    if not clauses:
        return []

    keys: list[tuple[str, bool]] = []
    if is_verb_pos:
        saw_to = any(c.lower().startswith("to ") for c in clauses)
        if not saw_to:
            override = _CLOSED_CLASS_OVERRIDES.get((lemma, pos))
            return [override] if override is not None else []
        for clause in clauses[:5]:
            low = clause.lower()
            if low.startswith("to "):
                body = low[3:].strip()
            else:
                body = low
            if not body or len(body.split()) > 4:
                continue
            key = f"to {body}"
            if _CLEAN_CLAUSE_RE.match(key) and (key, True) not in keys:
                keys.append((key, True))
        return keys

    for clause in clauses[:5]:
        variants = [clause] if is_proper_pos else (
            [clause, clause.lower()] if clause[0].isupper() else [clause.lower()]
        )
        for raw_cand in variants:
            candidate = raw_cand
            if not candidate[0].isupper():
                for art in ("a ", "an ", "the "):
                    if candidate.startswith(art) and len(candidate) > len(art) + 1:
                        candidate = candidate[len(art) :].strip()
            if not candidate or len(candidate.split()) > 5:
                continue
            if _CLEAN_CLAUSE_RE.match(candidate) and (candidate, False) not in keys:
                keys.append((candidate, False))
    return keys


def project_cedict_zh_rows(
    input_path: Path,
    *,
    source_file_id: int | None = None,
    connection: psycopg.Connection | None = None,
    **_kwargs: object,
) -> int:
    owns_connection = connection is None
    with connection_scope(connection) as conn:
        resolved_file_id = source_file_id_for_path(
            conn,
            source_name="cedict_zh",
            local_path=input_path,
            source_file_id=source_file_id,
            allow_active=source_file_id is not None,
        )
        conn.execute(
            """
            delete from semantic.sense_alignment_candidate
            where source_document_id in (
                select id from warehouse.source_document where source_file_id = %s
            )
            """,
            (resolved_file_id,),
        )
        conn.execute(
            """
            delete from semantic.zh_gloss_candidate c
            where c.source_document_id in (
                select id from warehouse.source_document where source_file_id = %s
            )
              and not exists (
                  select 1
                  from semantic.zh_gloss_selection sel
                  where sel.zh_gloss_candidate_id = c.id
              )
            """,
            (resolved_file_id,),
        )

        doc_rows = conn.execute(
            """
            select id, payload
            from warehouse.source_document
            where source_file_id = %s
            order by id
            """,
            (resolved_file_id,),
        ).fetchall()

        # (en_key, is_verb) -> (doc_id, gloss_zh, candidates_zh, primary_exact)
        cedict_index: dict[tuple[str, bool], tuple[int, str, list[str], bool]] = {}
        for doc_id, payload in doc_rows:
            if not isinstance(payload, dict):
                continue
            en_key = str(payload.get("en_key", ""))
            is_verb = bool(payload.get("is_verb", False))
            gloss_zh = str(payload.get("gloss_zh", ""))
            cands = [str(w) for w in (payload.get("candidates_zh") or []) if isinstance(w, str)]
            primary_exact = bool(payload.get("primary_exact", False))
            if en_key and gloss_zh and cands:
                cedict_index[(en_key, is_verb)] = (int(doc_id), gloss_zh, cands, primary_exact)

        if not cedict_index:
            if owns_connection:
                conn.commit()
            return resolved_file_id

        sense_rows = conn.execute(
            """
            select l.lemma, l.part_of_speech, ls.id, ls.sense_key, coalesce(ls.gloss_en, '')
            from lexicon.lexeme l
            join lexicon.lexeme_sense ls on ls.lexeme_id = l.id
            where l.is_lemma = true
              and not ('form-of' = any(ls.labels))
              and ls.gloss_en is not null
            order by l.id, ls.sort_order, ls.id
            """
        ).fetchall()

        first_cedict_doc_id = next(iter(cedict_index.values()))[0]
        seen_closed_class: set[tuple[str, str]] = set()
        alignment_rows: list[tuple[str, int, int, str, float, str]] = []
        candidate_rows: list[tuple[int, str, int, str, float, str]] = []

        for lemma_raw, pos_raw, sense_id_raw, sense_key_raw, gloss_en_raw in sense_rows:
            lemma = str(lemma_raw)
            pos = str(pos_raw)
            sense_id = int(sense_id_raw)
            sense_key = str(sense_key_raw)
            gloss_en = str(gloss_en_raw)

            if (lemma, pos) in _CLOSED_CLASS_DIRECT_ZH and (lemma, pos) not in seen_closed_class:
                seen_closed_class.add((lemma, pos))
                direct_zh = _CLOSED_CLASS_DIRECT_ZH[(lemma, pos)]
                meta_json = json.dumps(
                    {
                        "sense_key": sense_key,
                        "lemma": lemma,
                        "part_of_speech": pos,
                        "pivot_en": "closed_class_primary",
                    },
                    ensure_ascii=False,
                )
                alignment_rows.append(
                    ("cedict_zh", first_cedict_doc_id, sense_id, "cedict_closed_class", 0.795, meta_json)
                )
                candidate_rows.append(
                    (sense_id, "cedict_zh", first_cedict_doc_id, direct_zh, 0.795, meta_json)
                )
                continue

            lookup_keys = _extract_lookup_keys(lemma, pos, gloss_en)
            if not lookup_keys:
                continue

            matched = [
                (en_key, is_verb, *cedict_index[(en_key, is_verb)])
                for en_key, is_verb in lookup_keys
                if (en_key, is_verb) in cedict_index
            ]
            if not matched:
                continue

            chosen_doc_id: int | None = None
            chosen_gloss_zh: str | None = None
            chosen_score = 0.0
            chosen_kind = ""
            chosen_key = ""

            # 1. Multi-synonym consensus: >= 2 distinct English synonyms point to the same Chinese word.
            if len(matched) >= 2:
                votes: dict[str, list[tuple[int, str]]] = {}
                for en_key, _is_v, doc_id, _gz, cands, _pex in matched:
                    for zh_word in cands:
                        votes.setdefault(zh_word, []).append((doc_id, en_key))
                consensus = [
                    (zh_word, voters)
                    for zh_word, voters in votes.items()
                    if len({ek for _did, ek in voters}) >= 2
                ]
                if consensus:
                    consensus.sort(key=lambda item: (-len(item[1]), len(item[0])))
                    chosen_gloss_zh = "；".join(w for w, _v in consensus[:2])
                    chosen_doc_id = consensus[0][1][0][0]
                    chosen_key = consensus[0][1][0][1]
                    chosen_score = 0.77
                    chosen_kind = "cedict_synonym_consensus"

            # 2. Primary English gloss phrase or unambiguous headword.
            if chosen_gloss_zh is None:
                first_key, first_is_verb = lookup_keys[0]
                if (first_key, first_is_verb) in cedict_index:
                    doc_id, gloss_zh, _cands, primary_exact = cedict_index[
                        (first_key, first_is_verb)
                    ]
                    bare_word = first_key[3:].strip() if first_is_verb else first_key
                    word_count = len(bare_word.split())
                    if word_count >= 2:
                        chosen_doc_id = doc_id
                        chosen_gloss_zh = gloss_zh
                        chosen_key = first_key
                        chosen_score = 0.76
                        chosen_kind = "cedict_multiword_exact"
                    elif (
                        primary_exact
                        and bare_word.lower() not in _AMBIGUOUS_SINGLE_ENGLISH_WORDS
                    ):
                        chosen_doc_id = doc_id
                        chosen_gloss_zh = gloss_zh
                        chosen_key = first_key
                        chosen_score = 0.74
                        chosen_kind = "cedict_primary_headword"

            if chosen_doc_id is None or chosen_gloss_zh is None:
                continue

            meta_json = json.dumps(
                {
                    "sense_key": sense_key,
                    "lemma": lemma,
                    "part_of_speech": pos,
                    "pivot_en": chosen_key,
                },
                ensure_ascii=False,
            )
            alignment_rows.append(
                ("cedict_zh", chosen_doc_id, sense_id, chosen_kind, chosen_score, meta_json)
            )
            candidate_rows.append(
                (sense_id, "cedict_zh", chosen_doc_id, chosen_gloss_zh, chosen_score, meta_json)
            )

        if candidate_rows:
            conn.execute(
                """
                create temporary table tmp_cedict_alignment (
                    source_name text not null,
                    source_document_id bigint not null,
                    target_sense_id bigint not null,
                    candidate_kind text not null,
                    confidence_score numeric(6, 5) not null,
                    match_payload jsonb not null
                ) on commit drop
                """
            )
            conn.execute(
                """
                create temporary table tmp_cedict_candidate (
                    target_sense_id bigint not null,
                    source_name text not null,
                    source_document_id bigint not null,
                    gloss_zh text not null,
                    confidence_score numeric(6, 5) not null,
                    candidate_payload jsonb not null
                ) on commit drop
                """
            )
            with conn.cursor() as cursor:
                with cursor.copy(
                    """
                    copy tmp_cedict_alignment (
                        source_name, source_document_id, target_sense_id,
                        candidate_kind, confidence_score, match_payload
                    ) from stdin
                    """
                ) as copy:
                    for row in alignment_rows:
                        copy.write_row(row)
                with cursor.copy(
                    """
                    copy tmp_cedict_candidate (
                        target_sense_id, source_name, source_document_id,
                        gloss_zh, confidence_score, candidate_payload
                    ) from stdin
                    """
                ) as copy:
                    for row in candidate_rows:
                        copy.write_row(row)

            conn.execute(
                """
                insert into semantic.sense_alignment_candidate (
                    source_name, source_document_id, target_sense_id,
                    candidate_kind, confidence_score, match_payload
                )
                select distinct on (source_name, source_document_id, target_sense_id, candidate_kind)
                    source_name, source_document_id, target_sense_id,
                    candidate_kind, confidence_score, match_payload
                from tmp_cedict_alignment
                order by source_name, source_document_id, target_sense_id, candidate_kind, confidence_score desc
                on conflict (source_name, source_document_id, target_sense_id, candidate_kind)
                do update set
                    confidence_score = excluded.confidence_score,
                    match_payload = excluded.match_payload
                """
            )
            conn.execute(
                """
                insert into semantic.zh_gloss_candidate (
                    target_sense_id, source_name, source_document_id,
                    gloss_zh, confidence_score, candidate_payload
                )
                select distinct on (target_sense_id, source_name, source_document_id, gloss_zh)
                    target_sense_id, source_name, source_document_id,
                    gloss_zh, confidence_score, candidate_payload
                from tmp_cedict_candidate
                order by target_sense_id, source_name, source_document_id, gloss_zh, confidence_score desc
                on conflict (target_sense_id, source_name, source_document_id, gloss_zh)
                do update set
                    confidence_score = excluded.confidence_score,
                    candidate_payload = excluded.candidate_payload
                """
            )

        if owns_connection:
            conn.commit()
    return resolved_file_id
