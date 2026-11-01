# Odd radio circles

A blind, reproducible search of public LOFAR radio maps (LoTSS DR3) for odd radio circles. Candidates, never discoveries.
Muse Wonder screens for rings; code checks the physics and known lookalikes. The model layer, ledger and leak guard come
from the sibling repo ../finding-landers (package `landers`).

## Commands

    uv sync             # environment, with ../finding-landers installed editable
    scripts/check.sh    # tests, lint, prompt check. This decides done.

## Rules

- The key comes from the environment (MODEL_API_KEY), never from code, prompts, logs or commits.
- What the model sees: no designation, name, coordinate, survey or file name in any prompt or image, so it cannot recognise
  a famous example. Code checks every prompt before sending.
- Verdict words: candidate, needs second look, likely known class, not assessed. Never discovery, confirmed, found.
- A model vote can lower a verdict, never raise it past what the code checks allow.
- Every model call goes through the landers Ledger. Real calls only with LANDERS_REAL_CALLS=1 (the runner sets it for the
  paid item). This project's total cap is 40 USD.
- A number in any .md comes from a file a runner wrote.
- Keep downloads small (cutouts and server-side catalogue queries, never full mosaics or the full catalogue file); the Mac
  has 8 GB of RAM and limited disk.
- One plan item per session, commit with the item number, never push, report under docs/reports/.
