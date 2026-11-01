"""Build the pre-filter from the LoTSS DR3 catalogue, server side. Safe to kill and run again; a step skips what it has.

    uv run python -I scripts/prefilter.py fetch    # rows with majax >= 20 by strip, and the bright sources
    uv run python -I scripts/prefilter.py fit      # picks the box on the tuning circles, lookalikes and random sources
    uv run python -I scripts/prefilter.py fit2     # the same for a pair of boxes, one per s_code
    uv run python -I scripts/prefilter.py fit3     # the pair again, with a finer low end on peak_ratio
    (commit the frozen cuts)
    uv run python -I scripts/prefilter.py heldout  # writes the list and counts the held-out circles once

The rules are in docs/proposals/prefilter-v1.md, -v2.md and -v3.md. The fit steps read no held-out position.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time as clock
from pathlib import Path

import numpy as np
import pyvo

from probe import prefilter as pf
from probe.score import wilson

TAP_URL = "https://vo.astron.nl/tap"
SOURCES = "lotss_dr3.main_sources"
TRIES = 4
WAIT_SECONDS = 30
MAXREC = 2_000_000


def tap_query(tap, query: str):
    for attempt in range(TRIES):
        try:
            return tap.run_sync(query, maxrec=MAXREC).to_table()
        except Exception as e:
            if attempt == TRIES - 1:
                raise RuntimeError(f"TAP: {type(e).__name__}: {str(e)[:300]}") from e
            clock.sleep(WAIT_SECONDS)


def to_arrays(table) -> dict[str, np.ndarray]:
    out = {}
    for name in pf.COLUMNS:
        column = table[name]
        if name in ("source_name", "s_code"):
            out[name] = np.array([str(v).strip() for v in column], dtype="U24" if name == "source_name" else "U1")
        else:
            out[name] = np.ma.filled(np.ma.asarray(column, dtype=float), np.nan)
    return out


def save(path: Path, arrays: dict[str, np.ndarray]) -> None:
    tmp = path.with_name(path.name + ".part.npz")
    np.savez_compressed(tmp, **arrays)
    tmp.rename(path)


def fetch(data: Path) -> int:
    strips = data / "strips"
    strips.mkdir(parents=True, exist_ok=True)
    tap = pyvo.dal.TAPService(TAP_URL)
    columns = ", ".join(pf.COLUMNS)
    for low, high in pf.strip_edges():
        path = strips / f"ra{low:03d}.npz"
        if path.exists():
            continue
        where = f"majax >= {pf.FLOOR_MAJOR_ARCSEC} and ra >= {low} and ra < {high}"
        expected = int(tap_query(tap, f"select count(*) as n from {SOURCES} where {where}")["n"][0])
        start = clock.monotonic()
        table = tap_query(tap, f"select {columns} from {SOURCES} where {where}")
        pf.check_count(f"strip {low}", len(table), expected)
        save(path, to_arrays(table))
        print(f"strip {low}: {len(table)} rows in {clock.monotonic() - start:.0f} s", flush=True)
    path = data / "bright.npz"
    if not path.exists():
        where = f"total_flux >= {pf.BRIGHT_FLOOR_MJY}"
        expected = int(tap_query(tap, f"select count(*) as n from {SOURCES} where {where}")["n"][0])
        table = tap_query(tap, f"select {columns} from {SOURCES} where {where}")
        pf.check_count("bright", len(table), expected)
        save(path, to_arrays(table))
        print(f"bright: {len(table)} rows", flush=True)
    return 0


def load(data: Path) -> tuple[dict, dict]:
    paths = [data / "strips" / f"ra{low:03d}.npz" for low, _ in pf.strip_edges()]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise SystemExit(f"run fetch first; missing {missing}")
    return pf.combine_strips(paths), dict(np.load(data / "bright.npz"))


def row_json(rows: dict, index: int) -> dict:
    return {
        name: (str(rows[name][index]) if name in ("source_name", "s_code") else float(rows[name][index]))
        for name in pf.COLUMNS
    }


def objects_report(rows: dict, objects: list[dict], chosen: np.ndarray, radius_of) -> dict:
    """Per object: the rows of the search table near it at each radius, and whether any is on the list."""
    out = {}
    for obj in objects:
        primary = pf.rows_near(rows, obj["ra"], obj["dec"], radius_of(obj))
        loose = pf.rows_near(rows, obj["ra"], obj["dec"], pf.SENSITIVITY_ARCSEC)
        out[obj["name"]] = {
            "radius_arcsec": radius_of(obj),
            "kept": bool(chosen[primary].any()),
            "kept_at_60_arcsec": bool(chosen[loose].any()),
            "rows_at_or_above_floor_within_60_arcsec": [
                row_json(rows, int(i)) | {"listed": bool(chosen[i])} for i in loose
            ],
        }
    return out


def fit(data: Path, controls: Path, items: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    rows, bright = load(data)
    objects = pf.load_fit_objects(controls, items)
    targets = fit_targets(rows, objects)
    print(f"{len(rows['ra'])} rows; tuning rows per circle {[len(t) for t in targets['tuning']]}", flush=True)
    path = out / "fit_progress.json"
    progress = json.loads(path.read_text()) if path.exists() else {"done": [], "best": None, "tried": 0}
    start = clock.monotonic()

    def on_unit(value, best, tried):
        progress["done"].append(value)
        progress["best"] = best
        progress["tried"] += tried
        path.write_text(json.dumps(progress, indent=1) + "\n")
        print(f"major_min {value}: best {best} in {clock.monotonic() - start:.0f} s", flush=True)

    for value in pf.GRID["major_min"]:
        if value in progress["done"]:
            continue
        pf.search(rows, bright, targets, (value,), progress["best"], on_unit)
    best = progress["best"]
    if best is None:
        print("no box of at most the list size exists", file=sys.stderr)
        return 1
    box = pf.Box.from_json(best["box"])
    chosen = pf.box_mask(rows, bright, box)
    if int(chosen.sum()) != best["size"]:
        raise RuntimeError(f"the box gives {int(chosen.sum())} rows, the search counted {best['size']}")
    result = {
        "rule": "docs/proposals/prefilter-v1.md",
        "grid_boxes": pf.grid_size(),
        "boxes_counted": progress["tried"],
        "search_table_rows": int(len(rows["ra"])),
        "bright_rows": int(len(bright["ra"])),
        "list_size": best["size"],
        "tuning_circles_kept": best["circles"],
        "tuning_circles": len(objects["tuning"]),
        "lookalikes_kept": best["lookalikes"],
        "lookalikes": len(objects["lookalike"]),
        "random_kept": best["randoms"],
        "random": len(objects["random"]),
        "box": best["box"],
    }
    (out / "frozen_cuts.json").write_text(json.dumps(result, indent=1) + "\n")
    per_object = objects_report(rows, objects["tuning"], chosen, lambda o: pf.circle_radius_arcsec(o["name"]))
    (out / "tuning_circles.json").write_text(json.dumps(per_object, indent=1) + "\n")
    print(json.dumps(result, indent=1))
    return 0


def fit_targets(rows: dict, objects: dict) -> dict:
    field = pf.FIELD_RADIUS_ARCMIN * 60
    radius = pf.circle_radius_arcsec
    return {
        "tuning": [pf.rows_near(rows, o["ra"], o["dec"], radius(o["name"])) for o in objects["tuning"]],
        "lookalike": [pf.rows_near(rows, o["ra"], o["dec"], field) for o in objects["lookalike"]],
        "random": [pf.rows_near(rows, o["ra"], o["dec"], field) for o in objects["random"]],
    }


def footprint_for(rows: dict, bright: dict, targets: dict, code: str, data: Path, version: str, grid: dict) -> dict:
    """One s_code's footprint for one version, kept on disk as it lands so that a rerun skips it."""
    path = data / f"footprint_{version}_{code}.json"
    if path.exists():
        stored = json.loads(path.read_text())
        return {tuple(entry["key"]): {int(s): c for s, c in entry["sizes"].items()} for entry in stored}
    found = pf.footprints(rows, bright, targets, code, grid)
    stored = [{"key": list(key), "sizes": {str(s): c for s, c in sizes.items()}} for key, sizes in found.items()]
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(stored))
    tmp.rename(path)
    return found


