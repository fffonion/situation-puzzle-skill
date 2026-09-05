#!/usr/bin/env bash
set -euo pipefail

PASSWORD="123456"
EXPECTED_SHA256="cc3d013bddf0f67b83db6623b10f087951322cbc0213637f5a48171a22822003"
URL="https://github.com/fffonion/situation-puzzle-skill/releases/download/puzzle-library-v1/situation-puzzle-library-v1.zip"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DESTINATION="${1:-$SKILL_DIR/references}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ARCHIVE="$TMP_DIR/situation-puzzle-library-v1.zip"

if [[ -n "${PUZZLE_LIBRARY_ARCHIVE:-}" ]]; then
  cp "$PUZZLE_LIBRARY_ARCHIVE" "$ARCHIVE"
else
  curl -fL "$URL" -o "$ARCHIVE"
fi

echo "$EXPECTED_SHA256  $ARCHIVE" | sha256sum -c -
mkdir -p "$TMP_DIR/extracted" "$DESTINATION"
unzip -q -P "$PASSWORD" "$ARCHIVE" 'situation-puzzle-library-v1/MASTER_all_puzzles.json' -d "$TMP_DIR/extracted"
install -m 600 "$TMP_DIR/extracted/situation-puzzle-library-v1/MASTER_all_puzzles.json" "$DESTINATION/MASTER_all_puzzles.json"
echo "$DESTINATION/MASTER_all_puzzles.json"
