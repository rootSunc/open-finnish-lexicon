"""Small, dependency-free checks for learner-facing Chinese text."""

from __future__ import annotations

import re


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# Two-letter lowercase residues such as ``go`` or ``ok`` are common enough in
# partially translated model output to reject. All-uppercase acronyms remain
# allowed by the caller (USB, DNA, etc.).
_LATIN_RUN_RE = re.compile(r"[A-Za-z]{2,}")
_ZH_METADATA_RE = re.compile(
    r"(?:\*?[A-Za-zÅÄÖÜåäöü][\w\-'’.]*(?:\s+[\w\-'’.]+)*"
    r"(?:\s*(?:\([^)]{0,40}\)|（[^）]{0,40}）))?)?\s*(?:的|之)\s*"
    r"(?:"
    r"(?:(?:第一|第二|第三)(?:人(?:称|稱)|主動|主动|被動|被动|不定式)|第[0-9一二三四五六七八九十]+(?:人(?:称|稱)|不定式))"
    r"|(?:主格|属格|屬格|宾格|賓格|部分格|内格|內格|出格|入格|向格|所格|共格|欠格|具格|手段格|变格|變格|接格|奪格|方向格|經由格|经由格|分配格|上方格|離格|离格|趨向格|趋向格|處所格|处所格|倍數格|倍数格|原因格|對立格|对立格|分離格|分离格|時間用法|时间用法)"
    r"|(?:直陈式|直陳式|命令式|条件式|條件式|现在时|現在時|过去时|過去時|否定|共否定)"
    r"|(?:最高级|最高級|异体|異體|省略|屈折|变形|變形|另一种|另一種|同义词|同義詞|首字母缩略词|首字母縮略詞|简写|簡寫|縮寫)"
    r"|(?:不定式|持續體|持续体|主動|主动|被動|被动)"
    r"|(?:passive|active|allative|ablative|genitive|nominative|partitive|illative|inessive|elative|adessive|essive|translative|abessive|comitative|lative|prolative|distributive|superessive|delative|sublative|situative|multiplicative|causative|oppositive|separative|locative|temporal|infinitive|participle)"
    r"|(?:单数|單數|复数|複數)"
    r")"
)
_ZH_STANDALONE_METADATA_RE = re.compile(
    r"^(?:"
    r"(?:主格|属格|屬格|宾格|賓格|部分格|内格|內格|出格|入格|向格|所格|共格|欠格|具格|手段格|变格|變格|接格|奪格|方向格|經由格|经由格|分配格|上方格|離格|离格|趨向格|趋向格|處所格|处所格|倍數格|倍数格|原因格|對立格|对立格|分離格|分离格|時間用法|时间用法)"
    r"(?:单数|單數|复数|複數)?(?:形式|形)?"
    r"|(?:(?:第一|第二|第三)(?:人(?:称|稱)|主動|主动|被動|被动|不定式)|第[0-9一二三四五六七八九十]+(?:人(?:称|稱)|不定式))"
    r"|(?:最高级|最高級|异体|異體|省略|屈折|变形|變形|另一种|另一種|同义词|同義詞|简写|簡寫|縮寫)"
    r")[。；;，,、\s]*$"
)
_PLACEHOLDER_ZH_RE = re.compile(r"待核|待补|待确认|待翻译")

# Conservative high-signal characters whose common simplified forms differ.
# This is not a converter: uncertain text should be reviewed, not rewritten.
TRADITIONAL_ONLY_CHARACTERS = frozenset(
    "萬與專業東絲兩書畫樂車門國學體這個會為來發後時說嗎點過開關處線電風語詞實應無專較從讓對裡還"
    "聽誕覺現見頭買賣機號臺灣醫藥廣廠邊進遠連選運價錢區並壓報變別標補參長場帶單當導動讀隊飛費復婦幹"
    "個給漢華歡幾間將節結經舊劇據決離歷劉龍滿沒夢難鳥農歐氣親認師識試樹帥態條團網衛問務縣響寫學"
    "選亞樣業陰營預員雲則張這轉準總組賊傳"
    # Common characters that are easy to miss in short glosses or labels.
    "愛辦寶貝賓倉層產陳遲齒蟲創達黨燈敵遞斷額兒豐該購觀館歸"
    "壞環擊級極記講節盡舉開類聯練輛滿盤憑評齊遷親輕請慶讓熱榮賽殺"
    "審聲勝視獸術雙誰雖隨孫談題鐵圖萬鄉協謝興嚴顏陽養藥爺憶藝郵憂與譽"
    "園躍雜贊責擇趙證紙職質鐘種眾轉鑽綴綜縱"
    "習課資訊簡護頁錯險滅濟潔壽獨療終懸掛寧筆"
    # Frequent short-gloss characters omitted by earlier coverage audits.
    "們貓魚馬紅黃藍綠臉腳島韓陸際權義誤夠負貴"
    # Additional high-signal traditional forms observed in dictionary
    # candidates. Keep this list conservative: it is a rejection gate, not a
    # character converter, so only forms with an unambiguous learner-facing
    # simplified counterpart belong here.
    "乾匯兌幣屬彈徵捨捲換撻擔桿淨溫潛濕燒狀瞼禮細絕統維艦蘇衝"
    "訂財貨譯遊遺軸輪鏈閥閱閹雞項頓領顧飲餅餡骯髒"
    # High-signal written Cantonese/Hong Kong characters. These are not
    # simplified learner Chinese even when a sentence contains otherwise
    # ordinary Han characters (for example: ``我哋喺屋企。``).
    "乜冇喺啲咁唔佢哋係搵噉畀嘅咗嗰嚟㗎嘢撚俾瞓吽"
)

