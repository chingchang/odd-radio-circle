"""The radio circle probe: which fields, how a field is drawn, and the annulus ring score it is compared with.

No network here; ``scripts/radio_inputs.py`` fetches and calls these. The 18 circles in ``controls/`` are labelled
ring_like; the lookalikes below and the random catalogue sources are labelled not_ring_like.

Every field is the same size and centred on its object, so neither the framing nor the file says which group it is in.
Large objects therefore show only part of themselves. The images hold pixels only: no axes, text or colour bar.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
from landers.models.crops import to_png

from probe.harness import Item, ProbeSpec

SEED = 20261031
RING, NOT_RING = "ring_like", "not_ring_like"
FIELD_ARCMIN = 6.0  # the largest circle in the lists is about 3 arcmin across
FETCH_ARCMIN = 6.5  # cropped to the field, so rounding at the cutout's edge leaves no rim of empty pixels
IMAGE_SIDE = 720  # both maps are drawn at this size, by pixel repetition, so no interpolation invents detail
RANDOM_SOURCES = 30
PER_LOOKALIKE_GROUP = 6
CIRCLE_GROUPS = ("tuning", "heldout")
BARS = {"circles_ring_like": 14, "others_not_ring_like_fraction": 0.80}

# Stretch, fixed before any real map was drawn.
STRETCH_LOW_SIGMA = -2.0  # black
STRETCH_SOFT_SIGMA = 3.0  # linear below about this, logarithmic above
STRETCH_MIN_TOP_SIGMA = 20.0  # an empty field stays dark instead of showing its noise at full contrast
STRETCH_TOP_PERCENTILE = 99.9

# The zoomed view, fixed before any of these views was drawn, the same for every field. The central half of the field in
# each direction, and a linear stretch measured on the whole field, so nothing depends on an object's size or class.
ZOOM_ARCMIN = 3.0
ZOOM_LOW_SIGMA = -1.0  # black, measured from the field's median
ZOOM_TOP_SIGMA = 5.0  # white, so a surface a sigma or two above the background stands out of the noise's grey

# A lookalike must show something in the survey, or it would be an empty field and no test at all. The circles are kept
# whatever they show. An absolute peak, on most of the field: a remnant can fill the field, which inflates a noise taken
# from the map, and its middle can be hollow or its listed position off by minutes. About 10 times the survey's noise.
DETECTION_PEAK_JY = 1e-3
DETECTION_RADIUS_ARCMIN = 2.5

# The annulus score, fixed before its first run on a real field and not tuned on them.
RADII_ARCMIN = np.round(np.arange(0.4, 2.61, 0.1), 1)
SECTORS = 12
SECTORS_NEEDED = 8  # the ring has to go about two thirds of the way round, so one bright source cannot make one
MIN_SECTOR_PIXELS = 3
RING_SCORE_THRESHOLD = 3.0  # sigma of a sector's mean above the brighter of inside and outside

# Candidates per group, in the order they are tried; the first six that are covered and detected are used. Written down
# before any of these fields was fetched. Names are for the resolver and the agents and never reach the model.
LOOKALIKE_SOURCES = {
    "ring_galaxy": "Madore, Nelson & Petrillo 2009, ApJS 181, 572; Buta & Combes 1996, Fund. Cosmic Phys. 17, 95",
    "planetary_nebula": "Hajduk et al. 2021, ApJ 919, 121, on planetary nebulae in this survey",
    "supernova_remnant": "Green 2019, J. Astrophys. Astron. 40, 36",
    "radio_galaxy": "Spinrad et al. 1985, PASP 97, 932",
    "artefact_ring": "Scaife & Heald 2012, MNRAS 423, L30 (the bright calibrators); Shimwell et al. 2022, A&A 659, A1 "
    "(imaging limits around bright sources)",
}
LOOKALIKES = {
    "ring_galaxy": (
        "Arp 148",
        "Arp 143",
        "VII Zw 466",
        "NGC 7742",
        "NGC 7217",
        "NGC 4736",
        "NGC 6951",
        "PGC 54559",
        "Arp 147",
        "Arp 10",
        "NGC 4314",
    ),
    "planetary_nebula": (
        "NGC 6720",
        "Abell 39",
        "NGC 7662",
        "NGC 6826",
        "NGC 3587",
        "NGC 6543",
        "NGC 40",
        "NGC 7008",
        "NGC 1514",
        "NGC 650",
        "NGC 2392",
        "NGC 6210",
    ),
    "supernova_remnant": (
        "SNR G111.7-02.1",
        "SNR G120.1+01.4",
        "SNR G043.3-00.2",
        "SNR G039.2-00.3",
        "SNR G041.1-00.3",
        "SNR G084.9+00.5",
        "SNR G054.1+00.3",
        "SNR G074.9+01.2",
        "SNR G130.7+03.1",
        "SNR G184.6-05.8",
    ),
    "radio_galaxy": ("3C 310", "3C 348", "3C 317", "3C 338", "3C 465", "3C 449", "3C 66B", "3C 272.1", "3C 31"),
    "artefact_ring": ("3C 196", "3C 295", "3C 380", "3C 147", "3C 48", "3C 286", "3C 345", "3C 454.3"),
}

PROMPT = """These two images show the same patch of sky in radio continuum, 6 arcminutes on a side and centred on the
position of interest, in grey with an asinh stretch: white is bright, black is faint or has no data. The first image has
a resolution of about 6 arcsec and shows fine detail. The second has a resolution of about 20 arcsec and shows faint
diffuse emission better.

