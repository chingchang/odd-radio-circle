"""Check the radio path against the committed runs, with no model call: same requests, same baselines, same views.

    uv run python -I scripts/radio_unchanged.py docs/reports/2026-10-31-clean-up/radio_unchanged.json

Each request is rebuilt from the items on disk, guarded, and its hash compared with the hash the paid run recorded. The
annulus baselines and the zoomed views are redrawn in a temporary folder and compared byte for byte.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from landers.models.backend import make_backend, request_hash
from landers.models.ledger import Ledger

from probe import radio, recognition
from probe.harness import Item, ProbeClient, ProbeSpec, _read_rows
from scripts import radio_probe, radio_zoom

FIRST, ZOOM = Path("docs/reports/2026-10-31-probe-orc"), Path("docs/reports/2026-10-31-probe-orc-zoom")
BASELINE_FILES = ("score.json", "bar.json", "records.jsonl", "score.md")


def requests_match(spec: ProbeSpec, items: list[Item], recorded: Path, client: ProbeClient) -> dict:
    """How many of ``items`` rebuild the request the paid run recorded, each guarded on the way."""
    rows = _read_rows(recorded)
    same = 0
    for item in items:
        req = spec.request(item)
        client._guard(req)
        same += rows[item.id]["request_hash"] == request_hash(req)
    return {"items": len(items), "recorded": len(rows), "same_hash": same}


def same_files(a: Path, b: Path, names: tuple[str, ...]) -> dict:
    return {name: (a / name).read_bytes() == (b / name).read_bytes() for name in names}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("result")
    ap.add_argument("--out-root", default="out")
    a = ap.parse_args(argv)
    out_root, result_path = Path(a.out_root), Path(a.result)
    items_path = out_root / radio.SPEC.name / "items.json"
    items, _ = radio.load_items(items_path)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        client = ProbeClient(make_backend("fake", tmp), Ledger(path=tmp / "ledger.json"), "fake")
        assert radio_probe.main(["--items", str(items_path), "--out-root", str(tmp)]) == 0
        assert radio_zoom.main(["--items", str(items_path), "--out-root", str(tmp)]) == 0
        zoom_dir = tmp / radio.ZOOM_SPEC.name / "images"
        zoomed = [
            Item(
                it.id,
                it.label,
                (*it.images, *((zoom_dir / f"{it.id}-{r}.png").read_bytes() for r in (6, 20))),
            )
            for it in items
        ]
        checked = recognition.checked_items(items, recognition.FIELD_IDS)
        result = {
            "requests": {
                "first_run": requests_match(radio.SPEC, items, FIRST / "real" / "records.jsonl", client),
                "zoom_run": requests_match(radio.ZOOM_SPEC, zoomed, ZOOM / "real" / "records.jsonl", client),
                "recognition": requests_match(
                    recognition.FIELD_SPEC, checked, FIRST / "recognition" / "records.jsonl", client
                ),
            },
            "baselines_byte_equal": {
                "first_run": same_files(tmp / radio.SPEC.name / "annulus", FIRST / "annulus", BASELINE_FILES),
                "zoom_run": same_files(tmp / radio.ZOOM_SPEC.name / "annulus", ZOOM / "annulus", BASELINE_FILES),
            },
            "model_calls": client.ledger.entries["wonder"]["units"],
        }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
