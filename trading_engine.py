from __future__ import annotations

import argparse
import json
import sys

from core.config import load_config
from core.state_builder import save_current_state


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Build Stock Lab v2.0 state.")
    parser.add_argument("--print", action="store_true", dest="print_state", help="Print generated state JSON to stdout.")
    args = parser.parse_args()
    state = save_current_state(load_config())
    if args.print_state:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return
    account = state.get("account") or {}
    print(
        "Stock Lab v2.0 state updated | "
        f"phase={state.get('meta', {}).get('session_phase_label')} | "
        f"positions={len(state.get('positions') or [])} | "
        f"orders={len(state.get('orders') or [])} | "
        f"equity={account.get('equity')}"
    )


if __name__ == "__main__":
    main()
