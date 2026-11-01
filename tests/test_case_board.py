import hashlib

import pytest

from probe import case_board as cb
from probe import radio
from probe import screen as sc
from scripts.prefilter import committed_unchanged


def vote(item, number, prediction=radio.RING, known_class="no_known_class"):
    answer = {"answer": prediction, "known_class": known_class, "reason": "A <b>round</b> shell"}
    return {"item_id": item, "vote": number, "prediction": prediction, "answer": answer}


RING, NOT = vote("a", 1), vote("a", 1, radio.NOT_RING)


@pytest.mark.parametrize(
    ("first", "second", "removed", "expected"),
    [
        (RING, vote("a", 2), [], cb.CANDIDATE),
        (RING, vote("a", 2, radio.NOT_RING), [], cb.SECOND_LOOK),
        (RING, None, [], cb.SECOND_LOOK),
        (RING, {"prediction": "no_answer", "error": "x"}, [], cb.SECOND_LOOK),
        (RING, vote("a", 2), ["spokes"], cb.KNOWN),
        (RING, None, ["hii_region"], cb.KNOWN),
        (NOT, None, [], None),
        (None, None, [], cb.NOT_ASSESSED),
        ({"prediction": "no_answer", "error": "x"}, None, [], cb.NOT_ASSESSED),
    ],
)
def test_the_grade(first, second, removed, expected):
    assert cb.verdict(first, second, removed) == expected


def test_no_vote_can_raise_a_row_a_cut_removed():
    for cut in ("galaxy_larger", "planetary_nebula", "supernova_remnant", "hii_region", "calibrator", "spokes"):
        assert cb.verdict(RING, vote("a", 2), [cut]) != cb.CANDIDATE


def test_a_second_vote_can_only_lower():
    assert cb.verdict(RING, vote("a", 2, radio.NOT_RING), []) == cb.SECOND_LOOK
    assert cb.verdict(NOT, vote("a", 2), []) is None


def test_a_named_class_moves_no_verdict():
    jets = {"known_class": "radio_galaxy"}
    assert cb.verdict(vote("a", 1, **jets), vote("a", 2, **jets), []) == cb.CANDIDATE


def test_named_classes_leave_out_none_and_skip_failed_votes():
    failed = {"prediction": "no_answer", "error": "x"}
    assert cb.named_classes(vote("a", 1, known_class="galaxy"), vote("a", 2), failed, None) == ["galaxy"]


def records(*ids, known=None):
    return [{"id": i, "known_circle": (known or {}).get(i)} for i in ids]


def fixture():
    votes = {
        ("cand", sc.FIRST): vote("cand", 1),
        ("cand", sc.SECOND): vote("cand", 2),
        ("jets", sc.FIRST): vote("jets", 1, known_class="radio_galaxy"),
        ("jets", sc.SECOND): vote("jets", 2),
        ("look", sc.FIRST): vote("look", 1),
        ("look", sc.SECOND): vote("look", 2, radio.NOT_RING),
        ("cut", sc.FIRST): vote("cut", 1),
        ("cut", sc.SECOND): vote("cut", 2),
        ("no", sc.FIRST): vote("no", 1, radio.NOT_RING),
        ("orc", sc.FIRST): vote("orc", 1),
        ("orc", sc.SECOND): vote("orc", 2),
    }
    cut_rows = {
        k: {"id": k, "removed_by": ["spokes"] if k == "cut" else [], "ra": 10.0 + n, "dec": 5.0}
        for n, k in enumerate(("cand", "jets", "look", "cut", "orc"))
    }
    listed = records("cand", "jets", "look", "cut", "no", "orc", "unseen", known={"orc": "J1"})
    return votes, cut_rows, cb.graded(listed, cut_rows, votes)


def test_the_board_holds_only_other_rows_left_by_the_cuts_in_its_order():
    _, _, grades = fixture()
    assert [g["id"] for g in cb.board_rows(grades)] == ["cand", "jets", "look"]


def test_a_ring_like_row_the_cuts_never_read_stops_the_grade():
    votes = {("x", sc.FIRST): vote("x", 1)}
    with pytest.raises(ValueError, match="no row from the cuts"):
        cb.graded(records("x"), {}, votes)


def test_counts_keep_rows_circles_and_the_alternative_apart():
    _, cut_rows, grades = fixture()
    left = [cut_rows[g["id"]] for g in cb.board_rows(grades)]
    out = cb.counts(grades, left, {"J1": ["orc"], "J2": []}, {"J1": "tuning", "J2": "heldout"})
    assert out["verdicts"]["other_rows"] == {
        cb.CANDIDATE: 2,
        cb.SECOND_LOOK: 1,
        cb.KNOWN: 1,
        cb.NOT_ASSESSED: 1,
        cb.NO_VERDICT: 1,
    }
    assert out["verdicts"]["known_circle_rows"][cb.CANDIDATE] == 1
    assert out["class_reading"]["candidate_rows_with_a_named_class"] == 1
    assert out["class_reading"]["candidate_rows_with_no_named_class"] == 1
    assert out["class_reading"]["candidate_rows_by_class"] == {"radio_galaxy": 1}
    assert out["circles"]["candidate"]["called"] == 1
    assert out["circles"]["candidate"]["n"] == 2
    assert out["circles"]["heldout_candidate"]["called"] == 0
    assert out["circles_lost_at"]["pre-filter"] == 1
    assert out["circles_lost_at"]["kept to candidate grade"] == 1
    assert out["candidates_of_other_rows_voted"]["n"] == 5


