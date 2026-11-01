"""The known-object cut on the ring-like rows, code only. Safe to kill and run again; ``simbad`` skips what it has.

    uv run python -I scripts/known_cut.py tune      # freezes the spokes threshold; commit it
    uv run python -I scripts/known_cut.py simbad    # one cone per position, one line as each lands
    uv run python -I scripts/known_cut.py measure   # every count the report quotes

The rule is in docs/proposals/known-cut-v1.md. ``simbad`` and ``measure`` refuse unless the rule, the code and the
frozen threshold are committed and unchanged. ``tune`` reads no field of a row with a ring-like first vote. A failed
query stops the run instead of counting as no match, so the result does not depend on the weather.
"""

from __future__ import annotations

import argparse
import json
import sys
import time as clock
import warnings
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from PIL import Image, ImageDraw

from probe import baselines as bl
from probe import known_cut as kc
from probe import radio
from probe import screen as sc
from scripts.list_fields import EARLIER_ITEMS, read_list
from scripts.prefilter import committed_unchanged
from scripts.radio_inputs import RESOLVER, TIMEOUT, _retry, read_decisions, resolve

RULE = Path("docs/proposals/known-cut-v1.md")
CODE = Path("probe/known_cut.py")
VOTES = Path("docs/reports/2026-10-31-screen/votes.jsonl")
ITEMS = Path("docs/reports/2026-10-31-baselines/items.json")
REPORT = Path("docs/reports/2026-11-01-known-cut")
SHEET_SEED = [radio.SEED, 6]
SHEET_COLUMNS, SHEET_ROWS, TILE, CAPTION = 6, 6, 240, 16


def adql(query: str) -> str:
    def fetch():
        params = {"request": "doQuery", "lang": "adql", "format": "csv", "query": query}
        r = requests.get(RESOLVER, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text

    return _retry(fetch, "SIMBAD")


def refuse_unfrozen(report: Path) -> bool:
    bad = [path for path in (RULE, CODE, report / "frozen_spokes.json") if not committed_unchanged(path)]
    for path in bad:
        print(f"{path} must be committed and unchanged first", file=sys.stderr)
    return bool(bad)


def first_votes(votes: Path = VOTES) -> dict[str, dict]:
    rows = sc.read_votes(votes)
    return {item: row for (item, vote), row in rows.items() if vote == sc.FIRST}


def field_of(path: Path, ra: float, dec: float) -> np.ndarray:
    with fits.open(path) as hdul:
        header, image = hdul[0].header, hdul[0].data
    return radio.centred_field(image, header, ra, dec)[0]


def tune(report: Path, data: Path, earlier_data: Path, votes: Path = VOTES) -> int:
    """The depth of every field that is not a cut's row, and the threshold from the ones the rule names."""
    report.mkdir(parents=True, exist_ok=True)
    path = report / "frozen_spokes.json"
    if path.exists():
        print(f"{path} exists; the threshold is tuned once", file=sys.stderr)
        return 1
    warnings.filterwarnings("ignore")
    earlier = json.loads(EARLIER_ITEMS.read_text())
    depths = {
        i["id"]: kc.negative_depth(field_of(earlier_data / "cutouts" / f"{i['id']}-6.fits", i["ra"], i["dec"]))
        for i in earlier
    }
    firsts = first_votes(votes)
    records = {r["id"]: r for r in json.loads(ITEMS.read_text())}
    others = [k for k, row in firsts.items() if sc.valid(row) and not sc.called(row)]
    artefact_rows = sorted(k for k in others if firsts[k]["answer"]["known_class"] == "imaging_artefact")
    listed = {
        k: kc.negative_depth(field_of(data / "cutouts" / f"{k}-6.fits", records[k]["ra"], records[k]["dec"]))
        for k in others
    }
    fit = bl.tune(**kc.spoke_fit_fields(earlier, depths | listed, artefact_rows))
    groups: dict[str, list] = {}
    for i in earlier:
        groups.setdefault(i["group"], []).append({"name": i["name"], "depth": round(depths[i["id"]], 2)})
    result = {
        "rule": str(RULE),
        "threshold": fit["threshold"],
        "fit": {
            "with_spokes_called": fit["circles_called"],
            "with_spokes": fit["circles"],
            "without_not_called": fit["lookalikes_not_called"],
            "without": fit["lookalikes"],
            "value": fit["youden_j"],
        },
        "artefact_rows": artefact_rows,
        "earlier_fields_by_group": groups,
        "not_ring_like_rows": {
            "n": len(listed),
            "percentiles_5_25_50_75_95": [
                round(float(v), 2) for v in np.percentile(list(listed.values()), [5, 25, 50, 75, 95])
            ],
            "at_or_above_the_threshold": sum(v >= fit["threshold"] for v in listed.values()),
            "depths": {k: round(v, 2) for k, v in sorted(listed.items())},
        },
    }
    path.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "not_ring_like_rows"}, indent=1))
    return 0


