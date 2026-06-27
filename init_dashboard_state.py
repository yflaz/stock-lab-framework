from __future__ import annotations

import sys

from core.config import load_config
from core.state_builder import initial_state
from core.state_store import save_state


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    state = initial_state(load_config())
    save_state(state)
    print("Initialized simulation_state.json")


if __name__ == "__main__":
    main()
