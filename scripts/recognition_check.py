"""Ask the model which object it is looking at, on three of the radio fields. See ``probe/recognition.py``.

    uv run python -I scripts/recognition_check.py --backend real --cap-usd 8

The results land in ``out/radio_ring_recognition/<backend>/``, like a probe's.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from probe import radio, recognition
from probe.harness import PROBES_CAP_USD, open_client, run_probe


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-root", default="out")
    ap.add_argument("--backend", default="fake")
    ap.add_argument("--cap-usd", type=float, default=PROBES_CAP_USD, help="stop the ledger at this total")
    a = ap.parse_args(argv)
    out_root = Path(a.out_root)
    items, _ = radio.load_items(out_root / radio.SPEC.name / "items.json")
    client = open_client(a.backend, out_root, cap_usd=a.cap_usd)
    checked = recognition.checked_items(items, recognition.FIELD_IDS)
    result = run_probe(recognition.FIELD_SPEC, checked, client, out_root)
    print(f"fields: {result['correct']} of {result['n']} not recognised")
    return 0


if __name__ == "__main__":
    sys.exit(main())