def positions(votes: Path) -> list[dict]:
    """Every position the cuts read: id, where, group, the ring's size, and its row where it has one."""
    majax = {r["id"]: r["majax"] for r in read_list()}
    records = json.loads(ITEMS.read_text())
    firsts = first_votes(votes)
    out = []
    for record in records:
        if sc.called(firsts.get(record["id"])):
            base = {"ra": record["ra"], "ring_arcsec": majax[record["id"]]}
            out.append(base | {"id": record["id"], "dec": record["dec"], "group": "ring_like_row"})
            shifted = record["dec"] + kc.SHIFT_ARCMIN / 60
            out.append(base | {"id": f"shift-{record['id']}", "dec": shifted, "group": "shifted"})
    for item in json.loads(EARLIER_ITEMS.read_text()):
        group = "circle" if item["group"] in radio.CIRCLE_GROUPS else item["group"]
        where = {"ra": item["ra"], "dec": item["dec"], "ring_arcsec": kc.SMALLEST_RING_ARCSEC}
        out.append(where | {"id": item["id"], "group": group, "name": item["name"], "circle_group": item["group"]})
    return out


def simbad(report: Path, votes: Path = VOTES) -> int:
    if refuse_unfrozen(report):
        return 1
    otypedef = report / "otypedef.csv"
    if not otypedef.exists():
        otypedef.write_text(adql("select otype,description,path from otypedef"))
    kc.families(otypedef.read_text())
    for name in kc.CALIBRATORS:
        resolve(name, report)
    path = report / "simbad.jsonl"
    done = {row["id"] for row in read_decisions(path)}
    text = path.read_text() if path.exists() else ""
    if text and not text.endswith("\n"):  # a line cut off by a kill
        with path.open("a") as f:
            f.write("\n")
    todo = [p for p in positions(votes) if p["id"] not in done]
    print(f"{len(done)} cones on disk, {len(todo)} to do", flush=True)
    start = clock.monotonic()
    for k, p in enumerate(todo, 1):
        matches = kc.parse_cone(adql(kc.cone_query(p["ra"], p["dec"])))
        with path.open("a") as f:
            f.write(json.dumps({"id": p["id"], "ra": p["ra"], "dec": p["dec"], "cone": matches}) + "\n")
        if k % 50 == 0:
            print(f"{k} of {len(todo)} in {clock.monotonic() - start:.0f} s", flush=True)
    print("done", flush=True)
    return 0


