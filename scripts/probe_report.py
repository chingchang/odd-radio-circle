"""Copy a real run's results into a report folder and write what the report quotes: the wrong answers and their reasons.

    uv run python -I scripts/probe_report.py tess docs/reports/2026-10-31-probe-tess
    uv run python -I scripts/probe_report.py radio_ring docs/reports/2026-10-31-probe-orc
    uv run python -I scripts/probe_report.py radio_ring_zoom docs/reports/2026-10-31-probe-orc-zoom

``answers.json`` holds per item the label, the prediction and the reason, plus the group for the radio fields.
``wrong.md`` lists the items the bar counts that were answered wrongly. The TESS sheets it lists are copied beside it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from probe.harness import _read_rows

BASELINES = {"tess": "code_rule", "radio_ring": "annulus", "radio_ring_zoom": "annulus"}
FILES = ("score.json", "score.md", "score_all.json", "score_all.md", "bar.json", "ranks.json", "records.jsonl")
SCORED = {"tess": ("planet", "eclipsing_binary")}


def cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "/")


def copy_results(source: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        if (source / name).exists():
            shutil.copy2(source / name, dest / name)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("probe", choices=sorted(BASELINES))
    ap.add_argument("folder")
    ap.add_argument("--out-root", default="out")
    a = ap.parse_args(argv)
    out_root, folder = Path(a.out_root), Path(a.folder)
    root = out_root / a.probe
    copy_results(root / "real", folder / "real")
    copy_results(root / BASELINES[a.probe], folder / BASELINES[a.probe])
    copy_results(out_root / f"{a.probe}_recognition" / "real", folder / "recognition")
    shutil.copy2(out_root / "ledger.json", folder / "ledger.json")

    records = {r["id"]: r for r in json.loads((root / "items.json").read_text())}
    answers = []
    for item_id, row in _read_rows(root / "real" / "records.jsonl").items():
        answers.append(
            {
                "id": item_id,
                "group": records[item_id].get("group"),
                "label": row["label"],
                "prediction": row["prediction"],
                "reason": row.get("answer", {}).get("reason", row.get("error", "")),
            }
        )
    (folder / "answers.json").write_text(json.dumps(answers, indent=1) + "\n")

    scored = SCORED.get(a.probe)
    wrong = [r for r in answers if r["label"] != r["prediction"] and (scored is None or r["label"] in scored)]
    lines = ["| item | group | label | answer | reason given |", "|---|---|---|---|---|"]
    lines += [
        f"| {r['id']} | {r['group'] or ''} | {r['label']} | {r['prediction']} | {cell(r['reason'])} |" for r in wrong
    ]
    (folder / "wrong.md").write_text("\n".join(lines) + "\n")
    if a.probe == "tess":
        sheets = folder / "wrong_sheets"
        sheets.mkdir(exist_ok=True)
        for r in wrong:
            shutil.copy2(root / records[r["id"]]["sheet"], sheets / f"{r['id']}.png")
    print(f"{a.probe}: {len(answers)} answers, {len(wrong)} wrong among those the bar counts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
