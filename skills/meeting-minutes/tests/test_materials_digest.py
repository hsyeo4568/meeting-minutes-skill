# -*- coding: utf-8 -*-
"""Tests for the phase 1.5 materials-digest floor.

These lock the two defects a live run produced on 2026-07-29:
  1. a pptx digest built from evidence alone is number soup — evidence is
     numbers-with-eids, the slide's prose lives in a separate split;
  2. that split is keyed 1-based, so a 0-based lookup silently gives every
     slide its neighbour's text (two slides printed identical bodies).
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import materials_digest as MD  # noqa: E402


class _Ev:
    def __init__(self, eid, value, unit="", loc="shape1/para0"):
        self.eid, self.value, self.unit, self.loc = eid, value, unit, loc


class _Unit:
    def __init__(self, index, evidence=(), images=(), hidden=False):
        self.index, self.hidden = index, hidden
        self.evidence, self.images = list(evidence), list(images)


# --- routing ---------------------------------------------------------------

def test_route_known_extension_returns_handler_name():
    assert MD.route(".pptx") == "pptx"
    assert MD.route(".PDF") == "pdf"


def test_route_unknown_extension_returns_none():
    """Unsupported is surfaced by the caller, never silently digested."""
    assert MD.route(".zip") is None


# --- pptx rendering --------------------------------------------------------

def _prose():
    return {1: "slide one body", 2: "slide two body", 3: "slide three body"}


def test_pptx_digest_uses_one_based_prose_keys():
    units = [_Unit(0), _Unit(1), _Unit(2)]
    out = MD.render_pptx_digest("deck.pptx", units, _prose())
    assert "slide one body" in out and "slide two body" in out
    # the 0-based bug printed the same body twice
    assert out.count("slide two body") == 1


def test_pptx_digest_keeps_prose_and_numbers_together():
    units = [_Unit(0, evidence=[_Ev("s1:e001", "57", "건")])]
    out = MD.render_pptx_digest("deck.pptx", units, {1: "참여 건수 요약"})
    assert "참여 건수 요약" in out
    assert "57건" in out and "s1:e001" in out


def test_pptx_digest_flags_slides_whose_meaning_is_in_images():
    """deep_read is a separate, costed decision — the digest must say what it
    could not read instead of implying the slide was understood."""
    class _Img:
        def __init__(self, image_id):
            self.image_id = image_id

    units = [_Unit(0, images=[_Img("s1:img01")])]
    out = MD.render_pptx_digest("deck.pptx", units, {1: "도식"})
    assert "s1:img01" in out and "deep_read" in out


def test_pptx_digest_marks_missing_prose_rather_than_dropping_slide():
    units = [_Unit(0), _Unit(1)]
    out = MD.render_pptx_digest("deck.pptx", units, {1: "only first"})
    assert out.count("## slide") == 2
    assert "본문 텍스트 없음" in out


# --- sibling engine discovery ----------------------------------------------

def _fake_sibling(hub, name):
    """A sibling skill exposing the deck-distiller capability. The engine uses
    @dataclass on purpose: a module exec'd without a sys.modules entry dies
    there ('NoneType' object has no attribute '__dict__') and the loader then
    silently degrades to the floor — observed 2026-07-29."""
    skill = hub / name
    (skill / "references" / "engine").mkdir(parents=True)
    (skill / "SKILL.md").write_text("x", encoding="utf-8")
    (skill / "references" / "engine" / "extract.py").write_text(
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class Ev:\n"
        "    eid: str\n"
        "def extract_deck(path):\n"
        "    return []\n"
        "def split_markitdown(path):\n"
        "    return {}\n",
        encoding="utf-8")
    return skill


def test_load_deck_engine_finds_sibling_with_dataclasses(tmp_path):
    hub = tmp_path / "hub"
    (hub / "meeting-minutes" / "scripts").mkdir(parents=True)
    _fake_sibling(hub, "deck-distiller")
    engine = MD._load_deck_engine(hub=hub)
    assert engine is not None, "sibling engine not loaded — digest would degrade to the floor"
    assert hasattr(engine, "extract_deck") and hasattr(engine, "split_markitdown")


def test_load_deck_engine_ignores_sibling_without_capability(tmp_path):
    hub = tmp_path / "hub"
    skill = hub / "unrelated"
    (skill / "references" / "engine").mkdir(parents=True)
    (skill / "SKILL.md").write_text("x", encoding="utf-8")
    (skill / "references" / "engine" / "extract.py").write_text("def other(): pass\n",
                                                               encoding="utf-8")
    assert MD._load_deck_engine(hub=hub) is None
