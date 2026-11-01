import numpy as np
import pytest
from landers.models.backend import FakeBackend
from landers.models.crops import to_png
from landers.models.ledger import CapError, Ledger

from probe import guard, radio, recognition
from probe.harness import Item, ProbeClient, ProbeSpec, open_client, run_probe
from probe.promptcheck import problems


def client(tmp_path):
    return ProbeClient(FakeBackend(), Ledger(path=tmp_path / "ledger.json"), "fake")


def png():
    return to_png(np.zeros((4, 4), np.uint8))


@pytest.mark.parametrize("spec", [radio.SPEC, radio.ZOOM_SPEC, recognition.FIELD_SPEC])
def test_every_request_passes_the_guard_with_its_schema_name(tmp_path, spec):
    req = spec.request(Item("heldout-J1555+2726", "x", (png(),)))
    client(tmp_path)._guard(req)
    assert "lotss" not in req.schema_name.lower()


def test_a_survey_name_in_a_schema_name_is_refused(tmp_path):
    schema = recognition.SCHEMA
    spec = ProbeSpec("lotss", "Which is it? Answer with the schema.", schema)  # the default name is lotss_answer
    with pytest.raises(guard.LeakError):
        run_probe(spec, [Item("a", "recognised", (png(),))], client(tmp_path), tmp_path)


def test_the_recognition_prompts_pass_the_prompt_check():
    assert problems() == []


def test_checked_items_are_relabelled_and_the_ids_never_reach_a_request(tmp_path):
    items = [Item("heldout-J1555+2726", "ring_like", (png(),)), Item("ring_galaxy-NGC_4736", "not_ring_like", (png(),))]
    checked = recognition.checked_items(items, ["ring_galaxy-NGC_4736"])
    assert [(it.id, it.label) for it in checked] == [("ring_galaxy-NGC_4736", recognition.NOT_RECOGNISED)]
    assert "NGC_4736" not in str(recognition.FIELD_SPEC.request(checked[0]).to_wire(images="digest"))


def test_the_field_ids_are_in_the_lookalike_lists():
    names = {f"{group}-{n.replace(' ', '_')}" for group, listed in radio.LOOKALIKES.items() for n in listed}
    assert set(recognition.FIELD_IDS) <= names


def test_an_item_cap_lowers_the_ledger_cap_and_cannot_raise_it(tmp_path):
    assert open_client("fake", tmp_path, cap_usd=8.0).ledger.total_cap_usd == 8.0
    assert open_client("fake", tmp_path, cap_usd=50.0).ledger.total_cap_usd == 10.0


def test_the_item_cap_stops_a_run(tmp_path):
    c = open_client("fake", tmp_path, cap_usd=0.01)
    with pytest.raises(CapError):
        run_probe(recognition.FIELD_SPEC, [Item("a", recognition.NOT_RECOGNISED, (png(),))], c, tmp_path)
