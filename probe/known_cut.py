"""The known-object cut on the ring-like rows: what each cut removes and what the counts mean. The rule is written in
docs/proposals/known-cut-v1.md; this is that rule in code. No network here, and nothing here reaches a model. Nothing
here assigns a verdict.
"""

from __future__ import annotations

import csv
import io

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.units import arcmin, deg

from probe import radio
from probe.baselines import count

MATCH_ARCMIN = 1.0
SHIFT_ARCMIN = 10.0  # the chance-match control: the same position, this far north
LINK_ARCMIN = radio.FIELD_ARCMIN / 2  # the screen's distance for "another row near"
SMALLEST_RING_ARCSEC = 60.0  # the smallest the prompt allows; a position with no catalogue row uses this
HALF = 0.5  # a galaxy above this share of the ring is reported, and removes nothing

DEPTH_PERCENTILE = 0.1
BRIGHT_PEAK_OVER_NOISE = 100.0
BRIGHT_NEIGHBOUR_ARCMIN = 30.0  # the sources are the catalogue's of at least 1 Jy, the pre-filter's bright table

GALAXY, PN, SNR, HII = "galaxy", "planetary_nebula", "supernova_remnant", "hii_region"
LAST_STEP = {"PN": PN, "SNR": SNR, "HII": HII}
GALAXY_LARGER, CALIBRATOR, SPOKES = "galaxy_larger", "calibrator", "spokes"
SKY_CUTS = (GALAXY_LARGER, PN, SNR, HII, CALIBRATOR)  # those that read a position, so have a chance-match control
CUTS = (*SKY_CUTS, SPOKES)

CALIBRATORS = (*radio.LOOKALIKES["artefact_ring"], "Cas A", "Cyg A", "Tau A", "Vir A")
SIMBAD_COLUMNS = ("main_id", "ra", "dec", "otype", "galdim_majaxis", "galdim_minaxis", "rvz_redshift")


def cone_query(ra: float, dec: float, radius_arcmin: float = MATCH_ARCMIN) -> str:
    columns = ",".join(SIMBAD_COLUMNS)
    circle = f"CIRCLE('ICRS',{ra:.6f},{dec:.6f},{radius_arcmin / 60:.8f})"
    return f"select {columns} from basic where CONTAINS(POINT('ICRS',ra,dec),{circle})=1"


def parse_cone(text: str) -> list[dict]:
    """The rows of a cone's answer. An empty table is an answer; anything else raises, so an outage cannot pass for no
    match."""
    if not text.startswith(",".join(SIMBAD_COLUMNS)):
        raise RuntimeError("SIMBAD did not answer with its table")
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        number = {name: float(row[name]) if row[name] else None for name in SIMBAD_COLUMNS[1:] if name != "otype"}
        out.append({"main_id": row["main_id"], "otype": row["otype"], **number})
    return out


def families(otypedef_csv: str) -> dict[str, str]:
    """Object type to family, from SIMBAD's own table of types. A type in no family here is not in this dict."""
    out = {}
    for row in csv.DictReader(io.StringIO(otypedef_csv)):
        steps = [step.strip() for step in row["path"].split(">")]
        if steps[0] == "G":
            out[row["otype"]] = GALAXY
        elif steps[-1] in LAST_STEP:
            out[row["otype"]] = LAST_STEP[steps[-1]]
    if not {GALAXY, PN, SNR, HII} <= set(out.values()):
        raise RuntimeError("the table of object types lacks a family the cut needs")
    return out


def separation_arcmin(ra: float, dec: float, other_ra: float, other_dec: float) -> float:
    return float(SkyCoord(ra * deg, dec * deg).separation(SkyCoord(other_ra * deg, other_dec * deg)).arcmin)


def sky_matches(
    ra: float, dec: float, ring_arcsec: float, cone: list[dict], family: dict[str, str], calibrators: dict[str, dict]
) -> dict:
    """Per cut, what removes this position, with the galaxies that remove nothing beside them. A match outside the
    radius is ignored, whatever the service sent."""
    ring = ring_arcsec / 60
    found: dict = {name: [] for name in SKY_CUTS} | {"galaxy_no_size": [], "galaxy_above_half_the_ring": []}
    for obj in cone:
        if obj["ra"] is None or obj["dec"] is None:
            continue
        away = separation_arcmin(ra, dec, obj["ra"], obj["dec"])
        if away > MATCH_ARCMIN:
            continue
        kind = family.get(obj["otype"])
        hit = obj | {"arcmin_away": round(away, 3)}
        if kind in (PN, SNR, HII):
            found[kind].append(hit)
        elif kind == GALAXY:
            size = obj["galdim_majaxis"]
            if size is None:
                found["galaxy_no_size"].append(hit)
            elif size > ring:
                found[GALAXY_LARGER].append(hit)
            elif size > HALF * ring:
                found["galaxy_above_half_the_ring"].append(hit)
    for name, where in calibrators.items():
        away = separation_arcmin(ra, dec, where["ra"], where["dec"])
        if away <= MATCH_ARCMIN:
            found[CALIBRATOR].append({"main_id": name, "arcmin_away": round(away, 3)})
    return found


