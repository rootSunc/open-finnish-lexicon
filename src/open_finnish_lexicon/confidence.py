from __future__ import annotations

import math


def normalize_confidence_score(raw: object, *, default: float = 0.0) -> float:
    """Normalize confidence values into the database-safe ``0..1`` range.

    Sources and older tools sometimes emit scores outside ``0..1``, for
    example with a misplaced decimal point such
    as ``9.1`` or ``91``. We conservatively shift the decimal left until the
    value fits in ``0..1`` instead of treating such malformed values as
    database-breaking hard failures.
    """

    if raw is None or raw == "":
        return default

    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        value = float(raw)
    else:
        value = float(str(raw))
    if not math.isfinite(value):
        raise ValueError(f"confidence score must be finite, got {raw!r}")

    if value <= 0:
        return 0.0

    while value > 1.0:
        value /= 10.0

    return round(min(value, 1.0), 5)


__all__ = ["normalize_confidence_score"]
