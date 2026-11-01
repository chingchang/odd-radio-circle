"""The Wonder screen of the pre-filter list. Safe to kill and run again; ``run`` skips the votes it has.

    uv run python -I scripts/screen.py run --backend real --limit 200   # commit votes.jsonl between parts
    uv run python -I scripts/screen.py summary                          # every count the report quotes

The rule is in docs/proposals/screen-v1.md. ``run`` refuses unless that rule and the list's items file are committed and
unchanged. It exits 3 at the dollar stop, which is an expected end.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.units import arcmin, deg
from landers.models.ledger import PRICES_USD, spent_usd

from probe import radio
from probe import screen as sc
from probe.harness import PROJECT_CAP_USD, RunAborted
from scripts.list_fields import contact_sheet
from scripts.prefilter import committed_unchanged

RULE = Path("docs/proposals/screen-v1.md")
ITEMS = Path("docs/reports/2026-10-31-baselines/items.json")
EARLIER_RUN = Path("docs/reports/2026-10-31-probe-orc/real/records.jsonl")
BASELINE_CALLS = Path("docs/reports/2026-10-31-baselines/records.jsonl")
SHEET_SEED = [radio.SEED, 5]
LEDGER_BEFORE_USD = 6.7601  # out/ledger.json before this run's first call, as the rule says


def refuse_unfrozen(items_path: Path) -> bool:
    bad = [str(path) for path in (RULE, ITEMS) if not committed_unchanged(path)]
    if items_path.read_bytes() != ITEMS.read_bytes():
        bad.append(str(items_path))
    for path in bad:
        print(f"{path} must be committed, unchanged and the same as the list's items", file=sys.stderr)
    return bool(bad)


def reported_tokens(recordings: Path) -> dict:
    """What the API itself reported, from the recordings, which the ledger's image floor does not touch."""
    results = [json.loads(path.read_text())["result"] for path in recordings.glob("vote*/wonder_*.json")]
    return {
        "calls_recorded": len(results),
        "input_tokens": sum(r["input_tokens"] for r in results),
        "output_tokens": sum(r["output_tokens"] for r in results),
    }


