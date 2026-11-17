"""Runtime settings, read from ``OFL_*`` environment variables."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os

PROFILES = ("real", "fixture")


@dataclass(frozen=True)
class PipelineSettings:
    database_url: str
    data_dir: str
    data_profile: str
    source_manifest_path: str | None


@lru_cache(maxsize=1)
def get_pipeline_settings() -> PipelineSettings:
    """Return settings from the environment.

    ``OFL_DATABASE_URL`` is required. ``OFL_PROFILE`` is
    ``real`` (default) or ``fixture``; the real profile refuses fixture input
    so test data cannot replace a real snapshot by accident.
    """

    database_url = os.environ.get("OFL_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("set OFL_DATABASE_URL to a PostgreSQL connection string")
    profile = os.environ.get("OFL_PROFILE", "real").strip() or "real"
    if profile not in PROFILES:
        raise RuntimeError("OFL_PROFILE must be 'real' or 'fixture'")
    return PipelineSettings(
        database_url=database_url,
        data_dir=os.environ.get("OFL_DATA_DIR", "./data").strip() or "./data",
        data_profile=profile,
        source_manifest_path=os.environ.get("OFL_SOURCE_MANIFEST") or None,
    )
