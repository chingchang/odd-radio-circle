import json
import subprocess

import numpy as np
import pytest

from probe import baselines as bl
from probe import known_cut as kc
from probe import radio
from scripts import known_cut as runner

OTYPEDEF = """otype,description,path
"G","Galaxy","G"
"QSO","Quasar","G > AGN > QSO"
"PN","Planetary Nebula","* > Ev* > PN"
"PN?","Planetary Nebula Candidate","* > Ev* > PN"
"SNR","SuperNova Remnant","ISM > SNR"
"SR?","SuperNova Remnant Candidate","ISM > SNR"
"SN*","SuperNova","* > SN*"
"HII","HII Region","ISM > HII"
"*","Star","*"
"""
FAMILY = kc.families(OTYPEDEF)
HEAD = ",".join(kc.SIMBAD_COLUMNS)
RA, DEC = 150.0, 40.0


def obj(otype, away_arcmin=0.5, size=None):
    return {
        "main_id": "x",
        "otype": otype,
        "ra": RA,
        "dec": DEC + away_arcmin / 60,
        "galdim_majaxis": size,
        "galdim_minaxis": size,
        "rvz_redshift": None,
    }


def found(*cone, ring_arcsec=60.0, calibrators=None):
    return kc.sky_matches(RA, DEC, ring_arcsec, list(cone), FAMILY, calibrators or {})


def test_families_come_from_the_path():
    assert FAMILY["G"] == FAMILY["QSO"] == kc.GALAXY
    assert FAMILY["PN"] == FAMILY["PN?"] == kc.PN
    assert FAMILY["SNR"] == FAMILY["SR?"] == kc.SNR
    assert FAMILY["HII"] == kc.HII
    assert "SN*" not in FAMILY and "*" not in FAMILY


def test_a_table_of_types_lacking_a_family_stops_the_run():
    with pytest.raises(RuntimeError, match="lacks a family"):
        kc.families('otype,description,path\n"G","Galaxy","G"\n')


def test_an_empty_cone_is_an_answer_and_an_outage_is_not():
    assert kc.parse_cone(HEAD + "\n") == []
    with pytest.raises(RuntimeError, match="did not answer"):
        kc.parse_cone("<VOTABLE>service unavailable</VOTABLE>")
    with pytest.raises(RuntimeError, match="did not answer"):
        kc.parse_cone("")


def test_a_cone_row_keeps_missing_sizes_as_none():
    row = kc.parse_cone(f'{HEAD}\n"M  57",283.4,33.0,"PN",1.153,,\n')[0]
    assert row["main_id"] == "M  57" and row["otype"] == "PN" and row["galdim_majaxis"] == 1.153
    assert row["galdim_minaxis"] is None and row["rvz_redshift"] is None


def test_the_cone_is_one_arcmin_around_the_position():
    query = kc.cone_query(RA, DEC)
    assert "CIRCLE('ICRS',150.000000,40.000000,0.01666667)" in query
    assert "from basic" in query


@pytest.mark.parametrize(
    "otype,cut", [("PN", kc.PN), ("PN?", kc.PN), ("SNR", kc.SNR), ("SR?", kc.SNR), ("HII", kc.HII)]
)
def test_each_type_removes_under_its_own_cut(otype, cut):
    result = found(obj(otype))
    assert kc.removed_by(result, False) == [cut]


def test_a_match_outside_the_radius_removes_nothing_whatever_the_service_sent():
    assert kc.removed_by(found(obj("PN", 1.5)), False) == []


def test_a_star_or_a_supernova_removes_nothing():
    assert kc.removed_by(found(obj("*"), obj("SN*")), False) == []


def test_a_galaxy_removes_only_when_strictly_above_the_ring():
    assert kc.removed_by(found(obj("G", size=1.5), ring_arcsec=60.0), False) == [kc.GALAXY_LARGER]
    assert kc.removed_by(found(obj("G", size=1.0), ring_arcsec=60.0), False) == []
    assert kc.removed_by(found(obj("G", size=1.5), ring_arcsec=120.0), False) == []


def test_the_ring_size_is_in_arcsec_and_the_galaxy_in_arcmin():
    assert kc.removed_by(found(obj("G", size=2.0), ring_arcsec=100.0), False) == [kc.GALAXY_LARGER]
    assert kc.removed_by(found(obj("G", size=1.0), ring_arcsec=100.0), False) == []


def test_a_galaxy_with_no_size_or_a_smaller_one_is_noted_and_removes_nothing():
    result = found(obj("G"), obj("QSO", size=0.7), obj("G", size=0.2))
    assert kc.removed_by(result, False) == []
    assert len(result["galaxy_no_size"]) == 1
    assert len(result["galaxy_above_half_the_ring"]) == 1


