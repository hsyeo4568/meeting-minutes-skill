# -*- coding: utf-8 -*-
"""Characterization tests for dry_run.py.

These tests capture the *current observable behaviour* of the functions so
that the subsequent structural refactor is guarded. They import the
now-testable functions directly (after the module-level code was wrapped in
main()). Tests exercise logic paths without a real config.yaml on disk —
they patch pathlib.Path.exists() or supply minimal in-memory YAML where
needed.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import importlib
import dry_run as DR  # noqa: E402


# ---------------------------------------------------------------------------
# dig() — shared util (imported via _shared)
# ---------------------------------------------------------------------------

def test_dig_single_key():
    assert DR.dig({"a": 1}, "a") == 1


def test_dig_nested():
    assert DR.dig({"identity": {"me": "Alex"}}, "identity", "me") == "Alex"


def test_dig_missing_key_raises():
    import pytest
    with pytest.raises(KeyError):
        DR.dig({}, "missing")


# ---------------------------------------------------------------------------
# build_tokmap() — token map construction
# ---------------------------------------------------------------------------

_SAMPLE_CFG = {
    "identity": {"me": "Alex", "org": "Acme"},
    "project": {"name": "Demo", "slug": "acme", "profile": "profiles/example-acme"},
    "paths": {
        "vault": "/vault",
        "work_folder": "/work",
        "vault_meetings_subpath": "acme/meetings",
    },
    "channels": {
        "slack_workspace_id": "T000",
        "slack_channel_id": "C000",
        "slack_user_id": "U000",
        "slack_url_base": "https://slack.com",
    },
    "locale": {"language": "ko", "business_style": "korean-gaejosik"},
    "categories": {"daily": {"share_md": True, "canvas": "optional"}},
}


def test_build_tokmap_keys_present():
    tokmap = DR.build_tokmap(_SAMPLE_CFG)
    expected = {
        "me", "org", "project_name", "project_slug",
        "vault_path", "work_folder", "vault_meetings_subpath",
        "slack_workspace_id", "slack_channel_id", "slack_user_id",
        "slack_url_base", "language", "business_style",
    }
    assert expected <= set(tokmap.keys())


def test_build_tokmap_values():
    tokmap = DR.build_tokmap(_SAMPLE_CFG)
    assert tokmap["me"] == "Alex"
    assert tokmap["project_slug"] == "acme"
    assert tokmap["slack_workspace_id"] == "T000"


# ---------------------------------------------------------------------------
# check_tokens() — token resolution check
# ---------------------------------------------------------------------------

def test_check_tokens_all_resolved(tmp_path):
    """All tokens concrete -> returns 0 failures."""
    # Create minimal engine md files with a known token
    eng = tmp_path / "references" / "engine"
    eng.mkdir(parents=True)
    (eng / "writing-principles.md").write_text("{{me}}", encoding="utf-8")
    (eng / "output-templates.md").write_text("{{org}}", encoding="utf-8")
    skill = tmp_path / "SKILL.md"
    skill.write_text("", encoding="utf-8")

    tokmap = {"me": "Alex", "org": "Acme"}
    fail = DR.check_tokens(tokmap, tmp_path)
    assert fail == 0


def test_check_tokens_unresolved_returns_1(tmp_path):
    """Token in engine with no config mapping -> returns 1."""
    eng = tmp_path / "references" / "engine"
    eng.mkdir(parents=True)
    (eng / "writing-principles.md").write_text("{{unknown_tok}}", encoding="utf-8")
    (eng / "output-templates.md").write_text("", encoding="utf-8")
    skill = tmp_path / "SKILL.md"
    skill.write_text("", encoding="utf-8")

    tokmap = {"me": "Alex"}
    fail = DR.check_tokens(tokmap, tmp_path)
    assert fail == 1


def test_check_tokens_placeholder_left_returns_1(tmp_path):
    """Token mapped to a '<...>' placeholder -> returns 1."""
    eng = tmp_path / "references" / "engine"
    eng.mkdir(parents=True)
    (eng / "writing-principles.md").write_text("{{me}}", encoding="utf-8")
    (eng / "output-templates.md").write_text("", encoding="utf-8")
    (tmp_path / "SKILL.md").write_text("", encoding="utf-8")

    tokmap = {"me": "<fill-me>"}
    fail = DR.check_tokens(tokmap, tmp_path)
    assert fail == 1


# ---------------------------------------------------------------------------
# check_path_safety() — traversal guard
# ---------------------------------------------------------------------------

def test_check_path_safety_safe_values():
    checks = {"vault_meetings_subpath": "acme/meetings", "project_slug": "acme"}
    assert DR.check_path_safety(checks) == 0


def test_check_path_safety_dotdot_rejected():
    checks = {"vault_meetings_subpath": "acme/../../secret", "project_slug": "acme"}
    assert DR.check_path_safety(checks) == 1


def test_check_path_safety_absolute_rejected():
    checks = {"vault_meetings_subpath": "/etc/passwd", "project_slug": "acme"}
    assert DR.check_path_safety(checks) == 1


def test_check_path_safety_slug_with_slash_rejected():
    checks = {"vault_meetings_subpath": "meetings", "project_slug": "a/b"}
    assert DR.check_path_safety(checks) == 1


def test_check_path_safety_normalized_traversal_rejected():
    """Traversal that passes naive leading-char check but contains '..'."""
    checks = {"vault_meetings_subpath": "sub/../../../secret", "project_slug": "acme"}
    assert DR.check_path_safety(checks) == 1


# ---------------------------------------------------------------------------
# check_profile() — profile file existence
# ---------------------------------------------------------------------------

def test_check_profile_all_present(tmp_path):
    prof = tmp_path / "profiles" / "example-acme"
    prof.mkdir(parents=True)
    for name in ["domain-glossary.md", "contacts.md", "conventions.md"]:
        (prof / name).write_text("", encoding="utf-8")

    cfg = dict(_SAMPLE_CFG)
    assert DR.check_profile(cfg, tmp_path) == 0


def test_check_profile_missing_file_returns_1(tmp_path):
    prof = tmp_path / "profiles" / "example-acme"
    prof.mkdir(parents=True)
    # Only create 2 of 3 required files
    (prof / "domain-glossary.md").write_text("", encoding="utf-8")
    (prof / "contacts.md").write_text("", encoding="utf-8")

    cfg = dict(_SAMPLE_CFG)
    assert DR.check_profile(cfg, tmp_path) == 1


# ---------------------------------------------------------------------------
# check_degradation() — degradation dry-run output (no fail possible)
# ---------------------------------------------------------------------------

def test_check_degradation_returns_0():
    """Degradation check is informational — always 0."""
    assert DR.check_degradation(_SAMPLE_CFG) == 0