PAIR_VERSIONS = {"v2": (pf.GRID, "frozen_cuts_v2.json"), "v3": (pf.GRID_V3, "frozen_cuts_v3.json")}


def fit_pair(version: str, data: Path, controls: Path, items: Path, out: Path) -> int:
    grid, frozen_name = PAIR_VERSIONS[version]
    rows, bright = load(data)
    objects = pf.load_fit_objects(controls, items)
    targets = fit_targets(rows, objects)
    start = clock.monotonic()
    found = {}
    for code in pf.V2_CODES:
        found[code] = footprint_for(rows, bright, targets, code, data, version, grid)
        print(f"{code}: {len(found[code])} sets of objects, {clock.monotonic() - start:.0f} s", flush=True)
    best = pf.best_pair(found["M"], found["S"])
    if best is None:
        print("no pair of boxes fits the list size", file=sys.stderr)
        return 1
    boxes = [pf.box_from_cuts(cuts, code) for cuts, code in zip(best["cuts"], pf.V2_CODES, strict=True)]
    chosen = pf.union_mask(rows, bright, boxes)
    if int(chosen.sum()) != sum(best["sizes"]):
        raise RuntimeError(f"the boxes give {int(chosen.sum())} rows, the search counted {best['sizes']}")
    result = {
        "rule": f"docs/proposals/prefilter-{version}.md",
        "search_table_rows": int(len(rows["ra"])),
        "list_size": int(chosen.sum()),
        "box_sizes": dict(zip(pf.V2_CODES, best["sizes"], strict=True)),
        "tuning_circles_kept": best["circles"].bit_count(),
        "tuning_circles": len(objects["tuning"]),
        "lookalikes_kept": best["lookalikes"].bit_count(),
        "lookalikes": len(objects["lookalike"]),
        "random_kept": best["randoms"].bit_count(),
        "random": len(objects["random"]),
        "boxes": [box.to_json() for box in boxes],
    }
    (out / frozen_name).write_text(json.dumps(result, indent=1) + "\n")
    per_object = objects_report(rows, objects["tuning"], chosen, lambda o: pf.circle_radius_arcsec(o["name"]))
    (out / f"tuning_circles_{version}.json").write_text(json.dumps(per_object, indent=1) + "\n")
    print(json.dumps(result, indent=1))
    return 0


