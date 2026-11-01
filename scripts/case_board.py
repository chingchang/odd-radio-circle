"""The case board and the circles page. No model call and no query; it reads what items 2 to 5 wrote. Safe to run again.

    uv run python -I scripts/case_board.py

The rule is in docs/proposals/case-board-v1.md. It refuses unless the rule and the code are committed and unchanged,
and stops if its counts disagree with the screen's or the cut's summaries.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from probe import case_board as cb
from probe import radio
from probe import screen as sc
from scripts.list_fields import EARLIER_ITEMS
from scripts.prefilter import committed_unchanged
from scripts.radio_inputs import read_decisions

RULE = Path("docs/proposals/case-board-v1.md")
CODE = Path("probe/case_board.py")
VOTES = Path("docs/reports/2026-10-31-screen/votes.jsonl")
SCREEN = Path("docs/reports/2026-10-31-screen/summary.json")
ITEMS = Path("docs/reports/2026-10-31-baselines/items.json")
BASELINES = Path("docs/reports/2026-10-31-baselines/baselines.json")
PREFILTER = Path("docs/reports/2026-10-31-prefilter/summary.json")
CUT = Path("docs/reports/2026-11-01-known-cut")
REPORT_NAME = "2026-11-01-case-board"
REPORT = Path("docs/reports") / REPORT_NAME
README = Path("README.md")


def read_json(path: Path):
    return json.loads(path.read_text())


def check_against_earlier(summary: dict, screen: dict, cut: dict) -> None:
    """Stop if the grade's counts have moved away from what the earlier items reported."""
    other, rows, chain = summary["verdicts"]["other_rows"], cut["rows"], cut["chain"]["counts"]["all"]
    pairs = [
        ("candidate rows", other[cb.CANDIDATE], rows["left_other_rows_with_two_votes"]),
        ("board rows", other[cb.CANDIDATE] + other[cb.SECOND_LOOK], rows["left_other_rows"]),
        ("not assessed", other[cb.NOT_ASSESSED], screen["rows"]["not_assessed"]),
        ("board objects", summary["objects"]["board_objects"], rows["left_other_objects_within_3_arcmin"]),
        ("candidate objects", summary["objects"]["candidate_objects"], rows["left_other_objects_with_two_votes"]),
        ("circles left", summary["circles"]["left"]["called"], chain["left"]["called"]),
        ("circles with two votes", summary["circles"]["candidate"]["called"], chain["left_with_two_votes"]["called"]),
    ]
    wrong = [f"{name}: {a} here, {b} there" for name, a, b in pairs if a != b]
    if wrong:
        raise ValueError("; ".join(wrong))


def prefilter_text(circle: dict) -> str:
    near = len(circle["rows"])
    listed = sum(r["listed"] for r in circle["rows"])
    if not near:
        return "no catalogue row within 60 arcsec above the size floor"
    return f"{listed} of {near} catalogue rows within 60 arcsec listed"


