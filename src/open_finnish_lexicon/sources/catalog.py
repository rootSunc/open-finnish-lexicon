from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class SourceCompanion:
    name: str
    url: str
    local_path: str
    archive_kind: str
    checksum_sha256: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class SourceRelease:
    name: str
    version: str
    source_kind: str
    url: str
    local_path: str
    archive_kind: str
    checksum_sha256: str
    members: tuple[str, ...]
    companions: tuple[SourceCompanion, ...]


def _build_companions(source_name: str, config: Mapping[str, object]) -> tuple[SourceCompanion, ...]:
    companions = config.get("companions", [])
    if not companions:
        return ()
    return tuple(
        SourceCompanion(
            name=str(companion.get("name", f"{source_name}-companion-{index}")),
            url=str(companion["url"]),
            local_path=str(companion.get("local_path", "")),
            archive_kind=str(companion["archive_kind"]),
            checksum_sha256=str(companion.get("checksum_sha256", "")),
            members=tuple(companion["members"]),
        )
        for index, companion in enumerate(companions, start=1)
    )


def load_source_catalog(path: Path) -> dict[str, SourceRelease]:
    payload = tomllib.loads(path.read_text())
    return {
        source_name: SourceRelease(
            name=source_name,
            version=config["version"],
            source_kind=config["source_kind"],
            url=config["url"],
            local_path=str(config.get("local_path", "")),
            archive_kind=config["archive_kind"],
            checksum_sha256=config.get("checksum_sha256", ""),
            members=tuple(config["members"]),
            companions=_build_companions(source_name, config),
        )
        for source_name, config in payload["sources"].items()
    }
