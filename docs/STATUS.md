# Status: stopped on 2026-11-01

Work stopped here by the person's decision (11-01 00:26 PT). Nothing is running. Every number below is from the report named beside it.

## Where it ended (plan items 1 to 6 done)

- **Model test on known answers** (docs/reports/2026-10-31-probe-orc.md): Muse Wonder called 13 of 18 published circles ring-like and rejected 53 of 60 others; a zoomed view changed nothing (docs/reports/2026-10-31-probe-orc-zoom.md).
- **Code baselines** (docs/reports/2026-10-31-baselines.md): the annulus score tuned to threshold 0.30 calls 7 of 18 circles at their published positions but 18 of 30 random sources.
- **Pre-filter** (docs/reports/2026-10-31-prefilter.md): 1,200 of 13,667,877 catalogue rows, keeping 4 of 9 tuning and 2 of 9 held-out circles. This is the main loss.
- **Wonder screen** (docs/reports/2026-10-31-screen.md): stopped by the 36 USD cap after 934 of 1,200 rows; 200 ring-like. 5 of 18 known circles survive pre-filter plus a ring-like vote, including both held-out circles that reached the model.
- **Known-object cut and case board** (docs/reports/2026-11-01-known-cut.md, docs/reports/2026-11-01-case-board.md): 132 rows left; the board's rule grades 108 candidate and 24 needs second look, but 83 of the 108 carry a known class Wonder named (69 radio galaxy), so most are probably not rings. 3 of 18 known circles reach candidate grade.
- **Spend:** 35.971 USD on out/ledger.json (not committed).
- **README figures (11-07):** the board's rows as panels, `scripts/readme_figures.py`, from item 6's files; no verdict changed.

## Planned, not started (plan items 7 to 12)

A cheaper rerun: test the Spark contributor models (the only contributor variants with image input; no Wonder contributor variant exists on the API) on the 78-object set, then a loose pre-filter that keeps every known circle, cutouts, a new screen, a known-class grade for model-labelled rows, and a new board. Start with `caffeinate -i scripts/finish.sh 7 8 9 10 11 12` (out/queue/STOP must be removed first).

## Local state

- Archived earlier test workspace (TESS and video probes, old history): `~/HiRISE/probe_archive`.
- Cutouts under data/ and runs under out/ are gitignored.
