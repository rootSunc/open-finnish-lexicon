import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
import unicodedata

from collections.abc import Sequence

from open_finnish_lexicon.normalize.lexemes import normalize_part_of_speech

WORD_ID_RE = re.compile(r"\[WORD_ID=([^\]]+)\]")


@dataclass
class OmorfiRow:
    surface_form: str
    lemma: str
    part_of_speech: str
    features: dict[str, str]
    analysis_rank: int = 1
    confidence: float = 1.0


type GeneratedOmorfiRow = tuple[int, OmorfiRow]

OMORFI_CASES = (
    "NOM",
    "GEN",
    "PAR",
    "INE",
    "ELA",
    "ILL",
    "ADE",
    "ABL",
    "ALL",
    "ESS",
    "TRA",
    "ABE",
    "COM",
    "INS",
)

_SINGLE_OMORFI_FORM_RE = re.compile(
    r"[^\W\d_]+(?:[-'’ʼ‐‑‒–—][^\W\d_]+)*",
    re.UNICODE,
)


def _is_usable_omorfi_surface(value: str) -> bool:
    """Keep word-shaped analyses, not affix/morpheme placeholders."""

    return bool(_SINGLE_OMORFI_FORM_RE.fullmatch(value.strip()))


def find_omorfi_generation_models(data_dir: str | Path) -> tuple[Path, Path] | None:
    """Return the newest matching ``(generator, analyser)`` model pair.

    Generation is an optional enhancement for real data.  Requiring both
    models here is intentional: every generated surface is round-tripped
    through the analyser before it is stored.
    """

    releases = Path(data_dir) / "releases" / "omorfi"
    if not releases.is_dir():
        return None
    for release_dir in sorted(releases.iterdir(), key=lambda path: path.name, reverse=True):
        unpacked = release_dir / "unpacked"
        generator = unpacked / "omorfi.generate.hfst"
        analyser = unpacked / "omorfi.analyse.hfst"
        if generator.is_file() and analyser.is_file():
            return generator, analyser
    return None


def get_omorfi_source_kind(input_path: Path) -> str:
    if input_path.suffix == ".hfst":
        return "hfst"
    return "tsv"


def _extract_omorfi_lemma(analysis) -> str | None:
    lemmas = getattr(analysis, "lemmas", None)
    if lemmas:
        return lemmas[0]
    raw = getattr(analysis, "raw", None)
    if not raw:
        return None
    match = WORD_ID_RE.search(raw)
    if match is None:
        return None
    return match.group(1)


def _analysis_confidence(weight: float | int | None) -> float:
    if weight is None:
        return 1.0
    numeric_weight = float(weight)
    if not math.isfinite(numeric_weight):
        return 0.0
    return 1.0 / (1.0 + max(0.0, numeric_weight))


def read_omorfi_rows(input_path: Path) -> list[OmorfiRow]:
    rows: list[OmorfiRow] = []
    for index, line in enumerate(input_path.read_text().splitlines(), start=1):
        if index == 1 and line == "lemma\thomonym\tnew_para\torigin":
            continue
        if not line:
            continue
        surface_form, lemma, part_of_speech, features_json = line.split("\t")
        if not _is_usable_omorfi_surface(surface_form):
            continue
        rows.append(
            OmorfiRow(
                surface_form=surface_form,
                lemma=lemma,
                part_of_speech=normalize_part_of_speech(part_of_speech),
                features=json.loads(features_json),
                analysis_rank=index,
                confidence=1.0,
            )
        )
    return rows


def analyse_omorfi_model_rows(input_path: Path, candidate_tokens: list[str]):
    from omorfi.omorfi import Omorfi  # ty: ignore[import-not-found]

    omorfi = Omorfi()
    omorfi.load_analyser(str(input_path))

    for surface_form in candidate_tokens:
        if not _is_usable_omorfi_surface(surface_form):
            continue
        analyses = omorfi.analyse(surface_form)
        analysis_rank = 1
        for analysis in analyses:
            lemma = _extract_omorfi_lemma(analysis)
            upos = getattr(analysis, "upos", None)
            features = getattr(analysis, "ufeats", None) or {}
            if not lemma or not upos:
                continue
            yield OmorfiRow(
                surface_form=surface_form,
                lemma=lemma,
                part_of_speech=normalize_part_of_speech(upos),
                features=features,
                analysis_rank=analysis_rank,
                confidence=_analysis_confidence(getattr(analysis, "weight", None)),
            )
            analysis_rank += 1


def _normalize_omorfi_text(value: object) -> str:
    return unicodedata.normalize("NFC", str(value)).strip().casefold()


