"""The case board: the grade, its counts and the static pages. The rule is written in docs/proposals/case-board-v1.md;
this is that rule in code. ``scripts/case_board.py`` runs it. No model is called and nothing here reaches one.

``verdict`` is the only place a verdict is assigned. Pages and the README's results section are rendered from the
summary alone, so a number on them cannot differ from the file.
"""

from __future__ import annotations

import hashlib
import html
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from probe import known_cut as kc
from probe import screen as sc
from probe.baselines import count

CANDIDATE, SECOND_LOOK, KNOWN, NOT_ASSESSED = "candidate", "needs second look", "likely known class", "not assessed"
VERDICTS = (CANDIDATE, SECOND_LOOK, KNOWN, NOT_ASSESSED)
NO_VERDICT = "no verdict"  # a counted row with a not-ring-like first vote; the word is never given to a row
NO_CLASS = "no_known_class"
LOST_STAGES = ("pre-filter", "first vote", "known-object cut", "second vote", "kept to candidate grade")
RULED_OUT = re.compile(r"\b(discover\w*|confirm\w*|found|new)\b", re.I)
AS_GIVEN = re.compile(r'<(blockquote|span) class="as-given">.*?</\1>', re.S)
RESULTS_START = "<!-- results: written by scripts/case_board.py from its summary.json -->"
RESULTS_END = "<!-- end of results -->"
CAVEAT = (
    "Candidate is a screening grade. It says the code checks passed and Wonder called the row ring-like twice. "
    "It does not say the row is a ring."
)
CREDIT = (
    "LoTSS DR3: Shimwell et al. 2026, A&amp;A 707, A198, with the acknowledgements at "
    '<a href="https://www.lofar-surveys.org/credits.html">lofar-surveys.org/credits.html</a>. '
    "Known circles: De Gasperin et al. 2026 (arXiv:2602.18294). SIMBAD: Wenger et al. 2000, A&amp;AS 143, 9."
)
STYLE = """
body { font: 15px/1.45 system-ui, sans-serif; margin: 1.5rem auto; max-width: 70rem; padding: 0 1rem; }
table { border-collapse: collapse; margin: 0.75rem 0; }
th, td { border: 1px solid #8888; padding: 0.25rem 0.5rem; text-align: left; vertical-align: top; }
article { border-top: 2px solid #8888; margin-top: 1.5rem; padding-top: 0.5rem; }
figure { display: inline-block; margin: 0 0.75rem 0.5rem 0; }
img { height: auto; max-width: 100%; width: 320px; }
blockquote { border-left: 3px solid #8888; margin: 0.25rem 0 0.5rem; padding-left: 0.75rem; }
.verdict { font-weight: 600; }
.caveat { border: 1px solid #8888; padding: 0.5rem 0.75rem; }
"""


def verdict(first: dict | None, second: dict | None, removed_by: list[str]) -> str | None:
    """The grade. A vote can lower it and never raise it: nothing here lifts a row a cut removed."""
    if not sc.valid(first):
        return NOT_ASSESSED
    if not sc.called(first):
        return None
    if removed_by:
        return KNOWN
    return CANDIDATE if sc.called(second) else SECOND_LOOK


def named_classes(*votes: dict | None) -> list[str]:
    """Classes Wonder named on these votes, other than none. Read to describe rows; no verdict depends on it."""
    names = {v["answer"]["known_class"] for v in votes if sc.valid(v)}
    return sorted(names - {NO_CLASS})


def graded(records: list[dict], rows: dict[str, dict], votes: dict) -> dict[str, dict]:
    """Every listed row with its verdict. ``rows`` are the cut's rows, by id; a row not there was not ring-like or was
    not reached, so no cut has read it."""
    out = {}
    for record in records:
        first, second = votes.get((record["id"], sc.FIRST)), votes.get((record["id"], sc.SECOND))
        row = rows.get(record["id"], {})
        if sc.called(first) and record["id"] not in rows:
            raise ValueError(f"{record['id']} has a ring-like first vote and no row from the cuts")
        out[record["id"]] = {
            "id": record["id"],
            "known_circle": record.get("known_circle"),
            "verdict": verdict(first, second, row.get("removed_by", [])),
            "removed_by": row.get("removed_by", []),
            "named_classes": named_classes(first, second),
        }
    return out


