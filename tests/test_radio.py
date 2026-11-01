import io
import json

import numpy as np
import pytest
from astropy.io import fits
from landers.models.leak import check_png
from PIL import Image

from probe import guard, radio
from probe.harness import open_client
from scripts import radio_inputs, radio_probe

SCALE, BEAM, SIDE = 1.5, 6.0, 240


def blank(noise=1e-4, seed=1, side=SIDE):
    return np.random.default_rng(seed).normal(0, noise, (side, side))


def radius(side=SIDE, scale=SCALE):
    y, x = np.indices((side, side), dtype=float) - (side - 1) / 2
    return np.hypot(x, y) * scale / 60


def ring(amplitude=5e-4, r0=1.2, width=0.1, side=SIDE, scale=SCALE, **kwargs):
    return blank(side=side, **kwargs) + amplitude * np.exp(-0.5 * ((radius(side, scale) - r0) / width) ** 2)


def header(side=SIDE, ra=120.0, dec=40.0, scale=SCALE):
    h = fits.Header()
    h["NAXIS"] = 2
    h["NAXIS1"] = h["NAXIS2"] = side
    h["CTYPE1"], h["CTYPE2"] = "RA---TAN", "DEC--TAN"
    h["CRVAL1"], h["CRVAL2"] = ra, dec
    h["CRPIX1"] = h["CRPIX2"] = (side + 1) / 2
    h["CDELT1"], h["CDELT2"] = -scale / 3600, scale / 3600
    return h


def test_a_ring_scores_high_and_empty_or_compact_fields_do_not():
    assert radio.ring_score(ring(), SCALE, BEAM) >= radio.RING_SCORE_THRESHOLD
    assert radio.ring_score(blank(), SCALE, BEAM) < radio.RING_SCORE_THRESHOLD
    point = blank()
    point[(radius() < 0.1)] += 1.0
    assert radio.ring_score(point, SCALE, BEAM) < radio.RING_SCORE_THRESHOLD


def test_a_bright_source_on_the_annulus_is_not_a_ring():
    image = blank()
    y, x = np.indices(image.shape, dtype=float) - (SIDE - 1) / 2
    image[np.hypot(x - 48, y) * SCALE / 60 < 0.1] += 1.0
    assert radio.ring_score(image, SCALE, BEAM) < radio.RING_SCORE_THRESHOLD


def test_a_half_ring_is_not_a_ring():
    image = ring()
    y = np.indices(image.shape, dtype=float)[0] - (SIDE - 1) / 2
    half = blank(seed=2)
    image[y < 0] = half[y < 0]
    assert radio.ring_score(image, SCALE, BEAM) < radio.RING_SCORE_THRESHOLD


def test_a_smooth_blob_is_not_a_ring():
    image = blank() + 1e-2 * np.exp(-0.5 * (radius() / 0.8) ** 2)
    assert radio.ring_score(image, SCALE, BEAM) < radio.RING_SCORE_THRESHOLD


def test_a_ring_scores_on_the_coarse_map_scale_too():
    side, scale = 80, 4.5
    faint = ring(amplitude=4e-4, r0=1.5, width=0.2, side=side, scale=scale)
    assert radio.ring_score(faint, scale, 20.0) >= radio.RING_SCORE_THRESHOLD


def test_annulus_rule_takes_either_map_and_no_score_is_no_ring():
    assert radio.annulus_rule(3.0, float("nan")) == radio.RING
    assert radio.annulus_rule(float("nan"), 3.5) == radio.RING
    assert radio.annulus_rule(2.9, 1.0) == radio.NOT_RING
    assert radio.annulus_rule(float("nan"), float("nan")) == radio.NOT_RING


