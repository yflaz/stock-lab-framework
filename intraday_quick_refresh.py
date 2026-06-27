from __future__ import annotations

import sys

from core.config import load_config
from core.state_builder import save_current_state


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    state = save_current_state(load_config())
    meta = state.get("meta") or {}
    print(f"Intraday refresh complete: {meta.get('generated_at')} ({meta.get('session_phase_label')})")


if __name__ == "__main__":
    main()
