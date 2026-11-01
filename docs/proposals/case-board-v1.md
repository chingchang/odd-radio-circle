# Case board: the grade, written before any row is graded

From docs/plan.md item 6, code only, with no model call and no query to any service. The code is `probe/case_board.py`, run by
`scripts/case_board.py`, which refuses unless this rule and that code are committed and unchanged.

What I had seen when writing this: the reports of items 1 to 5, including the counts in item 5's `summary.json` (132 other rows
left, 108 of them with two ring-like votes, 57 of the 132 with the first-vote class `radio_galaxy`), and the shape of its files.
So the size of the top grade is known in advance, and this rule cannot be blind to it.

## The grade

Assigned by one function to every row of the 1,200, from `votes.jsonl` and the `removed_by` field of item 5's `rows.json`:

| the row | verdict |
|---|---|
| no valid first vote | not assessed |
| first vote not ring-like | none; the row has a vote and no verdict, and is not on the board |
| ring-like first vote, removed by any cut of item 5 | likely known class |
| ring-like first vote, left by every cut, two ring-like votes | candidate |
| ring-like first vote, left by every cut, anything else as second vote | needs second look |

- **Candidate is the plan's rule as the plan wrote it:** the code checks pass and there are two ring-like Wonder votes. The code
  checks are the six cuts of item 5, with their frozen threshold. No other check exists, and none is added here.
- **A vote can lower, never raise.** A cut's removal cannot be undone by any vote, and no answer can lift a row above where the
  cuts allow.
- **A failed or missing second vote is needs second look,** as is a second vote of not ring-like. `list-0409` has no second vote.
- **Spokes counts as a cut here,** so a row it alone removes reads likely known class, with imaging artefact as the class. Item 5
  says this test reads the field and may remove real objects, and the file of verdicts keeps which cut acted.

## The board

- **On the board:** every row with a verdict of candidate or needs second look that is not a known circle's row. Each has both maps
  byte for byte as Wonder saw them, its votes, classes and reasons as given, every cut's result, the objects in its SIMBAD cone, and
  the rows linked to it within 3 arcmin, the screen's distance.
- **The maps are checked:** each copied file's SHA-256 must equal the digest in that row's vote, or the run stops.
- **Known circles' rows are graded by the same function** but listed only on the circles page. They are the control for the grade.
- **Rows removed by a cut are not on the board.** They are in `verdicts.json` with their verdict and cut.

## Radio galaxies, which item 5 left open

Item 5 warned that this grade will call many visible radio galaxies candidates, and that no cut looks for them. **I do not change
the plan's grade for this.** A lowering rule written now would be a rule written after seeing the rows' classes, and the plan's
author set the grade. Instead, without moving any verdict:

- Each row shows every class Wonder gave it. Candidates with no named class on either vote sort first.
- The summary counts candidates by class, and gives the grade's size **had any named class lowered a candidate** to needs second
  look. "Named" means any class other than `no_known_class`. The same is counted on the known circles, so the cost of that stricter
  rule shows too. This alternative is a count, not a verdict.
- Every page and the README say that candidate is a screening grade: it says these checks passed, and does not say the row is a ring.

## The circles page

Each of the 18 known circles once, with where it was kept or lost, the first of these stages that ends it:

1. **pre-filter:** no row on the list.
2. **first vote:** no listed row has a ring-like first vote.
3. **known-object cut:** every ring-like row was removed by a cut.
4. **second vote:** a row is left, none with two ring-like votes.
5. **kept to candidate grade:** a listed row reads candidate.

The page also gives the earlier two-image call at the published position, the tuned annulus through the list, what the cuts would
do at the published position, and both maps at the published position from the earlier inputs.

## Words and numbers

- Each page's own wording is checked in code against the words the project rules out (discovery, confirmed, found, new). The
  model's reasons and SIMBAD's names are shown as given and are not checked; they are marked as given.
- Every count on the pages and in the README's results section is rendered from `summary.json`, which the runner writes. Counts of
  objects use a 95 percent Wilson interval. The runner stops if its counts disagree with item 4's or item 5's summaries.
