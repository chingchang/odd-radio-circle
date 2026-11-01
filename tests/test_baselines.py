import json
import subprocess

import numpy as np
import pytest
from astropy.io import fits
from PIL import Image

from probe import baselines as bl
from probe import radio
from scripts import list_fields as runner


def item(group, score_6, score_20=float("nan")):
    return {"group": group, "measures": {"score_6": score_6, "score_20": score_20}}


def test_the_field_value_is_the_larger_score_and_ignores_one_nan():
    assert bl.best_score({"score_6": 1.0, "score_20": 2.0}) == 2.0
    assert bl.best_score({"score_6": 1.0, "score_20": float("nan")}) == 1.0
    assert np.isnan(bl.best_score({"score_6": float("nan"), "score_20": float("nan")}))


def test_tuning_reads_tuning_circles_and_lookalikes_only():
    items = [item("tuning", 1.0), item("ring_galaxy", 2.0), item("artefact_ring", 3.0)]
    plain = bl.tuning_scores(items)
    assert plain == {"circles": [1.0], "lookalikes": [2.0, 3.0]}
    assert bl.tuning_scores([*items, item("heldout", 99.0), item("random", 99.0)]) == plain


def test_a_changed_held_out_score_cannot_move_the_threshold():
    items = [item("tuning", 2.0), item("tuning", 3.0), item("ring_galaxy", 1.0), item("ring_galaxy", 2.5)]
    a = bl.tune(**bl.tuning_scores([*items, item("heldout", 0.0)]))
    b = bl.tune(**bl.tuning_scores([*items, item("heldout", 50.0)]))
    assert a == b


def test_an_unknown_group_stops_the_tuning():
    with pytest.raises(ValueError, match="unknown group"):
        bl.tuning_scores([item("mystery", 1.0)])


def test_candidates_are_midpoints_and_both_outsides():
    assert bl.candidates([1.0, 3.0, 3.0, float("nan")]) == [0.0, 2.0, 4.0]
    with pytest.raises(ValueError):
        bl.candidates([float("nan")])


def test_tuning_separates_groups_that_can_be_separated():
    found = bl.tune([5.0, 6.0], [1.0, 2.0, 3.0])
    assert found["threshold"] == 4.0
    assert (found["circles_called"], found["lookalikes_not_called"], found["youden_j"]) == (2, 3, 1.0)


def test_scores_that_cannot_tell_the_groups_apart_call_nothing():
    found = bl.tune([1.0, 2.0], [1.0, 2.0])
    assert found["youden_j"] == 0.0
    assert found["threshold"] == 3.0
    assert found["circles_called"] == 0


def test_a_tie_goes_to_the_highest_threshold():
    # Calling the top circle alone and calling both with one lookalike tie at 0.5.
    found = bl.tune([4.0, 2.0], [3.0, 1.0])
    assert found["youden_j"] == 0.5
    assert found["threshold"] == 3.5


def test_a_nan_lookalike_is_not_called_and_a_nan_circle_is_not_a_hit():
    found = bl.tune([5.0, float("nan")], [1.0, float("nan")])
    assert found["circles_called"] == 1
    assert found["lookalikes_not_called"] == 2


def test_the_default_rule_is_unchanged_and_the_threshold_moves_it():
    assert radio.annulus_rule(2.9, 1.0) == radio.NOT_RING
    assert radio.annulus_rule(1.0, 3.0) == radio.RING
    assert radio.annulus_rule(2.9, 1.0, 2.5) == radio.RING
    assert radio.annulus_rule(float("nan"), float("nan"), -100.0) == radio.NOT_RING


def test_calls_differ_only_by_threshold():
    assert bl.calls({"score_6": 2.0, "score_20": 0.0}, 1.0) == {"annulus": radio.NOT_RING, "annulus_tuned": radio.RING}


def test_a_circle_the_prefilter_lost_misses_through_the_list_but_can_hit_at_its_position():
    published = {"annulus": radio.RING, "annulus_tuned": radio.RING}
    outcome = bl.circle_outcome("tuning", published, [])
    assert outcome["on_list"] is False
    assert outcome["through_list"] == {"annulus": False, "annulus_tuned": False}


