"""Cutouts and code baselines for the pre-filter list. Safe to kill and run again; ``fetch`` skips the fields it has.

    uv run python -I scripts/list_fields.py tune     # freezes the tuned threshold; commit it
    uv run python -I scripts/list_fields.py fetch    # both maps of every listed source, drawn, one line per field
    uv run python -I scripts/list_fields.py score    # every count the report quotes

The rule is in docs/proposals/baselines-v1.md. ``fields.jsonl`` gets a line per field as it lands. A network failure
stops the run instead of skipping the field, so the list does not depend on the weather. The service takes about 11
seconds per map whatever the load, so fields are fetched by a few workers at once.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import tempfile
import time as clock
import warnings
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.units import arcmin, deg
from landers.models.leak import check_png
from PIL import Image, ImageDraw

from probe import baselines as bl
from probe import guard, radio
from probe import prefilter as pf
from probe.score import wilson
from scripts.prefilter import committed_unchanged
from scripts.radio_inputs import ENDPOINTS, cutout, process, read_decisions, slug

LIST_PATH = Path("docs/reports/2026-10-31-prefilter/prefilter_list.csv")
EARLIER_ITEMS = Path("docs/reports/2026-10-31-radio-inputs/items.json")
WORKERS = 6
SHEET_COLUMNS, SHEET_ROWS, TILE, CAPTION = 6, 6, 240, 16
SAMPLE_SEED = [radio.SEED, 3]


def read_list(path: Path | None = None) -> list[dict]:
    """The listed sources, each with its field's id: its row number in the list, which says nothing of where it is."""
    with (path or LIST_PATH).open() as f:
        rows = list(csv.DictReader(f))
    if len(rows) > pf.MAX_LIST:
        raise ValueError(f"{len(rows)} rows on a list of at most {pf.MAX_LIST}")
    numeric = ("ra", "dec", "total_flux", "peak_flux", "majax", "minax")
    return [
        row | {name: float(row[name]) for name in numeric} | {"id": f"list-{k:04d}"} for k, row in enumerate(rows, 1)
    ]


def frozen_files(report: Path) -> list[Path]:
    return [report / "frozen_threshold.json", LIST_PATH]


def refuse_unfrozen(report: Path) -> bool:
    bad = [path for path in frozen_files(report) if not committed_unchanged(path)]
    for path in bad:
        print(f"{path} must be committed and unchanged first", file=sys.stderr)
    return bool(bad)


def tune(report: Path, items_path: Path = EARLIER_ITEMS) -> int:
    report.mkdir(parents=True, exist_ok=True)
    path = report / "frozen_threshold.json"
    if path.exists():
        print(f"{path} exists; the threshold is tuned once", file=sys.stderr)
        return 1
    scores = bl.tuning_scores(json.loads(items_path.read_text()))
    result = {"rule": "docs/proposals/baselines-v1.md", "read_from": str(items_path), **bl.tune(**scores)}
    path.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))
    return 0


def one_field(row: dict, data: Path, out: Path) -> dict:
    """Fetch and draw one listed source. Fetch and draw are timed apart, and the draw finds the cutouts on disk."""
    start = clock.monotonic()
    for resolution in ENDPOINTS:
        cutout(row["id"], resolution, row["ra"], row["dec"], data / "cutouts")
    fetched = clock.monotonic()
    result = process(row["id"], "list", None, row["ra"], row["dec"], data, out)
    done = clock.monotonic()
    return {
        "name": row["source_name"],
        "group": "list",
        "row_id": row["id"],
        **result,
        "fetch_seconds": round(fetched - start, 2),
        "draw_seconds": round(done - fetched, 2),
    }


