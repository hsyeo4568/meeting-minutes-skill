# -*- coding: utf-8 -*-
"""Characterization tests for preflight.py.

These tests capture the *current observable behaviour* of the individual
check functions so that structural refactoring is guarded. They import
functions directly after the module-level imperative code is wrapped in
main().
"""
from __future__ import annotations

import sys
import importlib.util
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import preflight as PF  # noqa: E402


# ---------------------------------------------------------------------------
# check_python_version()
# ---------------------------------------------------------------------------

def test_check_python_version_current_passes():
    """Running Python must satisfy the >=3.9 requirement."""
    result = PF.check_python_version()
    assert result == 0  # current interpreter is >=3.9


def test_check_python_version_old_fails():
    """Simulate Python 3.8 — should return 1."""
    from collections import namedtuple
    # Build a fake version_info that supports tuple comparison AND .major/.minor
    FakeVI = namedtuple("version_info", ["major", "minor", "micro", "releaselevel", "serial"])
    fake_info = FakeVI(3, 8, 0, "final", 0)
    with patch.object(sys, "version_info", fake_info):
        import preflight as _pf
        assert _pf.check_python_version() == 1


# ---------------------------------------------------------------------------
# check_deps()
# ---------------------------------------------------------------------------

def test_check_deps_yaml_present():
    """PyYAML must be installed in the test env (it's a project dep)."""
    missing_count = PF.check_deps()
    # yaml is required; if it's missing the test env is broken — assert 0
    assert missing_count == 0


def test_check_deps_missing_required(monkeypatch):
    """Simulate yaml missing — required dep -> returns 1."""
    import importlib.util as ilu

    original_find_spec = ilu.find_spec

    def patched_find_spec(name, *args, **kwargs):
        if name == "yaml":
            return None
        return original_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(ilu, "find_spec", patched_find_spec)
    assert PF.check_deps() == 1


# ---------------------------------------------------------------------------
# check_bash()
# ---------------------------------------------------------------------------

def test_check_bash_no_crash():
    """check_bash() should never raise regardless of bash presence."""
    result = PF.check_bash()
    assert result in (0, 1)  # either bash >=4 or not — both valid


# ---------------------------------------------------------------------------
# check_config()
# ---------------------------------------------------------------------------

def test_check_config_present(tmp_path):
    (tmp_path / "config.yaml").write_text("project:\n  name: test\n", encoding="utf-8")
    assert PF.check_config(tmp_path) == 0


def test_check_config_missing(tmp_path):
    assert PF.check_config(tmp_path) == 1


# ---------------------------------------------------------------------------
# main() exit code
# ---------------------------------------------------------------------------

def test_main_exits_0_when_all_present(tmp_path, monkeypatch, capsys):
    """Simulate a ready machine — main() returns 0."""
    # Patch ROOT so config check uses tmp_path
    monkeypatch.setattr(PF, "ROOT", tmp_path)
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")

    # Patch check functions to all return 0 (machine ready)
    monkeypatch.setattr(PF, "check_python_version", lambda: 0)
    monkeypatch.setattr(PF, "check_deps", lambda: 0)
    monkeypatch.setattr(PF, "check_bash", lambda: 0)
    monkeypatch.setattr(PF, "check_config", lambda root: 0)

    exit_code = PF.main()
    assert exit_code == 0


def test_main_exits_1_when_required_missing(tmp_path, monkeypatch):
    """main() returns 1 when a required check fails."""
    monkeypatch.setattr(PF, "ROOT", tmp_path)
    monkeypatch.setattr(PF, "check_python_version", lambda: 0)
    monkeypatch.setattr(PF, "check_deps", lambda: 1)  # required dep missing
    monkeypatch.setattr(PF, "check_bash", lambda: 0)
    monkeypatch.setattr(PF, "check_config", lambda root: 0)

    exit_code = PF.main()
    assert exit_code == 1