def test_one_called_row_is_enough_for_its_circle_and_it_counts_once():
    no = {"annulus": radio.NOT_RING, "annulus_tuned": radio.NOT_RING}
    yes = {"annulus": radio.NOT_RING, "annulus_tuned": radio.RING}
    rows = [{"calls": no}, {"calls": yes}, {"calls": yes}]
    outcomes = {"a": bl.circle_outcome("heldout", no, rows), "b": bl.circle_outcome("tuning", no, [])}
    counts = bl.circle_counts(outcomes)
    assert counts["heldout"]["annulus_tuned_through_list"]["called"] == 1
    assert counts["heldout"]["annulus_through_list"]["called"] == 0
    assert counts["all"]["annulus_tuned_through_list"] == {"called": 1, "n": 2, "wilson_95": counts["all"][
        "annulus_tuned_through_list"]["wilson_95"]}
    assert counts["all"]["kept_by_prefilter"]["called"] == 1


def test_the_field_id_says_nothing_of_the_source(tmp_path):
    path = tmp_path / "list.csv"
    path.write_text(
        "source_name,ra,dec,total_flux,peak_flux,majax,minax,s_code\nILTJ000325.56+034143.4,0.85,3.69,1,1,50,40,M\n"
    )
    row = runner.read_list(path)[0]
    assert row["id"] == "list-0001"
    assert row["ra"] == 0.85
    assert runner.guard.find_leak(row["id"]) is None


def test_a_list_over_the_cap_is_refused(tmp_path):
    path = tmp_path / "list.csv"
    line = "x,1,1,1,1,1,1,M\n"
    path.write_text("source_name,ra,dec,total_flux,peak_flux,majax,minax,s_code\n" + line * 1201)
    with pytest.raises(ValueError):
        runner.read_list(path)


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True
    )


def test_fetch_and_score_refuse_an_uncommitted_threshold(tmp_path, monkeypatch):
    git(tmp_path, "init")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "LIST_PATH", tmp_path / "list.csv")
    (tmp_path / "list.csv").write_text("x\n")
    report = tmp_path / "report"
    report.mkdir()
    (report / "frozen_threshold.json").write_text('{"threshold": 1.0}\n')
    assert runner.refuse_unfrozen(report) is True
    assert runner.fetch(tmp_path / "d", tmp_path / "o", report, None, 1) == 1
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "freeze")
    assert runner.refuse_unfrozen(report) is False
    (report / "frozen_threshold.json").write_text('{"threshold": 2.0}\n')
    assert runner.refuse_unfrozen(report) is True


def test_the_threshold_is_tuned_once(tmp_path):
    items = tmp_path / "items.json"
    items.write_text(json.dumps([item("tuning", 2.0), item("ring_galaxy", 1.0)]))
    assert runner.tune(tmp_path / "r", items) == 0
    first = (tmp_path / "r" / "frozen_threshold.json").read_text()
    assert json.loads(first)["threshold"] == 1.5
    assert runner.tune(tmp_path / "r", items) == 1
    assert (tmp_path / "r" / "frozen_threshold.json").read_text() == first


def synthetic_cutout(path, seed):
    data = np.random.default_rng(seed).normal(0, 1e-4, (120, 120))
    header = fits.Header()
    header.update(
        CTYPE1="RA---SIN", CTYPE2="DEC--SIN", CRVAL1=10.0, CRVAL2=20.0, CRPIX1=60.5, CRPIX2=60.5, CDELT1=-1 / 600,
        CDELT2=1 / 600, BMAJ=20 / 3600,
    )
    fits.PrimaryHDU(data, header).writeto(path)


def row_list(path, rows):
    lines = ["source_name,ra,dec,total_flux,peak_flux,majax,minax,s_code"]
    lines += [f"{name},10.0,20.0,1,1,50,40,M" for name in rows]
    path.write_text("\n".join(lines) + "\n")