def fetch(data: Path, out: Path, report: Path, limit: int | None, workers: int) -> int:
    if refuse_unfrozen(report):
        return 1
    (data / "cutouts").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(parents=True, exist_ok=True)
    warnings.filterwarnings("ignore")
    path = report / "fields.jsonl"
    done = {d["row_id"] for d in read_decisions(path)}
    todo = [row for row in read_list() if row["id"] not in done]
    if limit is not None:
        todo = todo[:limit]
    text = path.read_text() if path.exists() else ""
    if text and not text.endswith("\n"):  # a line cut off by a kill
        with path.open("a") as f:
            f.write("\n")
    print(f"{len(done)} fields on disk, {len(todo)} to do", flush=True)
    start = clock.monotonic()
    landed = 0
    with ThreadPoolExecutor(workers) as pool:
        pending = {pool.submit(one_field, row, data, out) for row in todo}
        while pending:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            failure = None
            for future in finished:
                if future.exception() is not None:
                    failure = future.exception()
                    continue
                with path.open("a") as f:
                    f.write(json.dumps(future.result()) + "\n")
                landed += 1
                if landed % 25 == 0:
                    print(f"{landed} of {len(todo)} in {clock.monotonic() - start:.0f} s", flush=True)
            if failure is not None:
                for future in pending:
                    future.cancel()
                print(f"stopped: {failure}; run again to continue", file=sys.stderr)
                return 1
    print(f"{landed} fields in {clock.monotonic() - start:.0f} s")
    return 0


def directory_bytes(folder: Path, pattern: str) -> tuple[int, int]:
    files = list(folder.glob(pattern))
    return len(files), sum(f.stat().st_size for f in files)


def quantiles(values: list[float]) -> dict:
    return {
        "median": round(float(np.median(values)), 2),
        "p95": round(float(np.percentile(values, 95)), 2),
        "max": round(float(np.max(values)), 2),
        "total": round(float(np.sum(values)), 1),
    }


def drawn_as_before(earlier: list[dict], earlier_data: Path, earlier_out: Path) -> dict:
    """Redraw the 18 circles from their stored cutouts with the code used here, and compare with the earlier run."""
    same_scores = same_images = 0
    circles = [r for r in earlier if r["label"] == radio.RING]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "images").mkdir()
        for r in circles:
            item_id = f"{r['group']}-{slug(r['name'])}"
            again = process(item_id, r["group"], r["label"], r["ra"], r["dec"], earlier_data, tmp)
            same_scores += all(again["measures"][f"score_{k}"] == r["measures"][f"score_{k}"] for k in ENDPOINTS)
            same_images += all(
                (tmp / again[f"image_{k}"]).read_bytes() == (earlier_out / r[f"image_{k}"]).read_bytes()
                for k in ENDPOINTS
            )
    return {"circles": len(circles), "same_scores": same_scores, "same_png_bytes": same_images}


