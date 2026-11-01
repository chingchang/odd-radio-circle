"""Run a probe: N labelled items, one Wonder call each, a fixed prompt and answer schema.

Every call goes through ``ProbeClient``, the landers client with this project's guard added, on one ledger. The fake
backend is the default. Each backend keeps its own ledger and results, so a fake run spends none of the real cap and
its answers are never taken for real ones: ``out/ledger.json`` and ``out/<probe>/real/`` hold the paid run,
``out/ledger_fake.json`` and ``out/<probe>/fake/`` the fake one.

``records.jsonl`` gets one row per attempted item as it lands: the request (images as digests), the answer, the label
and the cost. A rerun skips an item already answered under the same request hash, so a killed run continues without
paying twice; an item that failed is asked again. The item's id and label never enter the request.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from landers.models.backend import Backend, ModelClient, WonderRequest, make_backend, request_hash
from landers.models.ledger import TOTAL_CAP_USD, CapError, Ledger, spent_usd, total_cap_from_env

from probe import guard
from probe.score import score, summary_markdown

PROBES_CAP_USD = 10.0  # the model tests together; a lower stop than the project's 40 USD (CLAUDE.md)
# docs/models.md: 1,300 to 1,500 tokens per 1280 px image, but the API reported far fewer (497 for three images) and the
# bill may be higher. The ledger charges at least this much, so the cap holds if the reported count is short.
IMAGE_TOKENS_FLOOR = 1500
MAX_CONSECUTIVE_ERRORS = 3
NO_ANSWER = "no_answer"
INVALID = "invalid"


class RunAborted(RuntimeError):
    """Calls keep failing; stop rather than go on spending. What landed stays on disk for the rerun."""


@dataclass(frozen=True)
class Item:
    id: str
    label: str
    images: tuple[bytes, ...]


@dataclass(frozen=True)
class ProbeSpec:
    name: str
    prompt: str
    schema: dict
    answer_field: str = "answer"
    effort: str = "low"
    scored_labels: tuple[str, ...] | None = None  # None scores every item
    schema_name: str = ""  # reaches the model; the default is the probe's name and "answer"

    def __post_init__(self):
        spec = self.schema["properties"].get(self.answer_field, {})
        if "enum" not in spec or self.answer_field not in self.schema.get("required", []):
            raise ValueError(f"{self.name}: {self.answer_field} must be a required enum field of the schema")

    def request(self, item: Item) -> WonderRequest:
        name = self.schema_name or f"{self.name}_answer"
        return WonderRequest(self.prompt, list(item.images), self.schema, name, self.effort)

    def prediction(self, data: dict) -> str:
        answer = data.get(self.answer_field)
        return answer if answer in self.schema["properties"][self.answer_field]["enum"] else INVALID


class ImageTokenFloor:
    """Raises a Wonder result's input tokens to the per-image floor before the ledger sees them. It sits outside the
    recorded backend, so the recordings keep what the API reported."""

    def __init__(self, inner: Backend):
        self.inner = inner
        self.name = inner.name

    def sam(self, req):
        return self.inner.sam(req)

    def spark(self, req):
        return self.inner.spark(req)

    def wonder(self, req):
        result = self.inner.wonder(req)
        return replace(result, input_tokens=max(result.input_tokens, IMAGE_TOKENS_FLOOR * len(req.images)))


class ProbeClient(ModelClient):
    """The landers client, refusing this project's leaks as well, on any call made through it."""

    def __init__(self, backend: Backend, ledger: Ledger, kind: str, **kwargs):
        super().__init__(backend, ledger, **kwargs)
        self.kind = kind

    def _guard(self, req) -> None:
        super()._guard(req)
        # An underscore is a word character, so a name such as survey_answer would slip past the guard's boundaries.
        schema_name = getattr(req, "schema_name", "").replace("_", " ")
        for i, text in enumerate([*req.texts(), schema_name]):
            guard.check_text(text, f"text[{i}]")


