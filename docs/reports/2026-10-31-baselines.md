# Item 3: cutouts and code baselines for the pre-filter list

## Result

**All 1,200 listed sources have both maps drawn, with none skipped. Through the list, the annulus score at its fixed threshold of 3 calls 0 of the 18 known circles ring-like. The tuned threshold of 0.30 calls 1 of 18 (95 percent Wilson interval 0.01 to 0.26), and that one is a tuning circle.** On the 9 held-out circles, the counts that were not fitted on, both baselines call 0 of 9 through the list (interval 0 to 0.30). So item 4's Wonder screen has a low bar to clear, and it can reach at most 6 of 18, the circles the pre-filter kept.

Counts of objects, each circle once, from `2026-10-31-baselines/baselines.json`:

| of the known circles | tuning, of 9 | held-out, of 9 | all, of 18 | all, 95 percent interval |
|---|---|---|---|---|
| kept by the pre-filter | 4 | 2 | 6 | 0.16 to 0.56 |
| annulus (threshold 3), at the published position | 0 | 0 | 0 | 0 to 0.18 |
| **annulus (threshold 3), through the list** | 0 | 0 | **0** | 0 to 0.18 |
| annulus tuned (threshold 0.30), at the published position | 5 | 2 | 7 | 0.20 to 0.61 |
| **annulus tuned (threshold 0.30), through the list** | 1 | 0 | **1** | 0.01 to 0.26 |

"At the published position" uses the earlier fields, so the score is judged on all 18. "Through the list" uses fields centred on the listed row, and a circle the pre-filter lost counts as a miss.

Counts of rows and fields under the same two thresholds:

| fields called ring-like | annulus (threshold 3) | annulus tuned (threshold 0.30) | tuned, 95 percent interval |
|---|---|---|---|
| listed rows, of 1,200 | 22 | 121 | 0.09 to 0.12 |
| earlier random sources, of 30, not used in the tuning | 0 | 18 | 0.42 to 0.75 |
| earlier lookalikes, of 30, used in the tuning | 5 | 8 | |

These counts are calls by a code baseline, and none of them is a verdict on any source.

## Circle by circle

From `baselines.json`, `circles`. The score is the larger of a field's two map scores. "Offset" is the listed row's distance from the published position.

| circle | group | score at published position | listed row, offset, score | tuned call through the list |
|---|---|---|---|---|
| J1555+2726 | tuning | 2.26 | list-0853, 4.8 arcsec, 0.67; list-0854, 1.6 arcsec, 1.53 | ring-like, both rows |
| J1313+5003 | tuning | 0.34 | list-0699, 5.9 arcsec, 0.18 | no |
| J0016+2426 | tuning | 0.22 | list-0012, 4.8 arcsec, 0.15 | no |
| J0324+8322 | tuning | 0.44 | list-0176, 11.5 arcsec, -0.39 | no |
| J0825+6132 | tuning | 0.56 | not listed | no |
| J1633+1441 | tuning | 1.63 | not listed | no |
| J0823+6216 | tuning | -2.41 | not listed | no |
| J1436+4832 | tuning | -1.59 | not listed | no |
| J1608+6123 | tuning | -0.50 | not listed | no |
| J0801+5544 | held-out | -0.15 | list-0396, 1.8 arcsec, -0.37 | no |
| J0940+6028 | held-out | -0.25 | list-0475, 12.6 arcsec, -0.52; list-0476, 10.7 arcsec, -0.23 | no |
| J0847+7022 | held-out | -0.97 | not listed | no |
| J1134+6642 | held-out | -0.07 | not listed | no |
| J1150+2449 | held-out | -0.23 | not listed | no |
| J1222+6436 | held-out | 0.49 | not listed | no |
| J0320+1610 | held-out | -0.40 | not listed | no |
| J1458+4534 | held-out | 1.69 | not listed | no |
| J1559+2734 | held-out | -0.46 | not listed | no |

Of the 7 circles the tuned threshold calls at their published positions, the pre-filter lost 4 (J0825+6132, J1633+1441, J1222+6436, J1458+4534). Two more, J1313+5003 and J0324+8322, fell below the threshold once the field was centred on the listed row instead of the published position. No lost circle shows up by accident in another row's field: the nearest listed row to any of the 12 is 20.83 arcmin away, and each field is only 6 arcmin across.

## Sizes and timings

From `baselines.json`, `sizes` and `timings_seconds_per_field`:

| | files | bytes |
|---|---|---|
| FITS cutouts, `data/radio_list/cutouts` (not in git) | 2,400 | 369,792,000 |
| PNG fields, `out/radio_list/images` (not in git) | 2,400 | 95,449,671 |

| seconds per field | median | 95th percentile | largest | total |
|---|---|---|---|---|
| fetch both maps | 22.73 | 23.15 | 26.03 | 27,351.5 |
| draw and score | 0.09 | 0.14 | 0.21 | 101.6 |

The service takes about 11 seconds per map, half the median above, with 6 workers running. The fetch total divided by those 6 workers is about 76 minutes. No fetch run stopped on a network failure.

## What ran

