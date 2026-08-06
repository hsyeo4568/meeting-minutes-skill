#!/usr/bin/env python3
"""Update an installed copy of this skill without touching what the user wrote.

    python scripts/update_install.py --target ~/.claude/skills/meeting-minutes
    python scripts/update_install.py --target ... --apply

Run it from a fresh clone (that clone is the default `--source`). Engine files
are replaced; the user's own `profiles/<team>/`, `verify-denylist.local`,
`.mm/` and local `fixtures/` are outside the managed set and are never written
or deleted. `config.yaml` is likewise never written — it is only read, after
the copy, to list the config keys this version added. Without `--apply` the
script only prints the plan.
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Everything the engine owns. Anything not listed here belongs to the user.
MANAGED_FILES = [
    "SKILL.md", "ONBOARDING.md", "SETUP.md", "PROMPT-ONLY.md",
    "config.example.yaml", "requirements.txt", "verify.sh",
    ".gitignore", ".gitattributes",
]
MANAGED_DIRS = [
    "references", "scripts", "tests", "evals",
    "profiles/_template", "profiles/example-acme",
]
NEVER_TOUCH = ["config.yaml", "verify-denylist.local", ".mm/", "fixtures/",
               "profiles/<사용자 프로필>"]
# Directory names that sit inside managed trees but hold local data. `fixtures/`
# is where a team keeps real transcripts to test against (see .gitignore), so
# walking `tests/` as engine territory would prune them away.
PROTECTED_PARTS = {"fixtures", "__pycache__"}


def managed_rel_paths(root: Path) -> set[str]:
    found = {f for f in MANAGED_FILES if (root / f).is_file()}
    for d in MANAGED_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_file() and not PROTECTED_PARTS.intersection(p.parts):
                found.add(p.relative_to(root).as_posix())
    return found


def plan(source: Path, target: Path) -> tuple[list[str], list[str], list[str]]:
    src_files, dst_files = managed_rel_paths(source), managed_rel_paths(target)
    added = sorted(src_files - dst_files)
    removed = sorted(dst_files - src_files)
    updated = sorted(
        rel for rel in src_files & dst_files
        if not filecmp.cmp(source / rel, target / rel, shallow=False)
    )
    return added, updated, removed


def flatten_keys(node, prefix: str = "") -> set[str]:
    if not isinstance(node, dict):
        return set()
    keys = set()
    for k, v in node.items():
        path = f"{prefix}{k}"
        keys.add(path)
        keys |= flatten_keys(v, prefix=f"{path}.")
    return keys


def new_config_keys(source: Path, target: Path) -> list[str]:
    """Keys the shipped example gained that the user's config has never seen."""
    example, config = source / "config.example.yaml", target / "config.yaml"
    if not (example.is_file() and config.is_file()):
        return []
    try:
        import yaml
    except ImportError:
        print("  (PyYAML 없음 — 새 설정 키 비교 생략)")
        return []
    try:
        want = flatten_keys(yaml.safe_load(example.read_text(encoding="utf-8")) or {})
        have = flatten_keys(yaml.safe_load(config.read_text(encoding="utf-8")) or {})
    except Exception as e:
        print(f"  (설정 비교 실패: {e})")
        return []
    # Category rows differ per install, so compare the leaf name, not the path.
    have_leaves = {k.rsplit(".", 1)[-1] for k in have}
    return sorted({k for k in want if k.rsplit(".", 1)[-1] not in have_leaves})


def copy(source: Path, target: Path, rels: list[str]) -> None:
    for rel in rels:
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, dst)


def prune(target: Path, rels: list[str]) -> None:
    for rel in rels:
        p = target / rel
        if p.is_file():
            p.unlink()
        parent = p.parent
        while parent != target and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="설치된 meeting-minutes 스킬을 개인 설정 보존한 채 갱신")
    ap.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent,
                    help="새 버전 clone 안의 skills/meeting-minutes 경로 (기본: 이 스크립트 위치)")
    ap.add_argument("--target", type=Path, required=True, help="설치된 스킬 경로")
    ap.add_argument("--apply", action="store_true", help="실제로 복사 (없으면 계획만 출력)")
    args = ap.parse_args()

    source, target = args.source.expanduser().resolve(), args.target.expanduser().resolve()
    if not (source / "SKILL.md").is_file():
        print(f"중단 — 새 버전 소스가 아님(SKILL.md 없음): {source}")
        return 2
    if not (target / "SKILL.md").is_file():
        print(f"중단 — 설치된 스킬이 아님(SKILL.md 없음): {target}\n"
              f"  신규 설치라면 폴더째 복사할 것. 이 스크립트는 기존 설치 갱신 전용.")
        return 2
    if source == target:
        print("중단 — source와 target이 같은 경로")
        return 2

    added, updated, removed = plan(source, target)
    print(f"== 갱신 계획: {target}")
    for label, rels in (("추가", added), ("교체", updated), ("삭제(상위에서 없어짐)", removed)):
        print(f"  {label} {len(rels)}건" + (f": {', '.join(rels[:8])}" if rels else ""))
        if len(rels) > 8:
            print(f"    … 외 {len(rels) - 8}건")
    print("  건드리지 않음: " + ", ".join(NEVER_TOUCH))

    if not (added or updated or removed):
        print("== 이미 최신 — 할 일 없음")
        return 0
    if not args.apply:
        print("== 계획만 출력함. 실제 적용하려면 --apply")
        return 0

    # Two updates in the same minute must not collide — the backup is the only
    # way back, so a name clash may never abort the run.
    stamp = f"{datetime.now():%Y%m%d-%H%M}"
    backup = target.parent / f"{target.name}.backup.{stamp}"
    serial = 2
    while backup.exists():
        backup = target.parent / f"{target.name}.backup.{stamp}-{serial}"
        serial += 1
    shutil.copytree(target, backup, dirs_exist_ok=False)
    print(f"== 백업: {backup}")

    copy(source, target, added + updated)
    prune(target, removed)
    print(f"== 적용 완료 (추가 {len(added)} · 교체 {len(updated)} · 삭제 {len(removed)})")

    fresh = new_config_keys(source, target)
    if fresh:
        print("== 새로 생긴 설정 키 (지금 config.yaml엔 없음 — 없어도 동작, 쓰고 싶으면 추가):")
        for k in fresh[:20]:
            print(f"  - {k}")
        if len(fresh) > 20:
            print(f"  … 외 {len(fresh) - 20}건 — config.example.yaml 과 직접 대조 권장")
    print("== 확인: python scripts/dry_run.py  → PASS 나오면 끝")
    return 0


if __name__ == "__main__":
    sys.exit(main())
