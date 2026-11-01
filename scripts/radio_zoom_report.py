"""Set the zoom run against the first run and write what its report quotes. Run after ``scripts/probe_report.py``.

    uv run python -I scripts/radio_zoom_report.py docs/reports/2026-10-31-probe-orc-zoom

``comparison.json`` holds the counts, ``changes.md`` every answer that changed with both reasons, and
``missed_circles/`` the zoomed views of every circle still missed. These names are for people and never reach a model.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from probe import radio
from probe.harness import _read_rows
from probe.score import wilson
from scripts.probe_report import cell

CANDIDATE = "candidate"


def _rate(k: int, n: int) -> dict:
    return {"count": k, "of": n, "wilson_95": [round(x, 4) for x in wilson(k, n)]}


def _reason(row: dict) -> str:
    return row.get("answer", {}).get("reason", row.get("error", ""))


def white_fraction(path: Path) -> float:
    """How much of a view is at full white, so that any structure there is lost."""
    return round(float((np.asarray(Image.open(path).convert("L")) == 255).mean()), 3)


def saturation(records: list[dict], rows: dict[str, dict], root: Path) -> dict:
    """Each circle's white fractions in its two zoomed views, and the median over those called and those missed."""
    circles = {
        r["id"]: {"called": rows[r["id"]]["prediction"] == radio.RING}
        | {key: white_fraction(root / r[key]) for key in ("zoom_6", "zoom_20")}
        for r in records
        if r["label"] == radio.RING
    }
    medians = {
        name: {
            key: round(float(np.median([c[key] for c in circles.values() if c["called"] == called])), 3)
            for key in ("zoom_6", "zoom_20")
        }
        for name, called in (("called", True), ("missed", False))
    }
    return {"circles": circles, "medians": medians}


def reported_tokens(rows: dict[str, dict], recordings: Path) -> dict:
    """What the API itself reported, from the recordings, which sit inside the ledger's per-image floor."""
    values = []
    for row in rows.values():
        path = next(recordings.glob(f"*{row['request_hash']}*"))
        values.append(json.loads(path.read_text())["result"]["input_tokens"])
    return {"least": min(values), "most": max(values), "total": sum(values)}


def compare(records: list[dict], first: dict[str, dict], zoom: dict[str, dict]) -> dict:
    """The counts of both runs and the answers that changed."""

    def part(called: list[dict], circles: list[dict], keep) -> dict:
        return _rate(sum(map(keep, called)), sum(map(keep, circles)))

    def run(rows: dict[str, dict]) -> dict:
        circles = [r for r in records if r["label"] == radio.RING]
        called = [r for r in circles if rows[r["id"]]["prediction"] == radio.RING]
        others = [r for r in records if r["label"] == radio.NOT_RING]
        rejected = [r for r in others if rows[r["id"]]["prediction"] == radio.NOT_RING]
        groups: dict[str, dict] = {}
        for r in others:
            g = groups.setdefault(r["group"], {"rejected": 0, "of": 0})
            g["of"] += 1
            g["rejected"] += rows[r["id"]]["prediction"] == radio.NOT_RING
        return {
            "circles_called_ring_like": _rate(len(called), len(circles)),
            "confirmed_called": part(called, circles, lambda r: r["class"] != CANDIDATE),
            "candidates_called": part(called, circles, lambda r: r["class"] == CANDIDATE),
            "tuning_called": part(called, circles, lambda r: r["group"] == "tuning"),
            "heldout_called": part(called, circles, lambda r: r["group"] == "heldout"),
            "others_rejected": _rate(len(rejected), len(others)),
            "others_rejected_by_group": groups,
            "circles_missed": [r["id"] for r in circles if rows[r["id"]]["prediction"] != radio.RING],
            "others_called_ring_like": [r["id"] for r in others if rows[r["id"]]["prediction"] != radio.NOT_RING],
        }

    changed = [
        {
            "id": r["id"],
            "group": r["group"],
            "class": r.get("class", ""),
            "label": r["label"],
            "first": first[r["id"]]["prediction"],
            "zoom": zoom[r["id"]]["prediction"],
            "now_right": zoom[r["id"]]["prediction"] == r["label"],
            "first_reason": _reason(first[r["id"]]),
            "zoom_reason": _reason(zoom[r["id"]]),
        }
        for r in records
        if first[r["id"]]["prediction"] != zoom[r["id"]]["prediction"]
    ]
    return {
        "first_run": run(first),
        "zoom_run": run(zoom),
        "changed": changed,
        "changed_to_right": sum(c["now_right"] for c in changed),
        "changed_to_wrong": sum(not c["now_right"] for c in changed),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--out-root", default="out")
    a = ap.parse_args(argv)
    folder, out_root = Path(a.folder), Path(a.out_root)
    root = out_root / radio.ZOOM_SPEC.name
    records = json.loads((root / "items.json").read_text())
    first = _read_rows(out_root / radio.SPEC.name / "real" / "records.jsonl")
    zoom = _read_rows(root / "real" / "records.jsonl")
    result = compare(records, first, zoom)
    result["zoom_run_cost_usd"] = round(sum(zoom[r["id"]]["cost_usd"] for r in records), 4)
    result["zoom_run_reported_input_tokens"] = reported_tokens(zoom, out_root / "model_recordings")
    result["circle_saturation"] = saturation(records, zoom, root)
    (folder / "comparison.json").write_text(json.dumps(result, indent=1) + "\n")

    lines = [
        "| item | group | label | first run | zoom run | reason, first run | reason, zoom run |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {c['id']} | {c['group']} | {c['label']} | {c['first']} | {c['zoom']} | {cell(c['first_reason'])} "
        f"| {cell(c['zoom_reason'])} |"
        for c in result["changed"]
    ]
    (folder / "changes.md").write_text("\n".join(lines) + "\n")

    missed = folder / "missed_circles"
    missed.mkdir(exist_ok=True)
    by_id = {r["id"]: r for r in records}
    for item_id in result["zoom_run"]["circles_missed"]:
        for key, resolution in (("zoom_6", 6), ("zoom_20", 20)):
            shutil.copy2(root / by_id[item_id][key], missed / f"{item_id}-{resolution}.png")
    print(json.dumps({k: v for k, v in result.items() if k != "changed"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