def summary(items_path: Path, out_root: Path, report: Path, controls: Path) -> int:
    records = json.loads(items_path.read_text())
    rows = sc.read_votes(report / "votes.jsonl")
    circles = {
        obj["name"]: group
        for group in radio.CIRCLE_GROUPS
        for obj in json.loads((controls / f"{group}.json").read_text())["objects"]
    }
    outcomes = sc.circle_outcomes(records, rows, circles)

    ring = [r for r in records if sc.called(rows.get((r["id"], sc.FIRST)))]
    with_neighbour = 0
    if len(ring) > 1:
        here = SkyCoord(np.array([r["ra"] for r in ring]) * deg, np.array([r["dec"] for r in ring]) * deg)
        a, b, _, _ = here.search_around_sky(here, radio.FIELD_ARCMIN / 2 * arcmin)
        with_neighbour = len({int(i) for i, j in zip(a, b, strict=True) if i != j})

    ledger = json.loads((out_root / "ledger.json").read_text())
    shutil.copy(out_root / "ledger.json", report / "ledger.json")
    votes = list(rows.values())
    seconds = [row["seconds"] for row in votes]
    row_counts = sc.row_counts(records, rows)
    api = reported_tokens(out_root / sc.SPEC.name / "recordings")
    prices = PRICES_USD["wonder"]
    this_run = round(ledger["total_cost_usd"] - LEDGER_BEFORE_USD, 4)
    per_row = this_run / max(row_counts["reached"], 1)

    earlier = {r["item_id"]: r["prediction"] for r in map(json.loads, EARLIER_RUN.read_text().splitlines())}
    for name, outcome in outcomes.items():
        outcome["earlier_two_image_call_at_published_position"] = earlier[f"{outcome['group']}-{name}"]

    baseline_rows = map(json.loads, BASELINE_CALLS.read_text().splitlines())
    tuned = {r["item_id"]: r["calls"]["annulus_tuned"] for r in baseline_rows}
    overlap = {"first_vote_ring_like": [0, 0], "first_vote_not_ring_like": [0, 0]}
    for row in votes:
        if row["vote"] == sc.FIRST and sc.valid(row):
            tally = overlap["first_vote_ring_like" if sc.called(row) else "first_vote_not_ring_like"]
            tally[0] += tuned[row["item_id"]] == radio.RING
            tally[1] += 1

    said_ring = [o for o in outcomes.values() if o["earlier_two_image_call_at_published_position"] == radio.RING]
    on_list = [o for o in outcomes.values() if o["on_list"]]
    result = {
        "rule": str(RULE),
        "earlier_two_image_run": {
            "circles_called_ring_like": len(said_ring),
            "circles": len(outcomes),
            "of_those_lost_by_the_prefilter": sum(not o["on_list"] for o in said_ring),
            "listed_circles": len(on_list),
            "listed_circles_with_the_same_call_now": sum(
                (o["earlier_two_image_call_at_published_position"] == radio.RING) == o["one_vote"] for o in on_list
            ),
        },
        "rows": row_counts,
        "reading": sc.reading_counts(records, rows),
        "tuned_annulus_calls_ring_like_of_rows": overlap,
        "ring_like_rows_with_another_within_3_arcmin": with_neighbour,
        "circles_objects": sc.circle_counts(outcomes),
        "circles": outcomes,
        "cost": {
            "usd_per_row_reached": round(per_row, 4),
            "room_under_the_project_cap_usd": round(PROJECT_CAP_USD - ledger["total_cost_usd"], 4),
            "not_assessed_rows_at_that_rate_usd": round(row_counts["not_assessed"] * per_row, 2),
            "api_reported_tokens_at_ledger_prices_usd": round(
                api["input_tokens"] * prices["input_token"] + api["output_tokens"] * prices["output_token"], 4
            ),
            "landers_register_total_without_this_project_usd": spent_usd(),
            "ledger_before_usd": LEDGER_BEFORE_USD,
            "ledger_after_usd": ledger["total_cost_usd"],
            "this_run_usd": this_run,
            "stop_usd": sc.STOP_USD,
            "votes_with_a_row": len(votes),
            "votes_failed": sum("error" in row for row in votes),
            "ledger_calls_over_all_runs": ledger["entries"]["wonder"],
            "api_reported": api,
            "median_seconds_per_call": round(float(np.median(seconds)), 2) if seconds else None,
        },
    }
    (report / "summary.json").write_text(json.dumps(result, indent=1) + "\n")

    two = [
        r | {"row_id": r["id"]}
        for r in records
        if sc.called(rows.get((r["id"], sc.FIRST))) and sc.called(rows.get((r["id"], sc.SECOND)))
    ]
    sample = [two[int(k)] for k in np.random.default_rng(SHEET_SEED).permutation(len(two))]
    sheets = report / "contact_sheets"
    sheets.mkdir(exist_ok=True)
    for resolution in (6, 20):
        contact_sheet(sample, f"image_{resolution}", items_path.parent, sheets / f"two_votes-{resolution}.png")
    print(json.dumps({key: value for key, value in result.items() if key != "circles"}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=("run", "summary"))
    ap.add_argument("--backend", default="fake", help="fake or real")
    ap.add_argument("--items", default="out/radio_list/items.json")
    ap.add_argument("--out-root", default="out")
    ap.add_argument("--report", default="docs/reports/2026-10-31-screen")
    ap.add_argument("--controls", default="controls")
    ap.add_argument("--limit", type=int, help="work on at most this many rows, to commit between parts")
    a = ap.parse_args(argv)
    items_path, out_root, report = Path(a.items), Path(a.out_root), Path(a.report)
    if a.step == "summary":
        return summary(items_path, out_root, report, Path(a.controls))
    if refuse_unfrozen(items_path):
        return 1
    items, records = radio.load_items(items_path)
    clients = sc.open_clients(a.backend, out_root)
    try:
        result = sc.run(items, sc.order(list(records.values())), clients, report / "votes.jsonl", a.limit)
    except RunAborted as e:
        print(f"{e}; run again to continue", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 3 if result["status"].startswith("stopped") else 0


if __name__ == "__main__":
    sys.exit(main())
