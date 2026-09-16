"""Small synchronous hook entry point. Never print a false success on failure."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from research_memory.storage import Config, Store
from research_memory.capture import hook


def main():
    payload = {}
    try:
        payload = json.load(sys.stdin)
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--root')
        args = parser.parse_args()
        result = hook(Store(Config(args.root or ROOT)), payload)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(f"Research memory capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        # Generic hooks cannot reliably classify arbitrary commands as read-only.
        # The run wrapper independently enforces durable intent before experiments.
        sys.exit(1)


if __name__ == "__main__":
    main()
