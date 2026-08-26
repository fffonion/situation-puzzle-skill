#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def parse_fact(raw: str) -> dict[str, str]:
    if "::" not in raw:
        raise argparse.ArgumentTypeError(
            "fact must use the form 'yes::statement', 'no::statement', or 'irrelevant::statement'"
        )
    answer, statement = raw.split("::", 1)
    answer = answer.strip().lower()
    statement = statement.strip()
    if answer not in {"yes", "no", "irrelevant"}:
        raise argparse.ArgumentTypeError("fact answer must be yes, no, or irrelevant")
    if not statement:
        raise argparse.ArgumentTypeError("fact statement must not be empty")
    return {"answer": answer, "statement": statement}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Save a situation puzzle to the private local store."
    )
    parser.add_argument("--type", dest="puzzle_type", required=True)
    parser.add_argument("--surface", required=True)
    parser.add_argument("--solution", required=True)
    parser.add_argument("--hint", action="append", default=[])
    parser.add_argument("--fact", action="append", type=parse_fact, default=[])
    parser.add_argument("--difficulty", choices=["简单", "中等", "困难"], default="中等")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    store_dir = Path.home() / ".cache" / "turtlesoup"
    store_dir.mkdir(parents=True, exist_ok=True)
    store_dir.chmod(0o700)

    created_at = datetime.now(timezone.utc)
    puzzle_id = f"puzzle-{created_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    output_path = store_dir / f"{puzzle_id}.json"

    payload = {
        "id": puzzle_id,
        "type": args.puzzle_type,
        "surface": args.surface.strip(),
        "solution": args.solution.strip(),
        "hints": [hint.strip() for hint in args.hint if hint.strip()],
        "key_facts": args.fact,
        "difficulty": args.difficulty,
        "created_at": created_at.isoformat(),
        "format_version": 1,
    }

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_path.chmod(0o600)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
