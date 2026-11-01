# Known-object cut on the ring-like rows: the rule, written before any of those rows is measured

From docs/plan.md item 5, code only, with no model call. Nothing here assigns a verdict. Item 6 does that.

What I had seen when writing this: the screen's report, a query on one named object to learn SIMBAD's columns, SIMBAD's table of
object types, and images and pixel measures of fields outside the cut's rows: the earlier 78 fields, including the held-out
circles, and the list rows with a not-ring-like first vote. I had not queried SIMBAD at any listed position, and had not measured
or drawn anything new for a row with a ring-like first vote, though two contact sheets of such rows were viewed in item 4.

## The rows

Every row with a ring-like first vote in `docs/reports/2026-10-31-screen/votes.jsonl`. A second vote does not choose the rows, and
counts are also given for rows with two ring-like votes. The model's `known_class` and reasons are not read by any cut.

## The cuts

Each is run on every row, so a row can be removed by several. **A row is left if no cut removes it.**

| cut | removes a row when |
|---|---|
| `galaxy_larger` | a SIMBAD galaxy lies within 1 arcmin and its optical major axis is above the ring |
| `planetary_nebula` | a SIMBAD planetary nebula or candidate lies within 1 arcmin |
| `supernova_remnant` | a SIMBAD supernova remnant or candidate lies within 1 arcmin |
| `hii_region` | a SIMBAD HII region lies within 1 arcmin |
| `calibrator` | a source on the calibrator list lies within 1 arcmin |
| `spokes` | the field's negative depth reaches the frozen threshold and it has a bright source |

- **SIMBAD:** a cone of 1 arcmin around the row on the `basic` table, on the CfA mirror the project already uses. Only an object's
  main type counts, because secondary types are noisy (M 57 carries a star's types too). A type's family comes from SIMBAD's own
  `otypedef` table, saved in the report folder: galaxy if its path starts at `G`, which takes in AGN and quasars, and otherwise
  the last step of the path (`PN`, `SNR`, `HII`). An empty cone is an answer. A failed query stops the run, so an outage cannot
  pass for no match.
- **Galaxy size:** `galdim_majaxis` from SIMBAD, in arcmin, against the row's catalogue major axis `majax`, the only measured size
  a row has, as a strict "above". A galaxy with no size in SIMBAD removes nothing. The report gives two counts that remove
  nothing, rows with a galaxy of no size, and rows with a galaxy above half the ring, so the cost of the strict reading shows.
- **Calibrators:** the eight names of the project's `artefact_ring` list (3C 196, 3C 295, 3C 380, 3C 147, 3C 48, 3C 286, 3C 345,
  3C 454.3), whose first six are the Scaife & Heald 2012 calibrators, and the four sources LOFAR subtracts as the A-team (Cas A,
  Cyg A, Tau A, Vir A), resolved by SIMBAD name. **I expect this cut to remove nothing:** the pre-filter already refuses a row
  with a source of at least 1 Jy within 6 arcmin. It is run because the plan asks.

## The spokes test

An earlier statistic looked along radial lines, and a second looked at how the azimuth profile holds over radius. Neither moved on
the six bright calibrator fields, so neither is used. What those fields and the fields below do show is deep negative pixels:
errors around a bright source swing both ways, and real emission cannot go below the background.

- **Negative depth:** on the 6 arcsec map of a field, (median - 0.1st percentile) / noise, with the noise from
  `radio.noise`. Pure noise gives about 3.1. The 20 arcsec map holds too few beams for a percentile this far out.
- **Bright source:** the field's peak on the 6 arcsec map is at least 100 times its noise, or a source of at least 1 Jy in the
  catalogue lies within 30 arcmin. A deep field with neither is not flagged, and the report gives how many there are.
- **The threshold is fitted and frozen before any cut's row is measured,** by `scripts/known_cut.py tune`, in
  `docs/reports/2026-11-01-known-cut/frozen_spokes.json`. It uses `baselines.tune`, the rule item 3 used: the midpoint with the
  largest (fields with spokes called / n + others not called / n - 1), and on a tie the highest.
  - With spokes: the 6 accepted `artefact_ring` fields and the 7 list rows that Wonder gave a not-ring-like vote and the class
    `imaging_artefact`. I viewed all 13 and all show spokes. The model's class only picks fields to fit on here. It labels no row
    and can raise nothing. The calibrator fields alone would set the threshold far above the spokes seen around fainter sources.
  - Without: the 9 tuning circles at their published positions.
  - Not fitted on, though I have seen their values: held-out circles, other lookalikes, random sources and the other list rows.
    `tune` writes those values so a reader can see them. **One held-out circle, J0847+7022, has a depth above any threshold this
    fit can give and a bright peak, so I expect the cut to flag it.** It is not on the list, and the threshold is not raised for it.

## What counts against a cut

There is no pass bar in the plan, and I set none. For each cut the report gives:

1. Rows removed, of the ring-like rows, known-circle rows and other rows apart, and how many of those only this cut removes.
2. **The known circles it would remove, as objects:** of those that survive the screen on their listed rows, and of all 18 at their
   published positions, where the ring is taken as 60 arcsec, the smallest the prompt allows. Either is a count against it.
3. **Chance matches:** the SIMBAD and calibrator cuts run on every ring-like row's position moved 10 arcmin north, with the same
   ring size. What these remove is what the cut would remove with nothing there.
4. **Known answers:** what it removes of the 30 earlier lookalikes, by group, and of the 30 earlier random sources. The lookalikes'
   positions came from SIMBAD itself, so matches at these positions test the type families, not the positions.

The end of the chain: the known circles, of 18 with a 95 percent Wilson interval, tuning and held-out apart, with a row that has a
ring-like first vote and is left, and the same with two ring-like votes. Rows left, known-circle rows apart, and those rows
grouped into objects by linking any two within 3 arcmin, the screen's distance.

**A cut that removes a known circle stays in the chain.** Dropping it after seeing the count would be a rule change. Any such
change is a v2, shown beside this one. Item 6 reads the file of rows, and each row keeps every match, so a person can see why it
went.

## Order

1. This rule, the code and its tests, committed.
2. `tune` writes the frozen threshold, committed.
3. `simbad` and `measure` refuse to run unless the rule, the cut's code and the frozen threshold are committed and unchanged.
