"""The two code baselines on the pre-filter list: how the tuned threshold is chosen and what the counts mean. The rule
is written in docs/proposals/baselines-v1.md; this is that rule in code. No network here, and nothing here reaches a
model.
"""

from __future__ import annotations

import numpy as np

from probe import prefilter as pf
from probe import radio
from probe.score import wilson

UNLABELLED = "unlabelled"  # a listed source that is no known circle; nobody knows what it is


def best_score(measures: dict) -> float:
    """The larger of a field's two scores, so "either map reaches the threshold" is one number. NaN if both are."""
    return float(np.fmax(measures["score_6"], measures["score_20"]))


def tuning_scores(items: list[dict]) -> dict[str, list[float]]:
    """The scores the tuning may read: tuning circles and lookalikes. Held-out circles and random sources are left out,
    though the items file holds them, and an unknown group stops the run rather than being guessed at."""
    out: dict[str, list[float]] = {"circles": [], "lookalikes": []}
    for item in items:
        group = item["group"]
        if group == "tuning":
            out["circles"].append(best_score(item["measures"]))
        elif group in pf.OTHER_GROUPS:
            out["lookalikes"].append(best_score(item["measures"]))
        elif group not in ("heldout", "random"):
            raise ValueError(f"unknown group in the items file: {group}")
    return out


def candidates(scores: list[float]) -> list[float]:
    """Ascending: below the lowest finite score, the midpoints between neighbouring scores, above the highest."""
    values = np.unique([s for s in scores if np.isfinite(s)])
    if not len(values):
        raise ValueError("no finite score to tune on")
    return [float(values[0] - 1), *((values[:-1] + values[1:]) / 2).tolist(), float(values[-1] + 1)]


def tune(circles: list[float], lookalikes: list[float]) -> dict:
    """The candidate with the largest circles called / n + lookalikes not called / n - 1; on a tie, the highest."""
    if not circles or not lookalikes:
        raise ValueError("tuning needs circles and lookalikes")
    best = None
    with np.errstate(invalid="ignore"):
        c, o = np.array(circles), np.array(lookalikes)
        for threshold in candidates([*circles, *lookalikes]):
            hits, rejected = int((c >= threshold).sum()), int((~(o >= threshold)).sum())
            value = hits / len(c) + rejected / len(o) - 1
            if best is None or value >= best["youden_j"]:
                best = {
                    "threshold": threshold,
                    "youden_j": value,
                    "circles_called": hits,
                    "circles": len(c),
                    "lookalikes_not_called": rejected,
                    "lookalikes": len(o),
                }
    return best


def calls(measures: dict, tuned: float) -> dict[str, str]:
    return {
        "annulus": radio.annulus_rule(measures["score_6"], measures["score_20"]),
        "annulus_tuned": radio.annulus_rule(measures["score_6"], measures["score_20"], tuned),
    }


def count(called: int, n: int) -> dict:
    return {"called": called, "n": n, "wilson_95": [round(v, 4) for v in wilson(called, n)]}


def listed_near(rows: dict[str, np.ndarray], ra: float, dec: float, radius_arcsec: float) -> list[int]:
    """Indices of the listed rows within a radius of a position."""
    return [int(i) for i in pf.rows_near(rows, ra, dec, radius_arcsec)]


def circle_outcome(group: str, published: dict[str, str], near_rows: list[dict]) -> dict:
    """One known circle under both baselines: its call at the published position, and through the list, where it counts
    only if a listed row within its kept radius is called. No such row means the pre-filter lost it."""
    return {
        "group": group,
        "on_list": bool(near_rows),
        "at_published_position": published,
        "through_list": {
            name: any(r["calls"][name] == radio.RING for r in near_rows) for name in ("annulus", "annulus_tuned")
        },
    }


def circle_counts(outcomes: dict[str, dict]) -> dict:
    """Objects, not rows: each circle counts once, tuning and held-out apart and together."""
    groups = {"tuning": "tuning", "heldout": "heldout", "all": None}
    result = {}
    for label, group in groups.items():
        chosen = [o for o in outcomes.values() if group is None or o["group"] == group]
        result[label] = {
            "kept_by_prefilter": count(sum(o["on_list"] for o in chosen), len(chosen)),
            **{
                f"{name}_at_published_position": count(
                    sum(o["at_published_position"][name] == radio.RING for o in chosen), len(chosen)
                )
                for name in ("annulus", "annulus_tuned")
            },
            **{
                f"{name}_through_list": count(sum(o["through_list"][name] for o in chosen), len(chosen))
                for name in ("annulus", "annulus_tuned")
            },
        }
    return result
