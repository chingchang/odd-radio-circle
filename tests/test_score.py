import pytest

from probe.score import confusion_table, score, wilson


def test_wilson_known_values():
    assert wilson(8, 10) == pytest.approx((0.4902, 0.9433), abs=1e-4)
    assert wilson(32, 40) == pytest.approx((0.6524, 0.8951), abs=1e-3)


def test_wilson_edges():
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-4)
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and lo == pytest.approx(0.7225, abs=1e-4)


def test_score_and_confusion():
    r = score(["a", "a", "b", "b"], ["a", "b", "b", "no_answer"])
    assert (r["correct"], r["n"], r["accuracy"]) == (2, 4, 0.5)
    assert r["confusion"]["a"] == {"a": 1, "b": 1, "no_answer": 0}
    assert r["confusion"]["b"] == {"a": 0, "b": 1, "no_answer": 1}
    assert r["per_label"]["a"]["accuracy"] == 0.5
    assert confusion_table(r).splitlines()[0] == "| label | a | b | no_answer |"
    assert confusion_table(r).splitlines()[3] == "| b | 0 | 1 | 1 |"


def test_only_labels_keeps_a_wrong_class_as_wrong():
    r = score(["ring", "galaxy", "other"], ["ring", "other", "other"], only_labels=("ring", "galaxy"))
    assert (r["correct"], r["n"]) == (1, 2)
    assert r["labels"] == ["galaxy", "ring"]
    assert r["confusion"]["galaxy"]["other"] == 1


def test_mismatched_lengths_refused():
    with pytest.raises(ValueError):
        score(["a"], [])
