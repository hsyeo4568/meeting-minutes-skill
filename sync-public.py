#!/usr/bin/env python3
"""Sync public skill files from local working copies into this publish repo.

Usage:
    python sync-public.py            # copy + gates + stage (no commit)
    python sync-public.py --commit "msg"   # additionally commit if gates pass

Reads source locations from sync-config.local.json (gitignored) next to this
script:
    { "sources": { "skills/meeting-minutes": "C:/path/to/meeting-minutes",
                   "skills/stt-transcript-fix": "C:/path/to/stt-transcript-fix" } }

Never pushes. Gates: leak-pattern scan on every candidate file BEFORE copy,
then verify.sh (if bash is available) after copy.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
CONFIG = REPO / "sync-config.local.json"

# Mirrors skills/meeting-minutes/.gitignore + hygiene. Paths relative to each skill root.
EXCLUDE = [
    "config.yaml",
    "profiles/*",  # all profiles private by default...
    "*.bak",
    "*.backup.*",  # user backup convention: <file>.backup.<date>
    "*.orig",
    "__pycache__*",
    "verify-denylist.local",  # private org/people terms for verify.sh
    "fixtures/*",  # local regression fixtures (may contain real transcripts/names)
]
INCLUDE_PROFILES = ["profiles/_template", "profiles/example-acme"]  # ...except shipped examples

# Generic forbidden patterns (paths, plates, common token shapes). Your PRIVATE
# org/people terms go in sync-config.local.json under "denylist" (list of regex
# alternations) — never hardcode them here; this file is published.
LEAK_BASE = (
    r"C:/Users|/Users/|[0-9]{2}[가-힣][0-9]{4}"
    r"|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|xox[bp]-"
)


def build_leak_pat(cfg: dict) -> re.Pattern:
    denylist = list(cfg.get("denylist", []))
    if not denylist:
        # An empty denylist silently disables the org/people leak gate — refuse to publish.
        raise SystemExit(
            "FATAL: 'denylist' missing or empty in sync-config.local.json — "
            "org/people leak gate would be disabled. Fix the config before publishing."
        )
    parts = [LEAK_BASE] + denylist
    return re.compile("|".join(parts), re.IGNORECASE)
# Files that legitimately mention forbidden tokens (they document the ban).
LEAK_EXEMPT = {"references/engine/CONTRACT.md", "verify.sh"}


def excluded(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    for inc in INCLUDE_PROFILES:
        if rel == inc or rel.startswith(inc + "/"):
            return False
    return any(fnmatch.fnmatch(rel, pat) or rel.startswith(pat.rstrip("*")) and pat.endswith("*")
               for pat in EXCLUDE) or any(
        fnmatch.fnmatch(part, pat) for part in rel.split("/") for pat in ("__pycache__", ".git")
    )


def candidate_files(src_root: Path):
    for p in sorted(src_root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src_root).as_posix()
        if not excluded(rel):
            yield rel, p


def leak_scan(files, pat: re.Pattern) -> list[str]:
    hits = []
    for rel, path in files:
        if rel in LEAK_EXEMPT:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            hits.append(f"{rel}: unreadable ({e})")
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = pat.search(line)
            if m:
                hits.append(f"{rel}:{i}: {m.group(0)!r} in: {line.strip()[:80]}")
    return hits


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", metavar="MSG", help="commit after gates pass")
    ap.add_argument("--prune", action="store_true",
                    help="delete repo files reported stale (in repo, gone from source)")
    args = ap.parse_args()

    if not CONFIG.exists():
        print(f"FATAL: {CONFIG.name} missing. Create it with your local source paths (see docstring).")
        return 2
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    sources = cfg["sources"]
    leak_pat = build_leak_pat(cfg)

    # Regenerate the free-tier prompt from engine sources BEFORE syncing, so
    # PROMPT-ONLY.md can never drift from writing-principles/output-templates.
    print("== Regen: PROMPT-ONLY (build_prompt.py) ==")
    mm_src = Path(sources.get("skills/meeting-minutes", ""))
    builder = mm_src / "scripts" / "build_prompt.py"
    if builder.exists():
        r = subprocess.run([sys.executable, str(builder)], capture_output=True, text=True)
        print("  " + ((r.stdout or r.stderr or "").strip() or "(no output)"))
        if r.returncode != 0:
            print("  BLOCK — PROMPT-ONLY regeneration failed")
            return 1
    else:
        print("  SKIP — build_prompt.py not found")

    all_hits, plans = [], []
    for dest_rel, src in sources.items():
        src_root = Path(src)
        if not src_root.is_dir():
            print(f"FATAL: source not found: {src_root}")
            return 2
        files = list(candidate_files(src_root))
        all_hits += leak_scan(files, leak_pat)
        plans.append((REPO / dest_rel, src_root, files))

    print("== Gate: leak scan (pre-copy) ==")
    if all_hits:
        print("  BLOCK — forbidden tokens in source public files; nothing copied:")
        for h in all_hits:
            print(f"    {h}")
        return 1
    print("  OK")

    copied = 0
    for dest_root, src_root, files in plans:
        for rel, path in files:
            dst = dest_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or dst.read_bytes() != path.read_bytes():
                shutil.copy2(path, dst)
                copied += 1
        # stale detection (present in repo, gone from source) — warn, or delete with --prune
        for p in dest_root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(dest_root).as_posix()
                if not excluded(rel) and rel not in {r for r, _ in files}:
                    if args.prune:
                        p.unlink()
                        print(f"  PRUNED stale: {dest_root.name}/{rel}")
                    else:
                        print(f"  WARN stale in repo (not in source): {dest_root.name}/{rel} (--prune to delete)")
    print(f"== Copy: {copied} file(s) updated ==")

    # Paste-in prompts must be fully resolved — an unsubstituted {{placeholder}}
    # means build_prompt regression (free-tier users get a broken prompt).
    print("== Gate: PROMPT-ONLY placeholder residue ==")
    residue = []
    for p in REPO.glob("skills/*/PROMPT-ONLY.md"):
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "{{" in line:
                residue.append(f"{p.relative_to(REPO).as_posix()}:{i}: {line.strip()[:70]}")
    if residue:
        print("  BLOCK — unresolved placeholders:")
        for h in residue:
            print(f"    {h}")
        return 1
    print("  OK")

    print("== Gate: verify.sh ==")
    vsh = REPO / "skills/meeting-minutes/verify.sh"
    try:
        r = subprocess.run(["bash", str(vsh)], cwd=vsh.parent, capture_output=True, text=True)
        print("  " + (r.stdout or "").strip().replace("\n", "\n  "))
        if r.returncode != 0:
            print("  BLOCK — verify.sh failed")
            return 1
    except FileNotFoundError:
        print("  SKIP — bash not available (run verify.sh manually before push)")

    # Explicit paths only — NOT `git add -A`. Blind staging would sweep any
    # stray file in the repo root (temp diffs, editor backups) into a public
    # commit, bypassing the pre-copy leak scan (which only sees source files).
    subprocess.run(["git", "add", "skills", "README.md", "sync-public.py", ".gitignore"],
                   cwd=REPO, check=True)
    st = subprocess.run(["git", "status", "--short"], cwd=REPO, capture_output=True, text=True).stdout
    print("== Staged ==\n" + (st or "  (no changes)"))

    if args.commit and st.strip():
        subprocess.run(["git", "commit", "-m", args.commit], cwd=REPO, check=True)
        print("== Committed (push is manual — run secret recon first) ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