def test_centred_field_keeps_the_object_in_the_middle_of_a_truncated_cutout():
    full = np.zeros((SIDE, SIDE))
    full[SIDE // 2, SIDE // 2] = 1.0
    field, scale = radio.centred_field(full, header(), 120.0, 40.0)
    assert field.shape == (SIDE, SIDE) and scale == pytest.approx(SCALE)
    assert np.isfinite(field).all()
    peak = np.unravel_index(np.argmax(field), field.shape)
    assert peak == (SIDE // 2, SIDE // 2)
    # Cut off the left 60 columns, as a mosaic edge would, with the reference pixel following.
    h = header()
    h["CRPIX1"] -= 60
    short, _ = radio.centred_field(full[:, 60:], h, 120.0, 40.0)
    assert short.shape == (SIDE, SIDE)
    assert np.unravel_index(np.nanargmax(short), short.shape) == peak
    assert np.isnan(short[:, :50]).all()


def test_centred_field_outside_the_cutout_is_all_empty():
    field, _ = radio.centred_field(np.ones((SIDE, SIDE)), header(), 130.0, 40.0)
    assert np.isnan(field).all()


def test_stretch_is_black_for_no_data_and_keeps_faint_and_bright_apart():
    image = blank()
    image[0, 0] = np.nan
    image[10, 10] = 1.0
    image[20, 20] = 5e-4
    u8 = radio.stretched(image)
    assert u8[0, 0] == 0
    assert u8[10, 10] == 255
    assert 0 < np.median(u8) < u8[20, 20] < 255


def test_stretch_of_an_empty_field_does_not_fail():
    assert (radio.stretched(np.full((4, 4), np.nan)) == 0).all()
    assert (radio.stretched(np.zeros((4, 4))) == 0).all()


def test_images_are_pixels_only_and_both_maps_the_same_size():
    fine = radio.field_png(blank())
    coarse = radio.field_png(blank(side=80))
    check_png(fine)
    check_png(coarse)
    assert Image.open(io.BytesIO(fine)).size == Image.open(io.BytesIO(coarse)).size == (720, 720)
    assert not Image.open(io.BytesIO(fine)).info


def test_image_is_north_up():
    image = np.zeros((SIDE, SIDE))
    image[-10:] = 1.0  # the top rows of a FITS map
    array = np.asarray(Image.open(io.BytesIO(radio.field_png(image))))
    assert array[0, 0, 0] >= array[-1, 0, 0]


def test_detection_takes_a_peak_in_most_of_the_field_and_a_filled_field_counts():
    near = blank()
    near[radius() < 0.1] += 1.0
    off_centre = blank()
    off_centre[(np.abs(radius() - 2.0) < 0.1)] += 2e-3
    far = blank()
    far[:5, :5] += 1.0
    filled = blank(noise=1e-2) + 5e-2
    assert radio.detected(near, SCALE)
    assert radio.detected(off_centre, SCALE)
    assert radio.detected(filled, SCALE)
    assert not radio.detected(far, SCALE)
    assert not radio.detected(blank(), SCALE)


def test_prompt_passes_the_guard_and_says_nothing_of_the_groups():
    guard.check_text(radio.PROMPT)
    guard.check_text(radio.SPEC.name)
    assert radio.SCHEMA["properties"]["answer"]["enum"] == [radio.RING, radio.NOT_RING]


def test_the_guard_refuses_every_name_the_list_uses():
    for names in radio.LOOKALIKES.values():
        for name in names:
            if name not in ("VII Zw 466",):
                with pytest.raises(guard.LeakError):
                    guard.check_text(name)


def test_lookalikes_have_spares_and_a_source_in_every_group():
    assert set(radio.LOOKALIKES) == set(radio.LOOKALIKE_SOURCES)
    assert len(radio.LOOKALIKES) * radio.PER_LOOKALIKE_GROUP == 30
    assert all(len(set(names)) == len(names) > radio.PER_LOOKALIKE_GROUP for names in radio.LOOKALIKES.values())


def test_bar_needs_both_counts():
    circles = [{"label": radio.RING, "group": "tuning", "prediction": radio.RING}] * 14
    circles += [{"label": radio.RING, "group": "heldout", "prediction": radio.NOT_RING}] * 4
    others = [{"label": radio.NOT_RING, "group": "random", "prediction": radio.NOT_RING}] * 48
    others += [{"label": radio.NOT_RING, "group": "planetary_nebula", "prediction": radio.RING}] * 12
    result = radio.bar_result(circles + others)
    assert result["passes"] and result["others_fraction"] == 0.8
    assert result["groups"]["planetary_nebula"] == {"n": 12, "called_ring_like": 12}
    assert not radio.bar_result(circles[1:] + [circles[-1]] + others)["passes"]
    flipped = {"label": radio.NOT_RING, "group": "random", "prediction": radio.RING}
    assert not radio.bar_result(circles + others[1:] + [flipped])["passes"]


def test_rank_summary_is_threshold_free_and_a_nan_ranks_lowest():
    rows = [
        {"label": radio.RING, "group": "tuning", "score": 2.0},
        {"label": radio.RING, "group": "heldout", "score": float("nan")},
        {"label": radio.NOT_RING, "group": "random", "score": 1.0},
        {"label": radio.NOT_RING, "group": "artefact_ring", "score": 9.0},
    ]
    result = radio.rank_summary(rows)
    assert result["circle_outranks_other"] == 0.25
    assert result["circle_outranks_group"] == {"artefact_ring": 0.0, "random": 0.5}
    assert result["best_circle_score"] == 2.0


def test_parse_resolver_reads_the_table_knows_a_miss_and_refuses_an_outage():
    answer = 'main_id,ra,dec,otype\n"M  57",283.39623652,33.02913425,PN\n'
    assert radio_inputs.parse_resolver(answer) == {
        "ra": 283.39623652,
        "dec": 33.02913425,
        "main_id": "M  57",
        "type": "PN",
    }
    assert radio_inputs.parse_resolver("main_id,ra,dec,otype\n") is None
    with pytest.raises(RuntimeError):
        radio_inputs.parse_resolver("<html>Service unavailable</html>")


def test_table_layout_finds_rows_after_a_text_extension():
    table = fits.BinTableHDU.from_columns(
        [
            fits.Column("Source_Name", "22A", array=np.array(["ILTJ1", "ILTJ2"])),
            fits.Column("RA", "D", array=np.array([10.5, 20.5])),
            fits.Column("HEALPIX", "K", array=np.array([3, 4])),
        ]
    )
    buffer = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(np.zeros(3000, np.uint8)), table]).writeto(buffer)
    blob = buffer.getvalue()
    layout = radio_inputs.table_layout(blob)
    assert layout["rows"] == 2
    row = np.frombuffer(blob[layout["start"] + layout["row_bytes"] :][: layout["row_bytes"]], layout["dtype"])[0]
    assert row["Source_Name"].decode().strip() == "ILTJ2" and row["RA"] == 20.5 and row["HEALPIX"] == 4


