import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from probe import prefilter as pf
from scripts import prefilter as runner


def table(*rows):
    """Rows of (ra, dec, total, peak, majax, minax, s_code)."""
    columns = list(zip(*rows, strict=True))
    return {
        "source_name": np.array([f"s{k}" for k in range(len(rows))]),
        "ra": np.array(columns[0], float),
        "dec": np.array(columns[1], float),
        "total_flux": np.array(columns[2], float),
        "peak_flux": np.array(columns[3], float),
        "majax": np.array(columns[4], float),
        "minax": np.array(columns[5], float),
        "s_code": np.array(columns[6]),
    }


NO_BRIGHT = {"ra": np.array([]), "dec": np.array([]), "total_flux": np.array([])}


def test_the_derived_columns_follow_the_rule():
    d = pf.derived(table((10, 10, 8.0, 2.0, 40.0, 20.0, "M")))
    assert d["axial"][0] == 0.5
    assert d["sb"][0] == 8.0 / 800.0
    assert d["peak_ratio"][0] == 0.25


def test_each_cut_passes_and_fails_a_row():
    rows = table((10, 10, 8.0, 2.0, 40.0, 20.0, "M"))
    passing = pf.Box(major_min=40.0, major_max=40.0, axial_min=0.5, sb_max=0.01, peak_ratio_max=0.25, total_min=8.0,
                     total_max=8.0, s_code="M")
    assert pf.box_mask(rows, NO_BRIGHT, passing).all()
    for failing in (
        pf.Box(major_min=41.0),
        pf.Box(major_max=39.0),
        pf.Box(axial_min=0.6),
        pf.Box(sb_max=0.009),
        pf.Box(peak_ratio_max=0.2),
        pf.Box(total_min=9.0),
        pf.Box(total_max=7.0),
        pf.Box(s_code="S"),
    ):
        assert not pf.box_mask(rows, NO_BRIGHT, failing).any(), failing


def test_a_missing_value_fails_a_cut_on_it_but_passes_when_the_cut_is_off():
    rows = table((10, 10, np.nan, 2.0, 40.0, 20.0, "M"))
    assert not pf.box_mask(rows, NO_BRIGHT, pf.Box(sb_max=1.0)).any()
    assert not pf.box_mask(rows, NO_BRIGHT, pf.Box(total_max=1e9)).any()
    assert pf.box_mask(rows, NO_BRIGHT, pf.Box(major_min=20.0)).all()


def test_isolation_finds_a_bright_neighbour_and_ignores_the_source_itself_and_fainter_ones():
    bright = {"ra": np.array([10.0, 50.0]), "dec": np.array([10.0, 10.0]), "total_flux": np.array([5000.0, 1000.0])}
    near = 10 + 5 / 60  # 5 arcmin north of the bright source
    ra = np.array([10.0, 10.0, 10.0, 50.0])
    dec = np.array([10.0, near, 10 + 10 / 60, 10 + 5 / 60])
    # the bright source itself, one 5 arcmin off, one 10 arcmin off, one 5 arcmin from a source too faint for the cut
    assert pf.isolated(ra, dec, bright, 3000.0, 6.0).tolist() == [True, False, True, True]
    assert pf.isolated(ra, dec, bright, 1000.0, 6.0).tolist() == [True, False, True, False]


def test_the_box_mask_and_the_grid_masks_agree_at_every_grid_value():
    rng = np.random.default_rng(1)
    n = 50
    rows = table(*[
        (float(rng.uniform(0, 5)), float(rng.uniform(0, 5)), float(rng.uniform(0.1, 2000)), float(rng.uniform(0.1, 50)),
         float(rng.uniform(20, 400)), float(rng.uniform(6, 300)), "M" if k % 2 else "S")
        for k in range(n)
    ])
    bright = {"ra": rows["ra"][:5], "dec": rows["dec"][:5], "total_flux": np.full(5, 20000.0)}
    masks = pf.cut_masks(rows, bright)
    for name in pf.DIMENSIONS:
        for value in pf.GRID[name]:
            assert (masks[name][value] == pf.box_mask(rows, bright, pf.Box(**{name: value}))).all(), (name, value)


