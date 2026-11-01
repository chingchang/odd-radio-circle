# Wonder screen of the pre-filter list: the rule, written before the first call

From docs/plan.md item 4: every pre-filter source, the earlier prompt and the two 6-arcmin views, one vote each, a second vote
only for sources called ring-like, stop at 36 USD. Nothing here assigns a verdict. Items 5 and 6 do that.

What I had seen when writing this: the earlier reports' counts on 78 fields, the baselines report, and two contact sheets of
36 listed fields each. No model has been asked about any listed field.

## The request

- **Prompt:** `radio.PROMPT`, byte for byte, at the earlier low effort and under the earlier schema name.
- **Images:** the two PNGs from item 3, 6 and 20 arcsec, unchanged. The file `out/radio_list/items.json` must equal the committed
  `docs/reports/2026-10-31-baselines/items.json`, or the run refuses.
- **Schema, the one change:** the plan asks to record a known class, and the earlier schema has only `answer` and `reason`. A
  required enum `known_class` is added: `radio_galaxy`, `galaxy`, `planetary_nebula`, `supernova_remnant`, `hii_region`,
  `imaging_artefact`, `no_known_class`. The schema reaches the model, so this could shift its answers. The earlier 13 of 18 was
  measured without it, and the report says so. The class is the model's opinion, recorded for item 5 and never used for a count
  of ring-like calls.

## Order and the stop

The stop is 36 USD on the project's ledger, `out/ledger.json`, the total over all runs. That ledger starts at 6.7601 USD, so this
run has 29.2399 USD. The earlier 78 two-image calls averaged 0.0243 USD on the ledger, so **I expect 1,200 first votes to cost
about 29.2 USD and the stop to be reached before the list ends** once second votes are added. Neither the stop nor the image
floor in the ledger is changed to avoid that. The order is chosen so a stop leaves a fair result:

1. The 8 rows within a known circle's kept radius go first, so the end-to-end count does not depend on where the stop falls. The
   model cannot tell: calls share nothing, and the order reaches no request.
2. The other rows follow in a fixed random order (`numpy.random.default_rng([20261031, 4])`), so the rows not reached are a
   random sample of the list, not a slice of the sky. The list is in right-ascension order.
3. A row's second vote is asked straight after its first ring-like vote, not after the whole list. Every row reached then has
   all the votes the rule gives it. Asking all first votes first would spend the money before any second vote, and item 6's
   candidate grade needs two.

A row with no valid first vote when the stop falls is **not assessed**, and counts neither way. The report gives how many.

The ledger's cap of 300 Wonder calls is raised to 3,000 for this run, because the plan asks for at least 1,200 calls and sets a
dollar stop. 3,000 is above any count the dollar stop allows at the ledger's floor once failed attempts are allowed for.

## The second vote is a real call

The recording layer replays any request it has seen, and the second vote's request is identical to the first. Replaying would
return the first answer and charge for it. So each vote keeps its own recordings folder, `out/radio_screen/recordings/vote1` and
`vote2`, and a test holds that two votes make two calls. The second vote is told nothing about the first. The report gives how
many pairs came back byte-identical, which would point to caching on the service's side.

## Failures

A failed call is written down and counts as no vote. Three in a row stop the run, and a rerun asks again. A rerun skips valid votes
and refuses if a request's hash has changed. An answer outside the enum is `invalid`, gets no second vote, and is not assessed.

## What the report counts

There is no pass bar in the plan, and I set none.

- Rows: on the list, reached, with a valid first vote, not assessed. Rows called ring-like on the first vote, of the rows with a
  valid first vote, with a 95 percent Wilson interval. Second votes asked and how many agree. Rows are not objects, so also the
  ring-like rows with another ring-like row within 3 arcmin.
- **The end-to-end hit rate, in objects, of 18, tuning and held-out apart.** A known circle survives if **any of its listed rows
  has a ring-like first vote**. Circles the pre-filter lost count as misses. The same count with two ring-like votes on one row
  is given beside it, because item 6 needs two. Both have 95 percent Wilson intervals. The numbers to compare with are item 3's
  through-the-list baselines, 0 and 1 of 18.
- The known classes the model gave, over all rows and over ring-like rows.
- Cost: the ledger's total and this run's share, what the API reported in tokens, and the calls made.