def board_rows(grades: dict[str, dict]) -> list[dict]:
    """Rows on the board, in its order: candidates with no named class, candidates with one, then the rest."""
    chosen = [g for g in grades.values() if g["verdict"] in (CANDIDATE, SECOND_LOOK) and not g["known_circle"]]
    return sorted(chosen, key=lambda g: (VERDICTS.index(g["verdict"]), bool(g["named_classes"]), g["id"]))


def verdict_counts(grades: list[dict]) -> dict[str, int]:
    tally = dict.fromkeys((*VERDICTS, NO_VERDICT), 0)
    for g in grades:
        tally[g["verdict"] or NO_VERDICT] += 1
    return tally


def linked_rows(rows: list[dict]) -> dict[str, list[str]]:
    """For each row, the others within the screen's 3 arcmin, as objects are linked."""
    groups = kc.link_objects(rows)
    return {member: [other for other in group if other != member] for group in groups for member in group}


def lost_at(ids: list[str], grades: dict[str, dict]) -> str:
    """The stage that ended a known circle, from the verdicts on its listed rows."""
    seen = {grades[i]["verdict"] for i in ids}
    if not ids:
        return "pre-filter"
    if CANDIDATE in seen:
        return "kept to candidate grade"
    if SECOND_LOOK in seen:
        return "second vote"
    if KNOWN in seen:
        return "known-object cut"
    return "first vote"


def copy_checked(source: Path, target: Path, sha256: str | None = None) -> int:
    """Copy a map byte for byte. If a vote's digest is given and differs, stop: the board shows what was voted on."""
    data = source.read_bytes()
    if sha256 is not None and hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError(f"{source} is not the image the vote recorded")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return len(data)


def refuse_ruled_out(text: str) -> None:
    """Stop on a word the project rules out in our own wording. Text marked as given is the model's or SIMBAD's."""
    hit = RULED_OUT.search(re.sub(r"<[^>]+>", " ", AS_GIVEN.sub(" ", text)))
    if hit:
        raise ValueError(f"ruled-out word in a page: {hit.group(0)!r}")


def e(value) -> str:
    return html.escape(str(value))


def as_given(value) -> str:
    return f'<span class="as-given">{e(value)}</span>'


def two_places(value: float) -> str:
    """Half up from the stored four places, so 0.125 reads 0.13 as the earlier reports have it."""
    return str(Decimal(str(value)).quantize(Decimal("0.01"), ROUND_HALF_UP))


def share(c: dict) -> str:
    low, high = c["wilson_95"]
    return f"{c['called']} of {c['n']} (95 percent interval {two_places(low)} to {two_places(high)})"


def page(title: str, nav: str, body: str) -> str:
    text = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title><style>{STYLE}</style></head><body>
<h1>{e(title)}</h1><p>{nav}</p>
<p class="caveat">{CAVEAT}</p>
{body}
<footer><p>{CREDIT}</p></footer></body></html>
"""
    refuse_ruled_out(text)
    return text


def _figure(path: str, caption: str) -> str:
    alt = e(caption)
    return f'<figure><img src="{e(path)}" alt="{alt}" loading="lazy"><figcaption>{alt}</figcaption></figure>'


def _vote(number: int, vote: dict | None) -> str:
    if vote is None:
        return f"<p>Vote {number}: not asked, or no answer.</p>"
    answer = vote["answer"]
    return (
        f"<p>Vote {number}: {e(vote['prediction'])}, class {e(answer['known_class'])}. Wonder's reason, as given:</p>"
        f'<blockquote class="as-given">{e(answer["reason"])}</blockquote>'
    )


def _cross_match(card: dict) -> str:
    cuts = ", ".join(c.replace("_", " ") for c in kc.CUTS)
    cone = card["cone"]
    objects = "; ".join(f"{as_given(o['main_id'])} ({as_given(o['otype'])})" for o in cone) or "none"
    neighbour = card["neighbour"]
    bright = "none listed"
    if neighbour:
        bright = f"{neighbour['total_flux_mjy']:.0f} mJy at {neighbour['arcmin_away']:.1f} arcmin"
    no_size = "; ".join(as_given(o["main_id"]) for o in card["found"]["galaxy_no_size"]) or "none"
    half = "; ".join(as_given(o["main_id"]) for o in card["found"]["galaxy_above_half_the_ring"]) or "none"
    deep = ""
    if card["deep_with_no_bright_source"]:
        deep = " Deep enough for the cut, but with no bright source, so it is left."
    return (
        f"<p>Cross-match: no cut removes this row ({e(cuts)}). SIMBAD objects within 1 arcmin: {objects}. "
        f"Of those, galaxies with no listed size, which remove nothing: {no_size}. Galaxies above half the ring's size "
        f"and not above it, which remove nothing: {half}.</p>"
        f"<p>Negative depth {card['depth']:.2f}, cut at {card['threshold']:.2f} with a bright source; peak "
        f"{card['peak_over_noise']:.1f} times the noise; brightest neighbour within 30 arcmin of at least 1 Jy: "
        f"{e(bright)}.{deep}</p>"
    )


def _card(card: dict) -> str:
    linked = ", ".join(f'<a href="#{e(i)}">{e(i)}</a>' for i in card["linked"]) or "none"
    classes = ", ".join(card["named_classes"]) or "none"
    return f"""<article id="{e(card['id'])}">
