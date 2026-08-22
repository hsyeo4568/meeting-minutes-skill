# -*- coding: utf-8 -*-
"""Gate #2 — degradation contract check (formerly a manual SKILL.md read-through).

A read-through catches drift only when someone actually performs it, and
`verify.sh` has been printing gate #2 as "skipped" on every run. The parts of
that read-through that are mechanical are enforced here instead:

1. every tool the config can switch on declares a no-tool fallback, both in the
   interface contract and in the degradation matrix the runtime points at;
2. the never-fail principle is still stated in SKILL.md;
3. every engine reference SKILL.md links to exists on disk.

Judgement calls (is the documented fallback the *right* one?) stay human. This
gate only guarantees that no tool ships without a documented fallback at all.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - fallback parser below covers the gate
    yaml = None

CONFIG_NAME = "config.example.yaml"
SKILL_NAME = "SKILL.md"
ENGINE_DIR = Path("references") / "engine"
MATRIX_FILES = (ENGINE_DIR / "tooling.md", ENGINE_DIR / "CONTRACT.md")
NEVER_FAIL_PATTERN = re.compile(r"never\s+fail\s+on\s+a\s+missing\s+tool", re.IGNORECASE)
ENGINE_LINK_PATTERN = re.compile(r"references/engine/([A-Za-z0-9_-]+\.md)")
# A degradation row names the tool in the first cell: "| slack_mcp | write ... |".
TABLE_ROW_TEMPLATE = r"^\|\s*`?{tool}`?\s*(\||\s)"


def read_tools(config_path: Path) -> list[str]:
    """Return the tool keys under `tools:` in declaration order."""
    text = config_path.read_text(encoding="utf-8")
    if yaml is not None:
        loaded = yaml.safe_load(text) or {}
        tools = loaded.get("tools") or {}
        if isinstance(tools, dict):
            return [str(key) for key in tools]
    return _read_tools_without_yaml(text)


def _read_tools_without_yaml(text: str) -> list[str]:
    """Indent-scoped fallback parser so the gate runs without PyYAML installed."""
    tools: list[str] = []
    inside = False
    for line in text.splitlines():
        if not inside:
            inside = line.strip() == "tools:"
            continue
        if line.strip() and not line.startswith((" ", "\t")):
            break
        match = re.match(r"\s+([A-Za-z0-9_]+)\s*:", line)
        if match:
            tools.append(match.group(1))
    return tools


def documents_tool(text: str, tool: str) -> bool:
    """True when a Markdown table row in `text` starts with this tool's name."""
    pattern = re.compile(TABLE_ROW_TEMPLATE.format(tool=re.escape(tool)), re.MULTILINE)
    return bool(pattern.search(text))


def check(root: Path) -> list[str]:
    """Return one message per degradation-contract violation; empty means pass."""
    root = Path(root)
    failures: list[str] = []

    config_path = root / CONFIG_NAME
    skill_path = root / SKILL_NAME
    for required in (config_path, skill_path):
        if not required.is_file():
            failures.append(f"missing {required.name}")
    if failures:
        return failures

    skill_text = skill_path.read_text(encoding="utf-8")

    matrices = {}
    for relative in MATRIX_FILES:
        path = root / relative
        if not path.is_file():
            failures.append(f"missing degradation matrix: {relative.as_posix()}")
            continue
        matrices[relative.name] = path.read_text(encoding="utf-8")

    for tool in read_tools(config_path):
        for name, text in matrices.items():
            if not documents_tool(text, tool):
                failures.append(f"{tool}: no degradation row in {name} — tool ships without a documented fallback")

    if not NEVER_FAIL_PATTERN.search(skill_text):
        failures.append(f"{SKILL_NAME}: never-fail principle is no longer stated")

    linked = sorted(set(ENGINE_LINK_PATTERN.findall(skill_text)))
    for name in linked:
        if not (root / ENGINE_DIR / name).is_file():
            failures.append(f"{SKILL_NAME} links references/engine/{name}, which does not exist")
    for relative in MATRIX_FILES:
        if relative.name not in linked:
            failures.append(f"{SKILL_NAME} no longer links references/engine/{relative.name} — matrix unreachable")

    return failures


def main(argv: list[str] | None = None) -> int:
    # verify.sh runs this under a cp949 console; an em dash would otherwise die
    # with UnicodeEncodeError and fail the gate for the wrong reason.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):  # pragma: no cover - detached streams
                pass
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent
    failures = check(root)
    if failures:
        for failure in failures:
            print(f"  {failure}")
        print(f"  FAIL — {len(failures)} degradation contract violation(s)")
        return 1
    print("  OK — every configured tool declares a fallback; engine references reachable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
