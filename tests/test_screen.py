"""The screen's order, votes and counts, on the fake backend with synthetic images. No network."""

import io
import json
from dataclasses import dataclass

import numpy as np
import pytest
from landers.models.backend import FakeBackend, RecordedBackend, WonderResult
from landers.models.crops import to_png
from landers.models.ledger import Ledger
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from probe import guard, harness, radio
from probe import screen as sc
from probe.harness import Item, ProbeClient


def png(seed: int) -> bytes:
    return to_png(np.random.default_rng(seed).integers(0, 255, (32, 32), dtype=np.uint8))


def item(k: int, label: str = "unlabelled") -> Item:
    return Item(f"list-{k:04d}", label, (png(2 * k), png(2 * k + 1)))


@dataclass
class Scripted:
    """Answers by image, so a test says which fields are ring-like, and counts the calls that reach it."""

    ring: set[bytes]
    calls: int = 0
    fail: bool = False
    name: str = "scripted"

    def wonder(self, req):
        self.calls += 1
        if self.fail:
            raise ConnectionError("no network")
        answer = radio.RING if req.images[0] in self.ring else radio.NOT_RING
        data = {"answer": answer, "reason": "synthetic", "known_class": "no_known_class"}
        return WonderResult(data, json.dumps(data), 3000, 500)


def clients(backend, tmp_path, cap=36.0) -> dict[int, ProbeClient]:
    ledger = Ledger(path=tmp_path / "ledger.json", total_cap_usd=cap, caps={"sam": 0, "wonder": 3000, "spark": 0})
    return {vote: ProbeClient(backend, ledger, "fake", sleep=lambda _: None) for vote in (sc.FIRST, sc.SECOND)}


def test_the_prompt_is_the_earlier_prompt_and_the_schema_only_gains_the_class():
    assert sc.SPEC.prompt == radio.PROMPT
    assert sc.SCHEMA["properties"]["answer"] == radio.SCHEMA["properties"]["answer"]
    assert sc.SCHEMA["properties"]["reason"] == radio.SCHEMA["properties"]["reason"]
    assert set(sc.SCHEMA["required"]) == {"answer", "reason", "known_class"}
    assert "known_class" not in radio.SCHEMA["properties"]


def test_the_request_passes_the_guard_and_carries_no_id(tmp_path):
    wire = sc.SPEC.request(item(1)).to_wire(images="digest")
    assert "list-0001" not in json.dumps(wire)
    assert "radio_screen" not in json.dumps(wire)
    assert wire["response_format"]["json_schema"]["name"] == "radio_ring_answer"
    assert wire["reasoning_effort"] == "low"
    clients(FakeBackend(), tmp_path)[sc.FIRST]._guard(sc.SPEC.request(item(1)))


def test_a_leak_in_a_late_row_stops_the_run_before_any_call(tmp_path):
    backend = Scripted(set())
    with_metadata = Image.new("L", (32, 32))
    stream = io.BytesIO()
    info = PngInfo()
    info.add_text("Title", "a named field")
    with_metadata.save(stream, "PNG", pnginfo=info)
    bad = Item("list-0002", "unlabelled", (stream.getvalue(), png(1)))
    with pytest.raises(guard.LeakError):
        sc.run([item(1), bad], ["list-0001", "list-0002"], clients(backend, tmp_path), tmp_path / "v.jsonl")
    assert backend.calls == 0


def test_order_puts_known_rows_first_and_shuffles_the_rest_the_same_way_each_time():
    records = [{"id": f"list-{k:04d}", "known_circle": "X" if k in (50, 90) else None} for k in range(1, 101)]
    ids = sc.order(records)
    assert ids[:2] == ["list-0050", "list-0090"]
    assert sorted(ids) == sorted(r["id"] for r in records)
    assert ids == sc.order(records)
    assert ids[2:] != [r["id"] for r in records if not r["known_circle"]]


