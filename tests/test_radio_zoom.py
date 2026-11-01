import io
import json

import numpy as np
import pytest
from astropy.io import fits
from landers.models.leak import check_png
from PIL import Image

from probe import guard, radio
from scripts import radio_zoom, radio_zoom_report
from tests.test_radio import SIDE, blank, header


def test_the_zoom_is_the_central_half_and_the_same_size_on_both_maps():
    for side in (SIDE, 80):
        field = blank(side=side)
        field[side // 2, side // 2] = 1.0
        field[0, 0] = 1.0  # outside the crop
        u8 = radio.zoom_stretched(field)
        assert u8.shape == (side // 2, side // 2)
        assert u8[side // 4, side // 4] == 255
        png = radio.zoom_png(field)
        check_png(png)
        assert Image.open(io.BytesIO(png)).size == (720, 720)
        assert not Image.open(io.BytesIO(png)).info


def test_the_zoom_stretch_shows_a_faint_patch_beside_a_bright_source():
    field = blank(noise=1e-4)
    field[110:130, 110:130] += 2e-4  # two sigma
    field[70, 70] = 10.0
    zoom = radio.zoom_stretched(field)
    patch, background = zoom[50:70, 50:70].mean(), zoom[:20, :20].mean()  # the crop starts at pixel 60
    old = radio.stretched(field)
    assert patch - background > 1.5 * (old[110:130, 110:130].mean() - old[60:80, 60:80].mean())


def test_the_zoom_noise_comes_from_the_whole_field():
    field = blank(noise=1e-4)
    margin = field.shape[0] // 4
    bright = field.copy()
    bright[margin:-margin, margin:-margin] += np.random.default_rng(3).normal(0, 1e-2, (SIDE // 2, SIDE // 2))
    assert radio.noise(bright) < 3 * radio.noise(field)
    assert (radio.zoom_stretched(bright) == 255).mean() > 0.3


def test_the_zoom_of_no_data_is_black_and_does_not_fail():
    assert (radio.zoom_stretched(np.full((8, 8), np.nan)) == 0).all()
    assert (radio.zoom_stretched(np.zeros((8, 8))) == 0).all()
    field = blank()
    field[SIDE // 2, SIDE // 2] = np.nan
    assert radio.zoom_stretched(field)[SIDE // 4, SIDE // 4] == 0


def test_the_prompt_differs_only_by_saying_what_the_added_images_are():
    guard.check_text(radio.ZOOM_PROMPT)
    first = radio.PROMPT.split("\n\n")
    zoom = radio.ZOOM_PROMPT.split("\n\n")
    assert zoom[0] == first[0].replace("These two images", "The first two images")
    assert zoom[1] == radio.ZOOM_VIEWS_PROMPT
    assert zoom[2:] == first[1:]
    assert radio.ZOOM_SPEC.schema is radio.SPEC.schema
    assert radio.ZOOM_SPEC.request(radio_zoom.Item("x", "y", ())).schema_name == f"{radio.SPEC.name}_answer"


def _inputs(folder, labels):
    """Cutouts on disk and the first run's views drawn from them, as item 3 left them."""
    source, data = folder / "radio_ring", folder / "data"
    (source / "images").mkdir(parents=True)
    (data / "cutouts").mkdir(parents=True)
    records = []
    for k, (label, group) in enumerate(labels):
        item_id = f"{group}-J1555+2726-{k}"
        record = {
            "id": item_id,
            "name": f"name-{k}",
            "group": group,
            "class": "ORC" if label == radio.RING else "",
            "label": label,
            "ra": 120.0,
            "dec": 40.0,
            "measures": {"score_6": 0.0, "score_20": 0.0},
        }
        for resolution, side, scale in ((6, SIDE, 1.5), (20, 80, 4.5)):
            image = blank(seed=k + resolution, side=side)
            head = header(side=side, scale=scale)
            fits.PrimaryHDU(image, head).writeto(data / "cutouts" / f"{item_id}-{resolution}.fits")
            field, _ = radio.centred_field(image, head, 120.0, 40.0)
            record[f"image_{resolution}"] = f"images/f{k}-{resolution}.png"
            (source / record[f"image_{resolution}"]).write_bytes(radio.field_png(field))
        records.append(record)
    path = source / "items.json"
    path.write_text(json.dumps(records))
    return path, data, records


LABELS = [(radio.RING, "tuning"), (radio.NOT_RING, "random")]


def test_a_run_sends_four_images_and_no_id_and_keeps_to_its_own_folder(tmp_path):
    path, data, _ = _inputs(tmp_path, LABELS)
    args = ["--items", str(path), "--data", str(data), "--out-root", str(tmp_path), "--backend", "fake"]
    assert radio_zoom.main(args) == 0
    root = tmp_path / radio.ZOOM_SPEC.name
    row = json.loads((root / "fake" / "records.jsonl").read_text().splitlines()[0])
    sent = json.dumps(row["request"])
    assert sent.count('"type": "image_url"') == 4
    assert "J1555" not in sent and "name-" not in sent and "tuning" not in sent
    assert "radio_ring_answer" in sent and "radio_ring_zoom" not in sent
    assert json.loads((root / "fake" / "bar.json").read_text())["circles"] == 1
    assert not (tmp_path / radio.SPEC.name / "fake").exists()


def test_a_map_that_no_longer_draws_the_first_view_stops_the_run(tmp_path):
    path, data, records = _inputs(tmp_path, LABELS)
    (path.parent / records[0]["image_6"]).write_bytes(b"something else")
    with pytest.raises(RuntimeError, match="does not draw"):
        radio_zoom.main(["--items", str(path), "--data", str(data), "--out-root", str(tmp_path)])


def test_saturation_tells_called_circles_from_missed_ones(tmp_path):
    Image.fromarray(np.full((4, 4), 255, np.uint8)).save(tmp_path / "white.png")
    Image.fromarray(np.zeros((4, 4), np.uint8)).save(tmp_path / "black.png")
    records = [
        {"id": "a", "label": radio.RING, "zoom_6": "white.png", "zoom_20": "white.png"},
        {"id": "b", "label": radio.RING, "zoom_6": "black.png", "zoom_20": "white.png"},
        {"id": "c", "label": radio.NOT_RING, "zoom_6": "black.png", "zoom_20": "black.png"},
    ]
    rows = {"a": {"prediction": radio.NOT_RING}, "b": {"prediction": radio.RING}, "c": {"prediction": radio.RING}}
    result = radio_zoom_report.saturation(records, rows, tmp_path)
    assert set(result["circles"]) == {"a", "b"}
    assert result["medians"] == {"called": {"zoom_6": 0.0, "zoom_20": 1.0}, "missed": {"zoom_6": 1.0, "zoom_20": 1.0}}


def _row(prediction, reason="r"):
    return {"prediction": prediction, "answer": {"reason": reason}}


def test_compare_counts_both_runs_and_lists_each_change():
    records = [
        {"id": "a", "group": "tuning", "class": "ORC", "label": radio.RING},
        {"id": "b", "group": "heldout", "class": "candidate", "label": radio.RING},
        {"id": "c", "group": "random", "label": radio.NOT_RING},
        {"id": "d", "group": "ring_galaxy", "label": radio.NOT_RING},
    ]
    first = {"a": _row(radio.NOT_RING), "b": _row(radio.RING), "c": _row(radio.NOT_RING), "d": _row(radio.NOT_RING)}
    zoom = {"a": _row(radio.RING), "b": _row("no_answer"), "c": _row(radio.NOT_RING), "d": _row(radio.RING, "x | y")}
    result = radio_zoom_report.compare(records, first, zoom)
    run = result["zoom_run"]
    assert run["circles_called_ring_like"]["count"] == 1 and run["confirmed_called"]["count"] == 1
    assert run["candidates_called"] == {"count": 0, "of": 1, "wilson_95": run["candidates_called"]["wilson_95"]}
    assert run["others_rejected"]["count"] == 1
    assert run["others_rejected_by_group"]["ring_galaxy"] == {"rejected": 0, "of": 1}
    assert run["circles_missed"] == ["b"] and run["others_called_ring_like"] == ["d"]
    assert result["first_run"]["circles_missed"] == ["a"]
    assert [c["id"] for c in result["changed"]] == ["a", "b", "d"]
    assert result["changed_to_right"] == 1 and result["changed_to_wrong"] == 2