def committed_unchanged(path: Path) -> bool:
    """Is this file in a commit and the same as that commit? The held-out count must follow the freeze."""
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(path)], capture_output=True)
    if tracked.returncode != 0:
        return False
    return subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(path)], capture_output=True).returncode == 0


def write_list(path: Path, rows: dict, chosen: np.ndarray) -> None:
    indices = np.flatnonzero(chosen)
    order = indices[np.argsort(rows["source_name"][indices])]
    lines = [",".join(pf.COLUMNS)]
    for i in order:
        r = row_json(rows, int(i))
        lines.append(",".join(str(r[name]) if isinstance(r[name], str) else f"{r[name]:.6f}" for name in pf.COLUMNS))
    path.write_text("\n".join(lines) + "\n")


def count_heldout(rows: dict, chosen: np.ndarray, objects: list[dict]) -> dict:
    per_object = objects_report(rows, objects, chosen, lambda o: pf.circle_radius_arcsec(o["name"]))
    kept = sum(o["kept"] for o in per_object.values())
    loose = sum(o["kept_at_60_arcsec"] for o in per_object.values())
    return {
        "list_size": int(chosen.sum()),
        "heldout_circles": len(objects),
        "kept": kept,
        "kept_wilson_95": [round(v, 4) for v in wilson(kept, len(objects))],
        "kept_at_60_arcsec": loose,
        "kept_at_60_arcsec_wilson_95": [round(v, 4) for v in wilson(loose, len(objects))],
        "objects": per_object,
    }