# A small set of unambiguous dialectal characters that should not be shown as
# default Mandarin learner content.  This is deliberately separate from the
# traditional-character list: the text may be simplified in shape while still
# being the wrong register or dialect for the product.  ``𠲎`` and ``搿`` are
# high-signal Wu-dialect forms found in the same learner-translation batch as
# ``侬``.
NON_STANDARD_LEARNER_ZH_CHARACTERS = frozenset("侬𠲎搿")


def traditional_chinese_characters(text: object) -> tuple[str, ...]:
    """Return distinct high-signal traditional characters in encounter order."""

    if not isinstance(text, str):
        return ()
    return tuple(dict.fromkeys(char for char in text if char in TRADITIONAL_ONLY_CHARACTERS))


def has_traditional_chinese(text: object) -> bool:
    return bool(traditional_chinese_characters(text))


def traditional_chinese_detail(text: object) -> str | None:
    """Return a compact review detail when text is not Simplified Chinese."""

    characters = traditional_chinese_characters(text)
    if not characters:
        return None
    preview = text.strip()[:80] if isinstance(text, str) else ""
    return f"traditional Chinese characters ({', '.join(characters[:8])}): {preview}"


def non_standard_learner_zh_characters(text: object) -> tuple[str, ...]:
    """Return distinct dialectal characters unsuitable for default Mandarin."""

    if not isinstance(text, str):
        return ()
    return tuple(
        dict.fromkeys(char for char in text if char in NON_STANDARD_LEARNER_ZH_CHARACTERS)
    )


def non_standard_learner_zh_detail(text: object) -> str | None:
    """Return a compact detail when text uses a known non-Mandarin character."""

    characters = non_standard_learner_zh_characters(text)
    if not characters:
        return None
    preview = text.strip()[:80] if isinstance(text, str) else ""
    return f"non-standard/dialectal Chinese characters ({', '.join(characters[:8])}): {preview}"


def is_placeholder_simplified_chinese(text: object) -> bool:
    """Return whether text is an editorial placeholder rather than a gloss."""

    return isinstance(text, str) and _PLACEHOLDER_ZH_RE.search(text.strip()) is not None


def simplified_chinese_text_issue(text: object) -> str | None:
    """Return a deterministic issue for text promised to be Simplified Chinese."""

    if not isinstance(text, str) or not text.strip():
        return "Chinese text is missing"
    if not _CJK_RE.search(text):
        return "Chinese text has no Han characters"
    if non_learner_zh_gloss_detail(text) is not None:
        return "Chinese text is dictionary metadata, not a learner definition"
    if is_placeholder_simplified_chinese(text):
        return "Chinese text is an editorial placeholder, not a learner definition"
    traditional = traditional_chinese_detail(text)
    if traditional is not None:
        return traditional
    non_standard = non_standard_learner_zh_detail(text)
    if non_standard is not None:
        return non_standard
    leaks = [token for token in _LATIN_RUN_RE.findall(text) if not token.isupper()]
    if leaks:
        return "untranslated Latin residue (" + ", ".join(sorted(set(leaks))[:5]) + ")"
    return None


def is_usable_simplified_chinese(text: object) -> bool:
    return simplified_chinese_text_issue(text) is None


def non_learner_zh_gloss_detail(text: object) -> str | None:
    """Detect Chinese Wiktionary relation/form metadata mistaken for a gloss."""

    if not isinstance(text, str):
        return None
    normalized = text.strip()
    if not normalized or (
        _ZH_METADATA_RE.search(normalized) is None
        and _ZH_STANDALONE_METADATA_RE.search(normalized) is None
    ):
        return None
    return f"Chinese gloss is dictionary metadata, not a learner definition: {normalized[:80]}"


__all__ = [
    "TRADITIONAL_ONLY_CHARACTERS",
    "NON_STANDARD_LEARNER_ZH_CHARACTERS",
    "has_traditional_chinese",
    "is_placeholder_simplified_chinese",
    "is_usable_simplified_chinese",
    "non_learner_zh_gloss_detail",
    "simplified_chinese_text_issue",
    "traditional_chinese_characters",
    "traditional_chinese_detail",
    "non_standard_learner_zh_characters",
    "non_standard_learner_zh_detail",
]