def negative_depth(field: np.ndarray) -> float:
    """How far below the median the 0.1st percentile lies, in the field's noise. About 3.1 for pure noise. Errors around
    a bright source swing both ways, and real emission cannot go below the background. NaN for a field with no noise."""
    values = field[np.isfinite(field)]
    sigma = radio.noise(field)
    if not len(values) or not sigma > 0:
        return float("nan")
    return float((np.median(values) - np.percentile(values, DEPTH_PERCENTILE)) / sigma)


def peak_over_noise(field: np.ndarray) -> float:
    values = field[np.isfinite(field)]
    sigma = radio.noise(field)
    return float(values.max() / sigma) if len(values) and sigma > 0 else float("nan")


def brightest_neighbour(ra: float, dec: float, bright: dict[str, np.ndarray]) -> dict | None:
    """The brightest catalogue source of at least 1 Jy within reach, or None."""
    away = SkyCoord(ra * deg, dec * deg).separation(SkyCoord(bright["ra"] * deg, bright["dec"] * deg)).arcmin
    near = np.flatnonzero(away <= BRIGHT_NEIGHBOUR_ARCMIN)
    if not len(near):
        return None
    k = int(near[np.argmax(bright["total_flux"][near])])
    return {"total_flux_mjy": round(float(bright["total_flux"][k]), 1), "arcmin_away": round(float(away[k]), 2)}


def has_bright_source(peak: float, neighbour: dict | None) -> bool:
    return bool(peak >= BRIGHT_PEAK_OVER_NOISE) or neighbour is not None


def spoke_flag(depth: float, peak: float, neighbour: dict | None, threshold: float) -> bool:
    """A NaN depth fails its comparison: a field that cannot be measured is not flagged."""
    return bool(depth >= threshold) and has_bright_source(peak, neighbour)


def removed_by(found: dict, spokes: bool) -> list[str]:
    return [name for name in SKY_CUTS if found[name]] + ([SPOKES] if spokes else [])


def spoke_fit_fields(items: list[dict], depths: dict[str, float], artefact_rows: list[str]) -> dict[str, list[float]]:
    """What the threshold may read. Positives are artefact_ring fields and the given rows, negatives the tuning circles.
    Nothing else moves it, though ``depths`` may hold more."""
    with_spokes = [depths[i["id"]] for i in items if i["group"] == "artefact_ring"] + [depths[k] for k in artefact_rows]
    without = [depths[i["id"]] for i in items if i["group"] == "tuning"]
    return {"circles": with_spokes, "lookalikes": without}


def link_objects(rows: list[dict], radius_arcmin: float = LINK_ARCMIN) -> list[list[str]]:
    """Rows grouped into objects: any two within the radius are one, and so is anything linked through them."""
    if not rows:
        return []
    here = SkyCoord([r["ra"] for r in rows] * deg, [r["dec"] for r in rows] * deg)
    parent = list(range(len(rows)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    a, b, _, _ = here.search_around_sky(here, radius_arcmin * arcmin)
    for i, j in zip(a, b, strict=True):
        parent[root(int(i))] = root(int(j))
    groups: dict[int, list[str]] = {}
    for i, row in enumerate(rows):
        groups.setdefault(root(i), []).append(row["id"])
    return sorted(groups.values())


def cut_counts(rows: list[dict]) -> dict:
    """Per cut, rows removed, known-circle rows and others apart, and those only it removes."""
    out = {}
    for name in CUTS:
        hit = [r for r in rows if name in r["removed_by"]]
        out[name] = {
            "rows_removed": len(hit),
            "known_circle_rows_removed": sum(bool(r["known_circle"]) for r in hit),
            "other_rows_removed": sum(not r["known_circle"] for r in hit),
            "rows_only_this_cut_removes": sum(r["removed_by"] == [name] for r in hit),
            "known_circles_removed": sorted({r["known_circle"] for r in hit if r["known_circle"]}),
            "rows": [r["id"] for r in hit],
        }
    return out


def circle_chain(rows: list[dict], circles: dict[str, str]) -> dict:
    """Each known circle once, from name to group. It stays if a ring-like row of its own is left, and stays with two
    votes if that row's second vote is ring-like too. A circle with no ring-like row is a miss, like any lost
    earlier."""
    outcomes = {}
    for name, group in circles.items():
        own = [r for r in rows if r["known_circle"] == name]
        outcomes[name] = {
            "group": group,
            "ring_like_rows": [r["id"] for r in own],
            "rows_removed_by": {r["id"]: r["removed_by"] for r in own if r["removed_by"]},
            "before_the_cuts": bool(own),
            "left": any(not r["removed_by"] for r in own),
            "left_with_two_votes": any(not r["removed_by"] and r["two_votes"] for r in own),
        }
    counts = {}
    for label, group in {"tuning": "tuning", "heldout": "heldout", "all": None}.items():
        chosen = [o for o in outcomes.values() if group is None or o["group"] == group]
        counts[label] = {
            key: count(sum(o[key] for o in chosen), len(chosen))
            for key in ("before_the_cuts", "left", "left_with_two_votes")
        }
    return {"circles": outcomes, "counts": counts}


def control_counts(rows: list[dict]) -> dict:
    """Over a group of control positions, how many each cut removes and how many any cut does."""
    return {
        "n": len(rows),
        "removed_by_any": sum(bool(r["removed_by"]) for r in rows),
        "removed_by": {name: sum(name in r["removed_by"] for r in rows) for name in CUTS},
    }