def test_too_close_sees_a_neighbouring_field():
    assert radio_inputs.too_close(120.0, 40.0, [(120.0, 40.05)])
    assert not radio_inputs.too_close(120.0, 40.0, [(120.0, 40.2)])
    assert not radio_inputs.too_close(120.0, 40.0, [])


def _write_items(folder, labels):
    records = []
    (folder / "images").mkdir(parents=True)
    for k, (label, group) in enumerate(labels):
        for size in (6, 20):
            (folder / "images" / f"f{k}-{size}.png").write_bytes(radio.field_png(blank(seed=k + size, side=8)))
        measures = {"score_6": 5.0 if label == radio.RING else 0.0, "score_20": float("nan")}
        records.append(
            {
                "id": f"{group}-J1555+2726-{k}",
                "name": f"name-{k}",
                "group": group,
                "label": label,
                "image_6": f"images/f{k}-6.png",
                "image_20": f"images/f{k}-20.png",
                "measures": measures,
            }
        )
    path = folder / "items.json"
    path.write_text(json.dumps(records))
    return path


def test_probe_on_the_fake_backend_scores_the_bar_without_sending_an_id(tmp_path):
    labels = [
        (radio.RING, "tuning"),
        (radio.RING, "heldout"),
        (radio.NOT_RING, "random"),
        (radio.NOT_RING, "radio_galaxy"),
    ]
    path = _write_items(tmp_path / "radio_ring", labels)
    assert radio_probe.main(["--items", str(path), "--out-root", str(tmp_path), "--backend", "fake"]) == 0
    root = tmp_path / radio.SPEC.name
    bar = json.loads((root / radio_probe.BASELINE / "bar.json").read_text())
    assert bar["circles_called_ring_like"] == 2 and bar["others_called_not_ring_like"] == 2
    assert json.loads((root / "fake" / "bar.json").read_text())["circles"] == 2
    sent = json.dumps(json.loads((root / "fake" / "records.jsonl").read_text().splitlines()[0])["request"])
    assert "J1555" not in sent and "name-" not in sent and "tuning" not in sent


def test_without_a_backend_only_the_baseline_runs(tmp_path):
    path = _write_items(tmp_path / "radio_ring", [(radio.RING, "tuning"), (radio.NOT_RING, "random")])
    assert radio_probe.main(["--items", str(path), "--out-root", str(tmp_path)]) == 0
    assert (tmp_path / radio.SPEC.name / radio_probe.BASELINE / "score.json").exists()
    assert not (tmp_path / radio.SPEC.name / "fake").exists()


def test_a_real_run_still_needs_key_and_flag(tmp_path):
    with pytest.raises(RuntimeError):
        open_client("real", tmp_path, env={})
