"""Project OMW Chinese synsets onto Finnish ``lexicon.lexeme_sense`` via FinnWordNet."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re

import psycopg

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.sources.omw_zh_loader import normalize_wn30_synset_key
from open_finnish_lexicon.sources.warehouse import (
    active_source_file_for_name,
    source_file_id_for_path,
)

_PAREN_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_WORD_TOKEN_RE = re.compile(r"[a-z][a-z0-9'-]{1,}")
_EN_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "being",
        "by",
        "especially",
        "etc",
        "for",
        "from",
        "has",
        "have",
        "having",
        "in",
        "into",
        "is",
        "it",
        "its",
        "made",
        "make",
        "of",
        "on",
        "one",
        "ones",
        "or",
        "person",
        "someone",
        "something",
        "state",
        "such",
        "that",
        "the",
        "their",
        "them",
        "thing",
        "to",
        "used",
        "usually",
        "very",
        "which",
        "who",
        "with",
        "without",
    }
)
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
)


def _is_meta_gloss(gloss_en: str) -> bool:
    low = gloss_en.strip().lower()
    return not low or low.startswith(_META_GLOSS_PREFIXES)


def _extract_gloss_headwords_and_tokens(gloss_en: str) -> tuple[set[str], set[str]]:
    stripped = _PAREN_RE.sub(" ", gloss_en).lower()
    headwords: set[str] = set()
    for clause in re.split(r"[;,/]", stripped):
        term = " ".join(clause.split()).strip(" .:!?'\"“”‘’")
        for prefix in ("to ", "a ", "an ", "the "):
            if term.startswith(prefix) and len(term) > len(prefix) + 1:
                term = term[len(prefix) :].strip()
        if term and len(term) <= 48:
            headwords.add(term)
    # Keep parenthetical sense qualifiers in ``tokens`` so Kaikki notes such as
    # ``(occupy a place)`` or ``(copula, subject, complement)`` disambiguate
    # fine-grained WordNet synsets.
    tokens = {
        tok
        for tok in _WORD_TOKEN_RE.findall(gloss_en.lower())
        if len(tok) >= 3 and tok not in _EN_STOPWORDS
    }
    return headwords, tokens


def _load_finnwordnet_synset_index(
    conn: psycopg.Connection,
    input_path: Path,
    staged_omw_synsets: set[str],
) -> tuple[
    dict[tuple[str, str], list[str]],
    dict[tuple[str, str], set[str]],
    dict[str, set[str]],
    set[str],
]:
    """Return ``(fi_lemma_pos -> [synset_id], (synset_id, fi_lemma) -> {en_syn}, synset_id -> {def_tokens}, satellite_synsets)``."""

    fi_to_synsets: dict[tuple[str, str], list[str]] = defaultdict(list)
    en_syns_by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    def_tokens_by_synset: dict[str, set[str]] = {}
    satellite_synsets: set[str] = set()

    candidate_dirs: list[Path] = []
    if (input_path.parent / "fiwn-wsenses.tsv").exists():
        candidate_dirs.append(input_path.parent)
    active_fiwn = active_source_file_for_name(conn, source_name="finnwordnet")
    if active_fiwn is not None:
        fiwn_path = Path(str(active_fiwn[1]))
        if fiwn_path.is_dir():
            candidate_dirs.append(fiwn_path)

    rels_dir = next((d for d in candidate_dirs if (d / "fiwn-wsenses.tsv").exists()), None)
    if rels_dir is None:
        return fi_to_synsets, en_syns_by_pair, def_tokens_by_synset, satellite_synsets

    wsenses_path = rels_dir / "fiwn-wsenses.tsv"
    seen_pairs: set[tuple[str, str, str]] = set()
    with wsenses_path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            parts = raw_line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            parsed = normalize_wn30_synset_key(parts[0])
            if parsed is None:
                continue
            synset_id, lex_pos = parsed
            if synset_id not in staged_omw_synsets:
                continue
            word = parts[1].strip()
            if not word or (word, lex_pos, synset_id) in seen_pairs:
                continue
            seen_pairs.add((word, lex_pos, synset_id))
            fi_to_synsets[(word, lex_pos)].append(synset_id)

    transls_path = rels_dir / "fiwn-transls.tsv"
    if transls_path.exists():
        with transls_path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                parts = raw_line.rstrip("\n").split("\t")
                if len(parts) < 5 or parts[4].strip() not in {"synonym", "near_synonym"}:
                    continue
                if len(parts) >= 6 and "<unconfirmed/>" in parts[5]:
                    continue
                parsed = normalize_wn30_synset_key(parts[0])
                if parsed is None or parsed[0] not in staged_omw_synsets:
                    continue
                fi_word = parts[1].strip()
                en_word = " ".join(parts[3].strip().lower().split())
                if fi_word and en_word:
                    en_syns_by_pair[(parsed[0], fi_word)].add(en_word)

    synsets_path = rels_dir / "fiwn-synsets.tsv"
    if synsets_path.exists():
        with synsets_path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                parts = raw_line.rstrip("\n").split("\t")
                if len(parts) < 5:
                    continue
                parsed = normalize_wn30_synset_key(parts[0])
                if parsed is None or parsed[0] not in staged_omw_synsets:
                    continue
                if parts[1].strip() == "s":
                    satellite_synsets.add(parsed[0])
                def_part = parts[4].split('"', 1)[0].split(";", 1)[0].lower()
                tokens = {
                    tok
                    for tok in _WORD_TOKEN_RE.findall(def_part)
                    if len(tok) >= 3 and tok not in _EN_STOPWORDS
                }
                if tokens:
                    def_tokens_by_synset[parsed[0]] = tokens

    return fi_to_synsets, en_syns_by_pair, def_tokens_by_synset, satellite_synsets


def project_omw_zh_rows(
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
            source_name="omw_zh",
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

        omw_by_synset: dict[str, tuple[int, str, str]] = {}
        inline_fi_to_synsets: dict[tuple[str, str], list[str]] = defaultdict(list)
        inline_en_syns: dict[str, set[str]] = defaultdict(set)
        inline_def_tokens: dict[str, set[str]] = {}

        for doc_id, payload in doc_rows:
            if not isinstance(payload, dict):
                continue
            synset_id = str(payload.get("synset_id", ""))
            pos = str(payload.get("part_of_speech", ""))
            gloss_zh = str(payload.get("gloss_zh", ""))
            if not synset_id or not pos or not gloss_zh:
                continue
            omw_by_synset[synset_id] = (int(doc_id), pos, gloss_zh)
            for fi_lemma in payload.get("fin_lemmas") or []:
                if isinstance(fi_lemma, str) and fi_lemma:
                    inline_fi_to_synsets[(fi_lemma, pos)].append(synset_id)
            for en_lemma in payload.get("eng_lemmas") or []:
                if isinstance(en_lemma, str) and en_lemma:
                    inline_en_syns[synset_id].add(en_lemma.lower())
            eng_def = payload.get("eng_def")
            if isinstance(eng_def, str) and eng_def:
                inline_def_tokens[synset_id] = {
                    tok
                    for tok in _WORD_TOKEN_RE.findall(eng_def.lower())
                    if len(tok) >= 3 and tok not in _EN_STOPWORDS
                }

        (
            fi_to_synsets,
            en_syns_by_pair,
            def_tokens_by_synset,
            satellite_synsets,
        ) = _load_finnwordnet_synset_index(conn, input_path, set(omw_by_synset))
        for key, synsets in inline_fi_to_synsets.items():
            existing = set(fi_to_synsets[key])
            for syn in synsets:
                if syn not in existing:
                    fi_to_synsets[key].append(syn)
                    existing.add(syn)

        if not fi_to_synsets:
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

        senses_by_key: dict[tuple[str, str], list[tuple[int, str, str]]] = defaultdict(list)
        for lemma, pos, sense_id, sense_key, gloss_en in sense_rows:
            k = (str(lemma), str(pos))
            if k in fi_to_synsets:
                senses_by_key[k].append((int(sense_id), str(sense_key), str(gloss_en)))

        alignment_rows: list[tuple[str, int, int, str, float, str]] = []
        candidate_rows: list[tuple[int, str, int, str, float, str]] = []

        for (lemma, pos), local_senses in senses_by_key.items():
            synset_ids = [s for s in fi_to_synsets[(lemma, pos)] if s in omw_by_synset]
            if not synset_ids:
                continue

            eligible_senses = [s for s in local_senses if not _is_meta_gloss(s[2])]
            if not eligible_senses:
                continue

            if len(eligible_senses) == 1 and len(synset_ids) == 1:
                sense_id, sense_key, _gloss_en = eligible_senses[0]
                synset_id = synset_ids[0]
                doc_id, _syn_pos, gloss_zh = omw_by_synset[synset_id]
                meta_json = json.dumps(
                    {
                        "sense_key": sense_key,
                        "lemma": lemma,
                        "part_of_speech": pos,
                        "synset_id": synset_id,
                    },
                    ensure_ascii=False,
                )
                alignment_rows.append(
                    ("omw_zh", doc_id, sense_id, "single_synset_single_sense", 0.78, meta_json)
                )
                candidate_rows.append((sense_id, "omw_zh", doc_id, gloss_zh, 0.78, meta_json))
                continue

            # Count cross-synset Chinese word recurrence for this Finnish lemma so
            # broad verbs/adjectives (``olla``, ``hyvä``, ``ottaa``) prefer the
            # core Mandarin equivalent over narrow peripheral synsets.
            zh_lemma_freq: dict[str, int] = defaultdict(int)
            for sid in synset_ids:
                for zw in omw_by_synset[sid][2].split("；"):
                    if zw:
                        zh_lemma_freq[zw] += 1
            synonyms_by_synset = {
                synset_id: en_syns_by_pair.get((synset_id, lemma), set()) | inline_en_syns.get(synset_id, set())
                for synset_id in synset_ids
            }
            synonym_frequency = Counter(
                synonym for synonyms in synonyms_by_synset.values() for synonym in synonyms
            )

            for sense_id, sense_key, gloss_en in eligible_senses:
                headwords, gloss_tokens = _extract_gloss_headwords_and_tokens(gloss_en)
                if not headwords and not gloss_tokens:
                    continue
                best_match: tuple[tuple[int, int, int, int, int], str] | None = None
                for synset_index, synset_id in enumerate(synset_ids):
                    def_tokens = def_tokens_by_synset.get(synset_id) or inline_def_tokens.get(
                        synset_id, set()
                    )
                    matched_headwords = headwords & synonyms_by_synset[synset_id]
                    # A shared headword such as "bank" needs corroborating definition evidence.
                    syn_hits = sum(synonym_frequency[word] == 1 for word in matched_headwords)
                    def_hits = len(gloss_tokens & def_tokens)
                    if syn_hits == 0 and def_hits < 2:
                        continue
                    is_head = 0 if synset_id in satellite_synsets else 1
                    zh_words = omw_by_synset[synset_id][2].split("；")
                    consensus_freq = max((zh_lemma_freq[zw] for zw in zh_words), default=1)
                    # When neither multiple English synonyms nor definition tokens
                    # disambiguate among >= 4 competing synsets, require cross-synset
                    # Chinese consensus or head-adjective status instead of picking
                    # an arbitrary peripheral satellite synset.
                    if (
                        len(synset_ids) >= 4
                        and syn_hits <= 1
                        and def_hits == 0
                        and consensus_freq < 2
                        and not is_head
                    ):
                        continue
                    rank_key = (
                        syn_hits,
                        def_hits,
                        is_head,
                        consensus_freq,
                        -synset_index,
                    )
                    if best_match is None or rank_key > best_match[0]:
                        best_match = (rank_key, synset_id)

                if best_match is None:
                    continue
                (syn_hits, def_hits, _is_head, _cfreq, _neg_idx), chosen_synset = best_match
                doc_id, _syn_pos, gloss_zh = omw_by_synset[chosen_synset]
                score = 0.79 if syn_hits > 0 else 0.77
                kind = "synset_en_synonym" if syn_hits > 0 else "synset_def_overlap"
                meta_json = json.dumps(
                    {
                        "sense_key": sense_key,
                        "lemma": lemma,
                        "part_of_speech": pos,
                        "synset_id": chosen_synset,
                        "synonym_hits": syn_hits,
                        "def_token_hits": def_hits,
                    },
                    ensure_ascii=False,
                )
                alignment_rows.append(("omw_zh", doc_id, sense_id, kind, score, meta_json))
                candidate_rows.append((sense_id, "omw_zh", doc_id, gloss_zh, score, meta_json))

        if candidate_rows:
            conn.execute(
                """
                create temporary table tmp_omw_alignment (
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
                create temporary table tmp_omw_candidate (
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
                    copy tmp_omw_alignment (
                        source_name, source_document_id, target_sense_id,
                        candidate_kind, confidence_score, match_payload
                    ) from stdin
                    """
                ) as copy:
                    for row in alignment_rows:
                        copy.write_row(row)
                with cursor.copy(
                    """
                    copy tmp_omw_candidate (
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
                from tmp_omw_alignment
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
                from tmp_omw_candidate
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
