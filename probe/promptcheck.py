"""The prompt check: every prompt written in code passes the guard, and the guard still refuses known leaks.

A prompt is any string under an assignment to a name containing PROMPT or QUESTION, or under a keyword argument
containing ``prompt``. The harness guards every request again at run time. Run by scripts/leakcheck.sh.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from probe.guard import find_leak

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ("probe", "scripts")
PROMPT_NAME = re.compile(r"prompt|question", re.I)
# One of each kind the guard must refuse. If any passes, the check fails: a broken guard must not pass as clean prompts.
CANARIES = (
    "TIC 123456789",
    "TOI-1234.01",
    "J1555+2726",
    "NGC 6543",
    "TESS sector data",
    "LoTSS DR3 map",
    "RA 238.853",
    "12:30:45",
    "cutout.fits",
    "https://example.org",
    "ESP_012345_1234",
)


def prompts_in(source: str) -> list[tuple[int, str]]:
    """(line, text) of every prompt string in Python ``source``."""
    found = []
    for node in ast.walk(ast.parse(source)):
        values = []
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and PROMPT_NAME.search(t.id) for t in node.targets):
                values.append(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name) and PROMPT_NAME.search(node.target.id):
                values.append(node.value)
        elif isinstance(node, ast.keyword) and node.arg and PROMPT_NAME.search(node.arg):
            values.append(node.value)
        for value in values:
            for sub in ast.walk(value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    found.append((sub.lineno, sub.value))
    return found


def problems(root: Path = ROOT) -> list[str]:
    out = [f"guard passed the canary {c!r}" for c in CANARIES if not find_leak(c)]
    for folder in SOURCES:
        for path in sorted((root / folder).glob("*.py")):
            for line, text in prompts_in(path.read_text()):
                hit = find_leak(text)
                if hit:
                    out.append(f"{path.relative_to(root)}:{line}: {hit}")
    return out


def main() -> int:
    found = problems()
    for p in found:
        print(p, file=sys.stderr)
    print(f"prompt check: {len(found)} problems")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
