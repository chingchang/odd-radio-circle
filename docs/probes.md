# Probes

The pass bars, written before any real call. They are copied unchanged from docs/plan.md, and a test holds them equal.

## Pass bars

- TESS: planet vs eclipsing binary correct on at least 80 percent of those 40, and better than the code baseline.
- Radio circles: at least 14 of the 18 circles called ring-like, and at least 80 percent of the 60 others not.
- Video: agrees with the published rating on at least 80 percent, and better than the majority class.

## How a probe is scored

`probe.harness.run_probe` writes `out/<probe>/<backend>/records.jsonl` (request, answer, label, cost per item),
`score.json` and `score.md`; `run_baseline` writes the same beside it under the baseline's name. Accuracy comes with a
95 percent Wilson interval and a confusion table. A failed call or an off-schema answer counts as wrong and keeps its
own column.

## TESS inputs and code rule

`scripts/tess_inputs.py` picks 20 signals per class, in a fixed random order, and draws one sheet each; every signal it
tried is in `out/tess/decisions.jsonl`. A planet is CP or KP in the candidate table and a false alarm is FA. An eclipsing
binary is FP and also in the published eclipsing binary catalogue at the signal's period, half of it or twice it. A
signal needs SPOC 2-minute data, and at least 10 cadences in its odd dips and 10 in its even ones.

The code rule in `probe/tess.py`, on the same light curves, was fixed before its first run on these signals:

- False alarm if the dip's signal to noise is below 7.
- Otherwise eclipsing binary if any of these holds: depth over 3 percent; odd and even differ by at least 3 sigma and
  10 percent of the depth; a dip at phase 0.5 of at least 3 sigma and 5 percent of the depth.
- Otherwise planet.

## Radio circle inputs and annulus score

`scripts/radio_inputs.py` fetches a 6 arcmin square from the survey's 6 and 20 arcsec maps for each object, centred on
it, and draws both with one asinh stretch and nothing but pixels; every object it tried is in
`out/radio_ring/decisions.jsonl`. Ring-like is the 18 circles in `controls/`, kept whatever they show. Not ring-like is 6
each of ring galaxies, planetary nebulae, supernova remnants, radio galaxies and artefact rings, the first in each list
in `probe/radio.py` with both maps and a peak of at least 1 mJy per beam within 2.5 arcmin of the centre, and 30 random
rows of the source catalogue. No field centre is within 6 arcmin of another, apart from what the circle lists themselves hold.

The score in `probe/radio.py`, on the same maps, was fixed before its first run on a real field. For each radius from 0.4
to 2.6 arcmin, cut the annulus into 12 sectors and take each sector's mean above the brighter of the median inside and
the median outside, in units of the noise of that mean with the beam's correlation. The 8th best sector is the radius's
score, and the best radius is the map's score. A field is ring-like if either map's score is at least 3.

## Radio zoom test

Written before its real call. The first run drew a 1 arcmin circle in a sixth of a 6 arcmin image, so this run sends all 78
objects with two more images: the central 3 arcmin of each of the same two maps, cut from the cutouts already on disk and
checked against the first run's views pixel for pixel. The stretch is linear, black at 1 sigma below the median and white
at 5 sigma above it, with median and noise taken over that map's whole 6 arcmin field. Crop and stretch are constants in
`probe/radio.py`, the same for every object, and use no object's size or class. They were set before any zoomed view was
drawn. Pixels are repeated and never smoothed. The prompt says only what the two added images are; the rest of it, the
schema and the bar stay as they are, at least 14 of the 18 circles and at least 80 percent of the 60 others. The annulus
score is the first run's, on the same maps. The run stops at 4 USD of its own, 7.9922 USD on the shared ledger.

## Recognition check

Written before the first real call. Each probe's inputs also go to the model with a second question, `probe/recognition.py`:
do you recognise which object this is, and if so what is it called? The three sheets are the first three signals, in the
fixed random order, with disposition KP, known planets from before the survey. The three fields are NGC 6720, NGC 4736 and
3C 196, picked as the likeliest among the fields to be known by shape. The check does not change a probe's bar. A correct
name is reported beside the probe's verdict, as a reason to doubt that answers came from the pixels; a wrong name, or none,
means this check found no such doubt on those three, and says nothing of the other inputs.

## Cost

The real ledger is `out/ledger.json`, shared by the three probes and capped at 10 USD. It charges a Wonder call at least
1,500 input tokens per image, because the API's reported count may fall short of the bill; the recordings under
`out/model_recordings/` keep what the API reported.
