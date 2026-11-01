# Pre-filter v3: a finer low end on peak_ratio, written after v2's fit and before any held-out row

**This rule changes after seeing results, so all three versions are shown.** v1 and v2 each keep 4 of 9 tuning circles
(`frozen_cuts.json`, `frozen_cuts_v2.json`). The row tables show J0825+6132, J0823+6216 and J1436+4832 at peak_ratio 0.002 to
0.004, while the lowest value on the grid is 0.02. That was a flaw in the grid I wrote before reading these rows: no box could
pick out sources this diffuse.

## The rule

The same as v2 in every way (two boxes, one per `s_code`, sharing 1,200; the same ranking and tie-breaks), with one change: the
grid for peak_ratio at most gains 0.002, 0.003, 0.005, 0.0075, 0.01 and 0.015, so it reads 0.002, 0.003, 0.005, 0.0075, 0.01,
0.015, 0.02, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, off. No other value changes.

## Which list goes forward

Decided by code from tuning counts alone: **the version keeping the most tuning circles, and on a tie the earliest.** The
held-out count cannot change that choice.

**v3 is the last version before the held-out count, whatever it gives.** `scripts/prefilter.py heldout` counts the 9 held-out
circles for all three lists, once, and refuses unless all three frozen files are committed.

## Limits known in advance

- This is the third look at the same 9 circles, and these values were picked with their rows in view. The tuning count for v3
  is an optimistic number by construction. The held-out count is the honest one.
- It does not change the fate of J1633+1441, which has no row of 20 arcsec or more within its radius.
