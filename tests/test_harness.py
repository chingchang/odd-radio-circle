import json

import numpy as np
import pytest
from landers.models.backend import FakeBackend, TransientError, WonderResult
from landers.models.crops import to_png
from landers.models.ledger import CapError, Ledger

from probe import harness
from probe.guard import LeakError
from probe.harness import ImageTokenFloor, Item, ProbeClient, ProbeSpec, open_client, run_baseline, run_probe

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string", "enum": ["yes", "no"]}},
}
SPEC = ProbeSpec("demo", "Is this image bright? Answer with the schema.", SCHEMA)


def blank_png(k: int) -> bytes:
    return to_png(np.full((4, 4), k, np.uint8))


def items(n=4):
    return [Item(f"secret-id-{k}", "yes" if k % 2 else "no", (blank_png(k),)) for k in range(n)]


class Scripted(FakeBackend):
    """Answers from a list; an exception in the list is raised."""

    def __init__(self, answers):
        super().__init__()
        self.answers = list(answers)
        self.requests = []

    def wonder(self, req):
        self.requests.append(req)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return WonderResult({"answer": a}, json.dumps({"answer": a}), 100, 10)


def client(tmp_path, backend):
    return ProbeClient(backend, Ledger.load(tmp_path / "ledger_fake.json"), "fake", sleep=lambda _: None)


def rows(tmp_path):
    return [json.loads(x) for x in (tmp_path / "demo" / "fake" / "records.jsonl").read_text().splitlines()]


def test_writes_request_answer_label_cost_and_score(tmp_path):
    backend = Scripted(["no", "yes", "yes", "no"])
    r = run_probe(SPEC, items(), client(tmp_path, backend), tmp_path)
    assert (r["correct"], r["n"]) == (2, 4)
    written = rows(tmp_path)
    assert written[0]["label"] == "no" and written[0]["answer"] == {"answer": "no"} and written[0]["cost_usd"] > 0
    assert written[0]["request"]["messages"][0]["content"][1]["image_url"]["url"]["bytes"] > 0
    assert json.loads((tmp_path / "demo" / "fake" / "score.json").read_text())["correct"] == 2
    assert "| no | 1 | 1 |" in (tmp_path / "demo" / "fake" / "score.md").read_text()


def test_id_and_label_never_reach_the_model(tmp_path):
    its = [Item("secret-id-0", "secret-label", (blank_png(0),))]
    backend = Scripted(["no"])
    run_probe(SPEC, its, client(tmp_path, backend), tmp_path)
    wire = json.dumps(backend.requests[0].to_wire(images="digest"))
    assert "secret-id" not in wire and "secret-label" not in wire


def test_a_leak_in_any_prompt_stops_the_run_before_anything_is_sent(tmp_path):
    spec = ProbeSpec("demo", "Is NGC 6543 ring-like?", SCHEMA)
    backend = Scripted(["no"] * 4)
    c = client(tmp_path, backend)
    with pytest.raises(LeakError):
        run_probe(spec, items(), c, tmp_path)
    assert backend.requests == [] and c.ledger.entries["wonder"]["units"] == 0


def test_client_refuses_a_leak_on_a_direct_call(tmp_path):
    backend = Scripted(["no"])
    c = client(tmp_path, backend)
    req = ProbeSpec("demo", "What is J1555+2726?", SCHEMA).request(items(1)[0])
    with pytest.raises(LeakError):
        c.wonder(req)
    assert backend.requests == []


def test_a_png_with_metadata_is_refused(tmp_path):
    png = blank_png(0)
    tagged = png[:8] + b"\x00\x00\x00\x01tEXtx\x00\x00\x00\x00" + png[8:]
    with pytest.raises(LeakError):
        run_probe(SPEC, [Item("a", "no", (tagged,))], client(tmp_path, Scripted(["no"])), tmp_path)


def test_rerun_skips_answered_items_and_asks_failed_ones_again(tmp_path):
    first = Scripted(["no", ValueError("boom"), "yes", "yes"])
    r = run_probe(SPEC, items(), client(tmp_path, first), tmp_path)
    assert r["confusion"]["yes"]["no_answer"] == 1
    again = Scripted(["yes"])
    r = run_probe(SPEC, items(), client(tmp_path, again), tmp_path)
    assert len(again.requests) == 1 and r["correct"] == 3


def test_changed_prompt_is_asked_again(tmp_path):
    run_probe(SPEC, items(2), client(tmp_path, Scripted(["no", "no"])), tmp_path)
    changed = ProbeSpec("demo", "Is this image dark? Answer with the schema.", SCHEMA)
    again = Scripted(["yes", "yes"])
    run_probe(changed, items(2), client(tmp_path, again), tmp_path)
    assert len(again.requests) == 2