def build(report: Path, out: Path, earlier_out: Path, readme: Path) -> int:
    bad = [path for path in (RULE, CODE) if not committed_unchanged(path)]
    for path in bad:
        print(f"{path} must be committed and unchanged first", file=sys.stderr)
    if bad:
        return 1

    records = read_json(ITEMS)
    by_id = {r["id"]: r for r in records}
    cut_rows = {r["id"]: r for r in read_json(CUT / "rows.json")}
    votes = sc.read_votes(VOTES)
    cut, screen = read_json(CUT / "summary.json"), read_json(SCREEN)
    prefilter, baselines = read_json(PREFILTER), read_json(BASELINES)
    threshold = read_json(CUT / "frozen_spokes.json")["threshold"]
    cones = {row["id"]: row["cone"] for row in read_decisions(CUT / "simbad.jsonl")}
    grades = cb.graded(records, cut_rows, votes)

    board = cb.board_rows(grades)
    left_rows = [cut_rows[g["id"]] for g in board]
    linked = cb.linked_rows(left_rows)
    copied = 0
    cards = []
    for g in board:
        row, record = cut_rows[g["id"]], by_id[g["id"]]
        first, second = votes[g["id"], sc.FIRST], votes.get((g["id"], sc.SECOND))
        images = {}
        for key, digest in zip(("image_6", "image_20"), first["images"], strict=True):
            name = Path(record[key]).name
            copied += cb.copy_checked(out / record[key], report / "images" / name, digest["sha256"])
            images[key] = f"images/{name}"
        cards.append(
            row
            | g
            | images
            | {
                "first": first,
                "second": second if sc.valid(second) else None,
                "cone": cones[g["id"]],
                "threshold": threshold,
                "linked": linked[g["id"]],
                "beam_6": record["measures"]["beam_arcsec_6"],
            }
        )

    circles = []
    earlier = {i["name"]: i for i in read_json(EARLIER_ITEMS) if i["group"] in radio.CIRCLE_GROUPS}
    for name, outcome in screen["circles"].items():
        item = earlier[name]
        images = {}
        for key in ("image_6", "image_20"):
            image = Path(item[key]).name
            copied += cb.copy_checked(earlier_out / item[key], report / "images" / image)
            images[key] = f"images/{image}"
        published = cut["published_positions"]["by_circle"][name]
        circles.append(
            images
            | {
                "name": name,
                "group": outcome["group"],
                "earlier_call": outcome["earlier_two_image_call_at_published_position"],
                "prefilter": prefilter_text(prefilter["circles"][name]),
                "annulus_tuned": baselines["circles"][name]["through_list"]["annulus_tuned"],
                "removed_at_published": published["removed_by"],
                "lost_at": cb.lost_at(outcome["listed_rows"], grades),
                "rows": [
                    {
                        "id": i,
                        "first": votes[i, sc.FIRST]["prediction"],
                        "second": votes[i, sc.SECOND]["prediction"] if (i, sc.SECOND) in votes else None,
                        "verdict": grades[i]["verdict"],
                        "reason": votes[i, sc.FIRST]["answer"]["reason"],
                    }
                    for i in outcome["listed_rows"]
                ],
            }
        )

    circle_rows = {name: outcome["listed_rows"] for name, outcome in screen["circles"].items()}
    groups = {name: outcome["group"] for name, outcome in screen["circles"].items()}
    summary = {
        "rule": str(RULE),
        "folder": str(report),
        "report_name": REPORT_NAME,
        "threshold": threshold,
        "list": {
            "rows": screen["rows"]["rows"],
            "voted": screen["rows"]["valid_first_vote"],
            "ring_like": screen["rows"]["first_vote_ring_like"],
        },
        "cost": {"stop_usd": screen["cost"]["stop_usd"], "ledger_usd": screen["cost"]["ledger_after_usd"]},
        "published_positions_removed": cut["published_positions"]["removed_by_any"],
        "images_copied_bytes": copied,
    } | cb.counts(grades, left_rows, circle_rows, groups)
    summary["circles"] |= {
        "on_list": screen["circles_objects"]["all"]["on_list"],
        "one_vote": screen["circles_objects"]["all"]["one_vote"],
    }
    check_against_earlier(summary, screen, cut)

    report.mkdir(parents=True, exist_ok=True)
    (report / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    rows_out = [
        g | {"name": by_id[g["id"]]["name"], "ra": by_id[g["id"]]["ra"], "dec": by_id[g["id"]]["dec"]}
        for g in grades.values()
        if g["id"] in cut_rows
    ]
    (report / "verdicts.json").write_text(json.dumps(rows_out, indent=1) + "\n")
    (report / "board.html").write_text(cb.render_board(summary, cards))
    (report / "circles.html").write_text(cb.render_circles(summary, circles))
    readme.write_text(cb.with_results(readme.read_text(), cb.results_section(summary)))
    print(json.dumps(summary, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="out/radio_list")
    ap.add_argument("--earlier-out", default="out/radio_ring")
    ap.add_argument("--report", default=str(REPORT))
    ap.add_argument("--readme", default=str(README))
    a = ap.parse_args(argv)
    return build(Path(a.report), Path(a.out), Path(a.earlier_out), Path(a.readme))


if __name__ == "__main__":
    sys.exit(main())
