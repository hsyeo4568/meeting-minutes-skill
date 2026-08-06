#!/usr/bin/env python3
"""Read-back comparison that survives a rendering channel.

A byte hash proves an artifact arrived intact only on channels that store what
they were given. Slack canvas does not: it rewrites `-` bullets to `*`, wraps
dates as `![](slack_date:2026-07-28)`, and inserts blank lines between blocks
(measured against a live canvas, 2026-07-27). Hashing there would fail every
run and the gate would be switched off — worse than no gate.

So the comparison is declared per channel (`config.channels.<ch>.readback`):

    exact     byte-faithful after canon() — files, vault, anything we own
    semantic  the sent content must all be PRESENT after stripping the
              renderer's own formatting — canvas, mail bodies

Semantic still catches what read-back exists to catch: truncation, dropped
sections, an empty body, the wrong document. It does not catch reformatting,
which on those channels is not a defect.
"""
from __future__ import annotations

import re

EXACT = "exact"
SEMANTIC = "semantic"

# `![](slack_date:2026-07-28)` / `![](type:value)` -> the value it wraps.
_EMBED = re.compile(r"!\[\]\([a-z_]+:([^)]*)\)")
# Leading list/quote/heading marks and an optional checkbox.
_LEAD = re.compile(r"^[\s>]*(?:[-*+·]|\d+[.)])?\s*(?:\[[ xX]\])?\s*")
# Inline emphasis that renderers add or drop freely.
_EMPHASIS = re.compile(r"\*\*|__|~~|`")
_HEADING = re.compile(r"^#+\s*")


def normalize_line(line: str) -> str:
    """Reduce a line to the content a reader would see, minus the decoration."""
    # Emphasis first: `**Acme**` starts with a `*` that the list-marker
    # pattern would otherwise eat, leaving a stray `*`.
    out = _EMBED.sub(r"\1", line)
    out = _EMPHASIS.sub("", out)
    out = _HEADING.sub("", out)
    out = _LEAD.sub("", out)
    return " ".join(out.split())


def content_lines(text: str) -> list[str]:
    """Normalized, non-empty lines — the unit of presence."""
    return [n for n in (normalize_line(ln) for ln in text.split("\n")) if n]


def flatten(text: str) -> str:
    """All content as one line — the read-back's own line breaks stop mattering.

    Gmail stores a plaintext body hard-wrapped near 78 columns, so a sent line
    comes back split across two. Comparing line to line would call every mail a
    loss; comparing against the flattened body finds the content wherever the
    wrap fell.
    """
    return " ".join(content_lines(text))


def missing_lines(sent: str, readback: str) -> list[str]:
    """Sent content absent from the read-back. Empty list = the artifact is whole.

    Each match is consumed from the haystack, so a body that lost one of two
    identical lines is still reported — a plain containment test would hide it.
    """
    haystack = flatten(readback)
    missing = []
    for line in content_lines(sent):
        at = haystack.find(line)
        if at < 0:
            missing.append(line)
        else:
            haystack = haystack[:at] + haystack[at + len(line):]
    return missing


def mode_for(cfg: dict, artifact: str, default: str = EXACT) -> str:
    """Read-back mode declared for a channel; `exact` unless stated otherwise."""
    spec = (cfg.get("channels") or {}).get(artifact)
    if isinstance(spec, dict):
        declared = spec.get("readback", default)
        if declared not in (EXACT, SEMANTIC):
            raise ValueError(
                f"channels.{artifact}.readback must be {EXACT!r} or {SEMANTIC!r}, "
                f"got {declared!r}")
        return declared
    return default
