"""Draw the central 3 arcmin of every field from the cutouts on disk and, with ``--backend``, ask the model on all four
views.

    uv run python -I scripts/radio_zoom.py
    uv run python -I scripts/radio_zoom.py --backend real

Nothing is downloaded. A field that no longer draws the same as the first run's view stops the run, so the added views
are known to come from the same pixels. A rerun skips what was already answered, as in ``scripts/radio_probe.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from astropy.io import fits

from probe import guard, radio
from probe.harness import Item, open_client, run_baseline, run_probe
from scripts.radio_probe import BASELINE, write_bar

STOP_AT_USD = 7.9922  # item 4's 3.9922 on the shared ledger, and this item's 4


def draw(record: dict, source: Path, data: Path, out: Path) -> dict:
    """One object's two zoomed views on disk; their paths, relative to ``out``."""
    zoomed = {}
    for resolution in (6, 20):
        with fits.open(data / "cutouts" / f"{record['id']}-{resolution}.fits") as hdul:
            header, image = hdul[0].header, hdul[0].data
        field, _ = radio.centred_field(image, header, record["ra"], record["dec"])
        if radio.field_png(field) != (source / record[f"image_{resolution}"]).read_bytes():
            raise RuntimeError(f"{record['id']}: the {resolution} arcsec map does not draw the first run's view")
        png = radio.zoom_png(field)
        guard.check_png(png)
        zoomed[f"zoom_{resolution}"] = f"images/{record['id']}-{resolution}.png"
        (out / zoomed[f"zoom_{resolution}"]).write_bytes(png)
    return zoomed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", default="out/radio_ring/items.json")
    ap.add_argument("--data", default="data/radio")
    ap.add_argument("--out-root", default="out")
    ap.add_argument("--backend", help="fake, recorded or real; without it only the views and the baseline")
    ap.add_argument("--cap-usd", type=float, default=STOP_AT_USD, help="stop the ledger at this total")
    a = ap.parse_args(argv)
    source, data, out_root = Path(a.items).parent, Path(a.data), Path(a.out_root)
    spec = radio.ZOOM_SPEC
    out = out_root / spec.name
    (out / "images").mkdir(parents=True, exist_ok=True)

    first_items, records = radio.load_items(Path(a.items))
    guard.check_text(radio.ZOOM_PROMPT)
    items = []
    for item in first_items:
        records[item.id] |= draw(records[item.id], source, data, out)
        views = [(out / records[item.id][key]).read_bytes() for key in ("zoom_6", "zoom_20")]
        items.append(Item(item.id, item.label, (*item.images, *views)))
    (out / "items.json").write_text(json.dumps(list(records.values()), indent=1) + "\n")

    def predict(item: Item) -> str:
        m = records[item.id]["measures"]
        return radio.annulus_rule(m["score_6"], m["score_20"])

    baseline = run_baseline(spec, items, predict, BASELINE, out_root)
    bar = write_bar(out / BASELINE, records)
    print(f"{BASELINE} {baseline['correct']} of {baseline['n']}; bar {'passed' if bar['passes'] else 'not passed'}")
    if a.backend:
        model = run_probe(spec, items, open_client(a.backend, out_root, cap_usd=a.cap_usd), out_root)
        bar = write_bar(out / a.backend, records)
        print(f"{a.backend} {model['correct']} of {model['n']}; bar {'passed' if bar['passes'] else 'not passed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