def _sheet(records: list[dict], out: Path, path: Path, caption) -> None:
    """For people: the row's id and what removed it. Never sent to a model."""
    sheet = Image.new("RGB", (SHEET_COLUMNS * TILE, SHEET_ROWS * (TILE + CAPTION)), "navy")
    draw = ImageDraw.Draw(sheet)
    for i, record in enumerate(records[: SHEET_COLUMNS * SHEET_ROWS]):
        x, y = (i % SHEET_COLUMNS) * TILE, (i // SHEET_COLUMNS) * (TILE + CAPTION)
        sheet.paste(Image.open(out / record["image_6"]).resize((TILE, TILE)), (x, y + CAPTION))
        draw.text((x + 2, y + 2), caption(record), fill="yellow")
    sheet.save(path)


def circle_names(rows: list[dict], cones: dict) -> dict[str, list[str]]:
    """SIMBAD objects named as a circle in the cone, per position. Removes nothing; added after the first measure."""
    named = {r["id"]: [m["main_id"] for m in cones[r["id"]] if "ORC" in m["main_id"]] for r in rows}
    return {key: names for key, names in named.items() if names}


def reading(rows: list[dict], left_others: list[dict], threshold: float, votes: dict) -> dict:
    """Counts for reading the result, added after the first measure; none removes a row or moves another count. The
    model's class is read here only, to describe what the cuts leave."""
    n = len(rows)
    classes = {}
    for row in left_others:
        name = votes[row["id"], sc.FIRST]["answer"]["known_class"]
        classes[name] = classes.get(name, 0) + 1
    circle_depths = [r["depth"] for r in rows if r["known_circle"]]
    return {
        "removed_by_any_of_rows": bl.count(sum(bool(r["removed_by"]) for r in rows), n),
        "removed_by_a_sky_cut_of_rows": bl.count(sum(bool(set(r["removed_by"]) & set(kc.SKY_CUTS)) for r in rows), n),
        "removed_by_spokes_of_rows": bl.count(sum(kc.SPOKES in r["removed_by"] for r in rows), n),
        "deepest_known_circle_row": max(circle_depths),
        "rows_flagged_had_the_threshold_been": {
            str(value): sum(
                kc.spoke_flag(r["depth"], r["peak_over_noise"], r["neighbour"], value) for r in rows
            )
            for value in (3.5, round(threshold, 2), 4.0, 4.5, 5.0)
        },
        "left_other_rows_by_the_models_class": dict(sorted(classes.items(), key=lambda kv: -kv[1])),
    }


def measure(report: Path, data: Path, earlier_data: Path, controls: Path, out: Path, votes: Path = VOTES) -> int:
    if refuse_unfrozen(report):
        return 1
    warnings.filterwarnings("ignore")
    threshold = json.loads((report / "frozen_spokes.json").read_text())["threshold"]
    family = kc.families((report / "otypedef.csv").read_text())
    resolved = json.loads((report / "resolved.json").read_text())
    calibrators = {name: resolved[name] for name in kc.CALIBRATORS if resolved.get(name)}
    unresolved = [name for name in kc.CALIBRATORS if not resolved.get(name)]
    cones = {row["id"]: row["cone"] for row in read_decisions(report / "simbad.jsonl")}
    wanted = positions(votes)
    missing = [p["id"] for p in wanted if p["id"] not in cones]
    if missing:
        print(f"{len(missing)} cones are not fetched yet; run simbad", file=sys.stderr)
        return 1
    bright = dict(np.load(data.parent / "prefilter" / "bright.npz"))
    all_votes = sc.read_votes(votes)
    records = {r["id"]: r for r in json.loads(ITEMS.read_text())}

    measured = []
    for p in wanted:
        found = kc.sky_matches(p["ra"], p["dec"], p["ring_arcsec"], cones[p["id"]], family, calibrators)
        row = p | {"found": found}
        if p["group"] != "shifted":
            folder = data if p["group"] == "ring_like_row" else earlier_data
            field = field_of(folder / "cutouts" / f"{p['id']}-6.fits", p["ra"], p["dec"])
            depth, peak = kc.negative_depth(field), kc.peak_over_noise(field)
            neighbour = kc.brightest_neighbour(p["ra"], p["dec"], bright)
            spokes = kc.spoke_flag(depth, peak, neighbour, threshold)
            row |= {"depth": round(depth, 3), "peak_over_noise": round(peak, 1), "neighbour": neighbour}
            row["deep_with_no_bright_source"] = bool(depth >= threshold) and not spokes
        else:
            spokes = False
        row["removed_by"] = kc.removed_by(found, spokes)
        measured.append(row)

    ring_rows = [m for m in measured if m["group"] == "ring_like_row"]
    for row in ring_rows:
        record = records[row["id"]]
        row |= {
            "name": record["name"],
            "known_circle": record.get("known_circle"),
            "two_votes": sc.called(all_votes.get((row["id"], sc.SECOND))),
            "second_vote": all_votes.get((row["id"], sc.SECOND), {}).get("prediction"),
            "image_6": record["image_6"],
            "image_20": record["image_20"],
        }
    (report / "rows.json").write_text(json.dumps(ring_rows, indent=1) + "\n")

    circles = {
        obj["name"]: group
        for group in radio.CIRCLE_GROUPS
        for obj in json.loads((controls / f"{group}.json").read_text())["objects"]
    }
    published = [m for m in measured if m["group"] == "circle"]
    left = [r for r in ring_rows if not r["removed_by"]]
    left_others = [r for r in left if not r["known_circle"]]
    groups = sorted({m["group"] for m in measured} - {"ring_like_row", "shifted", "circle", "random"})
    result = {
        "rule": str(RULE),
        "threshold": threshold,
        "calibrators_resolved": sorted(calibrators),
        "calibrators_unresolved": unresolved,
        "rows": {
            "ring_like_rows": len(ring_rows),
            "known_circle_rows": sum(bool(r["known_circle"]) for r in ring_rows),
            "other_rows": sum(not r["known_circle"] for r in ring_rows),
            "with_two_ring_like_votes": sum(r["two_votes"] for r in ring_rows),
            "removed_by_any_cut": sum(bool(r["removed_by"]) for r in ring_rows),
            "left": len(left),
            "left_known_circle_rows": sum(bool(r["known_circle"]) for r in left),
            "left_other_rows": len(left_others),
            "left_other_rows_with_two_votes": sum(r["two_votes"] for r in left_others),
            "left_other_rows_second_vote_not_ring_like": sum(r["second_vote"] == radio.NOT_RING for r in left_others),
            "left_other_rows_with_no_second_vote": [r["id"] for r in left_others if r["second_vote"] is None],
            "left_other_objects_within_3_arcmin": len(kc.link_objects(left_others)),
            "left_other_objects_with_two_votes": len(kc.link_objects([r for r in left_others if r["two_votes"]])),
            "deep_with_no_bright_source": [r["id"] for r in ring_rows if r["deep_with_no_bright_source"]],
            "rows_with_a_galaxy_of_no_size": sum(bool(r["found"]["galaxy_no_size"]) for r in ring_rows),
            "rows_with_a_galaxy_above_half_the_ring_only": sum(
                bool(r["found"]["galaxy_above_half_the_ring"]) and not r["found"][kc.GALAXY_LARGER] for r in ring_rows
            ),
            "left_rows_with_a_galaxy_of_no_size": sum(bool(r["found"]["galaxy_no_size"]) for r in left),
            "left_rows_with_a_galaxy_above_half_the_ring": sum(
                bool(r["found"]["galaxy_above_half_the_ring"]) for r in left
            ),
        },
        "cuts": kc.cut_counts(ring_rows),
        "chain": kc.circle_chain(ring_rows, circles),
        "published_positions": {
            **kc.control_counts(published),
            "by_circle": {
                m["name"]: {
                    "group": m["circle_group"],
                    "removed_by": m["removed_by"],
                    "depth": m["depth"],
                    "peak_over_noise": m["peak_over_noise"],
                    "neighbour": m["neighbour"],
                    "matches": {
                        cut: [hit["main_id"] for hit in m["found"][cut]] for cut in kc.CUTS if m["found"].get(cut)
                    },
                }
                for m in published
            },
            "circles_removed_by_cut": {
                name: sorted(m["name"] for m in published if name in m["removed_by"]) for name in kc.CUTS
            },
        },
        "chance_matches": kc.control_counts([m for m in measured if m["group"] == "shifted"]),
        "lookalikes": {g: kc.control_counts([m for m in measured if m["group"] == g]) for g in groups},
        "random": kc.control_counts([m for m in measured if m["group"] == "random"]),
        "reading": reading(ring_rows, left_others, threshold, all_votes),
        "depth_of_ring_like_rows_percentiles_5_25_50_75_95": [
            round(float(v), 2) for v in np.percentile([r["depth"] for r in ring_rows], [5, 25, 50, 75, 95])
        ],
    }
    result["reading"] |= {
        "chance_matches_of_positions": bl.count(result["chance_matches"]["removed_by_any"], len(ring_rows)),
        "simbad_orc_names_at_published_positions": circle_names(published, cones),
        "simbad_orc_names_at_ring_like_rows": circle_names(ring_rows, cones),
    }
    (report / "summary.json").write_text(json.dumps(result, indent=1) + "\n")

    sheets = report / "contact_sheets"
    sheets.mkdir(exist_ok=True)
    rng = np.random.default_rng(SHEET_SEED)
    two = [r for r in left_others if r["two_votes"]]
    pick = [two[int(k)] for k in rng.permutation(len(two))]
    _sheet(pick, out, sheets / "left_two_votes-6.png", lambda r: r["id"])
    hit = [r for r in ring_rows if kc.SPOKES in r["removed_by"]]
    pick = [hit[int(k)] for k in rng.permutation(len(hit))]
    _sheet(pick, out, sheets / "spokes-6.png", lambda r: f"{r['id']} depth {r['depth']:.1f}")
    sky = [r for r in ring_rows if set(r["removed_by"]) & set(kc.SKY_CUTS)]
    _sheet(sky, out, sheets / "sky_cuts-6.png", lambda r: f"{r['id']} {','.join(r['removed_by'])[:24]}")
    print(json.dumps({k: result[k] for k in ("rows", "reading", "chance_matches")}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=("tune", "simbad", "measure"))
    ap.add_argument("--data", default="data/radio_list")
    ap.add_argument("--earlier-data", default="data/radio")
    ap.add_argument("--out", default="out/radio_list")
    ap.add_argument("--report", default=str(REPORT))
    ap.add_argument("--controls", default="controls")
    a = ap.parse_args(argv)
    data, earlier, out, report = Path(a.data), Path(a.earlier_data), Path(a.out), Path(a.report)
    if a.step == "tune":
        return tune(report, data, earlier)
    if a.step == "simbad":
        return simbad(report)
    return measure(report, data, earlier, Path(a.controls), out)


if __name__ == "__main__":
    sys.exit(main())
