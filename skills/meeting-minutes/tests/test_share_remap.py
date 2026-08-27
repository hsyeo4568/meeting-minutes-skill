# -*- coding: utf-8 -*-
"""Phase 5 share is a snapshot remap, not a re-draft. Share-check stays."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
ENGINE = ROOT / "references" / "engine"


def test_skill_phase5_is_snapshot_remap():
    share = SKILL.split("## 4.")[1].split("## 5.")[0]
    assert "remaps" in share
    assert "snapshot_path" in share
    assert "Do not Read the transcript" in share
    assert "writing-principles.md" in share
    assert "heading remap" in share
    assert "share-check" in SKILL
    assert "Exit 8" in SKILL


def test_pipeline_phase5_remap_not_redraft():
    pipe = (ENGINE / "pipeline.md").read_text(encoding="utf-8")
    assert "detail_md is the only draft" in pipe
    assert "Remap, do not rewrite" in pipe
    assert "Do not Read the transcript" in pipe
    assert "Source = `gate` `snapshot_path` only" in pipe


def test_templates_canvas_vault_gmail_are_derivatives():
    tpl = (ENGINE / "output-templates.md").read_text(encoding="utf-8")
    assert "remap of the approved snapshot" in tpl
    assert "do not rewrite the meeting body from that mail" in tpl
    assert "copy of the approved snapshot" in tpl
    assert "Do not restack" in tpl


def test_runtime_protocol_forbids_share_reload():
    rt = (ENGINE / "RUNTIME-PROTOCOL.md").read_text(encoding="utf-8")
    assert "Remap form only" in rt
    assert "writing-principles at share time" in rt
    assert "share-check" in rt
    assert "exit 8" in rt.lower() or "Exit 8" in rt