def prepared(tmp_path, monkeypatch, names):
    list_path = tmp_path / "list.csv"
    row_list(list_path, names)
    monkeypatch.setattr(runner, "LIST_PATH", list_path)
    monkeypatch.setattr(runner, "refuse_unfrozen", lambda report: False)
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        response = type("R", (), {})()
        response.raise_for_status = lambda: None
        response.headers = {"content-type": "application/fits"}
        path = tmp_path / f"c{len(calls)}.fits"
        synthetic_cutout(path, len(calls))
        response.content = path.read_bytes()
        return response

    monkeypatch.setattr(runner.__dict__["cutout"].__globals__["requests"], "get", fake_get)
    return calls


def test_fetch_writes_each_field_and_a_rerun_fetches_nothing(tmp_path, monkeypatch):
    calls = prepared(tmp_path, monkeypatch, ["a", "b", "c"])
    report = tmp_path / "report"
    report.mkdir()
    data, out = tmp_path / "d", tmp_path / "o"
    assert runner.fetch(data, out, report, 2, 1) == 0
    assert len(calls) == 4
    assert runner.fetch(data, out, report, None, 1) == 0
    assert len(calls) == 6
    assert runner.fetch(data, out, report, None, 1) == 0
    assert len(calls) == 6
    rows = [json.loads(line) for line in (report / "fields.jsonl").read_text().splitlines()]
    assert sorted(r["row_id"] for r in rows) == ["list-0001", "list-0002", "list-0003"]
    assert all(r["status"] == "accepted" and r["name"] in "abc" for r in rows)


def test_the_files_written_for_a_field_carry_no_name_or_metadata(tmp_path, monkeypatch):
    prepared(tmp_path, monkeypatch, ["ILTJ000325.56+034143.4"])
    report = tmp_path / "report"
    report.mkdir()
    out = tmp_path / "o"
    assert runner.fetch(tmp_path / "d", out, report, None, 1) == 0
    names = sorted(p.name for p in (out / "images").iterdir())
    assert names == ["list-0001-20.png", "list-0001-6.png"]
    for path in (out / "images").iterdir():
        runner.check_png(path.read_bytes())
        assert not Image.open(path).info


def test_a_network_failure_stops_the_run_and_keeps_what_landed(tmp_path, monkeypatch):
    calls = prepared(tmp_path, monkeypatch, ["a", "b"])
    report = tmp_path / "report"
    report.mkdir()
    assert runner.fetch(tmp_path / "d", tmp_path / "o", report, 1, 1) == 0
    assert len(calls) == 2

    def broken(*args, **kwargs):
        raise RuntimeError("cutout: the network is gone")

    monkeypatch.setattr(runner, "cutout", broken)
    assert runner.fetch(tmp_path / "d", tmp_path / "o", report, None, 1) == 1
    rows = (report / "fields.jsonl").read_text().splitlines()
    assert len(rows) == 1


def test_score_refuses_until_every_listed_field_is_fetched(tmp_path, monkeypatch):
    prepared(tmp_path, monkeypatch, ["a", "b"])
    report = tmp_path / "report"
    report.mkdir()
    (report / "frozen_threshold.json").write_text('{"threshold": 1.0}\n')
    assert runner.fetch(tmp_path / "d", tmp_path / "o", report, 1, 1) == 0
    assert runner.score(tmp_path / "d", tmp_path / "o", report, tmp_path, tmp_path, tmp_path) == 1
    assert not (report / "baselines.json").exists()


def test_a_line_cut_off_by_a_kill_is_tried_again_and_harms_no_other(tmp_path, monkeypatch):
    prepared(tmp_path, monkeypatch, ["a", "b"])
    report = tmp_path / "report"
    report.mkdir()
    assert runner.fetch(tmp_path / "d", tmp_path / "o", report, 1, 1) == 0
    with (report / "fields.jsonl").open("a") as f:
        f.write('{"row_id": "list-0002", "sta')
    assert runner.fetch(tmp_path / "d", tmp_path / "o", report, None, 1) == 0
    found = runner.read_decisions(report / "fields.jsonl")
    assert sorted(d["row_id"] for d in found) == ["list-0001", "list-0002"]
