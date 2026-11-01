# Odd radio circles

A blind, reproducible search of public LOFAR radio maps (LoTSS DR3) for odd radio circles: faint rings of radio emission
about an arcminute across, of unknown origin. Muse Wonder screens for rings; code checks the physics and known lookalikes.
The model layer, ledger and prompt guard come from the sibling repo ../finding-landers (package `landers`).

## Commands

    uv sync             # environment, with ../finding-landers installed editable
    scripts/check.sh    # tests, lint, prompt check. This decides done.

## Requirements, with the reason for each

These are what the result is judged on. How to meet them is your call.

- **The key stays out of the repo.** It comes from MODEL_API_KEY in the environment, never from code, prompts, logs or
  commits. The repo is public.
- **The model never sees where an image is from.** No designation, name, coordinate, survey, date or file name in any prompt
  or image, checked in code before every call. The known circles are famous; a model that recognises one proves nothing.
- **Verdict words are fixed:** candidate, needs second look, likely known class, not assessed. Never discovery, confirmed,
  found or new. A claim we cannot defend costs the whole result.
- **Every verdict comes from code that assigns it.** If a grade depends on a test, the test and its limits exist in code and
  run on the rows before anyone reports the grade. A model vote can lower a verdict, never raise it.
- **Every number in a .md comes from a file a runner wrote,** and the sentence says what it counts (rows or objects, of how
  many, at what cut). Small samples get a 95 percent interval.
- **Decide the rule before measuring it.** Thresholds, cuts and pass bars are written down and committed before the run that
  tests them. If you change a rule after seeing results, say so and show both.
- **Paid calls go through the landers Ledger.** Real calls run only with LANDERS_REAL_CALLS=1, which the runner sets for the
  paid item. This project's cap is 40 USD in all. Do not use "-contributor" model variants.

## How to work

- **docs/plan.md is the source of truth.** One item per session; mark it [running], then [done, see report]. If an item truly
  needs a person, mark it [paused: reason] and stop.
- **Test the real thing.** No fake-backend runs unless the item asks for one. Before building around a model, try it on a few
  known answers.
- **Long runs:** run in the foreground, write each unit's result as it lands, make reruns skip finished units, and commit as
  results arrive, so a lost connection costs minutes, not the run.
- **Data stays small.** Cutouts and server-side catalogue queries only, never full mosaics or the full catalogue file. The Mac
  has 8 GB of RAM and limited disk; check free space before a big download.
- **Tests test the change.** Must-fail cases matter as much as must-pass.
- **Reports** go under docs/reports/<date>-<name>.md: the result first, then what ran, what you decided and why, what a reader
  should doubt, and the commands that made the numbers.
- **Commits** start with the item number. Never push; a person pushes.
- **The README** describes the work and its results. It does not mention any event or competition.

## Data and credit

LoTSS DR3: Shimwell et al. 2026, A&A 707, A198, with the acknowledgements at https://www.lofar-surveys.org/credits.html.
Known circles: De Gasperin et al. 2026 (arXiv:2602.18294), listed in controls/.
