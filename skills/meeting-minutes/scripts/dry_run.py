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
import mm_state  # noqa: E402  — same plan source the runner freezes at approve time

# Tokens supplied by the profile rather than config — not checked against TOKMAP.
_PROFILE_SUPPLIED = {"segments", "orgs"}

# Required profile file names.
_REQUIRED_PROFILE_FILES = ["domain-glossary.md", "contacts.md", "conventions.md"]


def build_tokmap(cfg: dict) -> dict:
    """Build the token -> concrete-value map from a parsed config dict."""

    def g(*keys):
        # Missing sections (e.g. no-slack org deletes `channels`) must surface
        # as UNRESOLVED-token reports, not a KeyError traceback (H11 2026-07-12).
        try:
            return dig(cfg, *keys)
        except KeyError:
            return None

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

    profile=null is a VALID degraded mode per the engine contract (tooling.md:
    skip domain/contact cross-validation, proceed with placeholders) — the
    validator must not crash on it (codex review 2026-07-12 #11: TypeError).

    Returns the number of failures (0 = profile complete or valid null).
    """
    profile_key = (cfg.get("project") or {}).get("profile")
    if profile_key is None:
        print("== profile null: OK (generic mode — domain/contact cross-validation skipped)")
        return 0
    prof = root / str(profile_key)
    missing = [n for n in _REQUIRED_PROFILE_FILES if not (prof / n).exists()]
    print(
        f"== profile {profile_key}: "
        + ("OK" if not missing else f"MISSING {missing}")
    )
    return 1 if missing else 0


# Degraded destination per artifact. Anything unlisted lands as a plain file.
_TOOLLESS_FALLBACK = {
    "canvas": ".md fallback (slack off)",
    "gmail": ".md fallback (gmail off)",
}


def check_degradation(cfg: dict) -> int:
    """Informational dry-run: all tools OFF -> file-only plan per category.

    The plan comes from ``mm_state.plan_artifacts`` — the same function
    ``mm_run approve`` freezes into the manifest. A second matrix walk here
    would let the dry-run bless a plan the runner never executes.

    Category names are config-defined — iterating (not hardcoding 'daily')
    keeps the validator aligned with the generic-engine contract (codex
    review 2026-07-12 #11: KeyError on configs without a 'daily' category).

    Always returns 0 (degradation path is never an error).
    """
    categories = cfg.get("categories") or {}
    if not categories:
        print("== degradation dry-run: no categories in config — skipped")
        return 0
    for cat_name in categories:
        print(f"== degradation dry-run (tools all OFF, category={cat_name})")
        plan = [
            f"{artifact} -> {_TOOLLESS_FALLBACK.get(artifact, 'file')}"
            for artifact in mm_state.plan_artifacts(cfg, cat_name)
        ]
        print("  outputs:", ", ".join(plan) if plan else "(none)")
    print("  -> file-only, no errors")
    return 0


_BODY_MODES = {"chronological", "axis"}


def check_categories(cfg: dict) -> int:
    """Validate per-category tuning knobs that only the model reads.

    `body_mode` has no code path — a typo degrades silently into "the drafter
    ignored it", which looks identical to a correct run until someone reads the
    minutes. Returns the failure count.
    """
    fail = 0
    for name, row in (cfg.get("categories") or {}).items():
        mode = (row or {}).get("body_mode")
        if mode is not None and mode not in _BODY_MODES:
            print(f"  FAIL categories.{name}.body_mode={mode!r} — "
                  f"expected one of {sorted(_BODY_MODES)}")
            fail += 1
    if not fail:
        print("== categories: body_mode values OK")
    return fail


# Handlers the engine can run without any sibling skill: python libs + the built-in
# vision read. Anything else is looked up as an installed sibling skill.
_LIB_HANDLERS = {
    "python-pptx": "pptx",
    "pandas": "pandas",
    "fitz": "fitz",
    "markitdown": "markitdown",
}
_BUILTIN_HANDLERS = {"read-vision"}
_DEEP_READ_MODES = {"auto", "ask", "off"}


def _handler_available(name: str, skill_root: pathlib.Path) -> bool:
    """True if this handler can actually run here (lib importable / skill installed)."""
    if name in _BUILTIN_HANDLERS:
        return True
    module = _LIB_HANDLERS.get(name)
    if module:
        import importlib.util
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            return False
    return (skill_root.parent / name / "SKILL.md").exists()


def check_materials(cfg: dict, skill_root: pathlib.Path) -> int:
    """Validate the phase 1.5 handler chains and report what would actually run.

    A chain is allowed to resolve to nothing (built-in extraction is the floor),
    but a *malformed* chain is a real config error: at runtime it silently drops
    the material instead of degrading, which is the failure phase 1.5 exists to
    prevent. Returns the failure count.
    """
    materials = cfg.get("materials")
    if not materials:
        print("== materials (phase 1.5): no `materials` block — skipped")
        return 0
    fail = 0
    mode = materials.get("deep_read", "ask")
    if mode not in _DEEP_READ_MODES:
        print(f"  FAIL materials.deep_read={mode!r} — expected one of {sorted(_DEEP_READ_MODES)}")
        fail += 1
    print(f"== materials (phase 1.5): deep_read={mode}")
    handlers = materials.get("handlers") or {}
    for ext, chain in handlers.items():
        if not isinstance(chain, list) or not chain:
            print(f"  FAIL {ext}: handler chain must be a non-empty list (got {chain!r})")
            fail += 1
            continue
        picked = next((h for h in chain if _handler_available(h, skill_root)), None)
        print(
            f"  {ext}: {picked}" if picked
            else f"  {ext}: chain exhausted -> built-in extraction floor"
        )
    return fail


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

    # 4b. Category knobs the model reads but no code enforces
    fail += check_categories(cfg)

    # 5. Materials handler chains (phase 1.5)
    fail += check_materials(cfg, ROOT)

    # 6. Degradation informational check
    fail += check_degradation(cfg)

    print("\nDRY-RUN:", "PASS" if not fail else "FAIL")
    return fail


if __name__ == "__main__":
    sys.exit(main())
