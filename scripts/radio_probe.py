"""Score the annulus baseline on the drawn fields and, with ``--backend``, run the model on them too.

    uv run python -I scripts/radio_probe.py --items out/radio_ring/items.json --out-root out
    uv run python -I scripts/radio_probe.py --items out/radio_ring/items.json --out-root out --backend real

Beside each ``score.json``, ``bar.json`` holds the bar's two counts and what each group was called. ``ranks.json`` says
how the annulus score orders the fields, whatever its threshold.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from probe import radio
from probe.harness import PROBES_CAP_USD, open_client, run_baseline, run_probe

BASELINE = "annulus"


def write_bar(folder: Path, records: dict[str, dict]) -> dict:
    rows = [json.loads(line) for line in (folder / "records.jsonl").read_text().splitlines()]
    latest = {r["item_id"]: r for r in rows}
    result = radio.bar_result([r | {"group": records[r["item_id"]]["group"]} for r in latest.values()])
    (folder / "bar.json").write_text(json.dumps(result, indent=1) + "\n")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", default="out/radio_ring/items.json")
    ap.add_argument("--out-root", default="out")
    ap.add_argument("--backend", help="fake, recorded or real; without it only the baseline runs")
    ap.add_argument("--cap-usd", type=float, default=PROBES_CAP_USD, help="stop the ledger at this total")
    a = ap.parse_args(argv)
    out_root = Path(a.out_root)
    items, records = radio.load_items(Path(a.items))

    def predict(item) -> str:
        m = records[item.id]["measures"]
        return radio.annulus_rule(m["score_6"], m["score_20"])

    baseline = run_baseline(radio.SPEC, items, predict, BASELINE, out_root)
    bar = write_bar(out_root / radio.SPEC.name / BASELINE, records)
    ranks = radio.rank_summary(
        [r | {"score": float(np.fmax(r["measures"]["score_6"], r["measures"]["score_20"]))} for r in records.values()]
    )
    (out_root / radio.SPEC.name / BASELINE / "ranks.json").write_text(json.dumps(ranks, indent=1) + "\n")
    print(f"{BASELINE} {baseline['correct']} of {baseline['n']}; bar {'passed' if bar['passes'] else 'not passed'}")
    if a.backend:
        model = run_probe(radio.SPEC, items, open_client(a.backend, out_root, cap_usd=a.cap_usd), out_root)
        bar = write_bar(out_root / radio.SPEC.name / a.backend, records)
        print(f"{a.backend} {model['correct']} of {model['n']}; bar {'passed' if bar['passes'] else 'not passed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
