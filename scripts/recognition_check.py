"""Ask the model which object it is looking at, on three inputs of a probe. See ``probe/recognition.py``.

    uv run python -I scripts/recognition_check.py sheets --backend real --cap-usd 8
    uv run python -I scripts/recognition_check.py fields --backend real --cap-usd 8

The results land in ``out/<probe>_recognition/<backend>/``, like a probe's.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from probe import radio, recognition, tess
from probe.harness import PROBES_CAP_USD, open_client, run_probe


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("which", choices=("sheets", "fields"))
    ap.add_argument("--out-root", default="out")
    ap.add_argument("--backend", default="fake")
    ap.add_argument("--cap-usd", type=float, default=PROBES_CAP_USD, help="stop the ledger at this total")
    a = ap.parse_args(argv)
    out_root = Path(a.out_root)
    if a.which == "sheets":
        path = out_root / "tess" / "items.json"
        items, _ = tess.load_items(path)
        ids = recognition.sheet_ids(json.loads(path.read_text()))
        spec = recognition.SHEET_SPEC
    else:
        items, _ = radio.load_items(out_root / radio.SPEC.name / "items.json")
        ids = recognition.FIELD_IDS
        spec = recognition.FIELD_SPEC
    client = open_client(a.backend, out_root, cap_usd=a.cap_usd)
    result = run_probe(spec, recognition.checked_items(items, ids), client, out_root)
    print(f"{a.which}: {result['correct']} of {result['n']} not recognised")
    return 0


if __name__ == "__main__":
    sys.exit(main())
