"""Build the pre-filter from the LoTSS DR3 catalogue, server side. Safe to kill and run again; a step skips what it has.

    uv run python -I scripts/prefilter.py fetch    # rows with majax >= 20 by strip, and the bright sources
    uv run python -I scripts/prefilter.py fit      # picks the box on the tuning circles, lookalikes and random sources
    (commit the frozen cuts)
    uv run python -I scripts/prefilter.py heldout  # writes the list and counts the held-out circles once

The rule is in docs/proposals/prefilter-v1.md. ``fit`` reads no held-out position.
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
    field = pf.FIELD_RADIUS_ARCMIN * 60
    radius = pf.circle_radius_arcsec
    targets = {
        "tuning": [pf.rows_near(rows, o["ra"], o["dec"], radius(o["name"])) for o in objects["tuning"]],
        "lookalike": [pf.rows_near(rows, o["ra"], o["dec"], field) for o in objects["lookalike"]],
        "random": [pf.rows_near(rows, o["ra"], o["dec"], field) for o in objects["random"]],
    }
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


def committed_unchanged(path: Path) -> bool:
    """Is this file in a commit and the same as that commit? The held-out count must follow the freeze."""
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(path)], capture_output=True)
    if tracked.returncode != 0:
        return False
    return subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(path)], capture_output=True).returncode == 0


def heldout(data: Path, controls: Path, cuts: Path, out: Path) -> int:
    if not committed_unchanged(cuts):
        print(f"{cuts} must be committed and unchanged before the held-out count", file=sys.stderr)
        return 1
    result_path = out / "heldout.json"
    if result_path.exists():
        print(f"{result_path} exists; the held-out count is made once", file=sys.stderr)
        return 1
    frozen = json.loads(cuts.read_text())
    box = pf.Box.from_json(frozen["box"])
    rows, bright = load(data)
    chosen = pf.box_mask(rows, bright, box)
    if int(chosen.sum()) != frozen["list_size"]:
        raise RuntimeError(f"the frozen box gives {int(chosen.sum())} rows, the fit counted {frozen['list_size']}")
    indices = np.flatnonzero(chosen)
    order = indices[np.argsort(rows["source_name"][indices])]
    lines = [",".join(pf.COLUMNS)]
    for i in order:
        r = row_json(rows, int(i))
        lines.append(",".join(str(r[name]) if isinstance(r[name], str) else f"{r[name]:.6f}" for name in pf.COLUMNS))
    (out / "prefilter_list.csv").write_text("\n".join(lines) + "\n")
    objects = json.loads((controls / "heldout.json").read_text())["objects"]
    per_object = objects_report(rows, objects, chosen, lambda o: pf.circle_radius_arcsec(o["name"]))
    kept = sum(o["kept"] for o in per_object.values())
    loose = sum(o["kept_at_60_arcsec"] for o in per_object.values())
    result = {
        "list_size": int(chosen.sum()),
        "heldout_circles": len(objects),
        "kept": kept,
        "kept_wilson_95": [round(v, 4) for v in wilson(kept, len(objects))],
        "kept_at_60_arcsec": loose,
        "kept_at_60_arcsec_wilson_95": [round(v, 4) for v in wilson(loose, len(objects))],
        "objects": per_object,
    }
    result_path.write_text(json.dumps(result, indent=1) + "\n")
    print({k: v for k, v in result.items() if k != "objects"})
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=("fetch", "fit", "heldout"))
    ap.add_argument("--data", default="data/prefilter")
    ap.add_argument("--controls", default="controls")
    ap.add_argument("--items", default="docs/reports/2026-10-31-radio-inputs/items.json")
    ap.add_argument("--out", default="docs/reports/2026-10-31-prefilter")
    a = ap.parse_args(argv)
    data, controls, out = Path(a.data), Path(a.controls), Path(a.out)
    if a.step == "fetch":
        return fetch(data)
    if a.step == "fit":
        return fit(data, controls, Path(a.items), out)
    return heldout(data, controls, out / "frozen_cuts.json", out)


if __name__ == "__main__":
    sys.exit(main())
