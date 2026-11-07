"""The README's figures: panels of the board's rows by verdict, drawn from the board's own maps. No model call, no
query, no grade. Safe to run again.

    uv run python -I scripts/readme_figures.py

It reads the committed verdicts.json and summary.json of the case board, writes the panels and figures.json under the
report's figures folder, and rewrites the README's figures section between its markers. It stops if a panel's count
disagrees with the summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from probe import figures as fg

# The same paths scripts/case_board.py uses; not imported from it, because a sibling repo's scripts.case_board
# shadows it in isolated mode.
REPORT = Path("docs/reports/2026-11-01-case-board")
README = Path("README.md")


def build(report: Path, readme: Path) -> int:
    summary = json.loads((report / "summary.json").read_text())
    verdicts = json.loads((report / "verdicts.json").read_text())
    spec = fg.draw_figures(report, verdicts)
    section = fg.figures_section(summary, spec)
    (report / fg.FOLDER / "figures.json").write_text(json.dumps(spec, indent=1) + "\n")
    readme.write_text(fg.with_figures(readme.read_text(), section))
    for key, part in spec.items():
        print(f"{key}: {len(part['rows'])} tiles in {part['file']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", default=str(REPORT))
    ap.add_argument("--readme", default=str(README))
    a = ap.parse_args(argv)
    return build(Path(a.report), Path(a.readme))


if __name__ == "__main__":
    sys.exit(main())