Decide whether the patch holds a ring-like object near its centre: a round ring, or a round disc of diffuse emission
with a brighter edge or structure inside it, about 1 to 3 arcminutes across, with or without a compact source at its
middle. It can be bright or barely above the noise.

These are not ring-like: patches with only point sources or background sources; jets, lobes and other irregular extended
emission; compact rings much smaller than an arcminute; and arcs or ripples caused by imaging errors around a very
bright source.

Answer with the schema."""
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "reason"],
    "properties": {"answer": {"type": "string", "enum": [RING, NOT_RING]}, "reason": {"type": "string"}},
}
SPEC = ProbeSpec("radio_ring", PROMPT, SCHEMA)  # the schema name reaches the model, so it does not say "circle"

ZOOM_VIEWS_PROMPT = """The third and fourth images show the central 3 arcminutes of the first and the second image, at
twice the scale, with a harder stretch that shows faint diffuse emission better: dark grey is the background, noise
shows as grain, and white is anything five times the noise or brighter, so bright emission loses its detail in these
two."""
# The first run's prompt, saying only what the two added images are. Results go to their own folder, under the same
# schema name, so they cannot be mixed with the first run's.
ZOOM_PROMPT = PROMPT.replace("These two images", "The first two images", 1).replace(
    "\n\nDecide", f"\n\n{ZOOM_VIEWS_PROMPT}\n\nDecide", 1
)
ZOOM_SPEC = ProbeSpec("radio_ring_zoom", ZOOM_PROMPT, SCHEMA, schema_name=f"{SPEC.name}_answer")


def noise(image: np.ndarray) -> float:
    """A robust noise of the finite pixels, in the map's units: 1.4826 times the median absolute deviation."""
    values = image[np.isfinite(image)]
    return float(1.4826 * np.median(np.abs(values - np.median(values)))) if len(values) else float("nan")


def centred_field(data: np.ndarray, header: fits.Header, ra: float, dec: float) -> tuple[np.ndarray, float]:
    """The FIELD_ARCMIN square centred on (ra, dec) and its arcsec per pixel. A cutout cut short by a mosaic edge keeps
    its object in the middle, and the missing part is NaN."""
    wcs = WCS(header).celestial
    scale = float(proj_plane_pixel_scales(wcs)[1] * 3600)
    side = int(round(FIELD_ARCMIN * 60 / scale))
    x, y = wcs.all_world2pix(ra, dec, 0)
    data = np.squeeze(data).astype(float)
    x0, y0 = int(round(float(x) - (side - 1) / 2)), int(round(float(y) - (side - 1) / 2))
    field = np.full((side, side), np.nan)
    ys, xs = max(y0, 0), max(x0, 0)
    ye, xe = min(y0 + side, data.shape[0]), min(x0 + side, data.shape[1])
    if ye > ys and xe > xs:
        field[ys - y0 : ye - y0, xs - x0 : xe - x0] = data[ys:ye, xs:xe]
    return field, scale


