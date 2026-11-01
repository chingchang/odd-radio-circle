# Plan

Odd radio circle search on LoTSS DR3. Wonder screens, code cuts, every number from a runner's file. Up to 40 USD of model
calls. Background: the model tests in docs/reports/2026-10-31-probe-orc*.md (13 of 18 circles, 53 of 60 others).

## Now (in order; the agent keeps the status)

1. [done, see docs/reports/2026-10-31-clean-up.md] Clean-up check. This repo was cut down from an earlier test workspace: everything for other tests was removed.
   Remove any code, tests, docs or imports that still refer to the removed TESS and video probes (probe/recognition.py,
   scripts/probe_report.py, scripts/recognition_check.py, tests/test_recognition.py and docs/probes.md mention them), keep
   the radio-circle path working, and make scripts/check.sh green. No behaviour change for the radio code. Report, done.
2. [done, see docs/reports/2026-10-31-prefilter.md] Pre-filter from the LoTSS DR3 catalogue, server side (ASTRON VO TAP, table lotss_dr3.main_sources; never the full catalogue file). Goal: a list of at most 1,200 sources over the whole survey that Wonder can screen within budget, keeping as many of the 18 known circles as possible. Use only catalogue columns (size, total and peak flux, surface brightness, component count, isolation from bright sources). Fit the cuts on the 9 tuning circles in controls/tuning.json, the lookalikes and random sources from the earlier inputs, then report how many of the 9 circles in controls/heldout.json the frozen cuts keep (that list may be read; it is not used for fitting). Write the rule in docs/proposals/prefilter-v1.md before measuring. Report list size, circles kept (of 9 and of 9), and how the cuts were chosen. Done.
3. [running] Cutouts and code baselines for the pre-filter list: 6 and 20 arcsec maps through the cutout API, resumable, written as they land, drawn as in the earlier inputs. Two code baselines on every source: the annulus score as before, and the same score with its threshold tuned on the tuning circles and lookalikes (state the tuning). Report sizes, timings and both baselines on the 18 known circles. Done.
4. [ ] Wonder screen, real run (the runner loads the key; stop at 36 USD): every pre-filter source, with the earlier prompt and the two 6-arcmin views, one vote each; a second vote only for sources called ring-like. Record ring-like, known class and the model's reason. Report: how many called ring-like, how many of the 18 known circles survive pre-filter plus Wonder (the end-to-end hit rate, with a 95 percent interval), and cost. Done.
5. [ ] Known-object cut on the ring-like sources, code only: cross-match within 1 arcmin against SIMBAD (galaxies with optical size above the ring, planetary nebulae, supernova remnants, HII regions) and the bright calibrator list, and flag sources sitting on artefact spokes of a bright source. A known circle that a cut would remove counts against the cut. Report what each cut removes and what is left. Done.
6. [ ] Case board and README: the surviving ring-like sources that are not known circles, each with both maps, Wonder's reason and votes, the cross-match result and the fixed verdict words (candidate needs the code checks to pass and two ring-like Wonder votes; otherwise needs second look). Plus a page with the 18 known circles and where each was kept or lost. Static HTML; README results section with the end-to-end numbers and their sources. Done.

## Decisions (dated)

- 10-31 19:30 (person): fresh repo for the radio circle search only; earlier test workspace archived outside the repo.
