# -*- coding: utf-8 -*-
"""Safe correction script for stt-transcript-fix. v2.2

Modes:
  1. Hardcoded: edit REPLACEMENTS/MARKERS/CONTEXTUAL below, run directly
  2. JSON input: python fix_template.py <transcript> --json replacements.json
  3. Quick-scan: python fix_template.py <transcript> --quick-scan

Options: --dry-run --force --json <file> --quick-scan --threshold N

JSON: {"replacements": [["old","new",count],...], "markers": [[line,"txt"],...],
       "contextual": [...], "quick_scan": true, "min_variant_density": 0.0005}
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).parent))
import _utils as U
from _utils import QUICK_SCAN_MIN_DENSITY

# --- AGENT FILLS IN ---
REPLACEMENTS = []
MARKERS = []
CONTEXTUAL = []


class CorrectionSet(NamedTuple):
    """Bundles the four data collections produced by JSON loading / defaults."""
    reps: list        # [old, new, expected_count]
    ctx: list         # [old, new, expected_count]  (contextual — softer gate)
    markers: list     # [line_num, marker_text]
    spans: list       # [(placeholder, original_span)]  from mask_comments


def load_replacements(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="fix_template.py",
        description="Safe correction script for stt-transcript-fix.",
    )
    p.add_argument("transcript", help="transcript .txt to correct")
    p.add_argument("--json", dest="json_file", metavar="FILE",
                   help="JSON correction file (replacements/markers/contextual)")
    p.add_argument("--threshold", type=float, default=QUICK_SCAN_MIN_DENSITY,
                   metavar="N", help="quick-scan variant density threshold")
    p.add_argument("--dry-run", action="store_true", help="show diff, no write")
    p.add_argument("--force", action="store_true", help="apply despite count mismatch")
    p.add_argument("--quick-scan", dest="quick_scan", action="store_true",
                   help="density check only (0=skip, 1=proceed)")
    p.add_argument("-V", "--version", action="version", version="fix_template v2.2")
    return p.parse_args(argv)


def _find_count_mismatches(masked: str, reps: list, ctx: list) -> list[tuple]:
    """Pure query: return list of (old, new, expected, actual, is_ctx) for mismatches."""
    results = []
    for old_str, new_str, expected in reps:
        actual = U.count_variant(masked, old_str, new_str)
        if actual != expected:
            results.append((old_str, new_str, expected, actual, False))
    for old_str, new_str, expected in ctx:
        actual = U.count_variant(masked, old_str, new_str)
        if actual != expected:
            results.append((old_str, new_str, expected, actual, True))
    return results


def verify_counts(masked: str, reps: list, ctx: list, force: bool) -> bool:
    """Print count check results. Returns True if a HALT-worthy mismatch exists.

    Implemented in terms of _find_count_mismatches() — no duplicated count loop.
    """
    mismatch_list = _find_count_mismatches(masked, reps, ctx)
    # Build lookup: (old_str, is_ctx) -> (expected, actual)
    mismatch_map = {(old, is_ctx): (expected, actual)
                    for old, _new, expected, actual, is_ctx in mismatch_list}

    for old_str, new_str, expected in reps:
        if (old_str, False) in mismatch_map:
            exp, actual = mismatch_map[(old_str, False)]
            if force:
                print(f"  FORCE: '{old_str}' expected={exp} actual={actual}")
            else:
                print(f"  COUNT MISMATCH: '{old_str}' expected={exp} actual={actual}")
        else:
            actual = U.count_variant(masked, old_str, new_str)
            print(f"  OK: '{old_str}' x{actual}")

    for old_str, new_str, expected in ctx:
        if (old_str, True) in mismatch_map:
            exp, actual = mismatch_map[(old_str, True)]
            print(f"  CTX WARN: '{old_str}' x{actual} (expected={exp})")
        else:
            actual = U.count_variant(masked, old_str, new_str)
            print(f"  CTX OK: '{old_str}' x{actual} (expected={expected})")

    return bool(mismatch_list) and not force


def apply_corrections(masked: str, cs: CorrectionSet, original: str, le: str) -> str:
    """Apply replacements, restore comments, then insert markers. Returns new text.

    Longest old-string first: an overlapping shorter rule must not rewrite the
    inside of a longer target before the longer rule runs (운동→응동 destroying
    운동폭→변동폭 — codex review 2026-07-12 #6). Counts were verified against the
    same pre-apply text, so ordering does not affect the verify gate.
    """
    by_len = lambda r: -len(r[0])  # noqa: E731
    changed = masked
    for old_str, new_str, _ in sorted(cs.reps, key=by_len):
        changed = U.safe_replace(changed, old_str, new_str)
    for old_str, new_str, expected in sorted(cs.ctx, key=by_len):
        if U.count_variant(changed, old_str, new_str) == expected:
            changed = U.safe_replace(changed, old_str, new_str)

    # Restore comments
    for ph, span in cs.spans:
        changed = changed.replace(ph, span)

    # Apply markers (speaker-header guard)
    if cs.markers:
        # HH:MM / H:MM / HH:MM:SS, optionally [bracketed] — timestamp-first
        # header formats (codex review 2026-07-12 #7; timestamp-last formats are
        # out of scope for this skill's supported transcript format).
        spkr_pat = re.compile(r'^\[?\d{1,2}:\d{2}(?::\d{2})?\]?\s')
        lines = changed.splitlines()
        for line_num, marker_text in sorted(cs.markers, reverse=True):
            idx = line_num - 1
            if 0 <= idx < len(lines):
                if spkr_pat.match(lines[idx]):
                    print(f"  MARKER WARN: L{line_num} is speaker header — SKIPPED")
                    continue
                if marker_text not in lines[idx]:
                    lines[idx] = lines[idx].rstrip() + " " + marker_text
                else:
                    print(f"  MARKER DUP: L{line_num} already has")
        changed = (le.join(lines)) + (le if original.endswith(le) else "")
    return changed


def write_atomic(
    target_path: Path,
    changed: str,
    enc: str,
    bak_path: Path,
    reps: list,
    ctx: list,
    markers_list: list,
) -> None:
    """Atomic write via temp (preserves original on crash; restores .bak on error).

    Precondition: bak_path must exist before calling (caller is responsible for
    creating it via shutil.copy2 before calling write_atomic).
    """
    assert bak_path.exists(), "bak_path must exist before calling write_atomic"
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="fix_", dir=target_path.parent)
        # encoding=enc + newline="" preserve original encoding and line endings
        with open(fd, "w", encoding=enc, newline="") as f:
            f.write(changed)
        Path(tmp_path).replace(target_path)
        print(f"DONE: {len(reps)}+{len(ctx)} replacements, {len(markers_list)} markers")
        # tmp was renamed onto target by replace() — no leftover to clean on success
    except OSError:
        if tmp_path and Path(tmp_path).exists():
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError as e:
                print(f"NOTE: temp cleanup failed ({e})")
        shutil.copy2(bak_path, target_path)
        print("ERROR during write — RESTORED from .bak")
        raise


def main() -> int:
    args = parse_args()

    target_path = Path(args.transcript)
    if not target_path.exists():
        print(f"ERROR: file not found: {target_path}")
        sys.exit(1)

    # Load correction data (before any file read — no lock needed yet)
    reps = list(REPLACEMENTS)
    markers_list = list(MARKERS)
    ctx = list(CONTEXTUAL)
    qs_enabled = False
    min_dens = args.threshold

    json_file = Path(args.json_file) if args.json_file else None
    if json_file:
        if not json_file.exists():
            # Silent fall-through to "no corrections" would report success on a
            # typo'd path (codex review 2026-07-12, additional finding) — fail loud.
            print(f"ERROR: --json file not found: {json_file}")
            sys.exit(1)
        data = load_replacements(json_file)
        reps = data.get("replacements", [])
        markers_list = data.get("markers", [])
        ctx = data.get("contextual", [])
        qs_enabled = data.get("quick_scan", False)
        min_dens = data.get("min_variant_density", args.threshold)

    all_rep = reps + ctx

    # Cross-rule contamination guard (operational-adversarial 2026-07-12 H6):
    # if rule A's NEW contains rule B's OLD, applying A creates fresh matches
    # for B — the count-verify gate (checked against the ORIGINAL text) passes,
    # then apply corrupts silently. Fail loud; --force overrides deliberately.
    for i, (_old_i, new_i, _e1) in enumerate(all_rep):
        for j, (old_j, _new_j, _e2) in enumerate(all_rep):
            if i != j and old_j in str(new_i):
                msg = (f"CROSS-RULE RISK: rule {j + 1} old '{old_j}' occurs inside "
                       f"rule {i + 1} new '{new_i}'")
                if args.force:
                    print(f"  FORCE: {msg}")
                else:
                    print(f"  {msg}")
                    print("HALT: cross-rule contamination — merge/split the rules or rerun with --force")
                    sys.exit(1)

    # Lock BEFORE reading — reading first then locking later let a concurrent
    # writer's changes be overwritten with our stale snapshot (TOCTOU, codex
    # review 2026-07-12 #4). Released in finally on ALL paths.
    if not U.acquire_lock(target_path):
        print(f"ERROR: could not lock {target_path.name}")
        sys.exit(1)
    try:
        try:
            enc = U.detect_encoding(target_path)
        except UnicodeError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
        # newline="" preserves original line endings (no universal-newline translation)
        with open(target_path, "r", encoding=enc, newline="") as f:
            original = f.read()

        # Quick-scan
        if args.quick_scan or qs_enabled:
            masked, _ = U.mask_comments(original)
            if not U.quick_scan_variants(masked, all_rep, min_dens):
                print("QUICK-SCAN SKIP: low density — no corrections needed")
                return 0
            if args.quick_scan:
                print("QUICK-SCAN PASS: warrants full correction")
                return 1

        if not all_rep and not markers_list:
            print("NOTE: no replacements or markers specified")
            return 0

        original_lines = original.splitlines()
        le = U.detect_line_ending(original)

        # Backup
        bak_path = target_path.with_suffix(target_path.suffix + ".bak")
        if not args.dry_run:
            shutil.copy2(target_path, bak_path)

        # Mask comments
        masked, spans = U.mask_comments(original)
        cs = CorrectionSet(reps=reps, ctx=ctx, markers=markers_list, spans=spans)

        # Log substring-risky pairs
        for old_str, new_str, _ in all_rep:
            if U.is_substring_of_either(old_str, new_str):
                print(f"  NOTE: substring-risky '{old_str}'↔'{new_str}' — using word-boundary regex")

        # Verify counts
        if verify_counts(masked, reps, ctx, args.force):
            print("HALT: count mismatches")
            sys.exit(1)

        # Apply corrections + markers
        changed = apply_corrections(masked, cs, original, le)

        # Verify line count
        new_lines = changed.splitlines()
        if len(new_lines) != len(original_lines):
            print(f"LINE MISMATCH: {len(original_lines)} → {len(new_lines)}")
            if not args.dry_run:
                shutil.copy2(bak_path, target_path)
                print("RESTORED from .bak")
            sys.exit(1)
        print(f"Lines OK: {len(new_lines)}")

        # Output
        if args.dry_run:
            diffs = U.compute_line_diff(original, changed)
            print(f"\nDRY-RUN: {len(reps)} sets + {len(ctx)} ctx + {len(markers_list)} markers")
            for d in diffs:
                print(d)
        else:
            write_atomic(target_path, changed, enc, bak_path, reps, ctx, markers_list)
    finally:
        U.release_lock(target_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
