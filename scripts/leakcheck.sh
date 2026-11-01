#!/bin/bash
# The prompt check. Called by check.sh and, after each item, by run_plan.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python -m probe.promptcheck
