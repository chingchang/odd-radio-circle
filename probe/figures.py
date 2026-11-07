"""Figures for the README: the board's rows as pictures, grouped by the verdict the board gave them.

Nothing here grades a row. The groups are read from ``verdicts.json`` and the maps are the board's own copies, which
are the bytes the model saw. The README's figures section is rendered from the same files, so every count in it comes
from a file a runner wrote, and the runner stops if those counts disagree with ``summary.json``. For people only: the
panels carry row ids and circle names and are never sent to a model.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from probe import case_board as cb

FIGURES_START = "<!-- figures: written by scripts/readme_figures.py from verdicts.json and summary.json -->"
FIGURES_END = "<!-- end of figures -->"
FOLDER = "figures"
CAPTION = 18
BACKGROUND, INK = "#202020", "white"
SHORT = {"radio_galaxy": "RG", "planetary_nebula": "PN", "supernova_remnant": "SNR"}
RANK = {cb.CANDIDATE: 0, cb.SECOND_LOOK: 1}  # the better verdict of a circle's rows is the circle's

# Each figure: file stem, columns and tile side in pixels. Fixed here so a rerun draws the same panels.
PLAIN = ("candidates_no_named_class", 5, 288)
NAMED = ("candidates_named_class", 9, 160)
SECOND = ("needs_second_look", 6, 240)
CIRCLES = ("known_circles_on_the_board", 5, 288)


def short_class(name: str) -> str:
    return SHORT.get(name, name)


def groups(verdicts: list[dict], images: Path) -> dict[str, list[dict]]:
    """The rows of each panel, in a fixed order: id for the board's rows, name for the circles. Known circles' rows are
    never on a candidate panel; a row is on one panel at most."""
    others = [v for v in verdicts if not v["known_circle"]]
    candidates = [v for v in others if v["verdict"] == cb.CANDIDATE]
    by_id = sorted(candidates, key=lambda v: v["id"])
    plain = [{"id": v["id"], "label": v["id"]} for v in by_id if not v["named_classes"]]
    named = [
        {"id": v["id"], "label": f"{v['id']} {' '.join(short_class(c) for c in v['named_classes'])}"}
        for v in sorted(candidates, key=lambda v: (sorted(v["named_classes"]), v["id"]))
        if v["named_classes"]
    ]
    second = [
        {"id": v["id"], "label": v["id"]}
        for v in sorted(others, key=lambda v: v["id"])
        if v["verdict"] == cb.SECOND_LOOK
    ]
    best: dict[str, str] = {}
    for v in verdicts:
        name, current = v["known_circle"], best.get(v["known_circle"])
        if name and v["verdict"] in RANK and (current is None or RANK[v["verdict"]] < RANK[current]):
            best[name] = v["verdict"]
    circles = []
    for name in sorted(best):
        stems = sorted(p.name[: -len("-6.png")] for p in images.glob(f"*-{name}-6.png"))
        if len(stems) != 1:
            raise FileNotFoundError(f"{name}: {len(stems)} maps at the published position, one expected")
        circles.append({"id": stems[0], "label": f"{name} {best[name]}"})
    return {"plain": plain, "named": named, "second": second, "circles": circles}


def panel(tiles: list[tuple[Path, str]], columns: int, side: int) -> Image.Image:
    """A grid of maps, each under its label. Rows follow from the count."""
    rows = max(1, -(-len(tiles) // columns))
    sheet = Image.new("RGB", (columns * side, rows * (side + CAPTION)), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=max(10, side // 20))
    for i, (path, label) in enumerate(tiles):
        x, y = (i % columns) * side, (i // columns) * (side + CAPTION)
        sheet.paste(Image.open(path).resize((side, side), Image.LANCZOS), (x, y + CAPTION))
        draw.text((x + 3, y + 2), label, fill=INK, font=font)
    return sheet


def panel_size(count: int, columns: int, side: int) -> tuple[int, int]:
    return columns * side, max(1, -(-count // columns)) * (side + CAPTION)


def draw_figures(report: Path, verdicts: list[dict]) -> dict:
    """Writes the four panels under the report's figures folder and returns what each shows, to be checked and kept."""
    images, out = report / "images", report / FOLDER
    out.mkdir(exist_ok=True)
    parts = groups(verdicts, images)
    spec = {}
    for key, (stem, columns, side), kinds in (
        ("plain", PLAIN, ("6",)),
        ("named", NAMED, ("6",)),
        ("second", SECOND, ("6",)),
        ("circles", CIRCLES, ("6", "20")),
    ):
        tiles = []
        for kind in kinds:
            tiles += [(images / f"{row['id']}-{kind}.png", row["label"]) for row in parts[key]]
        image = panel(tiles, columns, side)
        image.save(out / f"{stem}.png")
        spec[key] = {"file": f"{FOLDER}/{stem}.png", "columns": columns, "tile": side, "rows": parts[key]}
    return spec


