"""Check every drawn field against the guard, draw contact sheets for people, and copy the runner's files to the report.

    uv run python -I scripts/radio_report.py --report docs/reports/2026-10-31-radio-inputs

The contact sheets carry names and are never sent to a model; the probe reads only ``out/radio_ring/images``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

from landers.models.leak import check_png
from PIL import Image, ImageDraw

from probe import guard, radio

COLUMNS = 6
TILE = 240
CAPTION = 16


def contact_sheet(records: list[dict], key: str, out: Path, path: Path) -> None:
    rows = math.ceil(len(records) / COLUMNS)
    sheet = Image.new("RGB", (COLUMNS * TILE, rows * (TILE + CAPTION)), "navy")
    draw = ImageDraw.Draw(sheet)
    for i, record in enumerate(records):
        x, y = (i % COLUMNS) * TILE, (i // COLUMNS) * (TILE + CAPTION)
        sheet.paste(Image.open(out / record[key]).resize((TILE, TILE)), (x, y + CAPTION))
        draw.text((x + 2, y + 2), record["name"][:26], fill="yellow")
    sheet.save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="out/radio_ring")
    ap.add_argument("--data", default="data/radio")
    ap.add_argument("--report", required=True)
    a = ap.parse_args(argv)
    out, data, report = Path(a.out), Path(a.data), Path(a.report)
    records = json.loads((out / "items.json").read_text())

    guard.check_text(radio.PROMPT)
    guard.check_text(f"{radio.SPEC.name}_answer")
    digests = set()
    for record in records:
        for key in ("image_6", "image_20"):
            png = (out / record[key]).read_bytes()
            check_png(png)
            digests.add(hashlib.sha256(png).hexdigest())

    summary = {
        "items": len(records),
        "images_checked": 2 * len(records),
        "distinct_images": len(digests),
        "fields_with_a_9_arcsec_map_by_group": {},
        "fine_map_beams_arcsec": sorted({r["measures"]["beam_arcsec_6"] for r in records}),
        "largest_no_data_fraction": max(
            max(r["measures"]["no_data_fraction_6"], r["measures"]["no_data_fraction_20"]) for r in records
        ),
        "catalogue_rows_read": len((data / "random_rows.jsonl").read_text().splitlines()),
    }
    for record in records:
        if record["measures"]["beam_arcsec_6"] > 6.0:
            counts = summary["fields_with_a_9_arcsec_map_by_group"]
            counts[record["group"]] = counts.get(record["group"], 0) + 1

    (report / "annulus").mkdir(parents=True, exist_ok=True)
    (report / "contact_sheets").mkdir(exist_ok=True)
    for name in ("score.json", "score.md", "bar.json", "ranks.json"):
        shutil.copy(out / "annulus" / name, report / "annulus" / name)
    for name in ("items.json", "decisions.jsonl"):
        shutil.copy(out / name, report / name)
    shutil.copy(data / "resolved.json", report / "resolved.json")
    (report / "checks.json").write_text(json.dumps(summary, indent=1) + "\n")

    circles = [r for r in records if r["label"] == radio.RING]
    lookalikes = [r for r in records if r["label"] == radio.NOT_RING and r["group"] != "random"]
    random_fields = [r for r in records if r["group"] == "random"]
    for name, chosen in (("circles", circles), ("lookalikes", lookalikes), ("random", random_fields)):
        contact_sheet(chosen, "image_6", out, report / "contact_sheets" / f"{name}-6.png")
    contact_sheet(circles, "image_20", out, report / "contact_sheets" / "circles-20.png")
    contact_sheet(lookalikes, "image_20", out, report / "contact_sheets" / "lookalikes-20.png")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