<h3>{e(card['id'])}: <span class="verdict">{e(card['verdict'])}</span></h3>
<p>{e(card['name'])}, RA {card['ra']:.4f}, Dec {card['dec']:.4f}. Catalogue major axis {card['ring_arcsec']:.0f} arcsec.
Other board rows within 3 arcmin: {linked}. Classes Wonder named: {e(classes)}.</p>
{_figure(card['image_6'], f"fine map, 6 arcmin across, beam {card['beam_6']:.0f} arcsec")}
{_figure(card['image_20'], "20 arcsec map, 6 arcmin across")}
{_vote(1, card['first'])}{_vote(2, card['second'])}{_cross_match(card)}
</article>"""


def render_board(summary: dict, cards: list[dict]) -> str:
    other = summary["verdicts"]["other_rows"]
    reading = summary["class_reading"]
    listed, objects = summary["list"], summary["objects"]
    named = reading["candidate_rows_with_a_named_class"]
    jets = reading["candidate_rows_by_class"].get("radio_galaxy", 0)
    plain = reading["candidate_rows_with_no_named_class"]
    head = f"""<p>Of the {listed['rows']} rows on the pre-filter list, {listed['voted']} have a Wonder vote
and {other[NOT_ASSESSED]} other rows are not assessed. These counts are rows and leave out known circles' rows, which
are on the <a href="circles.html">circles page</a>.</p>
<table><tr><th>verdict</th><th>other rows</th><th>on this board</th></tr>
<tr><td>candidate</td><td>{other[CANDIDATE]}</td><td>yes</td></tr>
<tr><td>needs second look</td><td>{other[SECOND_LOOK]}</td><td>yes</td></tr>
<tr><td>likely known class</td><td>{other[KNOWN]}</td><td>no; see verdicts.json</td></tr>
<tr><td>not assessed</td><td>{other[NOT_ASSESSED]}</td><td>no</td></tr>
<tr><td>first vote not ring-like, no verdict</td><td>{other[NO_VERDICT]}</td><td>no</td></tr></table>
<p><strong>Most candidates may not be rings.</strong> No cut looks for radio galaxies. Of the {other[CANDIDATE]}
candidate rows, {named} carry a class Wonder named on a vote, {jets} of them radio_galaxy; those sort after the {plain}
with none. Wonder's class moves no verdict here. The {objects['board_rows']} rows on this board are
{objects['board_objects']} objects when rows within 3 arcmin are linked. These maps went to Wonder with no name,
position or survey; those shown here are for people. Wonder's reasons are shown as given and are not evidence: Wonder
saw two images and nothing else, so a reason that cites other surveys, spectra or the literature is invented.</p>"""
    nav = '<a href="circles.html">The 18 known circles</a>'
    return page("Case board", nav, head + "\n" + "\n".join(map(_card, cards)))


def _rows_cell(rows: list[dict]) -> str:
    if not rows:
        return "none"
    parts = []
    for r in rows:
        second = r["second"] or "not asked"
        parts.append(f"{e(r['id'])}: {e(r['first'])}; {e(second)}; verdict {e(r['verdict'] or 'none')}")
    return "<br>".join(parts)


def _circle_card(circle: dict) -> str:
    reasons = "".join(
        f"<p>{e(r['id'])}, first vote, Wonder's reason, as given:</p>"
        f'<blockquote class="as-given">{e(r["reason"])}</blockquote>'
        for r in circle["rows"]
    )
    return f"""<article id="{e(circle['name'])}">