def test_a_circle_is_kept_at_the_control_files_radius_only():
    rows = table((10.0, 10 + 25 / 3600, 1, 1, 50, 50, "M"), (20.0, 10 + 35 / 3600, 1, 1, 50, 50, "M"))
    assert pf.rows_near(rows, 10.0, 10.0, pf.circle_radius_arcsec("J0000+0000")).tolist() == [0]
    assert pf.rows_near(rows, 20.0, 10.0, pf.circle_radius_arcsec("J0000+0000")).tolist() == []
    assert pf.circle_radius_arcsec("J1633+1441") == 90.0


def test_rows_near_returns_the_rows_near_the_position_and_not_the_first_row():
    rows = table(
        (10.0, 10.0, 1, 1, 50, 50, "M"),
        (50.0, 40.0, 1, 1, 50, 50, "M"),
        (90.0, 20.0, 1, 1, 50, 50, "M"),
        (90.0, 20 + 20 / 3600, 1, 1, 50, 50, "M"),
    )
    assert pf.rows_near(rows, 50.0, 40.0, 30.0).tolist() == [1]
    assert pf.rows_near(rows, 90.0, 20.0, 30.0).tolist() == [2, 3]
    assert pf.rows_near(rows, 200.0, -10.0, 30.0).tolist() == []


def test_the_fit_never_receives_the_held_out_circles(tmp_path):
    (tmp_path / "tuning.json").write_text(json.dumps({"objects": [{"name": "t", "ra": 1.0, "dec": 2.0}]}))
    (tmp_path / "heldout.json").write_text(json.dumps({"objects": [{"name": "h", "ra": 3.0, "dec": 4.0}]}))
    items = tmp_path / "items.json"
    items.write_text(json.dumps([
        {"group": "tuning", "name": "t", "ra": 1.0, "dec": 2.0},
        {"group": "heldout", "name": "h", "ra": 3.0, "dec": 4.0},
        {"group": "planetary_nebula", "name": "p", "ra": 5.0, "dec": 6.0},
        {"group": "random", "name": "r", "ra": 7.0, "dec": 8.0},
    ]))
    got = pf.load_fit_objects(tmp_path, items)
    assert [o["name"] for group in got.values() for o in group] == ["t", "p", "r"]


def test_an_unknown_group_in_the_items_file_stops_the_fit(tmp_path):
    (tmp_path / "tuning.json").write_text(json.dumps({"objects": []}))
    items = tmp_path / "items.json"
    items.write_text(json.dumps([{"group": "surprise", "name": "x", "ra": 1.0, "dec": 1.0}]))
    with pytest.raises(ValueError, match="surprise"):
        pf.load_fit_objects(tmp_path, items)


def test_a_short_strip_stops_the_run():
    pf.check_count("strip", 5, 5)
    with pytest.raises(RuntimeError, match="server counts 6"):
        pf.check_count("strip", 5, 6)


def test_the_ranking_order_is_circles_then_lookalikes_then_random_then_size():
    assert pf.rank(5, 9, 9, 1) > pf.rank(4, 0, 0, 1200)
    assert pf.rank(5, 1, 9, 1) > pf.rank(5, 2, 0, 1200)
    assert pf.rank(5, 1, 0, 1) > pf.rank(5, 1, 1, 1200)
    assert pf.rank(5, 1, 0, 1200) > pf.rank(5, 1, 0, 1199)


def grid_rows(faint_copies):
    """One circle row, one lookalike row with worse surface brightness, and copies of a faint round diffuse row."""
    circle = (10.0, 10.0, 12.0, 1.0, 110.0, 100.0, "M")
    lookalike = (40.0, 10.0, 900.0, 300.0, 110.0, 100.0, "M")
    filler = [(100.0 + k * 0.01, 40.0, 12.0, 1.0, 110.0, 100.0, "M") for k in range(faint_copies)]
    return table(circle, lookalike, *filler)