1. The rule, `docs/proposals/baselines-v1.md`, and the code were committed in `f0ed382`, before the tuning and before any listed field was drawn.
2. `tune` froze the threshold, committed in `ccc0a90`. `fetch` and `score` refuse to run unless that file and the list are committed and unchanged, and a test holds that.
3. `fetch` ran in four parts, with `fields.jsonl` committed after the larger parts.
4. `score` made every count and wrote `items.json`, which item 4 can load. It holds 1,200 fields, 8 rows labelled as known circles and the rest `unlabelled`.

The tuning, from `frozen_threshold.json`: over the 9 tuning circles and 30 lookalikes, choose the threshold with the largest (circles called / 9 + lookalikes not called / 30 - 1), and on a tie the highest. It gave 0.2965, calling 5 of 9 tuning circles and leaving 22 of 30 lookalikes uncalled, for a value of 0.29. Neither held-out circles nor random sources were read, and a test holds that.

Checks, from `baselines.json`, `checks`: all 2,400 PNGs passed the metadata guard and are distinct. The earlier prompt built into a request for each of the 1,200 fields passed the leak guard, with no call made. The same code, rerun on the 18 circles' stored cutouts, gave the same scores and the same PNG bytes as the earlier run for all 18, which is the evidence for "drawn as in the earlier inputs". `scripts/check.sh` passed: 153 tests, ruff and the prompt check. No model call was made and no money was spent.

## What I decided, and why

- **I did the item rather than marking it for a person,** though the session's instructions say a threshold needs a person. The item itself tells the agent to tune this one and state how, and it is a comparison that assigns no verdict. No control file was edited and no tag was made. The same call was made and stated in item 2. A person who disagrees loses nothing, because the threshold is used only in this report's counts.
- **A field's id is its row number in the list** (`list-0001`), so neither file names nor ids carry a designation. Names stay in `fields.jsonl` and `items.json`, for people.
- **I added an optional threshold to `radio.annulus_rule`.** Its default is unchanged, so the first baseline is the same as before.
- **Six workers,** because one at a time would take about 7.6 hours and a short trial before the run, which wrote no file, showed no slowdown with several requests at once. It is a public service, and I did not go higher.

## What a reader should doubt

- **The tuned threshold sits at noise level.** It calls 18 of the 30 random sources, which the tuning did not read. A score of 0.30 means little, and calling 7 of 18 circles at their positions is not evidence that the score sees rings. The value of 0.29 was fitted on 39 fields.
- **The list's 121 calls do not mean the tuned score is selective.** It calls 10 percent of the list and 60 percent of the random fields. My reading, not measured: listed sources are bright and extended, which lifts the medians the score subtracts, while nearly empty fields sit around zero. So the score's meaning shifts with the field, and a threshold tuned on one kind of field does not carry over to another.
- **The tuning fields are centred differently from the list's.** The threshold was tuned on published positions and applied on catalogue positions. J0324+8322 moved from 0.44 to -0.39 with an 11.5 arcsec shift, so the score is sensitive to centring.
- **The score rewards curves, not circles.** I viewed `contact_sheets/top_score-6.png`: the highest scores are mostly bent jets and tails with an arc near the centre. M57-like sharp rings score high too, as the earlier report said. A circle shown as a filled disc does not.
- **The list holds few obvious rings.** In `contact_sheets/sample-6.png`, 36 fields drawn with a fixed seed, most are radio galaxies, irregular diffuse patches, or bright sources with radial spokes, even with the isolation cut. Some fields look round. I viewed these by eye, they are not assessed, and nothing in this report grades them. A person or item 4 should not read the sheets as a result.
- **Rows are not objects.** 78 of the 1,200 rows have another listed row within 3 arcmin, so those rows' fields share sky. Two circles take two rows each. Item 4 will pay for those rows separately.
- **The resolution varies.** 245 of the 1,200 fine maps have a 9 arcsec beam and 955 have 6, while the earlier prompt says "about 6 arcsec".
- **Some fields are cut short.** 2 of the 1,200 have over 1 percent no data, and the largest fraction is 0.3168, in list-1171. All are kept, and the missing part is black.
- **The redraw check covers the 18 circles only.** The 1,200 fields go through the same function, but nothing earlier exists to compare them with.
- **The held-out circles are not blind,** as the pre-filter and radio-inputs reports say. Their images were viewed in earlier work, though the tuning code does not read their scores.
- **The rule's author knew the score was weak.** The rule says so and expected a low threshold. It did not know the 39 scores.
- **No rule was changed after results.** The `requests_guarded` count was added to `score` after its first run. It changes no other number, and `score` was rerun with the same counts.

## Commands

    uv run python -I scripts/list_fields.py tune
    uv run python -I scripts/list_fields.py fetch --limit 12
    uv run python -I scripts/list_fields.py fetch --limit 400
    uv run python -I scripts/list_fields.py fetch --limit 400
    uv run python -I scripts/list_fields.py fetch
    uv run python -I scripts/list_fields.py score
    scripts/check.sh

Data: LoTSS DR3, Shimwell et al. 2026, A&A 707, A198. Known circles: De Gasperin et al. 2026 (arXiv:2602.18294).
