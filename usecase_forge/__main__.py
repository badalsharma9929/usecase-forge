"""Command line entry point.

    python -m usecase_forge https://byjus.com/ --extra https://byjus.com/about-us/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from usecase_forge.graph import default_dependencies, stream_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate grounded GenAI use cases for a company website.")
    parser.add_argument("url", help="Company homepage URL")
    parser.add_argument("--extra", nargs="*", default=[], help="More pages to read (about, products, ...)")
    parser.add_argument("--out", default="output", help="Folder for the report (default: output)")
    args = parser.parse_args(argv)
    # Windows consoles default to cp1252; company names and LLM text may not fit it.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        deps = default_dependencies()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    state: dict = {}
    printed = 0
    try:
        for state in stream_pipeline(args.url, deps, args.extra):
            for line in state.get("log", [])[printed:]:
                print(f"  - {line}")
            printed = len(state.get("log", []))
    except Exception as exc:
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        if "NOT_FOUND" in str(exc):
            print("Hint: set GEMINI_MODEL in .env to a model your key can use.", file=sys.stderr)
        return 1

    slug = re.sub(r"[^a-z0-9]+", "-", state["profile"].name.lower()).strip("-") or "company"
    out_dir = Path(args.out) / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(state["report"], encoding="utf-8")
    data = {
        "profile": state["profile"].model_dump(),
        "scores": state.get("scores", []),
        "results": [r.model_dump() for r in state["results"]],
        "sources": [s.model_dump() for s in state["sources"]],
    }
    (out_dir / "results.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport written to {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
