"""Finnish morphology validator.

A pure-Python rule engine checks inflected forms against their paradigm and
marks each one ``verified``, ``mismatch`` or ``uncertain``.

Public entrypoints live in :mod:`open_finnish_lexicon.morphology.validator`.
"""

from open_finnish_lexicon.morphology.rules import (
    Verdict,
    RuleVerdict,
    validate_form,
)

__all__ = ["Verdict", "RuleVerdict", "validate_form"]