def contact_sheet(records: list[dict], key: str, out: Path, path: Path) -> None:
    """For people: the field's list id over each field. Never sent to a model."""
    sheet = Image.new("RGB", (SHEET_COLUMNS * TILE, SHEET_ROWS * (TILE + CAPTION)), "navy")
    draw = ImageDraw.Draw(sheet)
    for i, record in enumerate(records[: SHEET_COLUMNS * SHEET_ROWS]):
        x, y = (i % SHEET_COLUMNS) * TILE, (i // SHEET_COLUMNS) * (TILE + CAPTION)
        sheet.paste(Image.open(out / record[key]).resize((TILE, TILE)), (x, y + CAPTION))
        draw.text((x + 2, y + 2), f"{record['row_id']} score {bl.best_score(record['measures']):.1f}", fill="yellow")
    sheet.save(path)


def score(data: Path, out: Path, report: Path, controls: Path, earlier_data: Path, earlier_out: Path) -> int:
    if refuse_unfrozen(report):
        return 1
    warnings.filterwarnings("ignore")
    tuned = json.loads((report / "frozen_threshold.json").read_text())["threshold"]
    listed = read_list()
    fields = {d["row_id"]: d for d in read_decisions(report / "fields.jsonl")}
    missing = [row["id"] for row in listed if row["id"] not in fields]
    if missing:
        print(f"{len(missing)} fields are not fetched yet", file=sys.stderr)
        return 1
    accepted = [fields[row["id"]] for row in listed if fields[row["id"]]["status"] == "accepted"]
    skipped = [fields[row["id"]] for row in listed if fields[row["id"]]["status"] != "accepted"]

    digests = set()
    guard.check_text(radio.PROMPT)
    guard.check_text(f"{radio.SPEC.name}_answer")
    for record in accepted:
        guard.check_text(record["row_id"], "field id")
        for key in ("image_6", "image_20"):
            png = (out / record[key]).read_bytes()
            check_png(png)
            digests.add(hashlib.sha256(png).hexdigest())

    records = []
    for record in accepted:
        call = bl.calls(record["measures"], tuned)
        records.append({"item_id": record["row_id"], "score": bl.best_score(record["measures"]), "calls": call})
    by_id = {r["item_id"]: r for r in records}
    called = {name: sum(r["calls"][name] == radio.RING for r in records) for name in ("annulus", "annulus_tuned")}

    arrays = {name: np.array([row[name] for row in listed]) for name in ("ra", "dec")}
    earlier = json.loads(EARLIER_ITEMS.read_text())
    earlier_by_name = {r["name"]: r for r in earlier}
    outcomes, details = {}, {}
    known_ids = {}
    here = SkyCoord(arrays["ra"] * deg, arrays["dec"] * deg)
    for group in radio.CIRCLE_GROUPS:
        for obj in json.loads((controls / f"{group}.json").read_text())["objects"]:
            name = obj["name"]
            near = bl.listed_near(arrays, obj["ra"], obj["dec"], pf.circle_radius_arcsec(name))
            separation = here.separation(SkyCoord(obj["ra"] * deg, obj["dec"] * deg)).arcmin
            near_rows = [by_id[listed[i]["id"]] for i in near if listed[i]["id"] in by_id]
            outcomes[name] = bl.circle_outcome(group, bl.calls(earlier_by_name[name]["measures"], tuned), near_rows)
            for i in near:
                known_ids[listed[i]["id"]] = name
            details[name] = outcomes[name] | {
                "score_at_published_position": bl.best_score(earlier_by_name[name]["measures"]),
                "listed_rows": [
                    {
                        "id": listed[i]["id"],
                        "offset_arcsec": round(float(separation[i] * 60), 1),
                        "score": by_id[listed[i]["id"]]["score"] if listed[i]["id"] in by_id else None,
                        "calls": by_id[listed[i]["id"]]["calls"] if listed[i]["id"] in by_id else None,
                    }
                    for i in near
                ],
                "nearest_listed_row_arcmin": round(float(separation.min()), 2),
            }

    others = {}
    for group in ("random", *pf.OTHER_GROUPS):
        chosen = [r for r in earlier if r["group"] == group]
        others[group] = {
            name: bl.count(sum(bl.calls(r["measures"], tuned)[name] == radio.RING for r in chosen), len(chosen))
            for name in ("annulus", "annulus_tuned")
        }

    pairs_a, pairs_b, _, _ = here.search_around_sky(here, radio.FIELD_ARCMIN / 2 * arcmin)
    has_neighbour = {int(a) for a, b in zip(pairs_a, pairs_b, strict=True) if a != b}
    scores = np.array([r["score"] for r in records])
    fits_count, fits_bytes = directory_bytes(data / "cutouts", "*.fits")
    png_count, png_bytes = directory_bytes(out / "images", "*.png")
    fetches = [r["fetch_seconds"] for r in accepted]
    draws = [r["draw_seconds"] for r in accepted]
    n = len(listed)

    result = {
        "rule": "docs/proposals/baselines-v1.md",
        "tuned_threshold": tuned,
        "annulus_threshold": radio.RING_SCORE_THRESHOLD,
        "list": {
            "rows": n,
            "fields_drawn": len(accepted),
            "fields_skipped": len(skipped),
            "skip_reasons": sorted({r.get("reason", "") for r in skipped}),
            "rows_with_another_listed_row_within_3_arcmin": len(has_neighbour),
            **{f"called_by_{name}": called[name] for name in ("annulus", "annulus_tuned")},
            **{
                f"called_by_{name}_wilson_95": [round(v, 4) for v in wilson(called[name], len(records))]
                for name in ("annulus", "annulus_tuned")
            },
            "score_quantiles": {str(q): round(float(np.nanpercentile(scores, q)), 2) for q in (5, 25, 50, 75, 95, 100)},
            "scores_nan": int(np.isnan(scores).sum()),
        },
        "circles_objects": bl.circle_counts(outcomes),
        "circles": details,
        "earlier_fields_by_group": others,
        "sizes": {
            "fits_files": fits_count,
            "fits_bytes": fits_bytes,
            "png_files": png_count,
            "png_bytes": png_bytes,
            "fields_jsonl_bytes": (report / "fields.jsonl").stat().st_size,
        },
        "timings_seconds_per_field": {"fetch_both_maps": quantiles(fetches), "draw_and_score": quantiles(draws)},
        "checks": {
            "images_checked": 2 * len(accepted),
            "distinct_images": len(digests),
            "fine_map_beams_arcsec": {
                str(beam): sum(r["measures"]["beam_arcsec_6"] == beam for r in accepted)
                for beam in sorted({r["measures"]["beam_arcsec_6"] for r in accepted})
            },
            "largest_no_data_fraction": max(
                max(r["measures"]["no_data_fraction_6"], r["measures"]["no_data_fraction_20"]) for r in accepted
            ),
            "fields_over_1_percent_no_data": sum(
                max(r["measures"]["no_data_fraction_6"], r["measures"]["no_data_fraction_20"]) > 0.01 for r in accepted
            ),
            "drawn_as_before": drawn_as_before(earlier, earlier_data, earlier_out),
        },
    }
    (report / "baselines.json").write_text(json.dumps(result, indent=1) + "\n")

    records_path = report / "records.jsonl"
    records_path.write_text("".join(json.dumps(r) + "\n" for r in records))
    items = [
        {
            "id": r["row_id"],
            "name": r["name"],
            "group": "list",
            "label": radio.RING if r["row_id"] in known_ids else bl.UNLABELLED,
            "known_circle": known_ids.get(r["row_id"]),
            "ra": r["ra"],
            "dec": r["dec"],
            "image_6": r["image_6"],
            "image_20": r["image_20"],
            "measures": r["measures"],
        }
        for r in accepted
    ]
    (out / "items.json").write_text(json.dumps(items, indent=1) + "\n")
    shutil.copy(out / "items.json", report / "items.json")

    sheets = report / "contact_sheets"
    sheets.mkdir(exist_ok=True)
    size = SHEET_COLUMNS * SHEET_ROWS
    order = np.random.default_rng(SAMPLE_SEED).permutation(len(accepted))[:size]
    sample = [accepted[int(k)] for k in order]
    top = sorted(accepted, key=lambda r: -np.nan_to_num(bl.best_score(r["measures"]), nan=-np.inf))[:size]
    for name, chosen in (("sample", sample), ("top_score", top)):
        for resolution in ENDPOINTS:
            contact_sheet(chosen, f"image_{resolution}", out, sheets / f"{name}-{resolution}.png")
    print(json.dumps({k: v for k, v in result.items() if k != "circles"}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=("tune", "fetch", "score"))
    ap.add_argument("--data", default="data/radio_list")
    ap.add_argument("--out", default="out/radio_list")
    ap.add_argument("--report", default="docs/reports/2026-10-31-baselines")
    ap.add_argument("--controls", default="controls")
    ap.add_argument("--earlier-data", default="data/radio")
    ap.add_argument("--earlier-out", default="out/radio_ring")
    ap.add_argument("--limit", type=int, help="fetch at most this many fields, to commit between runs")
    ap.add_argument("--workers", type=int, default=WORKERS)
    a = ap.parse_args(argv)
    data, out, report = Path(a.data), Path(a.out), Path(a.report)
    if a.step == "tune":
        return tune(report)
    if a.step == "fetch":
        return fetch(data, out, report, a.limit, a.workers)
    return score(data, out, report, Path(a.controls), Path(a.earlier_data), Path(a.earlier_out))


if __name__ == "__main__":
    sys.exit(main())
