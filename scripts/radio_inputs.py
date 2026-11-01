"""Fetch the radio cutouts for the circles, the lookalikes and random catalogue sources, and draw them. Safe to kill and
run again.

    uv run python -I scripts/radio_inputs.py --controls controls --data data/radio --out out/radio_ring

``decisions.jsonl`` gets one line per object tried, as it is decided, and a rerun continues from there. A network
failure stops the run instead of skipping the object, so the selection does not depend on the weather. Only single rows
of the 3 GB catalogue are read, by HTTP range.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time as clock
import warnings
from pathlib import Path

import numpy as np
import requests
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.units import deg

from probe import radio

SITE = "https://lofar-surveys.org"
ENDPOINTS = {6: "dr3-cutout.fits", 20: "dr3-low-cutout.fits"}
BEAMS_ARCSEC = {6: 6.0, 20: 20.0}  # when a header gives no beam
CATALOGUE_URL = f"{SITE}/public/DR3/catalogues/LoTSS_DR3_v1.0.srl.fits"
CATALOGUE_HEAD_BYTES = 28800
RESOLVER = "https://simbad.cfa.harvard.edu/simbad/sim-tap/sync"  # the CfA mirror; the Strasbourg host times out here
RANDOM_DRAWS = 200  # more row numbers than are needed, in a fixed order
TRIES = 3
WAIT_SECONDS = 20
TIMEOUT = 120
FITS_FORMATS = {"D": ">f8", "E": ">f4", "K": ">i8", "J": ">i4", "I": ">i2"}


def _retry(work, what: str):
    for attempt in range(TRIES):
        try:
            return work()
        except Exception as e:
            if attempt == TRIES - 1:
                raise RuntimeError(f"{what}: {type(e).__name__}: {str(e)[:300]}") from e
            clock.sleep(WAIT_SECONDS)


def parse_resolver(text: str) -> dict | None:
    """The first row of the resolver's table, or None if it found nothing. A failed query answers something else and
    raises, so an outage cannot pass for an unknown name."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not text.startswith("main_id,"):
        raise RuntimeError("the resolver did not answer with its table")
    if not rows:
        return None
    return {
        "ra": float(rows[0]["ra"]),
        "dec": float(rows[0]["dec"]),
        "main_id": rows[0]["main_id"],
        "type": rows[0]["otype"],
    }


