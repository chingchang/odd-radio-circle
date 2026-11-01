import json

import pytest

from scripts import probe_report


def write_run(root, rows):
    (root / "real").mkdir(parents=True)
    (root / "real" / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (root / "real" / "score.json").write_text("{}\n")


def test_wrong_lists_only_the_wrong_answers(tmp_path):
    out, folder = tmp_path / "out", tmp_path / "report"
    root = out / "radio_ring"
    root.mkdir(parents=True)
    records = [{"id": i, "group": "circle"} for i in ("a", "b")]
    (root / "items.json").write_text(json.dumps(records))
    (out / "ledger.json").write_text("{}\n")
    write_run(
        root,
        [
            {"item_id": "a", "label": "ring_like", "prediction": "ring_like", "answer": {"reason": "a clear ring"}},
            {"item_id": "b", "label": "ring_like", "prediction": "not_ring_like", "answer": {"reason": "too | faint"}},
        ],
    )
    assert probe_report.main(["radio_ring", str(folder), "--out-root", str(out)]) == 0
    wrong = (folder / "wrong.md").read_text()
    assert "too / faint" in wrong and "a clear ring" not in wrong
    assert len(json.loads((folder / "answers.json").read_text())) == 2
    assert (folder / "real" / "score.json").exists()


def test_a_failed_call_is_listed_with_its_error(tmp_path):
    out, folder = tmp_path / "out", tmp_path / "report"
    root = out / "radio_ring"
    root.mkdir(parents=True)
    (root / "items.json").write_text(json.dumps([{"id": "a", "group": "random"}]))
    (out / "ledger.json").write_text("{}\n")
    write_run(root, [{"item_id": "a", "label": "not_ring_like", "prediction": "no_answer", "error": "timed out"}])
    assert probe_report.main(["radio_ring", str(folder), "--out-root", str(out)]) == 0
    assert "| a | random | not_ring_like | no_answer | timed out |" in (folder / "wrong.md").read_text()


@pytest.mark.parametrize("removed", ["tess", "video"])
def test_a_removed_probe_is_refused(tmp_path, removed):
    with pytest.raises(SystemExit):
        probe_report.main([removed, str(tmp_path / "report"), "--out-root", str(tmp_path)])