def test_second_vote_only_for_ring_like_and_straight_after_the_first(tmp_path):
    items = [item(1), item(2), item(3)]
    backend = Scripted({items[1].images[0]})
    path = tmp_path / "votes.jsonl"
    result = sc.run(items, [i.id for i in items], clients(backend, tmp_path), path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(r["item_id"], r["vote"]) for r in rows] == [
        ("list-0001", 1),
        ("list-0002", 1),
        ("list-0002", 2),
        ("list-0003", 1),
    ]
    assert backend.calls == 4 and result["status"] == "finished"
    assert "list-0002" not in json.dumps(rows[0]["images"]) and rows[0]["images"][0]["bytes"] > 0


def test_two_votes_in_one_recordings_folder_would_replay_so_each_vote_has_its_own(tmp_path, monkeypatch):
    inner = Scripted({png(2)})
    monkeypatch.setattr(harness, "make_backend", lambda kind, directory, env=None: RecordedBackend(directory, inner))
    monkeypatch.setattr(harness, "spent_usd", lambda: 0.0)
    both = sc.open_clients("fake", tmp_path)
    assert both[sc.FIRST].ledger is both[sc.SECOND].ledger
    assert both[sc.FIRST].ledger.total_cap_usd == sc.STOP_USD
    assert both[sc.FIRST].ledger.caps["wonder"] == sc.WONDER_CALLS
    sc.run([item(1)], ["list-0001"], both, tmp_path / "votes.jsonl")
    assert inner.calls == 2

    shared = RecordedBackend(tmp_path / "shared", inner)
    inner.calls = 0
    req = sc.SPEC.request(item(1))
    shared.wonder(req)
    shared.wonder(req)
    assert inner.calls == 1  # what the separate folders are there to avoid


def test_a_rerun_skips_what_landed_and_asks_only_what_is_missing(tmp_path):
    items = [item(1), item(2)]
    backend = Scripted({items[0].images[0]})
    path = tmp_path / "votes.jsonl"
    ids = [i.id for i in items]
    assert sc.run(items, ids, clients(backend, tmp_path), path, limit=1)["status"] == "limit"
    assert backend.calls == 2
    with path.open() as f:
        lines = f.readlines()
    path.write_text(lines[0] + lines[1][:20])  # killed while writing the second vote
    backend.calls = 0
    sc.run(items, ids, clients(backend, tmp_path), path)
    assert backend.calls == 2  # the lost second vote and the other row, not the first vote again
    backend.calls = 0
    sc.run(items, ids, clients(backend, tmp_path), path)
    assert backend.calls == 0


def test_a_changed_request_refuses_rather_than_paying_twice(tmp_path):
    items = [item(1)]
    path = tmp_path / "votes.jsonl"
    sc.run(items, ["list-0001"], clients(Scripted(set()), tmp_path), path)
    changed = [Item("list-0001", "unlabelled", (png(98), png(99)))]
    backend = Scripted(set())
    with pytest.raises(RuntimeError, match="request changed"):
        sc.run(changed, ["list-0001"], clients(backend, tmp_path), path)
    assert backend.calls == 0


def test_the_stop_ends_the_run_without_passing_it(tmp_path):
    items = [item(k) for k in range(1, 11)]
    backend = Scripted(set())
    both = clients(backend, tmp_path, cap=0.10)
    path = tmp_path / "votes.jsonl"
    result = sc.run(items, [i.id for i in items], both, path)
    assert result["status"].startswith("stopped")
    assert both[sc.FIRST].ledger.total_cost_usd() <= 0.10
    assert 0 < backend.calls < 10
    assert len(path.read_text().splitlines()) == backend.calls


def test_three_failures_in_a_row_stop_the_run_and_a_rerun_asks_again(tmp_path):
    items = [item(k) for k in range(1, 6)]
    backend = Scripted(set(), fail=True)
    path = tmp_path / "votes.jsonl"
    ids = [i.id for i in items]
    with pytest.raises(harness.RunAborted):
        sc.run(items, ids, clients(backend, tmp_path), path)
    assert backend.calls == 3
    backend.fail, backend.calls = False, 0
    sc.run(items, ids, clients(backend, tmp_path), path)
    assert backend.calls == 5


def vote(item_id, n, prediction, label="unlabelled"):
    row = {"item_id": item_id, "vote": n, "label": label, "prediction": prediction}
    if prediction in (radio.RING, radio.NOT_RING):
        row["answer"] = {"answer": prediction, "reason": "r", "known_class": "galaxy"}
    return {(item_id, n): row}


