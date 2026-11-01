import numpy as np
import pytest
from landers.models.backend import FakeBackend
from landers.models.crops import to_png
from landers.models.ledger import CapError, Ledger

from probe import guard, radio, recognition, tess
from probe.harness import Item, ProbeClient, ProbeSpec, open_client, run_probe
from probe.promptcheck import problems


def client(tmp_path):
    return ProbeClient(FakeBackend(), Ledger(path=tmp_path / "ledger.json"), "fake")


def png():
    return to_png(np.zeros((4, 4), np.uint8))


@pytest.mark.parametrize("spec", [tess.SPEC, radio.SPEC, recognition.SHEET_SPEC, recognition.FIELD_SPEC])
def test_every_request_passes_the_guard_with_its_schema_name(tmp_path, spec):
    req = spec.request(Item("toi-1.01", "x", (png(),)))
    client(tmp_path)._guard(req)
    assert "tess" not in req.schema_name.lower()


def test_a_survey_name_in_a_schema_name_is_refused(tmp_path):
    schema = recognition.SCHEMA
    spec = ProbeSpec("tess", "Which is it? Answer with the schema.", schema)  # the default name is tess_answer
    with pytest.raises(guard.LeakError):
        run_probe(spec, [Item("a", "recognised", (png(),))], client(tmp_path), tmp_path)


def test_the_recognition_prompts_pass_the_prompt_check():
    assert problems() == []


def test_sheet_ids_are_the_first_three_known_planets():
    records = [{"id": str(i), "disposition": d} for i, d in enumerate(["CP", "KP", "FP", "KP", "CP", "KP", "KP"])]
    assert recognition.sheet_ids(records) == ["1", "3", "5"]


def test_checked_items_are_relabelled_and_the_ids_never_reach_a_request(tmp_path):
    items = [Item("toi-9.01", "planet", (png(),)), Item("toi-8.01", "eclipsing_binary", (png(),))]
    checked = recognition.checked_items(items, ["toi-8.01"])
    assert [(it.id, it.label) for it in checked] == [("toi-8.01", recognition.NOT_RECOGNISED)]
    assert "toi-8.01" not in str(recognition.SHEET_SPEC.request(checked[0]).to_wire(images="digest"))


def test_the_field_ids_are_in_the_lookalike_lists():
    names = {f"{group}-{n.replace(' ', '_')}" for group, listed in radio.LOOKALIKES.items() for n in listed}
    assert set(recognition.FIELD_IDS) <= names


def test_an_item_cap_lowers_the_ledger_cap_and_cannot_raise_it(tmp_path):
    assert open_client("fake", tmp_path, cap_usd=8.0).ledger.total_cap_usd == 8.0
    assert open_client("fake", tmp_path, cap_usd=50.0).ledger.total_cap_usd == 10.0


def test_the_item_cap_stops_a_run(tmp_path):
    c = open_client("fake", tmp_path, cap_usd=0.01)
    with pytest.raises(CapError):
        run_probe(recognition.SHEET_SPEC, [Item("a", recognition.NOT_RECOGNISED, (png(),))], c, tmp_path)