def _style_prefixes(feature_hints: Sequence[dict]) -> tuple[str, ...]:
    """Return safe generator prefixes inferred from known analyses."""

    has_dialectal_style = any(
        str(key).casefold() == "style"
        and str(value).casefold() in {"coll", "dialectal"}
        for hint in feature_hints
        if isinstance(hint, dict)
        for key, value in hint.items()
    )
    return ("[STYLE=DIALECTAL]", "") if has_dialectal_style else ("",)


def _paradigm_spec(part_of_speech: str) -> tuple[str, str] | None:
    normalized_pos = part_of_speech.strip().casefold()
    if normalized_pos == "noun":
        return "NOUN", ""
    if normalized_pos in {"adj", "adjective"}:
        return "ADJ", "[CMP=POS]"
    return None


def _analysis_matches(
    analysis,
    *,
    lemma: str,
    upos: str,
    expected_features: dict[str, str],
) -> bool:
    if _normalize_omorfi_text(getattr(analysis, "upos", "")) != upos.casefold():
        return False
    if not any(
        _normalize_omorfi_text(candidate) == _normalize_omorfi_text(lemma)
        for candidate in (getattr(analysis, "lemmas", None) or ())
    ):
        return False
    features = {
        str(key).casefold(): _normalize_omorfi_text(value)
        for key, value in (getattr(analysis, "ufeats", None) or {}).items()
    }
    return all(
        features.get(key.casefold()) == _normalize_omorfi_text(value)
        for key, value in expected_features.items()
    )


def generate_omorfi_paradigm_rows(
    lexemes: Sequence[tuple[int, str, str, Sequence[dict]]],
    *,
    data_dir: str | Path,
) -> list[GeneratedOmorfiRow]:
    """Generate and analyser-verify noun/adjective paradigm cells.

    ``lexemes`` contains ``(lexeme_id, lemma, part_of_speech, feature_hints)``.
    The generator is deliberately not used for verbs: Omorfi 0.9.12's
    generator does not reliably generate their finite paradigms, while the
    analyser harvest already handles real verb forms.  A surface is emitted
    only when the analyser returns the same lemma, POS, and requested
    number/case/degree cell.
    """

    model_paths = find_omorfi_generation_models(data_dir)
    if model_paths is None:
        return []

    from omorfi.omorfi import Omorfi  # ty: ignore[import-not-found]

    generator_path, analyser_path = model_paths
    omorfi = Omorfi()
    omorfi.load_generator(str(generator_path))
    omorfi.load_analyser(str(analyser_path))

    generated: list[GeneratedOmorfiRow] = []
    for lexeme_id, lemma, part_of_speech, feature_hints in lexemes:
        spec = _paradigm_spec(part_of_speech)
        if spec is None or not lemma.strip() or any(char.isspace() for char in lemma):
            continue
        upos, extra_tags = spec
        for style_prefix in _style_prefixes(feature_hints):
            for number, number_value in (("SG", "Sing"), ("PL", "Plur")):
                for case in OMORFI_CASES:
                    expected_features = {
                        "Number": number_value,
                        "Case": {
                            "NOM": "Nom",
                            "GEN": "Gen",
                            "PAR": "Par",
                            "INE": "Ine",
                            "ELA": "Ela",
                            "ILL": "Ill",
                            "ADE": "Ade",
                            "ABL": "Abl",
                            "ALL": "All",
                            "ESS": "Ess",
                            "TRA": "Tra",
                            "ABE": "Abe",
                            "COM": "Com",
                            "INS": "Ins",
                        }[case],
                    }
                    if upos == "ADJ":
                        expected_features["Degree"] = "Pos"
                    raw = (
                        f"[WORD_ID={lemma}][UPOS={upos}]"
                        f"{extra_tags}{style_prefix}[NUM={number}][CASE={case}]"
                        "[WEIGHT=0.000000]"
                    )
                    output = omorfi.generate(raw)
                    if not isinstance(output, str) or not output:
                        continue
                    for surface_form in output.split("/"):
                        surface_form = surface_form.strip()
                        if not surface_form or any(char.isspace() for char in surface_form):
                            continue
                        matches = [
                            analysis
                            for analysis in omorfi.analyse(surface_form)
                            if _analysis_matches(
                                analysis,
                                lemma=lemma,
                                upos=upos,
                                expected_features=expected_features,
                            )
                        ]
                        if not matches:
                            continue
                        analysis = matches[0]
                        generated.append(
                            (
                                int(lexeme_id),
                                OmorfiRow(
                                    surface_form=surface_form,
                                    lemma=lemma,
                                    part_of_speech=part_of_speech,
                                    features=dict(getattr(analysis, "ufeats", None) or {}),
                                    analysis_rank=1,
                                    confidence=1.0,
                                ),
                            )
                        )
    return generated
