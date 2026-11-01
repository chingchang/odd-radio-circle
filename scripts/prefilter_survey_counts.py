"""Survey-wide counts on the LoTSS DR3 source table, to size the pre-filter's grid before any circle's row is read. The
queries touch no circle's position. Each answer is kept as it lands; a rerun skips it.

    uv run python -I scripts/lotss_schema.py --out out/prefilter/survey_counts.json
"""

from __future__ import annotations

import argparse
import json
import time as clock
from pathlib import Path

import pyvo

TAP_URL = "https://vo.astron.nl/tap"
SOURCES = "lotss_dr3.main_sources"
GAUSSES = "lotss_dr3.main_gausses"
# One degree of right ascension, to time the per-strip queries. It was picked for being a round number near zero.
STRIP = "ra >= 10 and ra < 11"
QUERIES = {
    "all": f"select count(*) as n from {SOURCES}",
    "majax_ge_20": f"select count(*) as n from {SOURCES} where majax >= 20",
    "majax_ge_30": f"select count(*) as n from {SOURCES} where majax >= 30",
    "majax_ge_40": f"select count(*) as n from {SOURCES} where majax >= 40",
    "majax_ge_60": f"select count(*) as n from {SOURCES} where majax >= 60",
    "majax_ge_90": f"select count(*) as n from {SOURCES} where majax >= 90",
    "majax_ge_120": f"select count(*) as n from {SOURCES} where majax >= 120",
    "majax_ge_30_round": f"select count(*) as n from {SOURCES} where majax >= 30 and minax >= 0.6*majax",
    "majax_ge_40_round": f"select count(*) as n from {SOURCES} where majax >= 40 and minax >= 0.6*majax",
    "majax_ge_60_round": f"select count(*) as n from {SOURCES} where majax >= 60 and minax >= 0.6*majax",
    "total_flux_ge_1000": f"select count(*) as n from {SOURCES} where total_flux >= 1000",
    "total_flux_ge_3000": f"select count(*) as n from {SOURCES} where total_flux >= 3000",
    "total_flux_ge_10000": f"select count(*) as n from {SOURCES} where total_flux >= 10000",
    "all_gausses": f"select count(*) as n from {GAUSSES}",
    "strip_sources": f"select count(*) as n from {SOURCES} where {STRIP}",
    "strip_sources_majax_ge_20": f"select count(*) as n from {SOURCES} where majax >= 20 and {STRIP}",
    "strip_gausses": f"select count(*) as n from {GAUSSES} where {STRIP}",
    "strip_sources_code_s": f"select count(*) as n from {SOURCES} where s_code = 'S' and {STRIP}",
    "strip_sources_code_m": f"select count(*) as n from {SOURCES} where s_code = 'M' and {STRIP}",
    "strip_sources_code_c": f"select count(*) as n from {SOURCES} where s_code = 'C' and {STRIP}",
    "all_sources_code_m": f"select count(*) as n from {SOURCES} where s_code = 'M'",
    "all_sources_code_m_majax_ge_20": f"select count(*) as n from {SOURCES} where s_code = 'M' and majax >= 20",
}
# Component counts for one strip: rows returned, not a count of a count.
STRIP_COMPONENTS = f"select source_name, count(*) as n from {GAUSSES} where {STRIP} group by source_name"
# The largest source of the strip, then every Gaussian around it: does the Gaussian table tie them to the source's name?
LARGEST = (
    f"select top 1 source_name, ra, dec, majax, s_code from {SOURCES} where s_code = 'M' and {STRIP} "
    "order by majax desc"
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="out/prefilter/survey_counts.json")
    a = ap.parse_args()
    path = Path(a.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    done = json.loads(path.read_text()) if path.exists() else {}
    tap = pyvo.dal.TAPService(TAP_URL)
    for name, query in QUERIES.items():
        if name in done:
            continue
        start = clock.monotonic()
        rows = tap.run_sync(query)
        done[name] = {"query": query, "rows": int(rows[0]["n"]), "seconds": round(clock.monotonic() - start, 1)}
        path.write_text(json.dumps(done, indent=1) + "\n")
        print(name, done[name]["rows"], done[name]["seconds"], flush=True)
    if "strip_component_rows" not in done:
        start = clock.monotonic()
        table = tap.run_sync(STRIP_COMPONENTS, maxrec=2_000_000).to_table()
        counts = [int(n) for n in table["n"]]
        done["strip_component_rows"] = {
            "query": STRIP_COMPONENTS,
            "rows": len(counts),
            "sources_with_2_or_more": sum(n >= 2 for n in counts),
            "sources_with_5_or_more": sum(n >= 5 for n in counts),
            "seconds": round(clock.monotonic() - start, 1),
        }
        path.write_text(json.dumps(done, indent=1) + "\n")
    if "largest_source_gausses" not in done:
        big = tap.run_sync(LARGEST)[0]
        name, ra, dec, major = str(big["source_name"]), float(big["ra"]), float(big["dec"]), float(big["majax"])
        radius = major / 3600
        cone = f"1=contains(point('ICRS', ra, dec), circle('ICRS', {ra}, {dec}, {radius}))"
        gausses = tap.run_sync(f"select source_name, gaus_id, total_flux, majax from {GAUSSES} where {cone}").to_table()
        done["largest_source_gausses"] = {
            "source": name,
            "majax": major,
            "gausses_within_major_axis": len(gausses),
            "gausses_named_for_the_source": sum(str(n) == name for n in gausses["source_name"]),
            "distinct_names": len({str(n) for n in gausses["source_name"]}),
        }
        path.write_text(json.dumps(done, indent=1) + "\n")
        print(done["largest_source_gausses"], flush=True)


if __name__ == "__main__":
    main()
