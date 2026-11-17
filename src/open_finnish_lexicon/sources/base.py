import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SourceRow:
    external_id: str
    payload: dict


class JsonlLoader:
    name = "fixture"
    source_kind = "jsonl"

    def read_rows(self, input_path: Path) -> list[SourceRow]:
        rows: list[SourceRow] = []
        for line in input_path.read_text().splitlines():
            record = json.loads(line)
            rows.append(SourceRow(external_id=record["id"], payload=record))
        return rows