def small_grid(monkeypatch):
    grid = dict.fromkeys(pf.GRID, (pf.OFF,))
    grid["major_min"] = (100.0, 20.0)
    grid["sb_max"] = (1e-3, 5e-2, pf.OFF)
    monkeypatch.setattr(pf, "GRID", grid)


def test_the_search_prefers_the_box_that_drops_the_lookalike_at_equal_circles(monkeypatch):
    small_grid(monkeypatch)
    rows = grid_rows(3)
    best = pf.search(rows, NO_BRIGHT, {"tuning": [np.array([0])], "lookalike": [np.array([1])], "random": []})
    assert best["circles"] == 1
    assert best["lookalikes"] == 0
    assert best["box"]["sb_max"] == 5e-2  # the circle's sb is above 1e-3, the lookalike's above 5e-2


def test_the_search_never_returns_a_box_over_the_list_size(monkeypatch):
    small_grid(monkeypatch)
    monkeypatch.setattr(pf, "MAX_LIST", 2)
    rows = grid_rows(3)  # every box keeping the circle holds at least four rows
    assert pf.search(rows, NO_BRIGHT, {"tuning": [np.array([0])], "lookalike": [], "random": []}) is None


def test_a_box_that_keeps_fewer_circles_does_not_win_on_size(monkeypatch):
    small_grid(monkeypatch)
    rows = table((10.0, 10.0, 12.0, 1.0, 110.0, 100.0, "M"), (40.0, 10.0, 9000.0, 300.0, 110.0, 100.0, "M"))
    best = pf.search(rows, NO_BRIGHT, {"tuning": [np.array([1])], "lookalike": [], "random": []})
    assert best["circles"] == 1
    assert best["box"]["sb_max"] is None


def test_the_search_agrees_with_brute_force_on_a_small_grid(monkeypatch):
    small_grid(monkeypatch)
    monkeypatch.setattr(pf, "MAX_LIST", 3)
    rng = np.random.default_rng(3)
    rows = table(*[
        (float(k), 10.0, float(rng.uniform(1, 2000)), 1.0, float(rng.uniform(20, 200)), 90.0, "M") for k in range(12)
    ])
    targets = {"tuning": [np.array([0]), np.array([1]), np.array([2])], "lookalike": [np.array([3])], "random": []}
    found = pf.search(rows, NO_BRIGHT, targets)

    def groupwise(mask, group):
        return sum(bool(mask[i].any()) for i in group)

    scores = []
    for major in pf.GRID["major_min"]:
        for sb in pf.GRID["sb_max"]:
            mask = pf.box_mask(rows, NO_BRIGHT, pf.Box(major_min=major, sb_max=sb))
            if 0 < mask.sum() <= pf.MAX_LIST:
                scores.append(pf.rank(groupwise(mask, targets["tuning"]), groupwise(mask, targets["lookalike"]), 0,
                                      int(mask.sum())))
    assert pf.rank(found["circles"], found["lookalikes"], found["randoms"], found["size"]) == max(scores)


def test_the_box_survives_its_json_form():
    box = pf.Box(major_min=30.0, isolation=(3000.0, 6.0))
    assert pf.Box.from_json(json.loads(json.dumps(box.to_json()))) == box


def test_the_grid_has_the_nine_cuts_written_in_the_rule():
    assert pf.DIMENSIONS == (
        "major_min",
        "major_max",
        "axial_min",
        "sb_max",
        "peak_ratio_max",
        "total_min",
        "total_max",
        "s_code",
        "isolation",
    )
    assert min(pf.GRID["major_min"]) == pf.FLOOR_MAJOR_ARCSEC