def open_client(
    kind: str = "fake", out_root: Path = Path("out"), env: dict | None = None, cap_usd: float = PROBES_CAP_USD
) -> ProbeClient:
    """A client on backend ``kind``: ``fake``, ``dry-run``, ``recorded``, or ``real``, which ``make_backend`` refuses
    without ``MODEL_API_KEY`` and ``LANDERS_REAL_CALLS=1``. The ledger continues from disk, so the cap holds over all
    runs. ``cap_usd`` can lower the cap for one plan item, never raise it. A real run also leaves the landers
    cumulative cap room, since both spend one credit."""
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    directory = {"dry-run": out_root / "model_requests"}.get(kind, out_root / "model_recordings")
    backend = make_backend(kind, directory, env)
    cap = min(PROBES_CAP_USD, cap_usd, total_cap_from_env())
    if kind == "real":
        backend = ImageTokenFloor(backend)
        cap = min(cap, TOTAL_CAP_USD - spent_usd())
    ledger = Ledger.load(out_root / ("ledger.json" if kind == "real" else f"ledger_{kind}.json"))
    ledger.total_cap_usd = cap
    return ProbeClient(backend, ledger, kind)


def _results_dir(probe: str, who: str, out_root: Path) -> Path:
    out = Path(out_root) / probe / who
    out.mkdir(parents=True, exist_ok=True)
    return out


def _read_rows(path: Path) -> dict[str, dict]:
    """The latest row per item id. A line cut off by a kill is dropped; its item is asked again."""
    rows: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows[row["item_id"]] = row
    return rows


def _append(path: Path, row: dict) -> None:
    text = path.read_text() if path.exists() else ""
    prefix = "" if not text or text.endswith("\n") else "\n"  # after a line cut off by a kill
    with path.open("a") as f:
        f.write(prefix + json.dumps(row) + "\n")


def _scrubbed(e: Exception) -> str:
    text = f"{type(e).__name__}: {e}"[:500]
    key = os.environ.get("MODEL_API_KEY")
    return text.replace(key, "[key]") if key else text


def _write_score(probe: str, who: str, out: Path, items: list[Item], rows: dict, only, extra: dict) -> dict:
    labels = [it.label for it in items]
    predictions = [rows[it.id]["prediction"] for it in items]
    result = {"probe": probe, "backend": who, **score(labels, predictions, only), **extra}
    (out / "score.json").write_text(json.dumps(result, indent=1) + "\n")
    (out / "score.md").write_text(summary_markdown(f"{probe}, {who}", result))
    return result


def run_probe(spec: ProbeSpec, items: list[Item], client: ProbeClient, out_root: Path = Path("out")) -> dict:
    """Ask about every item and score the answers. Every request is guarded before the first is sent, so a leak in
    item 40 costs nothing. A leak or the cap stops the run; a failed call is recorded and, if it stays that way, counts
    as wrong."""
    if len({it.id for it in items}) != len(items):
        raise ValueError(f"{spec.name}: duplicate item ids")
    requests = {it.id: spec.request(it) for it in items}
    for it in items:
        client._guard(requests[it.id])
    out = _results_dir(spec.name, client.kind, out_root)
    path = out / "records.jsonl"
    rows = _read_rows(path)
    failures = 0
    for it in items:
        req = requests[it.id]
        digest = request_hash(req)
        old = rows.get(it.id)
        if old and old["request_hash"] == digest and "error" not in old:
            continue
        before = sum(e["cost_usd"] for e in client.ledger.entries.values())
        row = {"item_id": it.id, "label": it.label, "request_hash": digest, "request": req.to_wire(images="digest")}
        try:
            result = client.wonder(req)
        except (guard.LeakError, CapError):
            raise
        except Exception as e:
            failures += 1
            row.update(error=_scrubbed(e), prediction=NO_ANSWER)
        else:
            failures = 0
            row.update(
                answer=result.data,
                raw=result.raw,
                prediction=spec.prediction(result.data),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
        row["cost_usd"] = round(sum(e["cost_usd"] for e in client.ledger.entries.values()) - before, 6)
        _append(path, row)
        rows[it.id] = row
        if failures >= MAX_CONSECUTIVE_ERRORS:
            raise RunAborted(f"{spec.name}: {failures} calls failed in a row; see {path}")
    cost = round(sum(rows[it.id]["cost_usd"] for it in items), 6)
    return _write_score(spec.name, client.kind, out, items, rows, spec.scored_labels, {"cost_usd": cost})


def run_baseline(
    spec: ProbeSpec, items: list[Item], predict: Callable[[Item], str], name: str, out_root: Path = Path("out")
) -> dict:
    """Score a code baseline on the same items, written to ``out/<probe>/<name>/`` beside the model's results."""
    out = _results_dir(spec.name, name, out_root)
    rows = {it.id: {"item_id": it.id, "label": it.label, "prediction": predict(it)} for it in items}
    (out / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows.values()))
    return _write_score(spec.name, name, out, items, rows, spec.scored_labels, {})