def test_a_calibrator_removes_within_the_radius_only():
    near = {"3C 196": {"ra": RA, "dec": DEC + 0.5 / 60}}
    far = {"3C 196": {"ra": RA, "dec": DEC + 2 / 60}}
    assert kc.removed_by(found(calibrators=near), False) == [kc.CALIBRATOR]
    assert kc.removed_by(found(calibrators=far), False) == []


def test_the_calibrator_list_holds_the_project_list_and_the_a_team():
    assert set(radio.LOOKALIKES["artefact_ring"]) < set(kc.CALIBRATORS)
    assert {"Cas A", "Cyg A", "Tau A", "Vir A"} < set(kc.CALIBRATORS)


def noise_field(seed=1, n=240):
    return np.random.default_rng(seed).normal(0, 1e-4, (n, n))


def spokes_field(seed=1, n=240):
    """Noise, a bright peak and thin radial lines of both signs around it, at ten times the noise."""
    field = noise_field(seed, n)
    y, x = np.indices(field.shape, dtype=float)
    wave = np.cos(36 * np.arctan2(y - n / 2, x - n / 2))
    field[wave > 0.99] += 1e-3
    field[wave < -0.99] -= 1e-3
    field[n // 2, n // 2] = 0.5
    return field


def wall_to_wall_field(seed=1, n=240):
    """Lines of both signs over every pixel, which inflate the noise the depth is measured in."""
    field = noise_field(seed, n)
    y, x = np.indices(field.shape, dtype=float)
    return field + 1e-3 * np.sign(np.cos(36 * np.arctan2(y - n / 2, x - n / 2)))


def real_disc_field(seed=1, n=240):
    """Noise and a bright filled disc, which goes above the background and never below."""
    field = noise_field(seed, n)
    y, x = np.indices(field.shape, dtype=float)
    field[np.hypot(x - n / 2, y - n / 2) < 40] += 5e-3
    return field


def test_pure_noise_has_the_depth_of_its_percentile():
    assert kc.negative_depth(noise_field()) == pytest.approx(3.09, abs=0.15)


def test_a_bright_real_disc_stays_at_the_depth_of_noise():
    assert kc.negative_depth(real_disc_field()) < 3.5


def test_thin_spokes_go_deep():
    assert kc.negative_depth(spokes_field()) > 3.8


def test_a_known_limit_spokes_over_every_pixel_do_not_go_deep():
    assert kc.negative_depth(wall_to_wall_field()) < 3.5


def test_the_depth_of_a_field_with_no_data_or_no_noise_is_nan():
    assert np.isnan(kc.negative_depth(np.full((5, 5), np.nan)))
    assert np.isnan(kc.negative_depth(np.zeros((5, 5))))


def test_no_data_pixels_do_not_move_the_depth():
    field = noise_field()
    cut = field.copy()
    cut[:10] = np.nan
    assert kc.negative_depth(cut) == pytest.approx(kc.negative_depth(field), abs=0.1)


def test_the_flag_needs_both_depth_and_a_bright_source():
    near = {"total_flux_mjy": 2000.0, "arcmin_away": 12.0}
    assert kc.spoke_flag(5.0, 200.0, None, 4.0)
    assert kc.spoke_flag(5.0, 10.0, near, 4.0)
    assert not kc.spoke_flag(5.0, 10.0, None, 4.0)
    assert not kc.spoke_flag(3.0, 200.0, near, 4.0)
    assert not kc.spoke_flag(float("nan"), 200.0, near, 4.0)
    assert not kc.spoke_flag(5.0, float("nan"), None, 4.0)


def test_the_threshold_is_at_its_bound_inclusive():
    assert kc.spoke_flag(4.0, 200.0, None, 4.0)


def test_the_neighbour_is_the_brightest_within_reach_and_none_outside():
    bright = {
        "ra": np.array([RA, RA, RA]),
        "dec": np.array([DEC + 0.1, DEC + 0.2, DEC + 1.0]),
        "total_flux": np.array([1500.0, 3000.0, 90000.0]),
    }
    near = kc.brightest_neighbour(RA, DEC, bright)
    assert near["total_flux_mjy"] == 3000.0 and near["arcmin_away"] == pytest.approx(12.0, abs=0.01)
    assert kc.brightest_neighbour(RA, DEC - 5, bright) is None


def test_the_fit_reads_only_what_the_rule_names():
    items = [
        {"id": "a", "group": "artefact_ring"},
        {"id": "t", "group": "tuning"},
        {"id": "h", "group": "heldout"},
        {"id": "r", "group": "random"},
        {"id": "p", "group": "planetary_nebula"},
    ]
    depths = {"a": 10.0, "t": 3.0, "h": 99.0, "r": 99.0, "p": 99.0, "list-1": 5.0, "list-2": 99.0}
    fields = kc.spoke_fit_fields(items, depths, ["list-1"])
    assert fields == {"circles": [10.0, 5.0], "lookalikes": [3.0]}
    assert bl.tune(**fields)["threshold"] == pytest.approx(4.0)


def row(item, ra=RA, dec=DEC, known=None, removed=(), two=False):
    return {"id": item, "ra": ra, "dec": dec, "known_circle": known, "removed_by": list(removed), "two_votes": two}


def test_rows_link_into_objects_through_a_neighbour():
    rows = [row("a"), row("b", dec=DEC + 2.5 / 60), row("c", dec=DEC + 5 / 60), row("d", dec=DEC + 10 / 60)]
    assert kc.link_objects(rows) == [["a", "b", "c"], ["d"]]
    assert kc.link_objects([]) == []


def test_a_cut_is_charged_for_the_known_circle_it_removes():
    rows = [
        row("a", known="J1", removed=[kc.PN]),
        row("b", removed=[kc.PN, kc.SPOKES]),
        row("c", removed=[kc.SPOKES]),
        row("d"),
    ]
    counts = kc.cut_counts(rows)
    assert counts[kc.PN]["rows_removed"] == 2
    assert counts[kc.PN]["known_circle_rows_removed"] == 1
    assert counts[kc.PN]["known_circles_removed"] == ["J1"]
    assert counts[kc.PN]["rows_only_this_cut_removes"] == 1
    assert counts[kc.SPOKES]["known_circles_removed"] == []
    assert counts[kc.SPOKES]["rows_only_this_cut_removes"] == 1
    assert counts[kc.HII]["rows_removed"] == 0


def test_a_circle_stays_if_one_of_its_rows_is_left_and_two_votes_must_be_on_that_row():
    rows = [
        row("a", known="J1", removed=[kc.PN], two=True),
        row("b", known="J1", two=False),
        row("c", known="J2", removed=[kc.SPOKES], two=True),
    ]
    chain = kc.circle_chain(rows, {"J1": "tuning", "J2": "heldout", "J3": "heldout"})
    one, two, three = (chain["circles"][name] for name in ("J1", "J2", "J3"))
    assert one["left"] and not one["left_with_two_votes"]
    assert two["before_the_cuts"] and not two["left"]
    assert not three["before_the_cuts"] and not three["left"]
    assert chain["counts"]["all"]["left"]["called"] == 1 and chain["counts"]["all"]["left"]["n"] == 3
    assert chain["counts"]["heldout"]["before_the_cuts"]["called"] == 1


def init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)


