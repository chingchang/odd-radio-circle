# Code baselines on the pre-filter list: the rule, written before the threshold is tuned

From docs/plan.md item 3: two code baselines on every pre-filter source, the annulus score as before, and the same score
with its threshold tuned on the tuning circles and lookalikes. Nothing here assigns a verdict. These are the comparison that
Wonder's screen in item 4 is read against.

What I had seen when writing this: the earlier report's summary of the annulus score (0 of 18 circles at the threshold of 3,
best circle 2.26, a circle outranks another field 42 percent of the time, `docs/reports/2026-10-31-radio-inputs.md`). I had not
read the 39 scores the tuning uses, nor drawn or scored any field of the pre-filter list. Since a circle barely outranks
anything, **I expect the tuned threshold to be low and to call a large share of the list ring-like.** The rule is not changed
if it does; the report gives the count.

## The two baselines

The score is `radio.ring_score`, unchanged, on the 6 arcsec map and the 20 arcsec map of a field. Each baseline calls a field
ring-like if either map's score reaches its threshold, as `radio.annulus_rule` does. A NaN score reaches no threshold.

| baseline | threshold |
|---|---|
| annulus | 3.0, as fixed in `probe/radio.py` before its first run |
| annulus tuned | from the fit below, frozen in `docs/reports/2026-10-31-baselines/frozen_threshold.json` |

## How the threshold is tuned

The rows are the fields already drawn in `docs/reports/2026-10-31-radio-inputs/items.json`, each centred on its published or
resolved position, with the scores stored there:

- the 9 tuning circles, which should be called ring-like;
- the 30 lookalikes (ring galaxies, planetary nebulae, supernova remnants, radio galaxies, artefact rings), which should not.

Held-out circles and random sources are not read. An unknown group stops the run.

A field's value is the larger of its two scores, so the "either map" rule becomes one number. The candidates are one value
below the lowest finite score, every midpoint between neighbouring distinct finite scores, and one value above the highest.

The threshold is the candidate with the largest **circles called / 9 + lookalikes not called / 30 - 1**. On a tie the highest
candidate wins, because it calls the fewest fields. A score that cannot tell the groups apart therefore gets a threshold above
every field and calls nothing.

## Order

1. This rule and the code, committed.
2. `scripts/list_fields.py tune` writes the frozen threshold, committed.
3. `fetch` refuses to run unless the frozen threshold and the pre-filter list are committed and unchanged. It fetches and
   draws every listed source, with each field's result written as it lands.
4. `score` refuses on the same condition, and makes every count. The held-out circles are first scored at the tuned threshold
   here. The threshold is not refitted afterwards, whatever the counts are. Any later change is a v2, shown beside this.

## What the report counts

There is no pass bar in the plan, and I set none.

- On the 1,200 rows: fields drawn, fields skipped and why, and how many rows each baseline calls ring-like.
- On the 18 known circles, each counted once as an object, in two ways, with 95 percent Wilson intervals and tuning and
  held-out apart:
  1. at the published position, on the earlier fields, so the score is judged on all 18;
  2. through the list: a circle counts only if a listed row within its kept radius (`prefilter.circle_radius_arcsec`) is called
     ring-like. Circles the pre-filter lost count as misses. This is the code's own end-to-end rate, the number item 4 compares
     with.
- On the earlier 30 random sources, which the tuning did not read, how many the tuned threshold calls, as a false-call rate.
- Sizes on disk and timings per field.

## Drawing

Exactly as in `scripts/radio_inputs.py`: both maps through the cutout API at 6.5 arcmin, cropped to 6, centred on the listed
position, drawn by `radio.field_png`. The check is that the same code, rerun on the 18 circles' stored cutouts, gives the same
PNG bytes and scores as the earlier run. Images and item ids carry no name or position. A field's id is its row number in the
list, `list-0001`; the source's name stays in the runner's files for people.
