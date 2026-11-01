import json

from scripts import probe_report


def write_run(root, rows):
    (root / "real").mkdir(parents=True)
    (root / "real" / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (root / "real" / "score.json").write_text("{}\n")


def test_wrong_lists_only_what_the_bar_counts_and_copies_those_sheets(tmp_path):
    out, folder = tmp_path / "out", tmp_path / "report"
    root = out / "tess"
    (root / "sheets").mkdir(parents=True)
    records = []
    for i in ("a", "b", "c"):
        (root / "sheets" / f"{i}.png").write_bytes(b"x")
        records.append({"id": i, "sheet": f"sheets/{i}.png"})
    (root / "items.json").write_text(json.dumps(records))
    (out / "ledger.json").write_text("{}\n")
    write_run(
        root,
        [
            {"item_id": "a", "label": "planet", "prediction": "planet", "answer": {"reason": "fine"}},
            {"item_id": "b", "label": "planet", "prediction": "eclipsing_binary", "answer": {"reason": "too | deep"}},
            {"item_id": "c", "label": "false_alarm", "prediction": "planet", "answer": {"reason": "not on the bar"}},
        ],
    )
    assert probe_report.main(["tess", str(folder), "--out-root", str(out)]) == 0
    wrong = (folder / "wrong.md").read_text()
    assert "too / deep" in wrong and "not on the bar" not in wrong
    assert [p.name for p in (folder / "wrong_sheets").iterdir()] == ["b.png"]
    assert len(json.loads((folder / "answers.json").read_text())) == 3
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
