"""The leak guard for the probes: nothing that lets the model recognise a famous example reaches it.

The landers guard (``landers.models.leak``) covers its own ids, dates and PNG metadata; this adds star and object ids,
catalogue designations, coordinates, survey names, file names and URLs. As there, an error names the kind of leak and
its offset, never the matched text. The lists are wider than radio needs on purpose: a name no prompt should carry stays
refused.
"""

from __future__ import annotations

import re

from landers.models import leak
from landers.models.leak import LeakError

__all__ = ["LeakError", "check_png", "check_text", "find_leak"]

_ID_PREFIXES = (
    "TIC|TOI|CTOI|KIC|KOI|EPIC|HD|HIP|HAT-P|HATS|WASP|TrES|XO|GJ|LHS|Kepler|K2|TYC|"
    "NGC|UGC|PGC|IC|PKS|3C|4C|Arp|Abell|ILT|ORC|SNR|PN"
)
PATTERNS = (
    ("object id", re.compile(rf"\b({_ID_PREFIXES})[\s_-]*[GJ]?\d", re.I)),
    ("object id", re.compile(r"\bM\s?\d{1,3}\b|\bMessier\b|\b2MASS\b|\bGaia\s+DR\d", re.I)),
    ("object id", re.compile(r"\b\d{7,}\b")),
    ("designation", re.compile(r"\b[JB]\d{4,6}(\.\d+)?[+-]\d{2,6}(\.\d+)?\b")),
    ("coordinate", re.compile(r"\b\d{1,2}[h:]\s?\d{2}[m:]\s?\d{2}(\.\d+)?s?\b|[+-]\d{1,2}[d°:]\s?\d{2}['m:]")),
    ("coordinate", re.compile(r"\b\d{1,3}\.\d{3,}\b")),
    ("coordinate", re.compile(r"\bRA\b|\bR\.A\.|\bDec\b|\bJ2000\b")),
    ("coordinate", re.compile(r"\b(right ascension|declination|galactic (longitude|latitude))\b", re.I)),
    (
        "survey name",
        re.compile(
            r"\b(TESS|Kepler|SPOC|QLP|ExoFOP|exoplanet archive|LoTSS|LOFAR|NVSS|VLASS|ASKAP|MeerKAT|RACS|SDSS|ZTF|"
            r"Pan-?STARRS|Gaia|YouTube)\b",
            re.I,
        ),
    ),
    ("survey name", re.compile(r"\b(MAST|FIRST|WISE|EMU)\b")),
    ("file name", re.compile(r"\.(fits?|fz|h5|hdf5|csv|tsv|png|jpe?g|mp4|webm|mkv|avi|mov|wav|mp3|json|txt)\b", re.I)),
    ("url", re.compile(r"https?://|\bwww\.", re.I)),
)


def find_leak(text: str) -> str | None:
    """The kind of the first leak in ``text`` and its offset, or None when clean."""
    hit = leak.find_leak(text)
    if hit:
        return hit
    for kind, pat in PATTERNS:
        m = pat.search(text)
        if m:
            return f"{kind} at offset {m.start()}"
    return None


def check_text(text: str, where: str = "prompt") -> None:
    hit = find_leak(text)
    if hit:
        raise LeakError(f"{where}: {hit}")


check_png = leak.check_png