def test_strips_cover_the_sky_without_a_gap():
    edges = pf.strip_edges()
    assert edges[0][0] == 0 and edges[-1][1] == 360
    assert all(a[1] == b[0] for a, b in zip(edges, edges[1:], strict=False))


def run_git(folder, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=folder, check=True,
                   capture_output=True)


def test_the_held_out_count_needs_the_cuts_committed_and_unchanged(tmp_path, monkeypatch):
    run_git(tmp_path, "init")
    cuts = tmp_path / "frozen_cuts.json"
    cuts.write_text("{}\n")
    monkeypatch.chdir(tmp_path)
    assert not runner.committed_unchanged(cuts.name)  # written, not committed
    run_git(tmp_path, "add", cuts.name)
    run_git(tmp_path, "commit", "-m", "freeze")
    assert runner.committed_unchanged(cuts.name)
    cuts.write_text('{"changed": 1}\n')
    assert not runner.committed_unchanged(cuts.name)  # changed after the commit


def test_the_held_out_step_refuses_before_the_freeze_and_reads_nothing(tmp_path, monkeypatch):
    run_git(tmp_path, "init")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "frozen_cuts.json").write_text("{}\n")
    (tmp_path / "frozen_cuts_v2.json").write_text("{}\n")
    assert runner.heldout(Path("no_data"), Path("no_controls"), Path(".")) == 1
    run_git(tmp_path, "add", "frozen_cuts.json")
    run_git(tmp_path, "commit", "-m", "only the first")
    assert runner.heldout(Path("no_data"), Path("no_controls"), Path(".")) == 1  # the second is not committed yet


def test_the_held_out_count_is_made_once(tmp_path, monkeypatch):
    run_git(tmp_path, "init")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "frozen_cuts.json").write_text("{}\n")
    (tmp_path / "frozen_cuts_v2.json").write_text("{}\n")
    run_git(tmp_path, "add", ".")
    run_git(tmp_path, "commit", "-m", "both")
    (tmp_path / "heldout.json").write_text("{}\n")
    assert runner.heldout(Path("no_data"), Path("no_controls"), Path(".")) == 1


def v2_targets():
    # row 0 M circle a; row 1 S circle b; row 2 S lookalike near the S box; rows 3.. filler
    return {"tuning": [np.array([0]), np.array([1])], "lookalike": [np.array([2])], "random": []}


def v2_rows():
    return table(
        (10.0, 10.0, 12.0, 0.5, 110.0, 100.0, "M"),
        (20.0, 10.0, 12.0, 0.1, 110.0, 100.0, "S"),
        (30.0, 10.0, 900.0, 300.0, 110.0, 100.0, "S"),
        (40.0, 10.0, 12.0, 0.5, 110.0, 100.0, "M"),
        (50.0, 10.0, 12.0, 0.1, 110.0, 100.0, "S"),
        (60.0, 10.0, 12.0, 0.1, 110.0, 100.0, "C"),
    )


def v2_grid(monkeypatch):
    grid = dict.fromkeys(pf.GRID, (pf.OFF,))
    grid["major_min"] = (100.0, 20.0)
    grid["sb_max"] = (5e-2, pf.OFF)
    grid["s_code"] = ("M", pf.OFF)
    monkeypatch.setattr(pf, "GRID", grid)


def test_each_footprint_holds_only_its_own_s_code_and_skips_boxes_with_no_circle(monkeypatch):
    v2_grid(monkeypatch)
    rows, targets = v2_rows(), v2_targets()
    assert set(pf.footprints(rows, NO_BRIGHT, targets, "M")) == {(0b01, 0, 0)}
    found = pf.footprints(rows, NO_BRIGHT, targets, "S")
    assert set(found) == {(0b10, 0, 0), (0b10, 1, 0)}
    assert set(found[(0b10, 0, 0)]) == {2}  # circle b and the other S filler, without the lookalike
    assert set(found[(0b10, 1, 0)]) == {3}