def freeze(path, monkeypatch, *names):
    monkeypatch.chdir(path)
    (path / "docs/proposals").mkdir(parents=True)
    (path / "probe").mkdir()
    report = path / "report"
    report.mkdir()
    for name in (runner.RULE, runner.CODE, report / "frozen_spokes.json"):
        (path / name).write_text("{}\n")
    init_repo(path)
    subprocess.run(["git", "add", *names], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=path, check=True)
    return report


def test_measuring_refuses_an_uncommitted_threshold(tmp_path, monkeypatch):
    report = freeze(tmp_path, monkeypatch, str(runner.RULE), str(runner.CODE))
    assert runner.refuse_unfrozen(report)


def test_measuring_refuses_a_rule_changed_since_its_commit(tmp_path, monkeypatch):
    report = freeze(tmp_path, monkeypatch, ".")
    assert not runner.refuse_unfrozen(report)
    runner.RULE.write_text("a different rule\n")
    assert runner.refuse_unfrozen(report)


def test_tuning_runs_once(tmp_path):
    (tmp_path / "frozen_spokes.json").write_text("{}\n")
    assert runner.tune(tmp_path, tmp_path, tmp_path) == 1


def test_positions_hold_the_ring_like_rows_and_their_shifts_only(tmp_path):
    votes = tmp_path / "votes.jsonl"
    rows = [
        {"item_id": "list-0001", "vote": 1, "prediction": radio.RING},
        {"item_id": "list-0002", "vote": 1, "prediction": radio.NOT_RING},
    ]
    votes.write_text("".join(json.dumps(r) + "\n" for r in rows))
    found = runner.positions(votes)
    groups = {p["id"]: p for p in found}
    assert "list-0001" in groups and "shift-list-0001" in groups
    assert "list-0002" not in groups and "list-0003" not in groups
    assert groups["shift-list-0001"]["dec"] == pytest.approx(groups["list-0001"]["dec"] + 10 / 60)
    assert groups["shift-list-0001"]["ring_arcsec"] == groups["list-0001"]["ring_arcsec"]
    assert sum(p["group"] == "circle" for p in found) == 18
    assert all(p["ring_arcsec"] == kc.SMALLEST_RING_ARCSEC for p in found if p["group"] == "circle")
