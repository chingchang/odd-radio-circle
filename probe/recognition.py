"""The recognition check: shown three of the radio fields, can the model say which object it is looking at?

The inputs carry no names, but a famous object's shape might give it away, and then an answer could come from memory
rather than from the pixels. Which three is fixed in ``docs/probes.md`` before the first call. A row's label is always
``not_recognised``, so the score counts how many went unrecognised. Whether a named object is the right one is for the
report to say, from the names in the records.
"""

from __future__ import annotations

from probe.harness import Item, ProbeSpec

RECOGNISED, NOT_RECOGNISED = "recognised", "not_recognised"
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "name", "reason"],
    "properties": {
        "answer": {"type": "string", "enum": [RECOGNISED, NOT_RECOGNISED]},
        "name": {"type": "string"},
        "reason": {"type": "string"},
    },
}
FIELD_PROMPT = """These two images show the same patch of sky in radio continuum, 6 arcminutes on a side and centred on
the position of interest, at resolutions of about 6 and 20 arcsec.

Do you recognise which specific astronomical object is at the centre? Answer recognised only if you can name it; give
its usual name in the name field. Otherwise answer not_recognised and leave the name empty. Answer with the schema."""
FIELD_SPEC = ProbeSpec("radio_ring_recognition", FIELD_PROMPT, SCHEMA, schema_name="identity_answer")

FIELD_IDS = ("planetary_nebula-NGC_6720", "ring_galaxy-NGC_4736", "artefact_ring-3C_196")


def checked_items(items: list[Item], ids: list[str] | tuple[str, ...]) -> list[Item]:
    """Those items, relabelled so that a correct score means not recognised."""
    by_id = {it.id: it for it in items}
    return [Item(i, NOT_RECOGNISED, by_id[i].images) for i in ids]
