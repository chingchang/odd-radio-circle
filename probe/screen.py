"""The Wonder screen of the pre-filter list: the order, the votes and what the counts mean. The rule is written in
docs/proposals/screen-v1.md; this is that rule in code. ``scripts/screen.py`` runs it.

``votes.jsonl`` gets one row per asked vote as it lands, so a killed run loses only the call in flight, and a rerun
skips what has a valid answer. A row holds digests of the images and never reaches a model. Nothing here assigns a
verdict.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from landers.models.backend import request_hash
from landers.models.ledger import CapError

from probe import guard, radio
from probe.baselines import count
from probe.harness import (
    INVALID,
    MAX_CONSECUTIVE_ERRORS,
    NO_ANSWER,
    Item,
    ProbeClient,
    ProbeSpec,
    RunAborted,
    _append,
    _scrubbed,
    open_backend,
    open_client,
)

STOP_USD = 36.0  # docs/plan.md item 4, on the ledger's total over all runs
WONDER_CALLS = 3000  # the ledger's count over all runs; the dollar stop is the one that bites
ORDER_SEED = [radio.SEED, 4]
FIRST, SECOND = 1, 2
KNOWN_CLASSES = (
    "radio_galaxy",
    "galaxy",
    "planetary_nebula",
    "supernova_remnant",
    "hii_region",
    "imaging_artefact",
    "no_known_class",
)
SCHEMA = {
    **radio.SCHEMA,
    "required": [*radio.SCHEMA["required"], "known_class"],
    "properties": {**radio.SCHEMA["properties"], "known_class": {"type": "string", "enum": list(KNOWN_CLASSES)}},
}
# The earlier prompt and the earlier schema name; the spec's own name goes to folders only, never to the model.
SPEC = ProbeSpec("radio_screen", radio.PROMPT, SCHEMA, schema_name=f"{radio.SPEC.name}_answer")


def open_clients(kind: str, out_root: Path, env: dict | None = None) -> dict[int, ProbeClient]:
    """One client per vote on one ledger. Each vote records in its own folder: the two requests are identical, so a
    shared folder would replay the first answer as the second vote, and two ledgers would overwrite each other."""
    recordings = Path(out_root) / SPEC.name / "recordings"
    first = open_client(
        kind,
        out_root,
        env,
        cap_usd=STOP_USD,
        ceiling_usd=STOP_USD,
        wonder_calls=WONDER_CALLS,
        recordings=recordings / "vote1",
    )
    return {FIRST: first, SECOND: ProbeClient(open_backend(kind, recordings / "vote2", env), first.ledger, kind)}


def order(records: list[dict]) -> list[str]:
    """Rows on a known circle first, in list order, so the stop cannot fall before them; then the rest at random, so the
    rows it does not reach are a random sample of the list."""
    known = [r["id"] for r in records if r.get("known_circle")]
    others = [r["id"] for r in records if not r.get("known_circle")]
    shuffled = np.random.default_rng(ORDER_SEED).permutation(len(others))
    return [*known, *(others[int(k)] for k in shuffled)]


def read_votes(path: Path) -> dict[tuple[str, int], dict]:
    """The latest row per item and vote. A line cut off by a kill is dropped; that vote is asked again."""
    rows: dict[tuple[str, int], dict] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows[row["item_id"], row["vote"]] = row
    return rows


def _ask(item: Item, vote: int, client: ProbeClient, path: Path, rows: dict) -> dict:
    """One vote, written as it lands. A failed call is a row with an error, and a rerun asks again."""
    req = SPEC.request(item)
    digest = request_hash(req)
    before = client.ledger.total_cost_usd()
    start = time.monotonic()
    row = {
        "item_id": item.id,
        "vote": vote,
        "label": item.label,
        "request_hash": digest,
        "images": [image["image_url"]["url"] for image in req.to_wire(images="digest")["messages"][0]["content"][1:]],
    }
    try:
        result = client.wonder(req)
    except (guard.LeakError, CapError):
        raise
    except Exception as e:
        row.update(error=_scrubbed(e), prediction=NO_ANSWER)
    else:
        row.update(
            answer=result.data,
            prediction=SPEC.prediction(result.data),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
    row["cost_usd"] = round(client.ledger.total_cost_usd() - before, 6)
    row["seconds"] = round(time.monotonic() - start, 2)
    _append(path, row)
    rows[item.id, vote] = row
    return row


def needed(row: dict | None, digest: str) -> bool:
    """Does this vote still have to be asked? A row answered under another request stops the run instead of paying
    twice for a different question."""
    if row is None or "error" in row:
        return True
    if row["request_hash"] != digest:
        raise RuntimeError(f"{row['item_id']}: the request changed since vote {row['vote']} was asked")
    return False


def run(
    items: list[Item], ids: list[str], clients: dict[int, ProbeClient], path: Path, limit: int | None = None
) -> dict:
    """Ask in ``ids`` order, a row's second vote straight after a ring-like first. Every request is guarded before the
    first is sent. ``limit`` counts rows that needed a call, so a long run can be committed in parts."""
    by_id = {item.id: item for item in items}
    if sorted(ids) != sorted(by_id):
        raise ValueError("the order must hold every row once")
    digests = {item.id: request_hash(SPEC.request(item)) for item in items}
    for item in items:
        clients[FIRST]._guard(SPEC.request(item))
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = read_votes(path)
    worked = asked = failures = 0
    status = "finished"
    try:
        for item_id in ids:
            if limit is not None and worked >= limit:
                status = "limit"
                break
            touched = False
            for vote in (FIRST, SECOND):
                if vote == SECOND and rows.get((item_id, FIRST), {}).get("prediction") != radio.RING:
                    break
                if needed(rows.get((item_id, vote)), digests[item_id]):
                    row = _ask(by_id[item_id], vote, clients[vote], path, rows)
                    touched = True
                    asked += 1
                    failures = failures + 1 if "error" in row else 0
                    if failures >= MAX_CONSECUTIVE_ERRORS:
                        raise RunAborted(f"{failures} calls failed in a row; see {path}")
            worked += touched
    except CapError as e:
        status = f"stopped: {e}"
    return {"status": status, "asked": asked, "ledger_usd": clients[FIRST].ledger.total_cost_usd()}


def valid(row: dict | None) -> bool:
    return row is not None and row["prediction"] not in (NO_ANSWER, INVALID)


def called(row: dict | None) -> bool:
    return row is not None and row["prediction"] == radio.RING


def circle_outcomes(records: list[dict], rows: dict, circles: dict[str, str]) -> dict[str, dict]:
    """Each known circle once, from name to group. It survives if any listed row has a ring-like first vote, and
    survives twice if one row has two. A circle with no listed row, or no vote, is a miss."""
    out = {}
    for name, group in circles.items():
        ids = [r["id"] for r in records if r.get("known_circle") == name]
        out[name] = {
            "group": group,
            "listed_rows": ids,
            "on_list": bool(ids),
            "first_votes": {i: rows[i, FIRST]["prediction"] for i in ids if (i, FIRST) in rows},
            "second_votes": {i: rows[i, SECOND]["prediction"] for i in ids if (i, SECOND) in rows},
            "reasons": {i: rows[i, FIRST].get("answer", {}).get("reason") for i in ids if (i, FIRST) in rows},
            "one_vote": any(called(rows.get((i, FIRST))) for i in ids),
            "two_votes": any(called(rows.get((i, FIRST))) and called(rows.get((i, SECOND))) for i in ids),
        }
    return out


def circle_counts(outcomes: dict[str, dict]) -> dict:
    """Objects, not rows: tuning and held-out apart and together."""
    result = {}
    for label, group in {"tuning": "tuning", "heldout": "heldout", "all": None}.items():
        chosen = [o for o in outcomes.values() if group is None or o["group"] == group]
        result[label] = {
            key: count(sum(o[key] for o in chosen), len(chosen)) for key in ("on_list", "one_vote", "two_votes")
        }
    return result


def classes(rows: list[dict]) -> dict[str, int]:
    tally = dict.fromkeys(KNOWN_CLASSES, 0)
    for row in rows:
        name = row.get("answer", {}).get("known_class")
        tally[name if name in tally else INVALID] = tally.get(name if name in tally else INVALID, 0) + 1
    return tally


def row_counts(records: list[dict], rows: dict) -> dict:
    """Rows, of the list. A row with no valid first vote is not assessed and counts neither way."""
    firsts = [rows.get((r["id"], FIRST)) for r in records]
    answered = [row for row in firsts if valid(row)]
    ring = [row for row in answered if called(row)]
    seconds = [rows.get((row["item_id"], SECOND)) for row in ring]
    second_valid = [row for row in seconds if valid(row)]
    return {
        "rows": len(records),
        "reached": sum(row is not None for row in firsts),
        "valid_first_vote": len(answered),
        "not_assessed": len(records) - len(answered),
        "failed_or_invalid_first_vote": sum(row is not None and not valid(row) for row in firsts),
        "first_vote_ring_like": count(len(ring), len(answered)),
        "first_vote_not_ring_like": len(answered) - len(ring),
        "ring_like_without_a_valid_second_vote": len(ring) - len(second_valid),
        "second_vote_valid": len(second_valid),
        "second_vote_ring_like": sum(called(row) for row in second_valid),
        "second_vote_not_ring_like": sum(not called(row) for row in second_valid),
        "two_ring_like_votes_on_known_circle_rows": sum(
            called(row) and row["label"] == radio.RING for row in second_valid
        ),
        "two_ring_like_votes_on_other_rows": sum(called(row) and row["label"] != radio.RING for row in second_valid),
        "second_vote_identical_to_first": sum(
            row["answer"] == rows[row["item_id"], FIRST]["answer"] for row in second_valid
        ),
        "known_class_all_first_votes": classes(answered),
        "known_class_ring_like_first_votes": classes(ring),
    }
