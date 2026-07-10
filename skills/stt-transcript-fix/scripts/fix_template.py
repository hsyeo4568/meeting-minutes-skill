# -*- coding: utf-8 -*-
"""Safe correction script for stt-transcript-fix. v2.1

Modes:
  1. Hardcoded: edit REPLACEMENTS/MARKERS/CONTEXTUAL below, run directly
  2. JSON input: python fix_template.py <transcript> --json replacements.json
  3. Quick-scan: python fix_template.py <transcript> --quick-scan

Options: --dry-run --force --json <file> --quick-scan --threshold N

JSON: {"replacements": [["old","new",count],...], "markers": [[line,"txt"],...],
       "contextual": [...], "quick_scan": true, "min_variant_density": 0.0005}
"""
import json
import sys
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _utils as U

QUICK_SCAN_MIN_DENSITY = 0.0003

# --- AGENT FILLS IN ---
REPLACEMENTS = []
MARKERS = []
CONTEXTUAL = []


def load_replacements(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    all_args = sys.argv[1:]

    if "--version" in all_args or "-V" in all_args:
        print("fix_template v2.1")
        return 0

    dry_run = "--dry-run" in all_args
    force = "--force" in all_args
    quick_scan_only = "--quick-scan" in all_args

    threshold = QUICK_SCAN_MIN_DENSITY
    if "--threshold" in all_args:
        idx = all_args.index("--threshold")
        try:
            threshold = float(all_args[idx + 1])
        except (ValueError, IndexError):
            pass

    json_file = None
    if "--json" in all_args:
        idx = all_args.index("--json")
        if idx + 1 < len(all_args):
            json_file = Path(all_args[idx + 1])

    positional = [a for a in all_args if not a.startswith("--")]
    flags_set = set(a for a in all_args if a.startswith("--"))
    for f in flags_set:
        if f in positional:
            positional.remove(f)

    # Remove --threshold value from positional
    filtered = []
    skip_next = False
    for a in positional:
        if skip_next:
            skip_next = False
            continue
        if a.startswith("--threshold"):
            skip_next = True
            continue
        filtered.append(a)
    positional = filtered

    if not positional:
        print("usage: fix_template.py <transcript> [--dry-run] [--force] [--json <file>] [--quick-scan] [--threshold N]")
        sys.exit(1)

    target_path = Path(positional[0])
    if not target_path.exists():
        print(f"ERROR: file not found: {target_path}")
        sys.exit(1)

    enc = U.detect_encoding(target_path)
    with open(target_path, "r", encoding=enc) as f:
        original = f.read()

    # Load correction data
    reps = list(REPLACEMENTS)
    markers_list = list(MARKERS)
    ctx = list(CONTEXTUAL)
    qs_enabled = False
    min_dens = threshold

    if json_file and json_file.exists():
        data = load_replacements(json_file)
        reps = data.get("replacements", [])
        markers_list = data.get("markers", [])
        ctx = data.get("contextual", [])
        qs_enabled = data.get("quick_scan", False)
        min_dens = data.get("min_variant_density", threshold)

    all_rep = reps + ctx

    # Quick-scan
    if quick_scan_only or qs_enabled:
        masked, _ = U.mask_comments(original)
        if not U.quick_scan_variants(masked, all_rep, min_dens):
            print(f"QUICK-SCAN SKIP: low density — no corrections needed")
            return 0
        if quick_scan_only:
            print("QUICK-SCAN PASS: warrants full correction")
            return 1

    if not all_rep and not markers_list:
        print("NOTE: no replacements or markers specified")
        return 0

    # Lock
    if not U.acquire_lock(target_path):
        print(f"ERROR: could not lock {target_path.name}")
        sys.exit(1)

    original_lines = original.splitlines()
    le = U.detect_line_ending(original)

    # Backup
    bak_path = target_path.with_suffix(target_path.suffix + ".bak")
    if not dry_run:
        shutil.copy2(target_path, bak_path)

    # Mask comments
    masked, spans = U.mask_comments(original)

    # Log substring-risky pairs
    for old_str, new_str, _ in all_rep:
        if U.is_substring_risky(old_str, new_str):
            print(f"  NOTE: substring-risky '{old_str}'↔'{new_str}' — using word-boundary regex")

    # Verify counts
    failed = False
    for old_str, new_str, expected in reps:
        actual = masked.count(old_str)
        if actual != expected:
            if force:
                print(f"  FORCE: '{old_str}' expected={expected} actual={actual}")
            else:
                print(f"  COUNT MISMATCH: '{old_str}' expected={expected} actual={actual}")
                failed = True
        else:
            print(f"  OK: '{old_str}' x{actual}")

    for old_str, new_str, expected in ctx:
        actual = masked.count(old_str)
        tag = "CTX OK" if actual == expected else "CTX WARN"
        print(f"  {tag}: '{old_str}' x{actual} (expected={expected})")
        if actual != expected and not force:
            failed = True

    if failed:
        print("HALT: count mismatches")
        U.release_lock(target_path)
        sys.exit(1)

    # Apply replacements
    changed = masked
    for old_str, new_str, _ in reps:
        changed = U.safe_replace(changed, old_str, new_str)
    for old_str, new_str, expected in ctx:
        if changed.count(old_str) == expected:
            changed = U.safe_replace(changed, old_str, new_str)

    # Restore comments
    for ph, span in spans:
        changed = changed.replace(ph, span)

    # Apply markers (speaker-header guard)
    if markers_list:
        import re as re_m
        spkr_pat = re_m.compile(r'^\d{2}:\d{2}\s')
        lines = changed.splitlines()
        for line_num, marker_text in sorted(markers_list, reverse=True):
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

    # Verify line count
    new_lines = changed.splitlines()
    if len(new_lines) != len(original_lines):
        print(f"LINE MISMATCH: {len(original_lines)} → {len(new_lines)}")
        if not dry_run:
            shutil.copy2(bak_path, target_path)
            print("RESTORED from .bak")
        U.release_lock(target_path)
        sys.exit(1)
    print(f"Lines OK: {len(new_lines)}")

    # Output
    if dry_run:
        diffs = U.compute_line_diff(original, changed)
        print(f"\nDRY-RUN: {len(reps)} sets + {len(ctx)} ctx + {len(markers_list)} markers")
        for d in diffs:
            print(d)
    else:
        # Atomic write via temp (preserves original on crash)
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="fix_", dir=target_path.parent)
            with open(fd, "w", encoding="utf-8", newline="") as f:
                f.write(changed)
            Path(tmp_path).replace(target_path)
            print(f"DONE: {len(reps)}+{len(ctx)} replacements, {len(markers_list)} markers")
            if 'tmp_path' in dir() and tmp_path and Path(tmp_path).exists():
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            if tmp_path and Path(tmp_path).exists():
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass
            shutil.copy2(bak_path, target_path)
            print("ERROR during write — RESTORED from .bak")
            raise


if __name__ == "__main__":
    sys.exit(main())