def stretched(image: np.ndarray) -> np.ndarray:
    """The asinh stretch to uint8, one fixed rule for every field. No data is black."""
    u8 = np.zeros(image.shape, np.uint8)
    good = np.isfinite(image)
    sigma = noise(image)
    if not good.any() or not sigma > 0:
        return u8
    top = max(float(np.percentile(image[good], STRETCH_TOP_PERCENTILE)), STRETCH_MIN_TOP_SIGMA * sigma)
    low = STRETCH_LOW_SIGMA * sigma
    soft = STRETCH_SOFT_SIGMA * sigma
    scaled = np.arcsinh((np.clip(image[good], low, top) - low) / soft) / np.arcsinh((top - low) / soft)
    u8[good] = np.round(scaled * 255).astype(np.uint8)
    return u8


def field_png(image: np.ndarray, side: int = IMAGE_SIDE) -> bytes:
    """The field as a PNG without metadata, north up as in the map, grown by pixel repetition to about ``side``."""
    return _grown_png(stretched(image), side)


def _grown_png(u8: np.ndarray, side: int) -> bytes:
    k = max(side // u8.shape[0], 1)
    u8 = u8[::-1]  # FITS rows run upward, image rows downward
    return to_png(np.repeat(np.repeat(u8, k, axis=0), k, axis=1))


def zoom_stretched(field: np.ndarray) -> np.ndarray:
    """The central ZOOM_ARCMIN of a field to uint8, linear from ZOOM_LOW_SIGMA to ZOOM_TOP_SIGMA about the median of the
    whole field, in the whole field's noise. No data is black."""
    margin = int(round((1 - ZOOM_ARCMIN / FIELD_ARCMIN) * field.shape[0] / 2))
    crop = field[margin : field.shape[0] - margin, margin : field.shape[1] - margin]
    u8 = np.zeros(crop.shape, np.uint8)
    good = np.isfinite(crop)
    sigma = noise(field)
    if not good.any() or not sigma > 0:
        return u8
    level = np.clip((crop[good] - np.nanmedian(field)) / sigma, ZOOM_LOW_SIGMA, ZOOM_TOP_SIGMA)
    u8[good] = np.round((level - ZOOM_LOW_SIGMA) / (ZOOM_TOP_SIGMA - ZOOM_LOW_SIGMA) * 255).astype(np.uint8)
    return u8


def zoom_png(field: np.ndarray, side: int = IMAGE_SIDE) -> bytes:
    """The zoomed view as a PNG without metadata, grown like the field to about ``side``."""
    return _grown_png(zoom_stretched(field), side)


def _radius_and_angle(image: np.ndarray, arcsec_per_pixel: float) -> tuple[np.ndarray, np.ndarray]:
    y, x = np.indices(image.shape, dtype=float)
    y -= (image.shape[0] - 1) / 2
    x -= (image.shape[1] - 1) / 2
    return np.hypot(x, y) * arcsec_per_pixel / 60, np.arctan2(y, x)


def ring_score(image: np.ndarray, arcsec_per_pixel: float, beam_arcsec: float) -> float:
    """How far a ring around the centre stands above both its inside and its outside, in sigma.

    For each radius the annulus is cut into 12 sectors. A sector's significance is its mean above the brighter median of
    the inside and the outside, over the noise of a mean of that many pixels with the beam's correlation. The radius's
    score is the 8th highest sector, so most of the circle must be bright, and the field's score is the best radius. The
    middle of the field is left out of the inside, so a source at the centre does not count against a ring."""
    r, angle = _radius_and_angle(image, arcsec_per_pixel)
    sigma = noise(image)
    if not sigma > 0:
        return float("nan")
    beam_pixels = 1.133 * (beam_arcsec / arcsec_per_pixel) ** 2
    beam = beam_arcsec / 60
    hole = 1.5 * beam
    good = np.isfinite(image)
    sector = np.minimum(((angle + np.pi) / (2 * np.pi) * SECTORS).astype(int), SECTORS - 1)
    best = float("-inf")
    for radius in RADII_ARCMIN:
        half = max(beam, 0.15 * radius)
        inner = good & (r > hole) & (r < radius - half)
        outer = good & (r > radius + half) & (r < radius + 3 * half)
        ring = good & (np.abs(r - radius) <= half)
        if inner.sum() < MIN_SECTOR_PIXELS or outer.sum() < MIN_SECTOR_PIXELS:
            continue
        background = max(np.median(image[inner]), np.median(image[outer]))
        significance = np.full(SECTORS, float("-inf"))
        for k in range(SECTORS):
            pixels = image[ring & (sector == k)]
            if len(pixels) >= MIN_SECTOR_PIXELS:
                error = sigma * np.sqrt(beam_pixels / len(pixels))
                significance[k] = (np.mean(pixels) - background) / error
        best = max(best, float(np.sort(significance)[-SECTORS_NEEDED]))
    return best if np.isfinite(best) else float("nan")


def annulus_rule(score_6: float, score_20: float, threshold: float = RING_SCORE_THRESHOLD) -> str:
    """Ring-like if either map's score reaches the threshold; a NaN score fails its comparison."""
    return RING if score_6 >= threshold or score_20 >= threshold else NOT_RING


def detected(image: np.ndarray, arcsec_per_pixel: float) -> bool:
    """Is there a peak of at least DETECTION_PEAK_JY within DETECTION_RADIUS_ARCMIN of the centre?"""
    r, _ = _radius_and_angle(image, arcsec_per_pixel)
    near = image[(r < DETECTION_RADIUS_ARCMIN) & np.isfinite(image)]
    return bool(len(near)) and bool(np.max(near) >= DETECTION_PEAK_JY)


def bar_result(rows: list[dict]) -> dict:
    """The pass bar from rows of label and prediction, and the same counts per group."""
    circles = [r for r in rows if r["label"] == RING]
    others = [r for r in rows if r["label"] == NOT_RING]
    hits = sum(r["prediction"] == RING for r in circles)
    rejections = sum(r["prediction"] == NOT_RING for r in others)
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r["group"], {"n": 0, "called_ring_like": 0})
        g["n"] += 1
        g["called_ring_like"] += r["prediction"] == RING
    return {
        "circles_called_ring_like": hits,
        "circles": len(circles),
        "others_called_not_ring_like": rejections,
        "others": len(others),
        "others_fraction": round(rejections / len(others), 4) if others else None,
        "bar_needs": BARS,
        "passes": hits >= BARS["circles_ring_like"]
        and bool(others)
        and rejections / len(others) >= BARS["others_not_ring_like_fraction"],
        "groups": groups,
    }


