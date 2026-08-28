# -*- coding: utf-8 -*-
"""SKILL.md router contracts: short, gated refs, share-check stays, no always-on ontology."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")


def test_skill_stays_a_short_router():
    n = len(SKILL.splitlines())
    assert n <= 120, f"SKILL.md bloated to {n} lines (router budget 120)"


def test_skill_keeps_share_check_exit_8():
    assert "share-check" in SKILL
    assert "slack_bot_dm_id" in SKILL
    assert "Exit 8" in SKILL
    assert "mm_run.py share-check" in SKILL
    assert "user_ids" in SKILL
    assert "{{slack_user_id}}" in SKILL


def test_skill_md_first_gate_stays():
    assert "mm_run.py approve" in SKILL
    assert "gate" in SKILL and "verify" in SKILL
    assert "snapshot_path" in SKILL


def test_ontology_and_phase7_are_opt_in_not_boot():
    boot = SKILL.split("## 1.")[0]
    assert "Do not detect `ontology`" in boot
    assert "Do not run phase 7" in boot
    assert "default OFF" in SKILL
    assert "Ontology 연동" not in SKILL


def test_boot_does_not_always_load_engine_refs_or_vault():
    boot = SKILL.split("## 1.")[0]
    assert "Do not Read writing-principles" in boot
    assert "Do **not** reread the vault" in SKILL or "not reread the vault" in SKILL
    assert "current phase heading" in SKILL


def test_after_approve_follow_section_4():
    assert "do **not** open `pipeline.md`" in SKILL
    assert "Follow §4" in SKILL
    assert "never `user_ids`-only" in SKILL
    share = SKILL.split("## 4.")[1].split("## 5.")[0]
    assert "read_canvas" in share
    assert "openable" in share
    assert "권한 없음" in share
    assert "post-create check = `canvas_id` only" not in share


def test_draft_is_one_file_not_engine_then_rewrite():
    draft = SKILL.split("## 1.")[1].split("## 2.")[0]
    assert "Do **not** write a full engine minutes then rewrite" in draft
    assert "Do **not** Task a named writer subagent" in draft
    assert "One file only" in draft
    assert "conventions-draft.md" in draft
    assert "writing-principles.md" in draft
    assert "Task `hemingway`" not in SKILL
    assert "Hemingway-first" not in SKILL