def test_a_line_cut_off_by_a_kill_is_asked_again(tmp_path):
    run_probe(SPEC, items(2), client(tmp_path, Scripted(["no", "yes"])), tmp_path)
    path = tmp_path / "demo" / "fake" / "records.jsonl"
    path.write_text(path.read_text()[:-20])
    again = Scripted(["yes"])
    r = run_probe(SPEC, items(2), client(tmp_path, again), tmp_path)
    assert len(again.requests) == 1 and r["correct"] == 2


def test_off_schema_answer_counts_as_wrong(tmp_path):
    r = run_probe(SPEC, items(2), client(tmp_path, Scripted(["maybe", "yes"])), tmp_path)
    assert r["correct"] == 1 and r["confusion"]["no"][harness.INVALID] == 1


def test_consecutive_failures_abort_and_keep_what_landed(tmp_path):
    bad = Scripted(["no"] + [ValueError("boom")] * 3)
    with pytest.raises(harness.RunAborted):
        run_probe(SPEC, items(8), client(tmp_path, bad), tmp_path)
    assert len(rows(tmp_path)) == 4


def test_transient_errors_retry_and_every_attempt_is_counted(tmp_path):
    c = client(tmp_path, Scripted([TransientError("429"), "no"]))
    run_probe(SPEC, items(1), c, tmp_path)
    assert c.ledger.entries["wonder"]["units"] == 2


def test_cap_of_ten_dollars_holds_over_probes_and_stops_the_run(tmp_path):
    c = open_client("fake", tmp_path)
    assert c.ledger.total_cap_usd == 10.0
    c.ledger.entries["wonder"]["cost_usd"] = 9.97
    c.ledger.save()
    reopened = open_client("fake", tmp_path)
    assert reopened.ledger.total_cap_usd == 10.0
    with pytest.raises(CapError):
        run_probe(SPEC, items(1), reopened, tmp_path)


def test_a_lower_env_cap_wins_and_a_higher_one_does_not(tmp_path, monkeypatch):
    monkeypatch.setenv("LANDERS_CAP_TOTAL_USD", "2")
    assert open_client("fake", tmp_path).ledger.total_cap_usd == 2.0
    monkeypatch.setenv("LANDERS_CAP_TOTAL_USD", "50")
    assert open_client("fake", tmp_path).ledger.total_cap_usd == 10.0


def test_real_needs_key_and_flag(tmp_path):
    with pytest.raises(RuntimeError, match="MODEL_API_KEY"):
        open_client("real", tmp_path, env={"LANDERS_REAL_CALLS": "1"})
    with pytest.raises(RuntimeError, match="LANDERS_REAL_CALLS"):
        open_client("real", tmp_path, env={"MODEL_API_KEY": "x"})


def test_real_leaves_room_under_the_landers_cap_and_floors_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "make_backend", lambda *_: FakeBackend())
    monkeypatch.setattr(harness, "spent_usd", lambda: harness.TOTAL_CAP_USD - 4.0)
    c = open_client("real", tmp_path)
    assert c.ledger.total_cap_usd == 4.0 and c.ledger.path.name == "ledger.json"
    assert isinstance(c.backend, ImageTokenFloor)


def test_fake_and_real_results_and_ledgers_are_apart(tmp_path):
    c = open_client("fake", tmp_path)
    run_probe(SPEC, items(2), c, tmp_path)
    assert c.ledger.path.name == "ledger_fake.json"
    assert not (tmp_path / "ledger.json").exists()
    assert (tmp_path / "demo" / "fake" / "records.jsonl").exists()


def test_token_floor_raises_the_ledger_charge_only(tmp_path):
    class Short(Scripted):
        name = "short"

    c = ProbeClient(ImageTokenFloor(Short(["no"])), Ledger.load(tmp_path / "l.json"), "fake")
    run_probe(SPEC, items(1), c, tmp_path)
    assert c.ledger.entries["wonder"]["input_tokens"] == harness.IMAGE_TOKENS_FLOOR


def test_baseline_on_the_same_items(tmp_path):
    r = run_baseline(SPEC, items(), lambda _: "no", "majority", tmp_path)
    assert (r["correct"], r["n"]) == (2, 4)
    assert (tmp_path / "demo" / "majority" / "score.json").exists()


def test_spec_needs_a_required_enum_answer():
    with pytest.raises(ValueError):
        ProbeSpec("x", "p", {"properties": {"answer": {"type": "string"}}, "required": ["answer"]})