def rank_summary(rows: list[dict]) -> dict:
    """How the score orders the fields, whatever the threshold: the chance that a circle outranks another field, against
    all others and per group, from rows of group, label and score. A NaN score ranks lowest."""

    def value(r: dict) -> float:
        return r["score"] if np.isfinite(r["score"]) else float("-inf")

    circles = [value(r) for r in rows if r["label"] == RING]

    def beats(others: list[float]) -> float | None:
        if not circles or not others:
            return None
        wins = sum((c > o) + 0.5 * (c == o) for c in circles for o in others)
        return round(wins / (len(circles) * len(others)), 4)

    others = [r for r in rows if r["label"] == NOT_RING]
    groups = sorted({r["group"] for r in others})
    return {
        "circle_outranks_other": beats([value(r) for r in others]),
        "circle_outranks_group": {g: beats([value(r) for r in others if r["group"] == g]) for g in groups},
        "best_circle_score": round(max(circles), 2) if circles else None,
        "median_circle_score": round(float(np.median(circles)), 2) if circles else None,
        "threshold": RING_SCORE_THRESHOLD,
    }


def load_items(path: Path) -> tuple[list[Item], dict[str, dict]]:
    """The probe items and each one's record, from the ``items.json`` written by ``scripts/radio_inputs.py``."""
    path = Path(path)
    records = json.loads(path.read_text())
    items = [
        Item(
            r["id"], r["label"], ((path.parent / r["image_6"]).read_bytes(), (path.parent / r["image_20"]).read_bytes())
        )
        for r in records
    ]
    return items, {r["id"]: r for r in records}
