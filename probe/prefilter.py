"""The catalogue pre-filter: columns, the grid of cuts, what kept means and how a box is chosen. The rule is written in
docs/proposals/prefilter-v1.md; this is that rule in code. Nothing here reaches a model.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.units import arcmin, arcsec, deg

MAX_LIST = 1200
FLOOR_MAJOR_ARCSEC = 20.0
BRIGHT_FLOOR_MJY = 1000.0
STRIP_DEGREES = 15
SELF_ARCSEC = 1.0  # a bright source is not its own neighbour

CIRCLE_FLOOR_ARCSEC = 30.0  # max(30 arcsec, half the object's extent), the control file's rule
EXTENT_ARCMIN = {"J1633+1441": 3.0}  # the only extent the control files give
SENSITIVITY_ARCSEC = 60.0
FIELD_RADIUS_ARCMIN = 3.0  # inside a 6 arcmin field
OTHER_GROUPS = ("ring_galaxy", "planetary_nebula", "supernova_remnant", "radio_galaxy", "artefact_ring")

OFF = None
GRID = {
    "major_min": (20.0, 25.0, 30.0, 40.0, 50.0, 60.0, 80.0, 100.0),
    "major_max": (120.0, 180.0, 240.0, 360.0, OFF),
    "axial_min": (0.8, 0.7, 0.6, 0.5, 0.4, OFF),
    "sb_max": (1e-4, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2, OFF),
    "peak_ratio_max": (0.02, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, OFF),
    "total_min": (50.0, 20.0, 10.0, 5.0, 2.0, 1.0, OFF),
    "total_max": (10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, OFF),
    "s_code": ("M", OFF),
    "isolation": ((10000.0, 30.0), (10000.0, 15.0), (3000.0, 12.0), (3000.0, 6.0), (1000.0, 6.0), (1000.0, 3.0), OFF),
}
DIMENSIONS = tuple(GRID)
COLUMNS = ("source_name", "ra", "dec", "total_flux", "peak_flux", "majax", "minax", "s_code")


def grid_size() -> int:
    return int(np.prod([len(values) for values in GRID.values()]))


@dataclass(frozen=True)
class Box:
    major_min: float | None = None
    major_max: float | None = None
    axial_min: float | None = None
    sb_max: float | None = None
    peak_ratio_max: float | None = None
    total_min: float | None = None
    total_max: float | None = None
    s_code: str | None = None
    isolation: tuple[float, float] | None = None

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, values: dict) -> Box:
        isolation = values.get("isolation")
        return cls(**(values | {"isolation": tuple(isolation) if isolation else None}))


def derived(rows: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """The rule's columns from the catalogue's. A row with a missing or non-positive size or flux fails every cut on it,
    because comparisons with NaN are false."""
    with np.errstate(divide="ignore", invalid="ignore"):
        area = rows["majax"] * rows["minax"]
        return {
            "major": rows["majax"],
            "axial": rows["minax"] / rows["majax"],
            "sb": np.where(area > 0, rows["total_flux"] / area, np.nan),
            "peak_ratio": np.where(rows["total_flux"] > 0, rows["peak_flux"] / rows["total_flux"], np.nan),
            "total": rows["total_flux"],
            "s_code": rows["s_code"],
        }


def isolated(ra: np.ndarray, dec: np.ndarray, bright: dict[str, np.ndarray], flux: float, radius: float) -> np.ndarray:
    """True where no source of at least ``flux`` mJy lies within ``radius`` arcmin, the source itself excluded."""
    keep = np.ones(len(ra), bool)
    chosen = bright["total_flux"] >= flux
    if not len(ra) or not chosen.any():
        return keep
    here = SkyCoord(ra * deg, dec * deg)
    there = SkyCoord(bright["ra"][chosen] * deg, bright["dec"][chosen] * deg)
    near, _, separation, _ = there.search_around_sky(here, radius * arcmin)
    keep[near[separation.arcsec >= SELF_ARCSEC]] = False
    return keep


def cut_masks(rows: dict[str, np.ndarray], bright: dict[str, np.ndarray]) -> dict[str, dict]:
    """For each dimension and each of its values, which rows pass. Off passes every row, even one with a NaN."""
    d = derived(rows)
    with np.errstate(invalid="ignore"):
        tests = {
            "major_min": lambda v: d["major"] >= v,
            "major_max": lambda v: d["major"] <= v,
            "axial_min": lambda v: d["axial"] >= v,
            "sb_max": lambda v: d["sb"] <= v,
            "peak_ratio_max": lambda v: d["peak_ratio"] <= v,
            "total_min": lambda v: d["total"] >= v,
            "total_max": lambda v: d["total"] <= v,
            "s_code": lambda v: d["s_code"] == v,
            "isolation": lambda v: isolated(rows["ra"], rows["dec"], bright, *v),
        }
        return {
            name: {
                value: np.ones(len(rows["ra"]), bool) if value is OFF else np.asarray(tests[name](value), bool)
                for value in GRID[name]
            }
            for name in DIMENSIONS
        }


def box_mask(rows: dict[str, np.ndarray], bright: dict[str, np.ndarray], box: Box) -> np.ndarray:
    """Which rows pass a box, computed from its own values, so a frozen box need not be on the grid."""
    d = derived(rows)
    keep = np.ones(len(rows["ra"]), bool)
    with np.errstate(invalid="ignore"):
        for value, passed in (
            (box.major_min, lambda v: d["major"] >= v),
            (box.major_max, lambda v: d["major"] <= v),
            (box.axial_min, lambda v: d["axial"] >= v),
            (box.sb_max, lambda v: d["sb"] <= v),
            (box.peak_ratio_max, lambda v: d["peak_ratio"] <= v),
            (box.total_min, lambda v: d["total"] >= v),
            (box.total_max, lambda v: d["total"] <= v),
            (box.s_code, lambda v: d["s_code"] == v),
            (box.isolation, lambda v: isolated(rows["ra"], rows["dec"], bright, *v)),
        ):
            if value is not OFF:
                keep &= np.asarray(passed(value), bool)
    return keep


def circle_radius_arcsec(name: str) -> float:
    return max(CIRCLE_FLOOR_ARCSEC, EXTENT_ARCMIN.get(name, 0.0) * 60 / 2)


def rows_near(rows: dict[str, np.ndarray], ra: float, dec: float, radius_arcsec: float) -> np.ndarray:
    """Indices of the rows within a radius of a position."""
    if not len(rows["ra"]):
        return np.array([], int)
    here = SkyCoord([ra] * deg, [dec] * deg)
    there = SkyCoord(rows["ra"] * deg, rows["dec"] * deg)
    _, found, _, _ = here.search_around_sky(there, radius_arcsec * arcsec)
    return np.unique(found)


def load_fit_objects(controls: Path, items_path: Path) -> dict[str, list[dict]]:
    """The objects the fit may read: tuning circles, lookalikes, random sources. The held-out circles are never returned,
    though the items file holds them, and an unknown group stops the run rather than being guessed at."""
    tuning = json.loads((controls / "tuning.json").read_text())["objects"]
    out: dict[str, list[dict]] = {"tuning": tuning, "lookalike": [], "random": []}
    for item in json.loads(items_path.read_text()):
        group = item["group"]
        if group in OTHER_GROUPS:
            out["lookalike"].append(item)
        elif group == "random":
            out["random"].append(item)
        elif group not in ("tuning", "heldout"):
            raise ValueError(f"unknown group in the items file: {group}")
    return out


def rank(circles: int, lookalikes: int, randoms: int, size: int) -> tuple[int, int, int, int]:
    """Larger is better: most circles, then fewest lookalikes, fewest random sources, then the largest list. The grid's
    order breaks what is left, by keeping the first box met."""
    return (circles, -lookalikes, -randoms, size)


def pack(mask: np.ndarray) -> np.ndarray:
    """A boolean mask as 64-bit words, so that the box search's ANDs are fast on a million rows."""
    bits = np.packbits(mask)
    padded = np.zeros((len(bits) + 7) // 8 * 8, np.uint8)
    padded[: len(bits)] = bits
    return padded.view(np.uint64)


def search(
    rows: dict[str, np.ndarray],
    bright: dict[str, np.ndarray],
    targets: dict[str, list[np.ndarray]],
    first_values: tuple = (None,),
    best: dict | None = None,
    on_unit=None,
) -> dict | None:
    """The best box of at most MAX_LIST rows. ``targets`` holds, per group, the row indices near each object. Every grid
    box is met in its fixed order, skipping only those that cannot equal the best so far, because they keep too few
    circles. ``best`` and ``first_values`` let a run continue unit by unit."""
    if not len(rows["ra"]):
        return best
    masks = cut_masks(rows, bright)
    tracked = np.unique(np.concatenate([i for group in targets.values() for i in group] or [np.array([], int)]))
    position = {int(row): k for k, row in enumerate(tracked)}

    def groups_of(name: str) -> list[np.ndarray]:
        return [np.array([position[int(i)] for i in near], int) for near in targets.get(name, [])]

    tuning, lookalike, random = groups_of("tuning"), groups_of("lookalike"), groups_of("random")

    def kept(small: np.ndarray, group: list[np.ndarray]) -> int:
        return sum(bool(small[near].any()) for near in group if len(near))

    small_masks = {n: {v: m[tracked] for v, m in masks[n].items()} for n in DIMENSIONS}
    words = {n: {v: pack(m) for v, m in masks[n].items()} for n in DIMENSIONS}
    del masks
    last = len(DIMENSIONS) - 1
    state = {"best": best, "tried": 0}

    def walk(level: int, small: np.ndarray, big: np.ndarray | None, chosen: tuple) -> None:
        name = DIMENSIONS[level]
        for value in GRID[name]:
            next_small = small & small_masks[name][value]
            circles = kept(next_small, tuning)
            current = state["best"]
            if current is not None and circles < current["circles"]:
                continue
            next_big = words[name][value] if big is None else big & words[name][value]
            if level < last:
                walk(level + 1, next_small, next_big, (*chosen, value))
                continue
            state["tried"] += 1
            size = int(np.bitwise_count(next_big).sum())
            if size > MAX_LIST or size == 0:
                continue
            lookalikes, randoms = kept(next_small, lookalike), kept(next_small, random)
            score = rank(circles, lookalikes, randoms, size)
            if current is None or score > rank(current["circles"], current["lookalikes"], current["randoms"],
                                               current["size"]):
                state["best"] = {
                    "circles": circles,
                    "lookalikes": lookalikes,
                    "randoms": randoms,
                    "size": size,
                    "box": Box(**dict(zip(DIMENSIONS, (*chosen, value), strict=True))).to_json(),
                }

    whole = np.ones(len(tracked), bool)
    first = DIMENSIONS[0]
    for value in GRID[first] if first_values == (None,) else first_values:
        walk(1, whole & small_masks[first][value], words[first][value], (value,))
        if on_unit is not None:
            on_unit(value, state["best"], state["tried"])
    return state["best"]


def combine_strips(paths: list[Path]) -> dict[str, np.ndarray]:
    """One table from the strip files, in the order given."""
    parts = [np.load(path) for path in paths]
    return {name: np.concatenate([part[name] for part in parts]) for name in COLUMNS}


def strip_edges() -> list[tuple[int, int]]:
    return list(itertools.pairwise(range(0, 360 + STRIP_DEGREES, STRIP_DEGREES)))


def check_count(what: str, got: int, expected: int) -> None:
    """A short answer must stop the run: a truncated strip would silently shrink every list counted over it."""
    if got != expected:
        raise RuntimeError(f"{what}: {got} rows returned, the server counts {expected}")
