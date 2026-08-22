# -*- coding: utf-8 -*-
"""S6 documentation contracts for the lazy operational references.

Salvaged from a parallel hardening attempt (hermes `opsguardian` profile) and
re-pointed at this tree's reference vocabulary. The thinned SKILL.md only works
if the operational detail it defers to stays reachable AND keeps stating the
rules the runtime enforces — an empty or drifted reference silently removes a
safety boundary the main file no longer spells out.
"""
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
