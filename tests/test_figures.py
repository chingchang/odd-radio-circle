import json
import re
from pathlib import Path

import pytest
from PIL import Image

from probe import case_board as cb
from probe import figures as fg
from scripts import readme_figures as runner

REPORT = runner.REPORT


def row(id_, verdict, classes=(), circle=None):
    return {"id": id_, "known_circle": circle, "verdict": verdict, "removed_by": [], "named_classes": list(classes)}


def maps(folder: Path, stems):
    folder.mkdir(parents=True, exist_ok=True)
    for stem in stems:
        for kind in ("6", "20"):
            Image.new("RGB", (720, 720), "black").save(folder / f"{stem}-{kind}.png")


def test_groups_put_each_row_on_one_panel_by_verdict_and_class(tmp_path):
    maps(tmp_path, ["tuning-J0001+0001", "heldout-J0002+0002"])
    verdicts = [
        row("list-0002", cb.CANDIDATE, ["radio_galaxy"]),
        row("list-0001", cb.CANDIDATE),
        row("list-0003", cb.SECOND_LOOK),
        row("list-0004", cb.KNOWN),
        row("list-0005", cb.NOT_ASSESSED),
        row("list-0006", cb.CANDIDATE, ["planetary_nebula", "odd_class"]),
        row("list-0007", cb.CANDIDATE, ["planetary_nebula"], circle="J0001+0001"),
        row("list-0008", cb.SECOND_LOOK, [], circle="J0001+0001"),
        row("list-0009", cb.SECOND_LOOK, ["radio_galaxy"], circle="J0002+0002"),
    ]
    parts = fg.groups(verdicts, tmp_path)
    assert [r["label"] for r in parts["plain"]] == ["list-0001"]
    assert [r["label"] for r in parts["named"]] == ["list-0006 PN odd_class", "list-0002 RG"]
    assert [r["label"] for r in parts["second"]] == ["list-0003"]
    assert parts["circles"] == [
        {"id": "tuning-J0001+0001", "label": "J0001+0001 candidate"},
        {"id": "heldout-J0002+0002", "label": "J0002+0002 needs second look"},
    ]
    everywhere = [r["id"] for key in ("plain", "named", "second") for r in parts[key]]
    assert "list-0004" not in everywhere and "list-0005" not in everywhere
    assert not {"list-0007", "list-0008", "list-0009"} & set(everywhere)


def test_a_circle_without_a_map_at_its_published_position_stops_the_run(tmp_path):
    maps(tmp_path, [])
    with pytest.raises(FileNotFoundError, match="one expected"):
        fg.groups([row("list-0001", cb.CANDIDATE, circle="J0001+0001")], tmp_path)


def test_a_panel_has_a_tile_under_a_caption_for_every_map(tmp_path):
    maps(tmp_path, ["a", "b", "c"])
    tiles = [(tmp_path / f"{s}-6.png", s) for s in "abc"]
    image = fg.panel(tiles, columns=2, side=100)
    assert image.size == fg.panel_size(3, 2, 100) == (200, 2 * (100 + fg.CAPTION))
    assert fg.panel_size(0, 5, 10) == (50, 10 + fg.CAPTION)


def spec(plain=2, named=3, second=1, circles=("candidate", "needs second look")):
    return {
        "plain": {"rows": [{"id": f"p{i}", "label": f"p{i}"} for i in range(plain)]},
        "named": {"rows": [{"id": f"n{i}", "label": f"n{i} RG"} for i in range(named)]},
        "second": {"rows": [{"id": f"s{i}", "label": f"s{i}"} for i in range(second)]},
        "circles": {"rows": [{"id": f"c{i}", "label": f"J000{i}+0000 {v}"} for i, v in enumerate(circles)]},
    }


def summary(candidate=5, plain=2, second=1, left=2, at_candidate=1):
    return {
        "folder": "docs/reports/x",
        "verdicts": {"other_rows": {cb.CANDIDATE: candidate, cb.SECOND_LOOK: second}},
        "class_reading": {
            "candidate_rows_with_no_named_class": plain,
            "candidate_rows_with_a_named_class": candidate - plain,
            "candidate_rows_by_class": {"radio_galaxy": 3},
        },
        "circles": {"left": {"called": left}, "candidate": {"called": at_candidate}},
        "circles_lost_at": {"pre-filter": 12, "first vote": 1, "known-object cut": 0},
    }


@pytest.mark.parametrize(
    ("wrong", "message"),
    [
        (dict(candidate=6), "candidates with a named class"),
        (dict(plain=3), "no named class"),
        (dict(second=2), "needs second look"),
        (dict(left=3), "circles on the board"),
        (dict(at_candidate=2), "circles at candidate grade"),
    ],
)
def test_a_panel_that_disagrees_with_the_summary_stops_the_section(wrong, message):
    with pytest.raises(ValueError, match=message):
        fg.figures_section(summary(**wrong), spec())


def test_the_section_counts_from_the_panels_and_needs_its_markers():
    full = {k: v | {"file": f"figures/{k}.png"} for k, v in spec().items()}
    section = fg.figures_section(summary(), full)
    assert "The 2 candidate rows, of 5, with no class" in section
    assert "The other 3 candidate rows" in section and "3 rows carry RG" in section
    assert "The 1 needs second look rows" in section
    assert "The 2 known circles, of 18" in section and "1 at candidate grade and\n1 at needs second look" in section
    assert "The other 13 ended before the board,\n12 of them at the pre-filter" in section
    assert not cb.RULED_OUT.search(section)
    readme = f"a\n{fg.FIGURES_START}\nstale 999\n{fg.FIGURES_END}\nb\n"
    out = fg.with_figures(readme, section)
    assert out.startswith("a\n") and out.endswith("b\n") and "stale 999" not in out
    with pytest.raises(ValueError, match="no figures markers"):
        fg.with_figures("no markers", section)


def committed():
    read = lambda name: json.loads((REPORT / name).read_text())  # noqa: E731
    return read("summary.json"), read("verdicts.json"), fg.read_spec(REPORT)


def test_the_committed_panels_hold_the_committed_verdicts_rows():
    _, verdicts, spec_file = committed()
    parts = fg.groups(verdicts, REPORT / "images")
    for key, part in spec_file.items():
        assert part["rows"] == parts[key]
        count = len(part["rows"]) * (2 if key == "circles" else 1)
        assert Image.open(REPORT / part["file"]).size == fg.panel_size(count, part["columns"], part["tile"])
        for r in part["rows"]:
            assert (REPORT / "images" / f"{r['id']}-6.png").exists()
    others = [v for v in verdicts if not v["known_circle"]]
    plain = {v["id"] for v in others if v["verdict"] == cb.CANDIDATE and not v["named_classes"]}
    assert {r["id"] for r in spec_file["plain"]["rows"]} == plain


def test_the_readme_figures_are_the_ones_the_runner_wrote():
    summary_file, _, spec_file = committed()
    text = runner.README.read_text()
    section = fg.figures_section(summary_file, spec_file)
    assert section in text
    for name in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", section):
        assert Path(name).exists()
