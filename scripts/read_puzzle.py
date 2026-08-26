#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read a field from a situation puzzle JSON file."
    )
    parser.add_argument("file", help="Puzzle JSON file path")
    parser.add_argument(
        "--field",
        choices=[
            "surface",
            "solution",
            "hints",
            "hint",
            "key_facts",
            "type",
            "difficulty",
        ],
        required=True,
    )
    parser.add_argument("--index", type=int, default=0, help="Hint index for --field hint")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))

    if args.field == "hint":
        hints = payload.get("hints", [])
        if not hints:
            return 1
        index = min(max(args.index, 0), len(hints) - 1)
        print(hints[index])
        return 0

    value = payload.get(args.field)
    if isinstance(value, list):
        print(json.dumps(value, ensure_ascii=False))
    else:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
