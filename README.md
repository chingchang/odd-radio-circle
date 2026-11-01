# Odd radio circles

A blind search of public LOFAR radio maps for odd radio circles, using Meta's vision models to screen for rings and code to check the physics.

Odd radio circles are faint rings of radio emission about an arcminute across, seen only at radio wavelengths, with no agreed explanation. This project screens sources from the LOFAR Two-metre Sky Survey (LoTSS DR3) with Muse Wonder, checks each ring-like source against known classes of lookalike in code, and reports how many of the 18 published LoTSS circles it recovers end to end. Results are candidates or needs second look, never discoveries.

## Status

Work in progress. Before building, the model was tested on known answers: Muse Wonder called 13 of 18 published circles ring-like and rejected 53 of 60 non-circles, where a simple ring-detection rule flagged none of the circles (`docs/reports/2026-10-31-probe-orc.md`). A zoomed view made no measurable difference (`docs/reports/2026-10-31-probe-orc-zoom.md`).

## Data and credit

LoTSS DR3: Shimwell et al. 2026, A&A 707, A198, with the acknowledgements at https://www.lofar-surveys.org/credits.html. Known circles: De Gasperin et al. 2026 (arXiv:2602.18294).

## Commands

    uv sync
    scripts/check.sh