def heldout(data: Path, controls: Path, out: Path) -> int:
    paths = {"v1": out / "frozen_cuts.json"} | {v: out / name for v, (_, name) in PAIR_VERSIONS.items()}
    for path in paths.values():
        if not committed_unchanged(path):
            print(f"{path} must be committed and unchanged before the held-out count", file=sys.stderr)
            return 1
    result_path = out / "heldout.json"
    if result_path.exists():
        print(f"{result_path} exists; the held-out count is made once", file=sys.stderr)
        return 1
    frozen = {version: json.loads(path.read_text()) for version, path in paths.items()}
    rows, bright = load(data)
    masks = {}
    for version, cuts in frozen.items():
        boxes = cuts["boxes"] if "boxes" in cuts else [cuts["box"]]
        masks[version] = pf.union_mask(rows, bright, [pf.Box.from_json(box) for box in boxes])
        if int(masks[version].sum()) != cuts["list_size"]:
            raise RuntimeError(f"{version} gives {int(masks[version].sum())} rows, the fit counted {cuts['list_size']}")
    forward = pf.go_forward({version: cuts["tuning_circles_kept"] for version, cuts in frozen.items()})
    write_list(out / "prefilter_list.csv", rows, masks[forward])
    objects = json.loads((controls / "heldout.json").read_text())["objects"]
    result = {
        "goes_forward": forward,
        "chosen_from": "tuning counts in the frozen files, before this count",
    }
    result |= {version: count_heldout(rows, mask, objects) for version, mask in masks.items()}
    result_path.write_text(json.dumps(result, indent=1) + "\n")
    for version in masks:
        print(version, {k: v for k, v in result[version].items() if k != "objects"})
    print("goes forward:", forward)
    return 0


def summary(out: Path) -> int:
    """The totals and the per-circle table the report quotes, from the files the other steps wrote."""
    held = json.loads((out / "heldout.json").read_text())
    versions = {}
    names = {"v1": "tuning_circles.json", "v2": "tuning_circles_v2.json", "v3": "tuning_circles_v3.json"}
    for version, name in names.items():
        tuning = json.loads((out / name).read_text())
        kept = [n for n, o in tuning.items() if o["kept"]]
        kept_held = [n for n, o in held[version]["objects"].items() if o["kept"]]
        total = len(kept) + len(kept_held)
        count = len(tuning) + len(held[version]["objects"])
        versions[version] = {
            "tuning_kept": kept,
            "tuning_kept_at_60_arcsec": sum(o["kept_at_60_arcsec"] for o in tuning.values()),
            "heldout_kept": kept_held,
            "heldout_wilson_95": held[version]["kept_wilson_95"],
            "all_circles_kept": total,
            "all_circles": count,
            "all_circles_wilson_95": [round(v, 4) for v in wilson(total, count)],
        }
    forward = held["goes_forward"]
    tuning = json.loads((out / "tuning_circles.json").read_text())
    table = {}
    for group, objects in (("tuning", tuning), ("heldout", held[forward]["objects"])):
        for name, o in objects.items():
            rows = o["rows_at_or_above_floor_within_60_arcsec"]
            table[name] = {
                "group": group,
                "radius_arcsec": o["radius_arcsec"],
                "kept": o["kept"],
                "rows_within_60_arcsec_at_or_above_floor": len(rows),
                "rows": [
                    {
                        "major": round(r["majax"], 1),
                        "axial": round(r["minax"] / r["majax"], 2),
                        "total_mjy": round(r["total_flux"], 1),
                        "peak_ratio": round(r["peak_flux"] / r["total_flux"], 4),
                        "s_code": r["s_code"],
                        "listed": r["listed"],
                    }
                    for r in rows
                ],
            }
    with (out / "prefilter_list.csv").open() as f:
        listed = sum(1 for _ in f) - 1
    result = {"goes_forward": forward, "list_rows_in_file": listed, "versions": versions, "circles": table}
    (out / "summary.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=("fetch", "fit", "fit2", "fit3", "heldout", "summary"))
    ap.add_argument("--data", default="data/prefilter")
    ap.add_argument("--controls", default="controls")
    ap.add_argument("--items", default="docs/reports/2026-10-31-radio-inputs/items.json")
    ap.add_argument("--out", default="docs/reports/2026-10-31-prefilter")
    a = ap.parse_args(argv)
    data, controls, out = Path(a.data), Path(a.controls), Path(a.out)
    if a.step == "summary":
        return summary(out)
    if a.step == "fetch":
        return fetch(data)
    if a.step == "fit":
        return fit(data, controls, Path(a.items), out)
    if a.step in ("fit2", "fit3"):
        return fit_pair({"fit2": "v2", "fit3": "v3"}[a.step], data, controls, Path(a.items), out)
    return heldout(data, controls, out)


if __name__ == "__main__":
    sys.exit(main())
