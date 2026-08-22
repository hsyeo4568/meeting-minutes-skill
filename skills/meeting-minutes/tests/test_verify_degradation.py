# -*- coding: utf-8 -*-
"""Gate #2 (degradation) tests — the read-through the humans kept skipping.

The gate asserts three things a manual read-through is supposed to catch:
every configurable tool declares a no-tool fallback, the never-fail principle
is still stated where the runtime points, and every engine reference the skill
links actually exists.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import verify_degradation as VD  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent


def clone_skill(tmp_path: Path) -> Path:
    """Copy the parts of the skill the gate reads, so tests can corrupt them."""
    root = tmp_path / "skill"
    (root / "references" / "engine").mkdir(parents=True)
    shutil.copy2(SKILL_ROOT / "SKILL.md", root / "SKILL.md")
    shutil.copy2(SKILL_ROOT / "config.example.yaml", root / "config.example.yaml")
    for reference in (SKILL_ROOT / "references" / "engine").glob("*.md"):
        shutil.copy2(reference, root / "references" / "engine" / reference.name)
    return root


def test_shipped_skill_passes_the_degradation_gate():
    assert VD.check(SKILL_ROOT) == []


def test_tool_without_a_documented_fallback_fails_the_gate(tmp_path):
    root = clone_skill(tmp_path)
    config = root / "config.example.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("\ntools:\n", "\ntools:\n  notion_mcp: auto\n"),
        encoding="utf-8",
    )

    failures = VD.check(root)

    assert any("notion_mcp" in failure for failure in failures), failures


def test_missing_degradation_matrix_row_fails_the_gate(tmp_path):
    root = clone_skill(tmp_path)
    tooling = root / "references" / "engine" / "tooling.md"
    tooling.write_text(
        "\n".join(
            line for line in tooling.read_text(encoding="utf-8").splitlines()
            if not line.startswith("| qmd ")
        ),
        encoding="utf-8",
    )

    failures = VD.check(root)

    assert any("qmd" in failure and "tooling.md" in failure for failure in failures), failures


def test_dropped_never_fail_principle_fails_the_gate(tmp_path):
    root = clone_skill(tmp_path)
    skill = root / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8").replace("never fail on a missing tool", "abort the run"),
        encoding="utf-8",
    )

    failures = VD.check(root)

    assert any("never-fail" in failure.lower() for failure in failures), failures


def test_unreachable_engine_reference_fails_the_gate(tmp_path):
    root = clone_skill(tmp_path)
    (root / "references" / "engine" / "tooling.md").unlink()

    failures = VD.check(root)

    assert any("tooling.md" in failure for failure in failures), failures


def test_main_returns_nonzero_when_a_check_fails(tmp_path, capsys):
    root = clone_skill(tmp_path)
    (root / "references" / "engine" / "tooling.md").unlink()

    assert VD.main([str(root)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_main_returns_zero_on_the_shipped_skill(capsys):
    assert VD.main([str(SKILL_ROOT)]) == 0
    assert "OK" in capsys.readouterr().out
