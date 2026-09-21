"""Optional JSON Schema validation for Go artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schema" / "entities.json"


def load_entity_schema() -> dict[str, Any] | None:
    path = _schema_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def validate_data_dir(data_dir: str | Path) -> list[str]:
    """
    Light structural checks against expected artifact files.
    Returns a list of warning strings (empty = ok). Does not require jsonschema pkg.
    """
    root = Path(data_dir)
    warnings: list[str] = []
    if not root.exists():
        return [f"data_dir missing: {root}"]
    for name in ("manifest.json",):
        if not (root / name).exists():
            warnings.append(f"missing {name}")
    files_dir = root / "files"
    if files_dir.exists():
        sample = list(files_dir.glob("*.json"))[:5]
        for fp in sample:
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                if "rel_path" not in data and "path" not in data:
                    warnings.append(f"{fp.name}: missing path/rel_path")
            except (json.JSONDecodeError, OSError) as exc:
                warnings.append(f"{fp.name}: {exc}")
    schema = load_entity_schema()
    if schema is None:
        warnings.append("schema/entities.json not loaded (skipped deep validation)")
    return warnings
