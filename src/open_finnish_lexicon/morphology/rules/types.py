"""Morphology rule engine types and feature constants."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

class Verdict(str, Enum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class RuleVerdict:
    verdict: Verdict
    predicted_surface: str | None
    rule: str | None
    explanation: str
    confidence: float


BACK_VOWELS = set("aou")
FRONT_VOWELS = set("äöy")
NEUTRAL_VOWELS = set("ei")
ALL_VOWELS = BACK_VOWELS | FRONT_VOWELS | NEUTRAL_VOWELS

NOMINAL_POS = {"noun", "adjective", "pronoun", "numeral", "propn", "adj", "n"}
VERB_POS = {"verb", "v"}

CASE_CANONICAL = {
    "nominative": "nom",
    "nom": "nom",
    "accusative": "acc",
    "acc": "acc",
    "genitive": "gen",
    "gen": "gen",
    "partitive": "par",
    "par": "par",
    "part": "par",
    "inessive": "ine",
    "ine": "ine",
    "elative": "ela",
    "ela": "ela",
    "illative": "ill",
    "ill": "ill",
    "adessive": "ade",
    "ade": "ade",
    "ablative": "abl",
    "abl": "abl",
    "allative": "all",
    "all": "all",
    "essive": "ess",
    "ess": "ess",
    "tra": "tra",
    "translat": "tra",
    "translative": "tra",
    "abessive": "abe",
    "abe": "abe",
    "comitative": "com",
    "com": "com",
    "instructive": "ins",
    "ins": "ins",
}

NUMBER_CANONICAL = {
    "singular": "sg",
    "sg": "sg",
    "sing": "sg",
    "plural": "pl",
    "pl": "pl",
    "plur": "pl",
}

CASE_NAMES = {
    "nom": "nominative",
    "acc": "accusative",
    "gen": "genitive",
    "par": "partitive",
    "ine": "inessive",
    "ela": "elative",
    "ill": "illative",
    "ade": "adessive",
    "abl": "ablative",
    "all": "allative",
    "ess": "essive",
    "tra": "translative",
    "abe": "abessive",
    "com": "comitative",
    "ins": "instructive",
}
