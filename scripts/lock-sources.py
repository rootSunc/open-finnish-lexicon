"""Write a buildable TOML catalog from the input assets in a release manifest."""

import argparse
import json
from pathlib import Path
import re
import tomllib


def lock_catalog(catalog: dict, manifest: dict) -> str:
    lines = ["# Locked input catalog generated from a release manifest."]
    sources = manifest["summary"]["sources"]
    if not sources:
        raise ValueError("release manifest has no sources")
    names = set()
    for source in sources:
        name = source["name"]
        if name in names:
            raise ValueError(f"duplicate release source: {name}")
        names.add(name)
        config = catalog["sources"][name]
        if config["version"] != source["version"]:
            raise ValueError(f"catalog version differs from release for {name}")
        companions = config.get("companions", [])
        assets = {asset["name"]: asset for asset in source["assets"]}
        if set(assets) != {name, *(asset["name"] for asset in companions)}:
            raise ValueError(f"catalog assets differ from release for {name}")

        for settings in [config, *companions]:
            asset_name = name if settings is config else settings["name"]
            archived = assets[asset_name]
            checksum = archived["sha256"]
            if settings["url"] != archived["url"] or not re.fullmatch("[a-f0-9]{64}", checksum or ""):
                raise ValueError(f"missing checksum or different URL for {name}/{asset_name}")
            lines.extend(("", f"[sources.{name}]" if settings is config else f"[[sources.{name}.companions]]"))
            fields = {key: value for key, value in settings.items() if key not in ("local_path", "companions")}
            fields["checksum_sha256"] = checksum
            lines.extend(f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items())
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("release_manifest", type=Path)
    args = parser.parse_args()
    try:
        catalog = tomllib.loads(args.catalog.read_text(encoding="utf-8"))
        manifest = json.loads(args.release_manifest.read_text(encoding="utf-8"))
        print(lock_catalog(catalog, manifest), end="")
    except (OSError, KeyError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
