from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "simulation_state.json"
SECTOR_PATH = ROOT / "sector_summary.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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