def check_against_summary(spec: dict, summary: dict) -> None:
    """Stop if the panels do not hold what the summary counts."""
    other, reading, circles = summary["verdicts"]["other_rows"], summary["class_reading"], summary["circles"]
    pairs = [
        ("candidates with no named class", len(spec["plain"]["rows"]), reading["candidate_rows_with_no_named_class"]),
        ("candidates with a named class", len(spec["named"]["rows"]), reading["candidate_rows_with_a_named_class"]),
        ("candidates", len(spec["plain"]["rows"]) + len(spec["named"]["rows"]), other[cb.CANDIDATE]),
        ("needs second look", len(spec["second"]["rows"]), other[cb.SECOND_LOOK]),
        ("circles on the board", len(spec["circles"]["rows"]), circles["left"]["called"]),
        (
            "circles at candidate grade",
            sum(r["label"].endswith(cb.CANDIDATE) for r in spec["circles"]["rows"]),
            circles["candidate"]["called"],
        ),
    ]
    wrong = [f"{name}: {a} on the panel, {b} in the summary" for name, a, b in pairs if a != b]
    if wrong:
        raise ValueError("; ".join(wrong))


def figures_section(summary: dict, spec: dict) -> str:
    """The README's figures, every count from the summary and the panels, checked against each other first."""
    check_against_summary(spec, summary)
    folder = summary["folder"]
    other, circles, lost = summary["verdicts"]["other_rows"], summary["circles"], summary["circles_lost_at"]
    plain, named = len(spec["plain"]["rows"]), len(spec["named"]["rows"])
    second, on_board = len(spec["second"]["rows"]), len(spec["circles"]["rows"])
    at_candidate = circles["candidate"]["called"]
    jets = summary["class_reading"]["candidate_rows_by_class"].get("radio_galaxy", 0)
    text = f"""{FIGURES_START}
**The rows the search left, as pictures.** Each tile is a reduced copy of the LoTSS DR3 map Wonder voted on, 6 arcmin
on a side at the 6 arcsec resolution, labelled with the row's id on the [case board]({folder}/board.html), where the
full-size maps at both resolutions, the votes, reasons and cross-match are. {cb.CAVEAT} Nothing in these figures has
been followed up at other wavelengths.

**Figure 1. The {plain} candidate rows, of {other[cb.CANDIDATE]}, with no class Wonder named on either vote.** These
have the least against them: the code checks passed, two ring-like votes, and no class named. The report's reading of
this panel by eye, which grades nothing, is that many are filled discs or bent doubles rather than rings, and a few have
open or edge-bright shapes.

![The candidate rows with no class named]({folder}/{spec['plain']['file']})

**Figure 2. The other {named} candidate rows, with the class Wonder named on a vote** (RG radio galaxy, PN planetary
nebula, SNR supernova remnant; {jets} rows carry RG). A named class moves no verdict under the board's rule. It is shown
because it is the main reason to doubt the row.

![The candidate rows with a class named]({folder}/{spec['named']['file']})

**Figure 3. The {second} needs second look rows.** The code checks passed and the first vote was ring-like, and the
second vote was not ring-like or did not arrive. A real ring that Wonder doubted once would sit here.

![The needs second look rows]({folder}/{spec['second']['file']})

**Figure 4. The {on_board} known circles, of 18, that reached the board,** with the 6 arcsec map (top) and the 20 arcsec
map (bottom) at the published position, and the grade their rows took: {at_candidate} at candidate grade and
{on_board - at_candidate} at needs second look. They are the control for the grade, and the only published rings on
these pages. The other {lost['pre-filter'] + lost['first vote'] + lost['known-object cut']} ended before the board,
{lost['pre-filter']} of them at the pre-filter; the [circles page]({folder}/circles.html) shows each.

![The known circles that reached the board]({folder}/{spec['circles']['file']})

Figures drawn by `scripts/readme_figures.py` from `{folder}/verdicts.json` and the board's maps; what each panel holds
is in `{folder}/{FOLDER}/figures.json`.
{FIGURES_END}"""
    cb.refuse_ruled_out(text)
    return text


def with_figures(readme: str, section: str) -> str:
    """The README with its figures replaced. Refuses a README with no markers instead of writing somewhere else."""
    start, end = readme.find(FIGURES_START), readme.find(FIGURES_END)
    if start < 0 or end < start:
        raise ValueError("the README has no figures markers")
    return readme[:start] + section + readme[end + len(FIGURES_END) :]


def read_spec(report: Path) -> dict:
    return json.loads((report / FOLDER / "figures.json").read_text())
