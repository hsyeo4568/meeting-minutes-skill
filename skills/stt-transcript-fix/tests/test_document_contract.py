# -*- coding: utf-8 -*-
"""S6 documentation contracts for the lazy operational references.

Salvaged from a parallel hardening attempt (hermes `opsguardian` profile) and
re-pointed at this tree's reference vocabulary. The thinned SKILL.md only works
if the operational detail it defers to stays reachable AND keeps stating the
rules the runtime enforces — an empty or drifted reference silently removes a
safety boundary the main file no longer spells out.
"""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "SKILL.md"
REFERENCES = {
    "batch": ROOT / "references" / "batch-mode.md",
    "marker": ROOT / "references" / "marker-policy.md",
    "encoding": ROOT / "references" / "encoding-fallback.md",
}


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_s6_operational_references_exist_and_are_linked_from_skill():
    skill = text(SKILL)
    for path in REFERENCES.values():
        assert path.is_file(), f"missing S6 reference: {path.name}"
        assert text(path).strip(), f"empty S6 reference: {path.name}"
        assert f"references/{path.name}" in skill


def test_bash_temp_contract_uses_msys_and_never_powershell_temp_syntax():
    docs = "\n".join(text(path) for path in [SKILL, *REFERENCES.values()])
    assert "$env:TEMP" not in docs
    assert "$LOCALAPPDATA/Temp" in docs

    encoding = text(REFERENCES["encoding"])
    for needle in ("cygpath -m", "cygpath -u", "mktemp", "trap", "CP949", "PYTHONUTF8=1"):
        assert needle in encoding, f"encoding-fallback.md omits: {needle}"


def test_batch_reference_states_the_entry_point_and_lock_contract():
    batch = text(REFERENCES["batch"])
    for needle in ("fixstamp.py batch", "exit 4", ".lock", "fail-closed", "unchanged",
                   "max 3", "read-only"):
        assert needle in batch, f"batch-mode.md omits: {needle}"


def test_marker_reference_states_the_fail_closed_cap_contract():
    marker = text(REFERENCES["marker"])
    for needle in ("(*", "fail-closed", "Tier-C", "max(15, lines // 16)"):
        assert needle in marker, f"marker-policy.md omits: {needle}"


def test_encoding_reference_states_the_restore_contract():
    encoding = text(REFERENCES["encoding"])
    for needle in ("UTF-16", "line-count parity", "restore", "atomic", "backup"):
        assert needle in encoding, f"encoding-fallback.md omits: {needle}"


def test_skill_skip_zero_is_a_hard_stop_and_stays_a_short_router():
    """Stamp 0 must stop the agent from rereading transcript/glossary/refs."""
    skill = text(SKILL)
    assert "0=skip" in skill
    assert "즉시 종료" in skill
    assert "sections" in skill
    assert "§1" in skill and "§7" in skill and "§8" in skill
    n_lines = len(skill.splitlines())
    assert n_lines <= 80, f"SKILL.md bloated to {n_lines} lines (router budget 80)"
    single_row = next(ln for ln in skill.splitlines() if ln.startswith("| 단일 파일 |"))
    assert "references/" not in single_row


def test_skill_does_not_always_load_lazy_references():
    skill = text(SKILL)
    assert "표의 해당 행이 맞을 때만" in skill
    assert "단일 `.txt`에서는 열지 않는다" in skill


def test_skill_stamp_one_forbids_glossary_and_scan_dumps():
    """Isolated stamp=1 must not invite glossary Read, scan dump, Grep, or full-transcript Read."""
    skill = text(SKILL)
    assert "Never glossary-only" in skill
    assert "sections <glossary> <target>" in skill
    assert "glossary 파일" in skill and "Read 금지" in skill
    assert "직접 읽기를 지시" not in skill
    assert "`-v`" in skill and "붙이지" in skill
    assert "cat/Read" in skill
    assert "후보는 Grep" not in skill
    assert "녹취 Grep 금지" in skill
    assert "stdout으로 판단" in skill
    assert "1=new" in skill and "녹취·glossary 파일 Read 금지" in skill
    assert "녹취 전문 금지" in skill
    assert "--dry-run --json" in skill
    assert "fixstamp.py write" in skill
    for needle in (
        "녹취 전체를 읽을 수 있다",
        "stamp 1이 아니면",
        "stamp 1이 아닌",
        "녹취 전문을 열지 않는다",
        "녹취 전체를 열지 않는다",
        "전문을 열 수 있다",
    ):
        assert needle not in skill, f"stamp=1 full-transcript invite remains: {needle!r}"
    for pattern in (
        r"stamp\s*1.{0,24}아니면",
        r"1이 아니면.{0,40}(녹취|전문|열지)",
        r"(녹취\s*전문|녹취\s*전체).{0,16}열지 않는다",
        r"(녹취\s*전문|녹취\s*전체).{0,16}읽을 수 있다",
        r"stamp\s*1.{0,24}(전문|전체).{0,12}(읽|열)",
    ):
        hit = re.search(pattern, skill)
        assert hit is None, f"stamp=1 full-transcript invite remains: {hit.group(0)!r}"

