"""Accuracy, the 95 percent Wilson interval and the confusion table, for the model and the baselines alike."""

from __future__ import annotations

import math

Z_95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """The Wilson score interval for ``k`` of ``n``; with no items it says nothing, (0, 1)."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z**2 / n
    mid = (p + z**2 / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    # At k = 0 and k = n the exact bound is 0 or 1; rounding must not lose it.
    return (0.0 if k == 0 else mid - half), (1.0 if k == n else mid + half)


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {
        "correct": k,
        "n": n,
        "accuracy": round(k / n, 4) if n else None,
        "wilson_95": [round(lo, 4), round(hi, 4)],
    }


def score(labels: list[str], predictions: list[str], only_labels: tuple[str, ...] | None = None) -> dict:
    """Score predictions against labels. A prediction outside the labels (``invalid``, ``no_answer``, a class not being
    scored) counts as wrong and keeps its own column, so a failed call can never raise the accuracy by being dropped.
    ``only_labels`` keeps the items with those labels: planet against eclipsing binary, say, of a three-class list."""
    if len(labels) != len(predictions):
        raise ValueError(f"{len(labels)} labels but {len(predictions)} predictions")
    pairs = [(y, p) for y, p in zip(labels, predictions, strict=True) if only_labels is None or y in only_labels]
    rows = sorted({y for y, _ in pairs})
    columns = rows + sorted({p for _, p in pairs} - set(rows))
    confusion = {y: {p: sum(1 for a, b in pairs if a == y and b == p) for p in columns} for y in rows}
    per_label = {y: _rate(confusion[y][y], sum(confusion[y].values())) for y in rows}
    return {
        **_rate(sum(1 for y, p in pairs if y == p), len(pairs)),
        "labels": rows,
        "predictions": columns,
        "confusion": confusion,
        "per_label": per_label,
    }


def confusion_table(result: dict) -> str:
    """The confusion table as markdown: rows are labels, columns are predictions."""
    columns = result["predictions"]
    lines = ["| label | " + " | ".join(columns) + " |", "|---|" + "---|" * len(columns)]
    for y in result["labels"]:
        lines.append(f"| {y} | " + " | ".join(str(result["confusion"][y][p]) for p in columns) + " |")
    return "\n".join(lines) + "\n"


def summary_markdown(title: str, result: dict) -> str:
    lo, hi = result["wilson_95"]
    return (
        f"# {title}\n\n"
        f"Accuracy {result['correct']} of {result['n']} ({result['accuracy']}), "
        f"95 percent Wilson interval {lo} to {hi}.\n\n{confusion_table(result)}"
    )
