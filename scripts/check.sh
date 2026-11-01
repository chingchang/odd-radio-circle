#!/bin/bash
# Tests, lint, prompt check. This decides done.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run pytest
uv run ruff check .
scripts/leakcheck.sh