<h3>{e(circle['name'])}: {e(circle['lost_at'])}</h3>
{_figure(circle['image_6'], "fine map at the published position, 6 arcmin across")}
{_figure(circle['image_20'], "20 arcsec map at the published position, 6 arcmin across")}
{reasons}
</article>"""


def render_circles(summary: dict, circles: list[dict]) -> str:
    c = summary["circles"]
    stages = "".join(f"<tr><td>{e(s)}</td><td>{summary['circles_lost_at'][s]}</td></tr>" for s in LOST_STAGES)
    rows = "".join(
        f"<tr><td><a href=\"#{e(o['name'])}\">{e(o['name'])}</a></td><td>{e(o['group'])}</td>"
        f"<td>{e(o['earlier_call'])}</td><td>{e(o['prefilter'])}</td>"
        f"<td>{'called' if o['annulus_tuned'] else 'not called'}</td><td>{_rows_cell(o['rows'])}</td>"
        f"<td>{e(', '.join(o['removed_at_published']) or 'none')}</td><td>{e(o['lost_at'])}</td></tr>"
        for o in circles
    )
    body = f"""<p>Each circle counts once, and a lost circle counts as a miss. Published positions are in controls/.</p>
<table><tr><th>of the 18 known circles</th><th>count</th></tr>
<tr><td>on the pre-filter list</td><td>{share(c['on_list'])}</td></tr>
<tr><td>and a ring-like first vote</td><td>{share(c['one_vote'])}</td></tr>
<tr><td>and left by the cuts</td><td>{share(c['left'])}</td></tr>
<tr><td>and a row at candidate grade</td><td>{share(c['candidate'])}</td></tr></table>
<table><tr><th>where each ended</th><th>circles</th></tr>{stages}</table>
<p>{summary['published_positions_removed']} of the 18 would be removed by a cut at their published positions, though
neither is on the list. The prompt and the pre-filter were tuned with known circles in view, so these rates are not
blind. At candidate grade: {share(c['tuning_candidate'])} tuning circles, {share(c['heldout_candidate'])} held-out.</p>
<table><tr><th>circle</th><th>group</th><th>earlier call, published position</th><th>pre-filter</th>
<th>tuned annulus, through the list</th><th>listed rows: first vote; second vote; verdict</th>
<th>cuts at the published position</th><th>ended at</th></tr>{rows}</table>
{"".join(map(_circle_card, circles))}"""
    return page("The 18 known circles", '<a href="board.html">Case board</a>', body)


def results_section(summary: dict) -> str:
    """The README's results, every number from the summary."""
    c, other, listed = summary["circles"], summary["verdicts"]["other_rows"], summary["list"]
    reading, objects, cost = summary["class_reading"], summary["objects"], summary["cost"]
    folder = summary["folder"]
    named = reading["candidate_rows_with_a_named_class"]
    jets = reading["candidate_rows_by_class"].get("radio_galaxy", 0)
    plain = reading["candidate_rows_with_no_named_class"]
    ended_early = summary["circles_lost_at"]["pre-filter"]
    circles_now, circles_stricter = c["candidate"]["called"], c["candidate_with_no_named_class"]["called"]
    stop, ledger = f"{cost['stop_usd']:.0f}", f"{cost['ledger_usd']:.2f}"
    text = f"""{RESULTS_START}
**End to end, known circles, each counted once of 18 (95 percent Wilson intervals, from `{folder}/summary.json`):**

| stage | circles |
|---|---|
| on the pre-filter list of {listed['rows']} rows | {share(c['on_list'])} |
| and a ring-like first vote from Wonder | {share(c['one_vote'])} |
| and left by the known-object cuts | {share(c['left'])} |
| and a row at candidate grade (two ring-like votes) | {share(c['candidate'])} |

Most of the loss is at the pre-filter, which ended {ended_early} of the 18. These rates are not blind: the prompt and
the pre-filter's cuts were tuned with known circles in view. At candidate grade, by group:
{share(c['tuning_candidate'])} tuning, {share(c['heldout_candidate'])} held-out. The
[circles page]({folder}/circles.html) shows where each was kept or lost.

**The search, in rows.** The money stopped at the plan's limit of {stop} USD ({ledger} USD on the ledger over all runs),
so Wonder voted on {listed['voted']} of the {listed['rows']} rows, and {listed['ring_like']['called']} of those were
called ring-like. Without known circles' rows:

| verdict | rows |
|---|---|
| candidate | {other[CANDIDATE]} |
| needs second look | {other[SECOND_LOOK]} |
| likely known class | {other[KNOWN]} |
| not assessed | {other[NOT_ASSESSED]} |

A further {other[NO_VERDICT]} other rows had a not-ring-like first vote and take no verdict. The candidate and needs
second look rows are {objects['board_rows']} rows and {objects['board_objects']} objects when rows within 3 arcmin are
linked, and each has its maps, votes and cross-match on the [case board]({folder}/board.html).

**{CAVEAT}** Most candidates may not be rings: no cut looks for radio galaxies, and {named} of the {other[CANDIDATE]}
candidate rows carry a class Wonder named on a vote, {jets} of them radio_galaxy. Had any named class lowered a
candidate, {plain} rows would remain, and known circles at that grade would fall from {circles_now} to
{circles_stricter} of 18. That is a count and moves no verdict. Nothing on the board has been followed up at other
wavelengths.

Sources: `{folder}/summary.json`, `{folder}/verdicts.json`, and the [report](docs/reports/{summary['report_name']}.md).
{RESULTS_END}"""
    refuse_ruled_out(text)
    return text


