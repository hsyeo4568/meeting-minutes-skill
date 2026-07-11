# -*- coding: utf-8 -*-
"""Unit tests for meeting-minutes build_prompt.py — fill() token substitution."""
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_prompt as BP  # noqa: E402

BUILD_PROMPT = SCRIPTS / "build_prompt.py"


def run_build_prompt(args, timeout=60):
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, str(BUILD_PROMPT), *[str(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=timeout,
    )


# ---- fill(): known-token substitution -------------------------------------

def test_fill_replaces_known_token():
    assert BP.fill("hi {{me}}", {"me": "Alex"}) == "hi Alex"


def test_fill_replaces_multiple_tokens():
    table = {"me": "Alex", "org": "Acme"}
    assert BP.fill("{{me}}@{{org}}", table) == "Alex@Acme"


def test_fill_replaces_underscored_token():
    assert BP.fill("s={{project_slug}}", {"project_slug": "acme"}) == "s=acme"


def test_fill_replaces_adjacent_tokens():
    assert BP.fill("{{me}}{{org}}", {"me": "A", "org": "B"}) == "AB"


def test_fill_replaces_repeated_token():
    assert BP.fill("{{me}}/{{me}}", {"me": "X"}) == "X/X"


# ---- fill(): unknown / non-matching tokens are left verbatim ---------------

def test_fill_leaves_unknown_token_raw():
    # no-config display mode relies on this: unresolved token stays literal
    assert BP.fill("x {{unknown}}", {}) == "x {{unknown}}"


def test_fill_ignores_uppercase_token():
    # regex is [a-z_]+ — uppercase is not a token, must stay literal
    assert BP.fill("{{ME}}", {"ME": "nope"}) == "{{ME}}"


def test_fill_ignores_token_with_digits():
    assert BP.fill("{{me2}}", {"me2": "nope"}) == "{{me2}}"


def test_fill_empty_table_returns_text_unchanged():
    assert BP.fill("no tokens here", {}) == "no tokens here"


def test_fill_no_tokens_with_populated_table():
    assert BP.fill("plain text", {"me": "Alex"}) == "plain text"


# ---- unresolved_tokens(): query for silent-drop detection ------------------
# In --config mode a template {{token}} with no config value is currently
# substituted-through silently, producing a broken prompt. This query lets the
# caller detect that (command/query separation — no flag arg on fill()).

def test_unresolved_tokens_finds_missing():
    assert BP.unresolved_tokens("a {{me}} b {{missing}}", {"me": "X"}) == ["missing"]


def test_unresolved_tokens_empty_when_all_resolved():
    assert BP.unresolved_tokens("{{me}}/{{org}}", {"me": "A", "org": "B"}) == []


def test_unresolved_tokens_ignores_non_tokens():
    # uppercase / digit sequences are not [a-z_]+ tokens — not "unresolved"
    assert BP.unresolved_tokens("{{ME}} {{me2}}", {}) == []


def test_unresolved_tokens_dedups_order_preserving():
    assert BP.unresolved_tokens("{{a}} {{b}} {{a}}", {}) == ["a", "b"]


# ---- main(): happy-path subprocess coverage --------------------------------

def test_main_no_config_writes_output_file(tmp_path):
    """main() with no --config writes a PROMPT-ONLY file containing expected headers."""
    out_file = tmp_path / "PROMPT-ONLY.md"
    r = run_build_prompt(["-o", str(out_file)])
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert out_file.exists(), "output file not created"
    content = out_file.read_text(encoding="utf-8")
    assert "## A. 작성 규칙" in content
    assert "## B. 출력 구조" in content
