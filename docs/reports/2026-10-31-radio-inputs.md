# Item 3, radio circle probe inputs: done

All 78 fields are fetched and drawn at both resolutions, and the annulus baseline is scored. No real model call was made and no money was spent. I did not run the fake backend on these fields, because the person's decision of 10-31 11:55 says no fake-backend runs. The plan's item 3 text still asks for one, so this departs from that text. The plumbing is covered only by a test on synthetic images, and item 4 will be the first run of this probe through a model.

## Results

These counts come from the runner's files in [2026-10-31-radio-inputs/](2026-10-31-radio-inputs/annulus/).

| run | circles called ring-like (bar: at least 14 of 18) | others called not ring-like (bar: at least 48 of 60) | all fields | 95 percent Wilson interval |
|---|---|---|---|---|
| annulus score | 0 of 18 | 55 of 60 (0.9167) | 55 of 78 (0.7051) | 0.5962 to 0.7948 |

Confusion table (rows are labels):

| label | not_ring_like | ring_like |
|---|---|---|
| not_ring_like | 55 | 5 |
| ring_like | 18 | 0 |

The baseline fails the circle half of the bar outright. The 55 of 78 mostly reflects that it says "not ring-like" nearly every time, so it is a low comparison. The bar for this probe does not require beating the baseline.

| group | fields | called ring-like by the annulus score |
|---|---|---|
| tuning circles | 9 | 0 |
| held-out circles | 9 | 0 |
| ring galaxies | 6 | 0 |
| planetary nebulae | 6 | 1 |
| supernova remnants | 6 | 0 |
| radio galaxies | 6 | 0 |
| artefact rings | 6 | 4 |
| random sources | 30 | 0 |

The score was not retuned after these results. A lower threshold would not rescue it. Whatever the threshold, a circle outranks another field only 42 percent of the time (`ranks.json`), and it outranks a random source only 31 percent of the time. The best circle scores 2.26 against a threshold of 3. The score does respond to sharp rings: M57 and four of the artefact fields score well above every circle. It misses the circles because many of them look like filled discs at these resolutions, and the score asks for a ring brighter than its inside.

## What was built

- `probe/radio.py`: the lookalike lists, centring, the asinh stretch, the score, the prompt and the bar.
- `scripts/radio_inputs.py`: fetches and draws. It writes each decision as it lands, resumes after a kill, and stops on a network failure instead of skipping an object.
- `scripts/radio_probe.py`: runs the baseline, and the model too when given `--backend`. Item 4 runs it with `--backend real`.
- `scripts/radio_report.py`: the guard pass over all fields, the contact sheets and the copies in the report folder.
- `tests/test_radio.py`: new tests, 90 in the suite in all.

Results go to `out/radio_ring/`. The name avoids "circle" because the schema name reaches the model.

## Selection

- Circles: all 18 from `controls/tuning.json` and `controls/heldout.json`. All have both maps, and none was dropped. I did not edit the control files; the lookalike lists are in `probe/radio.py`, though `tuning.json` offers a slot for them.
- Lookalikes: the first 6 per group from fixed lists with spares, written before any of these fields was fetched. Positions are from SIMBAD (`resolved.json`).
- Random: uniform random rows of the source catalogue, seed 20261031, read one row at a time by HTTP range rather than downloading the 3 GB file. 60 rows were read and the first 30 were used.

83 objects were tried for 78 fields (`decisions.jsonl`). The 5 skips were all for missing map data: Abell 39, Cas A (SNR G111.7-02.1), Tycho (SNR G120.1+01.4), SNR G084.9+00.5 and 3C 348.

The cutouts take 24 MB in `data/radio`, which git ignores, like the 156 images in `out/radio_ring/images`. The contact sheets in the report folder carry names, are for people only, and are never sent to a model.

## Decisions changed after seeing data

The score's formula and threshold and the stretch did not change after any real field was seen. Three other things did, and each could affect the verdict:

- **The lookalike filter.** The first rule asked for 5 sigma within 0.75 arcmin of the centre. It refused bright remnants that fill the field, inflate the noise estimate, or sit off-centre. It is now a peak of at least 1 mJy per beam within 2.5 arcmin. That rule rejects little, so it removes only empty fields. I reran the selection from scratch. The ring galaxy and planetary nebula picks came out the same under both rules.
- **The cutout size.** Cutouts are now fetched at 6.5 arcmin and cropped to 6, which removes a thin rim of empty pixels that edge rounding left. The largest no-data fraction is now 0.0001 (`checks.json`).
- **The prompt, which I changed after viewing the circles, including the held-out ones.** My first wording said "large, faint, edge-brightened", but many circles here are bright round discs about 1 arcmin across. It now says "a round ring, or a round disc of diffuse emission with a brighter edge or structure inside it", and that it "can be bright or barely above the noise". This tunes the question on the positive examples. No model had seen either version. The plan allows reading both lists, but the prompt is not independent of the 9 held-out circles.

