"""Decide whether every word in a Finnish example sentence is a real Finnish word.

``morphology/validator.py`` checks the inflection tables we publish for a
lexeme. Nothing checked the other direction: the Finnish sentences we serve as
examples. About 129k of the 277k rows in ``lexicon.example`` were written by a
model, and a generated sentence can contain a word that simply does not exist —
a typo, a hallucinated stem, or an affix entry rendered as though it were a
sentence. That is one of the few example defects with an objective answer, so
it is worth deciding deterministically instead of asking another model.

A bare Omorfi lookup is not that decision. Measured over random samples of real
rows it rejects 8-28% of sentences, nearly all of them correct Finnish: Omorfi
0.9.12 ships a fixed lexicon that omits productive ``-minen`` verbal nouns,
productive participles, most compounds, and most proper nouns. A check with that
false-positive rate is noise, so recognition runs in layers and a token counts
as unknown only when every layer rejects it:

1. Omorfi's recased analyser, which handles inflection, clitics and
   sentence-initial capitals (``juoksentelisinkohan``, ``Helsingissä``);
2. the lexicon we built ourselves — ``lexicon.form`` plus lemmas — which comes
   from Kaikki and covers the derivations, compounds and names Omorfi omits;
3. colon-suffixed acronyms (``USA:ssa``) and hyphen-joined parts (``p-äänne``);
4. restoration of the productive ``-minen`` paradigm to its nominative
   (``sujumisesta`` -> ``sujuminen``), which Omorfi lacks entirely and the form
   table carries only in the nominative;
5. compound splitting, where every part must itself be a known word
   (``puupöytä``, ``ulkovarastossa``).

A capitalized word is reported separately as name-like rather than as a
defect. Omorfi carries only a small gazetteer, so ``Manchesterista``,
``Brazzavillen`` and ``Heimlichin`` fail every layer above while being perfectly
good Finnish. Sentence position does not help tell those from a real error —
sampling found sentence-initial unknown capitals to be names just as reliably —
so capitalization alone decides, and the cost is that a capitalized typo goes
unreported. That trade is deliberate: this job exists to produce a signal clean
enough to act on without review, and the defects it is aimed at are lowercase.

On the same samples the layered recognizer rejects 0.07% of Tatoeba rows and
0.6-0.8% of generated rows, and the rejections are real defects: doubled letters
(``persooonassa``), and affix stubs dressed as sentences (``Sanaan lisättiin
pääte -eliäs.``).

The recognizer takes its analyser as a callable so tests can run without the
164 MB HFST model. It never guesses on the analyser's behalf: when the model is
missing the caller is expected to fail rather than store weaker verdicts under
the same version string.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
import re

#: Bumped when a recognition layer changes, so stored verdicts from an older
#: rule set can be told apart and revalidated.
RECOGNIZER_VERSION = "fi-word-recognizer-v1"

VERDICT_VALID = "valid"
VERDICT_UNKNOWN_TOKENS = "unknown_tokens"
VERDICT_EMPTY = "empty"

#: A word, allowing the internal hyphen, apostrophe and colon that Finnish uses
#: to join parts (``p-äänne``, ``USA:ssa``, ``d'Artagnan``). Digits are matched
#: so that ``4H-kerholla`` comes out as one token and can be skipped whole
#: instead of leaving a bare ``H-kerholla`` behind.
_TOKEN_RE = re.compile(r"[^\W_]+(?:[-'’:][^\W_]+)*", re.UNICODE)

#: Omorfi returns a guess rather than an empty list for a word it does not know.
_UNKNOWN_ANALYSIS_MARKERS = ("GUESS=UNKNOWN", "[UPOS=X]")

#: Any inflected form of a ``-minen`` verbal noun keeps the ``mis`` stem:
#: ``sujumisesta``, ``avaamisessa``, ``noudattamista``. Restoring the nominative
#: is enough, because that is the form the Kaikki-derived table does carry.
_MINEN_INFLECTION_RE = re.compile(r"^(?P<stem>.+mi)s[a-zäöå]*$")

#: Shortest part a compound split will accept, to stop ``on`` + ``koira`` style
#: splits from accepting anything that happens to start with a short word.
_MIN_COMPOUND_PART = 3

#: Longest tail accepted after an abbreviation's colon (``USA:ssa``, ``EU:hun``).
_MAX_ABBREVIATION_SUFFIX = 6


@dataclass(frozen=True)
class SentenceMorphologyVerdict:
    verdict: str
    token_count: int
    unknown_tokens: tuple[str, ...]
    name_like_tokens: tuple[str, ...] = ()

    @property
    def unknown_count(self) -> int:
        return len(self.unknown_tokens)

    @property
    def name_like_count(self) -> int:
        return len(self.name_like_tokens)


def tokenize_finnish_sentence(text: str | None) -> list[str]:
    """Return the word tokens of ``text``, skipping anything containing a digit.

    Digit-bearing tokens (``1990-luvulla``, ``4H-kerholla``) are dropped rather
    than checked: they are not in any lexicon, and their shape carries no signal
    about whether a sentence is broken.
    """

    if not text:
        return []
    return [
        token
        for token in _TOKEN_RE.findall(text)
        if not any(character.isdigit() for character in token)
    ]


def find_omorfi_recased_analyser(data_dir: str | Path) -> Path | None:
    """Return the newest unpacked recased analyser under ``data_dir``, if any."""

    releases = Path(data_dir) / "releases" / "omorfi"
    if not releases.is_dir():
        return None
    candidates = sorted(
        (
            path
            for path in releases.glob("*/unpacked/omorfi_recased.analyse.hfst")
            if path.is_file()
        ),
        key=lambda path: path.parent.parent.name,
    )
    return candidates[-1] if candidates else None


def load_omorfi_analyse(analyser_path: str | Path) -> Callable[[str], bool]:
    """Load the HFST analyser and return a ``token -> is analysable`` callable."""

    from omorfi.omorfi import Omorfi  # ty: ignore[import-not-found]

    omorfi = Omorfi()
    omorfi.load_analyser(str(analyser_path))

    def analyse(token: str) -> bool:
        for analysis in omorfi.analyse(token):
            raw = getattr(analysis, "raw", "") or ""
            if not any(marker in raw for marker in _UNKNOWN_ANALYSIS_MARKERS):
                return True
        return False

    return analyse


def load_project_lexicon(conn) -> tuple[frozenset[str], frozenset[str]]:
    """Return ``(all known forms, bare lemmas)`` from our own lexicon.

    Lemmas are kept separately because a compound's non-final parts appear as
    bare stems (``puu`` in ``puupöytä``), not as inflected forms.
    """

    forms = {row[0] for row in conn.execute("select distinct normalized_form from lexicon.form")}
    lemmas = {row[0] for row in conn.execute("select distinct lower(lemma) from lexicon.lexeme")}
    return frozenset(forms | lemmas), frozenset(lemmas)


class FinnishWordRecognizer:
    """Layered recognizer for single Finnish word tokens."""

    def __init__(
        self,
        *,
        analyse: Callable[[str], bool],
        forms: Iterable[str],
        lemmas: Iterable[str],
    ) -> None:
        self._analyse = analyse
        self._forms = frozenset(forms)
        self._lemmas = frozenset(lemmas)
        self._cache: dict[str, bool] = {}

    def is_known(self, token: str) -> bool:
        cached = self._cache.get(token)
        if cached is None:
            cached = self._recognize(token)
            self._cache[token] = cached
        return cached

    def validate_sentence(self, text: str | None) -> SentenceMorphologyVerdict:
        tokens = tokenize_finnish_sentence(text)
        if not tokens:
            return SentenceMorphologyVerdict(
                verdict=VERDICT_EMPTY, token_count=0, unknown_tokens=()
            )

        unknown: list[str] = []
        name_like: list[str] = []
        for token in tokens:
            if self.is_known(token):
                continue
            if token[:1].isupper():
                name_like.append(token)
            else:
                unknown.append(token)

        unique_unknown = tuple(dict.fromkeys(unknown))
        verdict = VERDICT_UNKNOWN_TOKENS if unique_unknown else VERDICT_VALID
        return SentenceMorphologyVerdict(
            verdict=verdict,
            token_count=len(tokens),
            unknown_tokens=unique_unknown,
            name_like_tokens=tuple(dict.fromkeys(name_like)),
        )

    def _recognize(self, token: str) -> bool:
        return self._unjoined_known(token) or self._hyphen_parts_known(token)

    def _unjoined_known(self, token: str) -> bool:
        """Everything that can settle a token without splitting it on a hyphen."""

        # A lone letter is a list marker, an initial, or a foreign character.
        # No lexicon holds it and its shape carries no signal either way.
        if len(token) <= 1:
            return True
        if self._word_known(token):
            return True
        return self._abbreviation_with_case_suffix(token)

    def _word_known(self, token: str) -> bool:
        """The lexical layers: form table, analyser, -minen restoration, compounds."""

        normalized = token.casefold()
        if normalized in self._forms:
            return True
        if self._analyse(token):
            return True
        if self._minen_derivation_known(normalized):
            return True
        return self._compound_known(normalized)

    def _abbreviation_with_case_suffix(self, token: str) -> bool:
        """Accept ``USA:ssa``, ``kg:n``, ``d:llä``.

        In Finnish an internal colon only ever joins an abbreviation or symbol
        to its case ending, so an alphabetic head plus a short lowercase tail is
        the whole shape. The head is not required to be uppercase: unit symbols
        (``kg``) and single letters used as words (``d``) are lowercase.
        """

        head, separator, tail = token.partition(":")
        if not separator or not head or not tail:
            return False
        if not head.isalpha():
            return False
        return tail.isalpha() and tail.islower() and len(tail) <= _MAX_ABBREVIATION_SUFFIX

    def _hyphen_parts_known(self, token: str) -> bool:
        parts = [part for part in re.split(r"[-'’]", token) if part]
        if len(parts) < 2:
            return False
        # Parts are settled the same way whole tokens are, minus the hyphen
        # split itself, so ``pop-LP:tä`` reaches the abbreviation rule.
        return all(self._unjoined_known(part) for part in parts)

    def _minen_derivation_known(self, normalized: str) -> bool:
        match = _MINEN_INFLECTION_RE.match(normalized)
        if match is None:
            return False
        nominative = f"{match.group('stem')}nen"
        return nominative in self._forms or self._analyse(nominative)

    def _compound_known(self, normalized: str, depth: int = 2) -> bool:
        if len(normalized) < _MIN_COMPOUND_PART * 2:
            return False
        for split in range(_MIN_COMPOUND_PART, len(normalized) - _MIN_COMPOUND_PART + 1):
            head, tail = normalized[:split], normalized[split:]
            if not self._compound_head_known(head):
                continue
            if tail in self._forms or self._analyse(tail):
                return True
            if self._minen_derivation_known(tail):
                return True
            if depth > 1 and self._compound_known(tail, depth - 1):
                return True
        return False

    def _compound_head_known(self, head: str) -> bool:
        if head in self._lemmas or head in self._forms:
            return True
        # Compounds also join on the genitive (``valtionvarain``): accept a head
        # whose bare stem is a lemma.
        return head.endswith("n") and head[:-1] in self._lemmas


__all__ = [
    "FinnishWordRecognizer",
    "RECOGNIZER_VERSION",
    "SentenceMorphologyVerdict",
    "VERDICT_EMPTY",
    "VERDICT_UNKNOWN_TOKENS",
    "VERDICT_VALID",
    "find_omorfi_recased_analyser",
    "load_omorfi_analyse",
    "load_project_lexicon",
    "tokenize_finnish_sentence",
]