def test_the_alternative_counts_a_circle_a_named_class_would_lower():
    votes = {("o", sc.FIRST): vote("o", 1, known_class="planetary_nebula"), ("o", sc.SECOND): vote("o", 2)}
    grades = cb.graded(records("o", known={"o": "J1"}), {"o": {"removed_by": []}}, votes)
    out = cb.counts(grades, [], {"J1": ["o"]}, {"J1": "tuning"})
    assert out["circles"]["candidate"]["called"] == 1
    assert out["circles"]["candidate_with_no_named_class"]["called"] == 0
    assert grades["o"]["verdict"] == cb.CANDIDATE


@pytest.mark.parametrize(
    ("ids", "verdicts", "stage"),
    [
        ([], [], "pre-filter"),
        (["a"], [None], "first vote"),
        (["a"], [cb.KNOWN], "known-object cut"),
        (["a", "b"], [cb.SECOND_LOOK, None], "second vote"),
        (["a", "b"], [cb.SECOND_LOOK, cb.CANDIDATE], "kept to candidate grade"),
    ],
)
def test_where_a_circle_ended(ids, verdicts, stage):
    grades = {i: {"verdict": v} for i, v in zip(ids, verdicts, strict=True)}
    assert cb.lost_at(ids, grades) == stage


def test_a_map_that_is_not_the_voted_image_stops_the_run(tmp_path):
    source = tmp_path / "a.png"
    source.write_bytes(b"map")
    right = hashlib.sha256(b"map").hexdigest()
    assert cb.copy_checked(source, tmp_path / "out" / "a.png", right) == 3
    assert (tmp_path / "out" / "a.png").read_bytes() == b"map"
    with pytest.raises(ValueError, match="not the image"):
        cb.copy_checked(source, tmp_path / "out" / "b.png", "0" * 64)
    assert not (tmp_path / "out" / "b.png").exists()


@pytest.mark.parametrize("word", ["discovery", "Discoveries", "confirmed", "Found", "a new ring"])
def test_our_own_wording_refuses_ruled_out_words(word):
    with pytest.raises(ValueError, match="ruled-out"):
        cb.refuse_ruled_out(f"<p>This is {word}.</p>")


def test_words_marked_as_given_and_harmless_neighbours_pass():
    cb.refuse_ruled_out('<blockquote class="as-given">a new confirmed discovery</blockquote><p>renewed, profound</p>')
    cb.refuse_ruled_out(cb.as_given("NEW 1"))


def summary():
    c = {"called": 3, "n": 18, "wilson_95": [0.06, 0.39]}
    other = {cb.CANDIDATE: 108, cb.SECOND_LOOK: 24, cb.KNOWN: 61, cb.NOT_ASSESSED: 266, cb.NO_VERDICT: 733}
    return {
        "folder": "docs/reports/x",
        "report_name": "x",
        "list": {"rows": 1200, "voted": 934, "ring_like": {"called": 200, "n": 934, "wilson_95": [0.1, 0.2]}},
        "verdicts": {"other_rows": other},
        "class_reading": {
            "candidate_rows_with_a_named_class": 60,
            "candidate_rows_with_no_named_class": 48,
            "candidate_rows_by_class": {"radio_galaxy": 50},
        },
        "objects": {"board_rows": 132, "board_objects": 130},
        "circles": {k: c for k in ("on_list", "one_vote", "left", "candidate", "candidate_with_no_named_class")},
        "circles_lost_at": dict.fromkeys(cb.LOST_STAGES, 1),
        "published_positions_removed": 2,
        "cost": {"stop_usd": 36.0, "ledger_usd": 35.971},
    }


def card():
    row = vote("list-0001", 1)
    return {
        "id": "list-0001",
        "verdict": cb.CANDIDATE,
        "name": "ILTJ1",
        "ra": 1.0,
        "dec": 2.0,
        "ring_arcsec": 60.0,
        "linked": [],
        "named_classes": [],
        "image_6": "images/list-0001-6.png",
        "image_20": "images/list-0001-20.png",
        "beam_6": 6.0,
        "first": row,
        "second": None,
        "cone": [{"main_id": "NEW 1 <x>", "otype": "G"}],
        "neighbour": None,
        "depth": 2.5,
        "threshold": 3.75,
        "peak_over_noise": 20.0,
    }


def test_a_card_has_both_maps_votes_and_the_cross_match_and_escapes_what_it_was_given():
    text = cb.render_board(summary(), [card()])
    assert "images/list-0001-6.png" in text
    assert "images/list-0001-20.png" in text
    assert "Vote 2: not asked" in text
    assert "A &lt;b&gt;round&lt;/b&gt; shell" in text
    assert "NEW 1 &lt;x&gt;" in text
    assert "Candidate is a screening grade" in text
    assert "lofar-surveys.org/credits.html" in text
    assert "108" in text


def test_a_ruled_out_word_in_a_rows_own_fields_stops_the_page():
    bad = card() | {"verdict": "confirmed"}
    with pytest.raises(ValueError, match="ruled-out"):
        cb.render_board(summary(), [bad])


def test_the_readme_section_comes_from_the_summary_and_needs_its_markers():
    section = cb.results_section(summary())
    assert "3 of 18 (95 percent interval 0.06 to 0.39)" in section
    assert "| candidate | 108 |" in section
    assert "Candidate is a screening grade" in section
    readme = f"before\n{cb.RESULTS_START}\nold 999\n{cb.RESULTS_END}\nafter\n"
    out = cb.with_results(readme, section)
    assert out.startswith("before\n") and out.endswith("after\n") and "old 999" not in out
    with pytest.raises(ValueError, match="no results markers"):
        cb.with_results("no markers here", section)


def test_an_uncommitted_rule_would_refuse(tmp_path):
    assert not committed_unchanged(tmp_path / "unknown.md")
