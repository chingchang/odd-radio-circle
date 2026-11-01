# Pre-filter v1: the rule, written before any circle's catalogue row was read

Goal, from docs/plan.md item 2: a list of at most 1,200 LoTSS DR3 sources over the whole survey that Wonder can screen,
keeping as many of the 18 known circles as possible, from catalogue columns only.

The procedure is fixed here. The values of the cuts come out of the fit below and are added to this file, in a separate
commit, before the held-out circles are measured.

What I had seen when writing this: survey-wide counts that touch no circle's position (`scripts/prefilter_survey_counts.py`,
kept in the report folder) and the images of all 18 circles from the earlier model tests. I had not read any circle's row of
this table. The images are why the rule cannot claim the fitter was ignorant of the circles' looks.

## The columns

All from `lotss_dr3.main_sources`, per source:

| name | definition | unit |
|---|---|---|
| major | `majax`, the fitted major axis including the beam | arcsec |
| axial | `minax / majax`, 1 is round | |
| sb | `total_flux / (majax * minax)`, surface brightness | mJy per square arcsec |
| peak_ratio | `peak_flux / total_flux`, low means diffuse | per beam |
| total | `total_flux` | mJy |
| s_code | `S` single Gaussian, `M` several, `C` single in an island with others | |
| isolation | angular distance to the nearest brighter-than-S source, itself excluded (under 1 arcsec) | arcmin |

**Component count is `s_code`, not a number.** `lotss_dr3.main_gausses.source_name` names each Gaussian on its own: around
the largest multi-Gaussian source of one test strip there were 10 Gaussians with 10 different names, none of them the
source's (`survey_counts.json`, `largest_source_gausses`). So the table gives no count of components per source, and `s_code`
is what the catalogue says about it.

## The search space

A list is a box: a source is on it if it passes every cut. Every combination below is tried.

| cut | values | off means |
|---|---|---|
| major at least | 20, 25, 30, 40, 50, 60, 80, 100 arcsec | |
| major at most | 120, 180, 240, 360 arcsec, off | no upper limit |
| axial at least | 0.8, 0.7, 0.6, 0.5, 0.4, off | any shape |
| sb at most | 1e-4, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2, off | any |
| peak_ratio at most | 0.02, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, off | any |
| total at least | 50, 20, 10, 5, 2, 1, off | any |
| total at most | 10, 20, 50, 100, 200, 500, 1000, off | any |
| s_code | M only, any | |
| isolated from | (10 Jy, 30 arcmin), (10 Jy, 15 arcmin), (3 Jy, 12 arcmin), (3 Jy, 6 arcmin), (1 Jy, 6 arcmin), (1 Jy, 3 arcmin), off | no isolation cut |

The floor of 20 arcsec on major is fixed in advance. Sources below it are 12.6 million of the 13.67 million rows, and at this
list size no cut on them can be selective. A circle whose catalogue rows are all under 20 arcsec is lost, and the report says
so per circle.

The lists are computed from two server-side queries, never the catalogue file: every source with `majax >= 20` in strips of
15 degrees of right ascension, and every source with `total_flux >= 1000` for isolation. A strip whose row count differs from
the server's own count stops the run.

## What "kept" means

A circle is kept when a listed source's position lies within **the control file's rule, max(30 arcsec, half the object's
extent)** of the published position. Extents are used only where the control file gives one: J1633+1441, "diameter near 3
arcmin", so 90 arcsec. All others use 30 arcsec. The same count at a flat 60 arcsec is reported beside it as a sensitivity,
because a field centred 60 arcsec off still shows the ring near its centre, and is not used in the fit.

A lookalike or a random source is kept when a listed source lies within 3 arcmin of it, since it would then be inside a 6
arcmin field. The objects are the 30 lookalikes and 30 random sources accepted in `docs/reports/2026-10-31-radio-inputs/items.json`.

## How the box is chosen

Among all boxes of at most 1,200 sources, the first of these decides, and each later one breaks ties:

1. the most tuning circles kept, of the 9 in `controls/tuning.json`;
2. the fewest lookalikes kept, of 30;
3. the fewest random sources kept, of 30;
4. **the largest list**, because the budget pays for 1,200 and a looser box has more room for circles it was not fitted on;
5. the first in the grid's fixed order.

The fit reads no held-out position. The 9 held-out circles are in the survey the list sizes are counted over, as any source is.

## How the held-out circles are measured

Once, after the frozen cuts are committed. `scripts/prefilter.py heldout` refuses to run unless the file of frozen cuts is
committed and unchanged. It builds the list from those cuts and counts the 9 of `controls/heldout.json` under the same two
radii, with 95 percent Wilson intervals.

There is no pass bar in the plan, and I set none. **The cuts are not refitted after the held-out count, whatever it is.** If a
later item wants different cuts it writes a v2 and shows both.

## Frozen cuts (added after the fit, before the held-out count)

From `docs/reports/2026-10-31-prefilter/frozen_cuts.json`: major 40 to 240 arcsec, axial at least 0.6, peak_ratio at most
0.05, total 5 to 1000 mJy, s_code M, no source of 1 Jy or more within 6 arcmin, no cut on sb. List size 1,200 sources; it keeps
4 of 9 tuning circles, 1 of 30 lookalikes and 0 of 30 random sources.

The first fit gave 0 of 9 because `rows_near` returned row 0 for every object, a bug of mine and not a result. I fixed it, added
a test that fails on it, and refitted with the grid and the rule unchanged. A second rule, `prefilter-v2.md`, was written after
seeing these counts and before any held-out row.

## Limits known in advance

- 17 million boxes fitted on 9 circles can overfit, and the held-out count is the only check of that.
- The held-out list is not blind to me: its positions and images were read in the earlier model tests, and that list's own
  text reserves it for a blind evaluation by a person. The plan allows reading it here. It is held out from the fit only.
- Catalogue positions are PyBDSF's, and a ring may be split into pieces or fitted through its centre. A piece further than the
  radius from the published centre counts as a miss at 30 arcsec, which is why the 60 arcsec count is shown too.
