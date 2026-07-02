from __future__ import annotations

import json
import math
from numbers import Real
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "simulation_state.json"
SECTOR_PATH = ROOT / "sector_summary.json"


def sanitize_json_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_json_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json_payload(item) for item in value]
    if isinstance(value, Real) and not isinstance(value, bool):
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        if isinstance(value, int):
            return int(value)
        return numeric
    return value


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    clean = sanitize_json_payload(payload)
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def load_state() -> dict[str, Any]:
    return load_json(STATE_PATH, {})


def save_state(state: dict[str, Any]) -> None:
    save_json(STATE_PATH, state)


def load_sectors() -> list[dict[str, Any]]:
    data = load_json(SECTOR_PATH, [])
    if isinstance(data, dict):
        return list(data.get("items") or data.get("sectors") or [])
    if isinstance(data, list):
        return data
    return []