def resolve(name: str, folder: Path) -> dict | None:
    """What the resolver says of a name. Answers are kept on disk, so a rerun asks only about what it has not seen."""
    path = folder / "resolved.json"
    known = json.loads(path.read_text()) if path.exists() else {}
    if name not in known:

        def fetch():
            literal = name.replace("'", "''")
            query = f"select main_id,ra,dec,otype from basic join ident on oidref=oid where id='{literal}'"
            params = {"request": "doQuery", "lang": "adql", "format": "csv", "query": query}
            r = requests.get(RESOLVER, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return parse_resolver(r.text)

        known[name] = _retry(fetch, "name resolver")
        path.write_text(json.dumps(known, indent=1) + "\n")
    return known[name]


def table_layout(head: bytes) -> dict:
    """Where the rows of the first table in a FITS file start, and their dtype, from the file's first bytes."""
    offset = 0
    while offset < len(head):
        cards = []
        while True:
            block = head[offset : offset + 2880]
            if len(block) < 2880:
                raise ValueError("the head of the file ended inside a header")
            offset += 2880
            cards.extend(block[i : i + 80].decode("ascii") for i in range(0, 2880, 80))
            if any(c.startswith("END") and not c[3:].strip() for c in cards[-36:]):
                break
        header = fits.Header.fromstring("".join(cards))
        if header.get("XTENSION", "").strip() == "BINTABLE":
            fields = []
            for k in range(1, header["TFIELDS"] + 1):
                form = header[f"TFORM{k}"].strip()
                fields.append(
                    (header[f"TTYPE{k}"].strip(), f"S{form[:-1] or 1}" if form.endswith("A") else FITS_FORMATS[form])
                )
            dtype = np.dtype(fields)
            if dtype.itemsize != header["NAXIS1"]:
                raise ValueError("row size does not match the header")
            return {"start": offset, "row_bytes": dtype.itemsize, "rows": header["NAXIS2"], "dtype": dtype}
        size = header.get("NAXIS1", 0) * header.get("NAXIS2", 1) if header.get("NAXIS", 0) else 0
        offset += (size + 2879) // 2880 * 2880
    raise ValueError("no table in the head of the file")


def _read_range(start: int, size: int) -> bytes:
    def fetch():
        headers = {"Range": f"bytes={start}-{start + size - 1}"}
        r = requests.get(CATALOGUE_URL, headers=headers, timeout=TIMEOUT)
        if r.status_code != 206 or len(r.content) != size:
            raise RuntimeError(f"range read gave status {r.status_code} and {len(r.content)} bytes")
        return r.content

    return _retry(fetch, "catalogue range")


def random_rows(folder: Path) -> list[dict]:
    """The catalogue rows in a fixed random order, kept on disk one by one as they are read."""
    path = folder / "random_rows.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    layout = table_layout(_read_range(0, CATALOGUE_HEAD_BYTES))
    order = np.random.default_rng([radio.SEED, 7]).integers(0, layout["rows"], RANDOM_DRAWS)
    for number in order[len(rows) : radio.RANDOM_SOURCES * 2]:
        raw = _read_range(layout["start"] + int(number) * layout["row_bytes"], layout["row_bytes"])
        row = np.frombuffer(raw, layout["dtype"])[0]
        out = {
            "row": int(number),
            "name": row["Source_Name"].decode().strip(),
            "ra": float(row["RA"]),
            "dec": float(row["DEC"]),
            "total_flux": float(row["Total_flux"]),
            "peak_flux": float(row["Peak_flux"]),
            "s_code": row["S_Code"].decode().strip(),
            "resolution": float(row["Resolution"]),
        }
        with path.open("a") as f:
            f.write(json.dumps(out) + "\n")
        rows.append(out)
    return rows


def cutout(item_id: str, resolution: int, ra: float, dec: float, folder: Path) -> Path | None:
    """The cutout FITS on disk, or None when the survey does not cover the position (the service then gives a page)."""
    path = folder / f"{item_id}-{resolution}.fits"
    absent = path.with_suffix(".none")
    if path.exists():
        return path
    if absent.exists():
        return None

    def fetch():
        params = {"pos": f"{ra:.6f} {dec:+.6f}", "size": f"{radio.FETCH_ARCMIN:g}"}
        r = requests.get(f"{SITE}/{ENDPOINTS[resolution]}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        if not r.content.startswith(b"SIMPLE") and "html" not in r.headers.get("content-type", ""):
            raise RuntimeError(f"unexpected answer of type {r.headers.get('content-type')}")
        return r.content

    content = _retry(fetch, "cutout")
    if not content.startswith(b"SIMPLE"):
        absent.touch()
        return None
    tmp = path.with_suffix(".part")
    tmp.write_bytes(content)
    tmp.rename(path)
    return path


def process(item_id: str, group: str, label: str, ra: float, dec: float, data: Path, out: Path) -> dict:
    """One field: fetch both maps, measure them and draw them. A lookalike must be detected to be accepted."""
    measures: dict = {}
    fields = {}
    for resolution in ENDPOINTS:
        path = cutout(item_id, resolution, ra, dec, data / "cutouts")
        if path is None:
            return {"status": "skipped", "reason": f"no {resolution} arcsec map here"}
        with fits.open(path) as hdul:
            header, image = hdul[0].header, hdul[0].data
        field, scale = radio.centred_field(image, header, ra, dec)
        if not np.isfinite(field).any():
            return {"status": "skipped", "reason": f"the {resolution} arcsec field is empty"}
        beam = float(header.get("BMAJ", BEAMS_ARCSEC[resolution] / 3600)) * 3600
        fields[resolution] = (field, scale)
        measures[f"score_{resolution}"] = radio.ring_score(field, scale, beam)
        measures[f"noise_{resolution}"] = radio.noise(field)
        measures[f"no_data_fraction_{resolution}"] = round(float(np.mean(~np.isfinite(field))), 4)
        measures[f"beam_arcsec_{resolution}"] = round(beam, 2)
        measures[f"arcsec_per_pixel_{resolution}"] = round(scale, 3)
    if label == radio.NOT_RING and group != "random":
        if not any(radio.detected(*fields[resolution]) for resolution in ENDPOINTS):
            return {"status": "skipped", "reason": "nothing detected near the centre"}
    images = {}
    for resolution, (field, _) in fields.items():
        images[f"image_{resolution}"] = f"images/{item_id}-{resolution}.png"
        (out / images[f"image_{resolution}"]).write_bytes(radio.field_png(field))
    return {"status": "accepted", "id": item_id, "ra": ra, "dec": dec, **images, "measures": measures}


def read_decisions(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # cut off by a kill; that object is tried again
    return rows


def slug(name: str) -> str:
    return "".join(c if c.isalnum() or c in "+-." else "_" for c in name)


def too_close(ra: float, dec: float, others: list[tuple[float, float]]) -> bool:
    """Is this field's centre within one field width of another's, so that the two share what they show?"""
    if not others:
        return False
    here = SkyCoord(ra * deg, dec * deg)
    there = SkyCoord([o[0] for o in others] * deg, [o[1] for o in others] * deg)
    return bool(np.any(here.separation(there).arcmin < radio.FIELD_ARCMIN))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--controls", default="controls")
    ap.add_argument("--data", default="data/radio")
    ap.add_argument("--out", default="out/radio_ring")
    a = ap.parse_args(argv)
    controls, data, out = Path(a.controls), Path(a.data), Path(a.out)
    (data / "cutouts").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(parents=True, exist_ok=True)
    warnings.filterwarnings("ignore")

    path = out / "decisions.jsonl"
    decisions = read_decisions(path)
    decided = {d["name"] for d in decisions}

    def record(decision: dict) -> None:
        with path.open("a") as f:
            f.write(json.dumps(decision) + "\n")
        decisions.append(decision)
        decided.add(decision["name"])
        print(f"{decision['group']} {decision['name']}: {decision['status']} {decision.get('reason', '')}", flush=True)

    def accepted(group: str | None = None) -> list[dict]:
        return [d for d in decisions if d["status"] == "accepted" and (group is None or d["group"] == group)]

    def centres() -> list[tuple[float, float]]:
        return [(d["ra"], d["dec"]) for d in accepted()]

    for group in radio.CIRCLE_GROUPS:
        for obj in json.loads((controls / f"{group}.json").read_text())["objects"]:
            if obj["name"] not in decided:
                base = {"name": obj["name"], "group": group, "label": radio.RING, "class": obj["class"]}
                item_id = f"{group}-{slug(obj['name'])}"
                record(base | process(item_id, group, radio.RING, obj["ra"], obj["dec"], data, out))

    for group, names in radio.LOOKALIKES.items():
        base = {"group": group, "label": radio.NOT_RING, "source": radio.LOOKALIKE_SOURCES[group]}
        for name in names:
            if len(accepted(group)) >= radio.PER_LOOKALIKE_GROUP:
                break
            if name in decided:
                continue
            resolved = resolve(name, data)
            if resolved is None:
                record(base | {"name": name, "status": "skipped", "reason": "the resolver does not know the name"})
            elif too_close(resolved["ra"], resolved["dec"], centres()):
                record(base | {"name": name, "status": "skipped", "reason": "too close to a field already used"})
            else:
                item_id = f"{group}-{slug(name)}"
                ra, dec = resolved["ra"], resolved["dec"]
                info = {"name": name, "main_id": resolved["main_id"], "type": resolved["type"]}
                record(base | info | process(item_id, group, radio.NOT_RING, ra, dec, data, out))
        if len(accepted(group)) < radio.PER_LOOKALIKE_GROUP:
            print(f"{group}: the list ran out at {len(accepted(group))}", file=sys.stderr)
            return 1

    base = {"group": "random", "label": radio.NOT_RING, "source": "uniform random row of the source catalogue"}
    for row in random_rows(data):
        if len(accepted("random")) >= radio.RANDOM_SOURCES:
            break
        if row["name"] in decided:
            continue
        info = base | {"name": row["name"], "row": row["row"], "catalogue": row}
        if too_close(row["ra"], row["dec"], centres()):
            record(info | {"status": "skipped", "reason": "too close to a field already used"})
        else:
            item_id = f"random-{row['row']}"
            record(info | process(item_id, "random", radio.NOT_RING, row["ra"], row["dec"], data, out))
    if len(accepted("random")) < radio.RANDOM_SOURCES:
        print(f"random: only {len(accepted('random'))} sources", file=sys.stderr)
        return 1

    items = [d for d in decisions if d["status"] == "accepted"]
    (out / "items.json").write_text(json.dumps(items, indent=1) + "\n")
    print(f"{len(items)} fields, {len(decisions)} objects tried")
    return 0


if __name__ == "__main__":
    sys.exit(main())