def with_results(readme: str, section: str) -> str:
    """The README with its results replaced. Refuses a README with no markers instead of writing somewhere else."""
    start, end = readme.find(RESULTS_START), readme.find(RESULTS_END)
    if start < 0 or end < start:
        raise ValueError("the README has no results markers")
    return readme[:start] + section + readme[end + len(RESULTS_END) :]


def counts(grades: dict[str, dict], left_rows: list[dict], circle_rows: dict[str, list[str]], groups: dict) -> dict:
    """Every count of the grade: rows, other rows and known circles' rows apart, and circles as objects."""
    everything = list(grades.values())
    others = [g for g in everything if not g["known_circle"]]
    candidates = [g for g in others if g["verdict"] == CANDIDATE]
    on_board = [r for r in left_rows if grades[r["id"]]["verdict"] in (CANDIDATE, SECOND_LOOK)]
    by_class: dict[str, int] = {}
    for g in candidates:
        for name in g["named_classes"]:
            by_class[name] = by_class.get(name, 0) + 1
    voted_others = sum(g["verdict"] != NOT_ASSESSED for g in others)
    named = sum(bool(g["named_classes"]) for g in candidates)

    def circles_where(test) -> dict:
        return count(sum(any(test(grades[i]) for i in ids) for ids in circle_rows.values()), len(circle_rows))

    def plain(g: dict) -> bool:
        return g["verdict"] == CANDIDATE and not g["named_classes"]

    stages = {stage: 0 for stage in LOST_STAGES}
    for ids in circle_rows.values():
        stages[lost_at(ids, grades)] += 1
    known_candidates = [g for g in everything if g["known_circle"] and g["verdict"] == CANDIDATE]
    return {
        "verdicts": {"other_rows": verdict_counts(others), "known_circle_rows": verdict_counts(
            [g for g in everything if g["known_circle"]]
        )},
        "candidates_of_other_rows_voted": count(len(candidates), voted_others),
        "objects": {
            "board_rows": len(on_board),
            "board_objects": len(kc.link_objects(on_board)),
            "candidate_rows": len(candidates),
            "candidate_objects": len(kc.link_objects([r for r in on_board if grades[r["id"]]["verdict"] == CANDIDATE])),
        },
        "class_reading": {
            "candidate_rows_with_a_named_class": named,
            "candidate_rows_with_no_named_class": len(candidates) - named,
            "candidate_rows_by_class": dict(sorted(by_class.items(), key=lambda kv: -kv[1])),
            "known_circle_rows_at_candidate": len(known_candidates),
            "known_circle_rows_at_candidate_with_a_named_class": sum(
                bool(g["named_classes"]) for g in known_candidates
            ),
        },
        "circles": {
            "candidate": circles_where(lambda g: g["verdict"] == CANDIDATE),
            "candidate_with_no_named_class": circles_where(plain),
            "left": circles_where(lambda g: g["verdict"] in (CANDIDATE, SECOND_LOOK)),
            "tuning_candidate": count(
                sum(any(grades[i]["verdict"] == CANDIDATE for i in ids) for k, ids in circle_rows.items()
                    if groups[k] == "tuning"),
                sum(g == "tuning" for g in groups.values()),
            ),
            "heldout_candidate": count(
                sum(any(grades[i]["verdict"] == CANDIDATE for i in ids) for k, ids in circle_rows.items()
                    if groups[k] == "heldout"),
                sum(g == "heldout" for g in groups.values()),
            ),
        },
        "circles_lost_at": stages,
    }