def test_the_best_pair_keeps_both_circles_and_drops_the_lookalike_on_the_tie(monkeypatch):
    v2_grid(monkeypatch)
    rows, targets = v2_rows(), v2_targets()
    best = pf.best_pair(pf.footprints(rows, NO_BRIGHT, targets, "M"), pf.footprints(rows, NO_BRIGHT, targets, "S"))
    assert best["circles"] == 0b11
    assert best["lookalikes"] == 0
    assert best["sizes"] == (2, 2)
    boxes = [pf.box_from_cuts(cuts, code) for cuts, code in zip(best["cuts"], pf.V2_CODES, strict=True)]
    mask = pf.union_mask(rows, NO_BRIGHT, boxes)
    assert mask.tolist() == [True, True, False, True, True, False]  # no lookalike, no C source


def test_a_pair_over_the_list_size_is_refused_and_the_largest_that_fits_wins():
    first = {(0b01, 0, 0): {3: ["a3"], 5: ["a5"]}}
    second = {(0b10, 0, 0): {4: ["b4"], 9: ["b9"]}}
    original = pf.MAX_LIST
    try:
        pf.MAX_LIST = 6
        assert pf.best_pair(first, second) is None  # 3 + 4 is over
        pf.MAX_LIST = 10
        best = pf.best_pair(first, second)
        assert best["sizes"] == (5, 4)  # 3 + 9 is over, and 5 + 4 is larger than 3 + 4
    finally:
        pf.MAX_LIST = original


def test_the_pair_rank_puts_circles_before_lookalikes_before_size():
    first = {(0b001, 0, 0): {1: ["a"]}, (0b011, 1, 0): {1: ["b"]}}
    second = {(0b100, 0, 0): {100: ["c"]}, (0b100, 1, 0): {1: ["d"]}}
    best = pf.best_pair(first, second)
    assert best["circles"] == 0b111  # three circles beat fewer lookalikes
    assert best["lookalikes"] == 1
    assert best["sizes"] == (1, 100)  # the same union either way, so the larger list wins


def test_the_version_with_the_most_tuning_circles_goes_forward_and_the_earliest_on_a_tie():
    assert pf.go_forward({"v1": 4, "v2": 5, "v3": 3}) == "v2"
    assert pf.go_forward({"v1": 4, "v2": 4, "v3": 4}) == "v1"
    assert pf.go_forward({"v1": 4, "v2": 4, "v3": 7}) == "v3"
    assert pf.go_forward({"v1": 5, "v2": 4, "v3": 4}) == "v1"


def test_v3_only_adds_low_values_of_peak_ratio_to_the_grid():
    for name in pf.GRID:
        if name != "peak_ratio_max":
            assert pf.GRID_V3[name] == pf.GRID[name], name
    old = pf.GRID["peak_ratio_max"]
    added = pf.GRID_V3["peak_ratio_max"][: -len(old)]
    assert pf.GRID_V3["peak_ratio_max"][-len(old) :] == old
    assert added == (0.002, 0.003, 0.005, 0.0075, 0.01, 0.015)


def test_a_finer_peak_ratio_can_drop_what_the_v2_grid_could_not(monkeypatch):
    v2_grid(monkeypatch)
    rows = table(
        (10.0, 10.0, 100.0, 0.2, 110.0, 100.0, "S"),  # the circle, peak_ratio 0.002
        (20.0, 10.0, 100.0, 1.0, 110.0, 100.0, "S"),  # peak_ratio 0.01
    )
    targets = {"tuning": [np.array([0])], "lookalike": [], "random": []}
    coarse = dict(pf.GRID)
    coarse["peak_ratio_max"] = (0.02, pf.OFF)
    fine = coarse | {"peak_ratio_max": (0.002, 0.02, pf.OFF)}
    assert set(pf.footprints(rows, NO_BRIGHT, targets, "S", coarse)[(1, 0, 0)]) == {2}
    assert set(pf.footprints(rows, NO_BRIGHT, targets, "S", fine)[(1, 0, 0)]) == {1, 2}
