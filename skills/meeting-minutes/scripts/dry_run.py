#!/usr/bin/env python3
"""Dry-run: boot the meeting-minutes engine with config.yaml + profile, no side effects.
Validates: config parses, every engine {{token}} resolves to a concrete value,
profile files load, degradation (tools off) yields file-only plan."""
from __future__ import annotations

import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

try:
    import yaml
except ImportError:
    print("FAIL: PyYAML not installed (pip install pyyaml)")
    sys.exit(2)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _shared import dig  # noqa: E402

# Tokens supplied by the profile rather than config — not checked against TOKMAP.
_PROFILE_SUPPLIED = {"segments", "orgs"}

# Required profile file names.
_REQUIRED_PROFILE_FILES = ["domain-glossary.md", "contacts.md", "conventions.md"]


def build_tokmap(cfg: dict) -> dict:
    """Build the token -> concrete-value map from a parsed config dict."""

    def g(*keys):
        return dig(cfg, *keys)

    return {
        "me":                    g("identity", "me"),
        "org":                   g("identity", "org"),
        "project_name":          g("project", "name"),
        "project_slug":          g("project", "slug"),
        "vault_path":            g("paths", "vault"),
        "work_folder":           g("paths", "work_folder"),
        "vault_meetings_subpath": g("paths", "vault_meetings_subpath"),
        "slack_workspace_id":    g("channels", "slack_workspace_id"),
        "slack_channel_id":      g("channels", "slack_channel_id"),
        "slack_user_id":         g("channels", "slack_user_id"),
        "slack_url_base":        g("channels", "slack_url_base"),
        "language":              g("locale", "language"),
        "business_style":        g("locale", "business_style"),
    }


def check_tokens(tokmap: dict, root: pathlib.Path) -> int:
    """Verify every engine {{token}} resolves to a concrete (non-placeholder) value.

    Returns the number of failures (0 = all good).
    """
    engine_dir = root / "references" / "engine"
    files = [f for f in engine_dir.glob("*.md") if f.name != "CONTRACT.md"]
    files.append(root / "SKILL.md")

    used: set[str] = set()
    for path in files:
        used |= set(re.findall(r"\{\{([a-z_]+)\}\}", path.read_text(encoding="utf-8")))

    print(f"== engine uses {len(used)} placeholder tokens")
    fail = 0
    for token in sorted(used):
        if token in _PROFILE_SUPPLIED:
            continue
        val = tokmap.get(token)
        if val is None:
            print(f"  UNRESOLVED: {{{{{token}}}}} has no config mapping")
            fail = 1
        elif "<" in str(val) or str(val).strip() == "":
            # catches "<...>" anywhere, e.g. projects/<slug>/meetings
            print(f"  PLACEHOLDER LEFT: {{{{{token}}}}} = {val!r} (config not filled)")
            fail = 1
    if not fail:
        print("  all tokens resolve to concrete config values")
    return fail


def check_path_safety(path_checks: dict[str, str]) -> int:
    """Reject traversal / absolute / expansion values in path-composing keys.

    Uses pathlib to normalise before checking so that a value like
    ``sub\\..\\..\\.\\secret`` still triggers the guard.

    Returns the number of failures (0 = all safe).
    """
    fail = 0
    for key, raw in path_checks.items():
        val = str(raw)
        # Normalise separators so Path can resolve ".." segments.
        try:
            normalised = pathlib.PurePosixPath(val.replace("\\", "/"))
            has_dotdot = ".." in normalised.parts
        except Exception:
            has_dotdot = ".." in val

        bad = (
            has_dotdot
            or val.startswith(("/", "\\", "~", "$", "%"))
            or ":" in val          # drive-absolute (C:), URL scheme, NTFS ADS
            or (key == "project_slug" and any(c in val for c in "/\\"))
        )
        if bad:
            print(
                f"  UNSAFE PATH VALUE: {key} = {val!r} "
                "(traversal/absolute/expansion rejected)"
            )
            fail = 1
    return fail


def check_profile(cfg: dict, root: pathlib.Path) -> int:
    """Verify that required profile markdown files exist on disk.

    Returns the number of failures (0 = profile complete).
    """
    profile_key = cfg["project"]["profile"]
    prof = root / profile_key
    missing = [n for n in _REQUIRED_PROFILE_FILES if not (prof / n).exists()]
    print(
        f"== profile {profile_key}: "
        + ("OK" if not missing else f"MISSING {missing}")
    )
    return 1 if missing else 0


def check_degradation(cfg: dict) -> int:
    """Informational dry-run: all tools OFF for 'daily' meeting -> file-only plan.

    Always returns 0 (degradation path is never an error).
    """
    print("== degradation dry-run (tools all OFF, category=daily)")
    cat = cfg["categories"]["daily"]
    plan = []
    for delivery, enabled in cat.items():
        if not enabled or enabled == "optional":
            continue
        if delivery == "canvas":
            plan.append("canvas -> .md fallback (slack off)")
        elif delivery == "gmail":
            plan.append("gmail -> .md fallback (gmail off)")
        else:
            plan.append(f"{delivery} -> file")
    print("  outputs:", ", ".join(plan) if plan else "(none)")
    print("  -> file-only, no errors")
    return 0


def main() -> int:
    """Run all dry-run checks and return the total failure count as exit code."""
    # 1. config parses
    cfg_path = ROOT / "config.yaml"
    if not cfg_path.exists():
        print(
            "FAIL: config.yaml missing -> "
            "cp config.example.yaml config.yaml 후 값 채우기"
        )
        return 1
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    print(
        f"== config.yaml parsed OK — "
        f"project={cfg['project']['name']} me={cfg['identity']['me']}"
    )

    # 2. Build token map
    tokmap = build_tokmap(cfg)

    # 3. Token resolution
    fail = check_tokens(tokmap, ROOT)

    # 3b. Path safety
    path_checks: dict[str, str] = {
        "vault_meetings_subpath": tokmap["vault_meetings_subpath"],
        "project_slug":           tokmap["project_slug"],
    }
    topics = (cfg.get("paths") or {}).get("topics_moc")
    if topics:
        path_checks["topics_moc"] = topics
    fail += check_path_safety(path_checks)

    # 4. Profile completeness
    fail += check_profile(cfg, ROOT)

    # 5. Degradation informational check
    fail += check_degradation(cfg)

    print("\nDRY-RUN:", "PASS" if not fail else "FAIL")
    return fail


if __name__ == "__main__":
    sys.exit(main())
