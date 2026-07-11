"""Shared utilities for meeting-minutes scripts.

Kept intentionally small — only logic used by 2+ scripts lives here.
"""
from __future__ import annotations


def dig(cfg: dict, *keys: str):
    """Nested dict get: ``dig(cfg, 'identity', 'me')`` -> ``cfg['identity']['me']``.

    Raises ``KeyError`` (or ``TypeError`` if an intermediate value is not a
    mapping) when any key is absent — callers handle missing-key errors
    explicitly rather than receiving *None* silently.
    """
    for k in keys:
        cfg = cfg[k]
    return cfg