def test_circles_count_as_objects_and_a_lost_or_rejected_circle_is_a_miss():
    records = [
        {"id": "a1", "known_circle": "A"},
        {"id": "a2", "known_circle": "A"},
        {"id": "b1", "known_circle": "B"},
        {"id": "c1", "known_circle": "C"},
    ]
    rows = {
        **vote("a1", 1, radio.NOT_RING, radio.RING),
        **vote("a2", 1, radio.RING, radio.RING),
        **vote("a2", 2, radio.NOT_RING, radio.RING),
        **vote("b1", 1, radio.RING, radio.RING),
        **vote("b1", 2, radio.RING, radio.RING),
        **vote("c1", 1, radio.NOT_RING, radio.RING),
    }
    groups = {"A": "tuning", "B": "heldout", "C": "heldout", "Lost": "tuning"}
    outcomes = sc.circle_outcomes(records, rows, groups)
    assert outcomes["A"]["one_vote"] and not outcomes["A"]["two_votes"]
    assert outcomes["B"]["two_votes"]
    assert not outcomes["C"]["one_vote"]
    assert not outcomes["Lost"]["on_list"] and not outcomes["Lost"]["one_vote"]
    counts = sc.circle_counts(outcomes)
    assert counts["all"]["on_list"]["called"] == 3 and counts["all"]["on_list"]["n"] == 4
    assert counts["all"]["one_vote"]["called"] == 2
    assert counts["all"]["two_votes"]["called"] == 1
    assert counts["tuning"]["one_vote"]["called"] == 1 and counts["tuning"]["one_vote"]["n"] == 2
    assert counts["heldout"]["two_votes"]["called"] == 1


def test_reading_counts_split_known_rows_and_name_a_ring_like_row_the_stop_left_with_one_vote():
    records = [{"id": k} for k in ("a", "b", "c", "d")]
    rows = {
        **vote("a", 1, radio.RING, radio.RING),
        **vote("a", 2, radio.NOT_RING, radio.RING),
        **vote("b", 1, radio.RING),
        **vote("b", 2, radio.RING),
        **vote("c", 1, radio.RING),
        **vote("d", 1, radio.NOT_RING),
    }
    rows["b", 1]["answer"]["reason"] = "an ORC, maybe NGC 2276"
    counts = sc.reading_counts(records, rows)
    assert counts["known_circle_rows_first_vote_ring_like"] == {"called": 1, "n": 1, "wilson_95": [0.2065, 1.0]}
    assert counts["other_rows_first_vote_ring_like"]["called"] == 2
    assert counts["other_rows_first_vote_ring_like"]["n"] == 3
    assert counts["second_vote_agrees_all_rows"]["called"] == 1
    assert counts["second_vote_agrees_all_rows"]["n"] == 2
    assert counts["second_vote_agrees_known_circle_rows"]["called"] == 0
    assert counts["ring_like_rows_with_no_second_vote"] == ["c"]
    assert counts["votes_whose_reason_uses_the_class_name"] == 1
    assert counts["votes_whose_reason_names_a_catalogue_object"] == {"b": "NGC 2276"}


def test_a_row_with_no_valid_vote_is_not_assessed_and_counts_neither_way():
    records = [{"id": k} for k in ("a", "b", "c", "d", "e")]
    rows = {
        **vote("a", 1, radio.RING),
        **vote("a", 2, radio.RING),
        **vote("b", 1, radio.NOT_RING),
        **vote("c", 1, harness.NO_ANSWER),
        **vote("d", 1, harness.INVALID),
    }
    counts = sc.row_counts(records, rows)
    assert counts["not_assessed"] == 3
    assert counts["valid_first_vote"] == 2
    assert counts["failed_or_invalid_first_vote"] == 2
    assert counts["first_vote_ring_like"]["called"] == 1 and counts["first_vote_ring_like"]["n"] == 2
    assert counts["two_ring_like_votes_on_other_rows"] == 1
    assert counts["second_vote_identical_to_first"] == 1
