import json

import numpy as np
import pytest
from landers.models.backend import FakeBackend, request_hash
from landers.models.crops import to_png
from landers.models.ledger import Ledger

from probe import guard, radio
from probe.harness import Item, ProbeClient, ProbeSpec
from scripts import radio_unchanged


def client(tmp_path):
    return ProbeClient(FakeBackend(), Ledger(path=tmp_path / "ledger.json"), "fake")


def recorded(tmp_path, item):
    path = tmp_path / "records.jsonl"
    path.write_text(json.dumps({"item_id": item.id, "request_hash": request_hash(radio.SPEC.request(item))}) + "\n")
    return path


def item(k=0):
    return Item("a", "ring_like", (to_png(np.full((4, 4), k, np.uint8)),))


def test_the_same_request_matches(tmp_path):
    found = radio_unchanged.requests_match(radio.SPEC, [item()], recorded(tmp_path, item()), client(tmp_path))
    assert found == {"items": 1, "recorded": 1, "same_hash": 1}


def test_a_changed_prompt_does_not_match(tmp_path):
    changed = ProbeSpec(radio.SPEC.name, radio.SPEC.prompt + " Be brief.", radio.SCHEMA)
    found = radio_unchanged.requests_match(changed, [item()], recorded(tmp_path, item()), client(tmp_path))
    assert found["same_hash"] == 0


def test_a_changed_image_does_not_match(tmp_path):
    found = radio_unchanged.requests_match(radio.SPEC, [item(1)], recorded(tmp_path, item()), client(tmp_path))
    assert found["same_hash"] == 0


def test_a_leaking_prompt_is_refused(tmp_path):
    leaking = ProbeSpec(radio.SPEC.name, "Is NGC 6543 ring-like?", radio.SCHEMA)
    with pytest.raises(guard.LeakError):
        radio_unchanged.requests_match(leaking, [item()], recorded(tmp_path, item()), client(tmp_path))


def test_same_files_tells_a_changed_file(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    for folder, text in (("a", "x"), ("b", "y")):
        (tmp_path / folder / "same").write_text("z")
        (tmp_path / folder / "other").write_text(text)
    found = radio_unchanged.same_files(tmp_path / "a", tmp_path / "b", ("same", "other"))
    assert found == {"same": True, "other": False}