## Weaknesses that bear on the verdict

I viewed all 78 fields at 6 arcsec, and the circles and lookalikes at 20 arcsec too. These findings come from that viewing.

- **The held-out list is no longer blind.** Its own text says "Never read by an agent" and reserves it for a person's blind evaluation after a freeze tag. The plan and CLAUDE.md allow reading it here, so I did. Its names and positions are now in this report's `items.json`, and I have seen those fields. If any other project counts on these 9 as a blind test, they no longer are one, and that project needs a new set.
- **Several circles and lookalikes look alike, and a good answer may be impossible from pixels.** M97 (NGC 3587) and M57 are round discs or rings of about the right size. NGC 4736 shows clear rings. The prompt's size range and description do not exclude them, so a model that calls these ring-like is reading the image correctly and still scores wrong. The bar allows at most 12 such errors across the 60 others.
- **The 30 random fields are easy and help the second half of the bar.** Most hold only faint point sources. The 48 of 60 needs just 18 of the 30 lookalikes if all random fields are right, so the bar can be met while calling 12 of the 30 lookalikes ring-like. The per-group counts in `bar.json` will show this.
- **The supernova remnant group is weak.** Cas A and Tycho have no usable map. W 49B and 3C 396 show real shells but are larger than the field. SNR G041.1-00.3 sits in a corner, because the SIMBAD position appears to be about 2 arcmin off. SNR G054.1+00.3 shows almost nothing in the 6 arcsec map. SNR G074.9+01.2 and SNR G130.7+03.1 fill the field with cloud and no ring. Only about two of the six are real ring-like tests.
- **Ring galaxies are mostly compact here.** Only NGC 4736 shows a ring. The others are near-point sources or blobs, because the rings are small or weak at these frequencies, so this group is easier than its name suggests.
- **The artefact group is bright calibrators, not rings catalogued in a paper.** I chose 6 bright sources where imaging limits leave rings. All six show concentric rings or ripples on viewing, but no paper lists them as artefact rings. The score flagged 4 of them.
- **The citations were not checked paper by paper.** The per-group sources in `probe/radio.py` are written from memory at catalogue level. The one table I tried to fetch (the planetary nebulae of Hajduk et al. 2021) timed out repeatedly, so its membership is unverified for the six used.
- **Some circles are not clean rings.** The list includes candidates as well as confirmed circles, and J1436+4832 in particular is a large irregular complex. Its label comes from the control file and I did not change it. J1150+2449 and J1222+6436 are barely above the noise.
- **Resolution varies.** 10 of the 78 fine maps have a 9 arcsec beam rather than 6 (`checks.json`), at low declination, and the prompt says "about 6 arcsec". They are spread across groups, though 3 of the 6 remnants have it.
- **Field size.** All fields are 6 arcmin, so anything larger shows only part of itself. Fixing the size keeps framing from hinting at the group.
- **Famous objects may be recognised.** M57, 3C 196 and others have well-known shapes. Item 4's recognition check tests this for 3 of them, which is not all of them.

## Checks

`scripts/check.sh` passed: 90 tests, ruff, and the prompt check. The prompt, the schema name and all 156 images passed the guard (`checks.json`), and the images are pixels only. A test confirms no ID or group name reaches a request. Two parts were not tested: the real backend, and how the model reads a pair of 720 by 720 images.

For item 4, a rough cost is about 1.1 USD. That scales the simulated TESS charge of 0.43 USD for 60 images to 156 images and is an estimate, not a quote.

The catalogue file holds 13,667,877 rows, where the release page says 13,664,379. I used the file as it is and did not look into the difference.

Three commands were denied in this unattended session, and none affected a result: a search of the home directory for existing survey code, a comparison of these control lists with the ones in `../finding-landers`, so I do not know whether the two copies match, and one long inline script, which I replaced with `scripts/radio_report.py`. Four commits on this branch record the path before the final one: `8ad9953` (code before any real field), two for the resolver fix, because the first left the old address in place, and one for the filter and cutout size change.
