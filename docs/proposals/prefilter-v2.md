# Pre-filter v2: two boxes, written after seeing v1 on the tuning circles and before any held-out row

**This rule changes after seeing results, so both are shown.** v1 (`prefilter-v1.md`) is frozen and keeps 4 of 9 tuning
circles. Its row table (`docs/reports/2026-10-31-prefilter/tuning_circles.json`) shows why. The kept circles are `M` sources,
and most of the missed ones are large `S` sources with very low peak_ratio. One box holding both goes over 1,200. No held-out
row has been read, so the held-out count still tests whatever is chosen here.

## The rule

A list is the union of two boxes: one over `s_code = M` sources and one over `s_code = S`. Each uses the v1 grid for its other
eight cuts, with the same values. `C` sources are on neither. The two boxes share the budget of 1,200 sources.

Each box must keep at least one tuning circle, so the second box cannot be used as filler. Kept, the radii and the objects are
as in v1.

Among all pairs, the first of these decides and each later one breaks ties:

1. the most tuning circles kept by the union, of 9;
2. the fewest lookalikes kept by the union, of 30;
3. the fewest random sources kept by the union, of 30;
4. the largest list;
5. a fixed order: the sets of objects each box keeps in ascending order of their bit masks, then the first box in the v1
   grid's order that gives that set and size.

## Which list goes forward

Decided now, by code, from tuning counts alone: **v2 goes to item 3 if it keeps more tuning circles than v1; otherwise v1
does.** The held-out count cannot change that choice. `scripts/prefilter.py heldout` counts the 9 held-out circles for both
lists, once, and refuses unless both frozen files are committed. Neither is refitted afterwards.

## Limits known in advance

- More freedom on the same 9 circles means more room to overfit. Tuning counts for v2 say less than those for v1, and the
  held-out comparison of the two is the check.
- The split on `s_code` comes from looking at the tuning circles' rows. It is not a physical claim about circles.
- J1633+1441 has no row of 20 arcsec or more within its 90 arcsec radius, so neither rule can keep it.
