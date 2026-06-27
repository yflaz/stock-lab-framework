from __future__ import annotations

import json
import sys

from core.config import load_config
from core.state_builder import build_state


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    state = build_state(load_config())
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    main()
