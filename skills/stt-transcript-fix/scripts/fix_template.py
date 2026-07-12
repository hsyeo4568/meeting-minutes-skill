# -*- coding: utf-8 -*-
"""Safe correction script for stt-transcript-fix. v2.3

Modes:
  1. Hardcoded: edit REPLACEMENTS/MARKERS/CONTEXTUAL below, run directly
  2. JSON input: python fix_template.py <transcript> --json replacements.json
  3. Quick-scan: python fix_template.py <transcript> --quick-scan

Options: --dry-run --force --json <file> --quick-scan --threshold N

JSON: {"replacements": [["old","new",count],...], "markers": [[line,"txt"],...],
       "contextual": [...], "quick_scan": true, "min_variant_density": 0.0005}
"""
import argparse
import hashlib
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

# HH:MM / H:MM / HH:MM:SS, optionally [bracketed] — timestamp-first speaker
# header. Used BOTH to skip marker insertion on headers and to mask header
# lines against replacements (SKILL Tier-C: speaker labels are immutable —
# a glossary name rule must never rewrite who spoke; codex v2 #1).
SPEAKER_HEADER_RE = re.compile(r'^\[?\d{1,2}:\d{2}(?::\d{2})?\]?\s')

# Marker cap per SKILL.md auto-marking contract (enforced here, not just prose).
def marker_cap(line_count: int) -> int:
    return max(15, line_count // 16)


class SourceChangedError(RuntimeError):
    """Target file changed on disk between read and write (concurrent editor)."""


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
    p.add_argument("-V", "--version", action="version", version="fix_template v2.3")
    return p.parse_args(argv)


def validate_manifest(reps: list, ctx: list, markers: list) -> list[str]:
    """Schema/invariant validation — returns list of fatal problems.

    NOT force-bypassable: schema garbage, duplicate-old contradictions and
    unauthorized numeric edits must never reach the apply stage (codex v2
    #2/#5/#15). Numeric old/new requires an explicit 4th element "numeric-ok"
    (SKILL Tier-C: number changes need user confirmation — the flag records it).
    """
    problems = []
    all_rep = list(reps) + list(ctx)
    seen_old: dict[str, str] = {}
    for i, entry in enumerate(all_rep):
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            problems.append(f"rule {i + 1}: must be [old, new, count]")
            continue
        old, new, expected = entry[0], entry[1], entry[2]
        if not isinstance(old, str) or not old:
            problems.append(f"rule {i + 1}: empty/non-string old")
            continue
        if not isinstance(new, str):
            problems.append(f"rule {i + 1}: non-string new")
            continue
        if old == new:
            problems.append(f"rule {i + 1}: old == new ({old!r})")
        if "\n" in old or "\r" in old or "\n" in new or "\r" in new:
            problems.append(f"rule {i + 1}: newline inside old/new breaks line parity")
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            problems.append(f"rule {i + 1}: expected count must be int >= 0, got {expected!r}")
        if old in seen_old:
            problems.append(
                f"rule {i + 1}: duplicate old {old!r} (earlier maps to {seen_old[old]!r}) — "
                "contradictory rules, first-wins is silent corruption")
        seen_old[old] = new
        if (re.search(r"\d", old) or re.search(r"\d", new)) and \
                (len(entry) < 4 or entry[3] != "numeric-ok"):
            problems.append(
                f"rule {i + 1}: numeric content in {old!r}→{new!r} — numbers are Tier-C; "
                'add explicit 4th element "numeric-ok" after user confirmation')
    for k, m in enumerate(markers):
        if not isinstance(m, (list, tuple)) or len(m) != 2:
            problems.append(f"marker {k + 1}: must be [line, text]")
            continue
        line_num, text = m[0], m[1]
        if not isinstance(line_num, int) or isinstance(line_num, bool) or line_num < 1:
            problems.append(f"marker {k + 1}: line must be int >= 1, got {line_num!r}")
        if not isinstance(text, str) or not text.startswith("(*") or not text.endswith(")"):
            problems.append(f"marker {k + 1}: text must be a '(*...)' marker, got {text!r}")
        elif "\n" in text or "\r" in text:
            problems.append(f"marker {k + 1}: newline inside marker text")
    return problems


def mask_speaker_headers(text: str) -> tuple[str, list]:
    """Mask timestamp-first speaker-header lines against replacements.

    A glossary name rule (박상우→박상호) must correct the body but never the
    header — headers decide utterance attribution (codex v2 #1). Masking also
    keeps the verify gate honest: expected counts must exclude header hits,
    otherwise COUNT MISMATCH halts the run (fail loud, agent recounts body-only).
    """
    salt = ""
    while f"__SPK{salt}" in text:
        salt += "X"
    lines = text.splitlines(keepends=True)
    spans = []
    for i, line in enumerate(lines):
        content = line.rstrip("\r\n")
        if SPEAKER_HEADER_RE.match(content):
            ph = f"__SPK{salt}{i:08d}__"
            spans.append((ph, content))
            lines[i] = ph + line[len(content):]
    return "".join(lines), spans


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

    Contextual (ctx) mismatches are warnings only — ctx is the softer gate and
    apply_corrections re-checks each ctx rule at apply time anyway; halting the
    whole run on one soft-context drift forced full-manifest rework
    (codex v2 #25). Only hard (reps) mismatches halt.
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

    return any(not is_ctx for *_, is_ctx in mismatch_list) and not force


def apply_replacements(masked: str, cs: CorrectionSet) -> str:
    """Apply reps then ctx, longest old-string first.

    Longest-first: an overlapping shorter rule must not rewrite the inside of
    a longer target before the longer rule runs (운동→응동 destroying
    운동폭→변동폭). Counts were verified against the same pre-apply text, so
    ordering does not affect the verify gate.
    """
    by_len = lambda r: -len(r[0])  # noqa: E731
    changed = masked
    for old_str, new_str, _ in sorted(cs.reps, key=by_len):
        changed = U.safe_replace(changed, old_str, new_str)
    for old_str, new_str, expected in sorted(cs.ctx, key=by_len):
        if U.count_variant(changed, old_str, new_str) == expected:
            changed = U.safe_replace(changed, old_str, new_str)
    return changed


def restore_spans(text: str, spans: list) -> str:
    for ph, span in spans:
        text = text.replace(ph, span)
    return text


def apply_markers(text: str, markers: list) -> tuple[str, dict]:
    """Insert markers per line. Returns (text, stats).

    - splitlines(keepends=True): each line keeps ITS OWN ending — mixed
      CRLF/LF files must not be wholesale-normalized (codex v2 #12).
    - blank lines refused: a marker needs a host utterance (codex v2 #8).
    - stats report actual applied vs skipped — DONE used to echo the requested
      count even when nothing landed (codex v2 #9).
    """
    stats = {"applied": 0, "skipped": []}
    if not markers:
        return text, stats
    lines = text.splitlines(keepends=True)
    for line_num, marker_text in sorted(markers, reverse=True):
        idx = line_num - 1
        if not (0 <= idx < len(lines)):
            print(f"  MARKER WARN: L{line_num} out of range — SKIPPED")
            stats["skipped"].append((line_num, "out-of-range"))
            continue
        content = lines[idx].rstrip("\r\n")
        ending = lines[idx][len(content):]
        if SPEAKER_HEADER_RE.match(content):
            print(f"  MARKER WARN: L{line_num} is speaker header — SKIPPED")
            stats["skipped"].append((line_num, "speaker-header"))
            continue
        if not content.strip():
            print(f"  MARKER WARN: L{line_num} is blank — SKIPPED (marker needs a host utterance)")
            stats["skipped"].append((line_num, "blank-line"))
            continue
        if marker_text in content:
            print(f"  MARKER DUP: L{line_num} already has")
            stats["skipped"].append((line_num, "duplicate"))
            continue
        lines[idx] = content.rstrip() + " " + marker_text + ending
        stats["applied"] += 1
    return "".join(lines), stats


def apply_corrections(masked: str, cs: CorrectionSet, original: str, le: str) -> str:
    """Compat wrapper: replacements → restore comment spans → markers."""
    changed = apply_replacements(masked, cs)
    changed = restore_spans(changed, cs.spans)
    changed, _stats = apply_markers(changed, cs.markers)
    return changed


def write_atomic(
    target_path: Path,
    changed: str,
    enc: str,
    bak_path: Path,
    reps: list,
    ctx: list,
    markers_list: list,
    src_sha: str | None = None,
    markers_applied: int | None = None,
) -> None:
    """Atomic write via temp (preserves original on crash; restores .bak on error).

    - src_sha: sha256 of the bytes read at run start. Re-verified against the
      on-disk target immediately before replace — a concurrent editor save must
      abort the write, NOT be clobbered by our stale snapshot (codex v2 #14).
      On mismatch the user's newer file is kept (.bak NOT restored).
    - except (OSError, ValueError): UnicodeEncodeError is a ValueError — it
      used to leave a plaintext fix_* temp behind (codex v2 #16).

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
        if src_sha is not None:
            cur = hashlib.sha256(target_path.read_bytes()).hexdigest()
            if cur != src_sha:
                Path(tmp_path).unlink(missing_ok=True)
                raise SourceChangedError(
                    f"{target_path.name} changed on disk during the run "
                    "(external editor?) — aborting write, keeping the newer file")
        Path(tmp_path).replace(target_path)
        m_applied = len(markers_list) if markers_applied is None else markers_applied
        print(f"DONE: {len(reps)}+{len(ctx)} replacements, "
              f"{m_applied}/{len(markers_list)} markers applied")
        # tmp was renamed onto target by replace() — no leftover to clean on success
    except SourceChangedError:
        raise
    except (OSError, ValueError):
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

    # Schema/invariant validation — NOT force-bypassable (codex v2 #2/#5/#15).
    problems = validate_manifest(reps, ctx, markers_list)
    if problems:
        for pr in problems:
            print(f"  MANIFEST: {pr}")
        print("HALT: manifest validation failed (not overridable by --force)")
        sys.exit(1)
    # Normalize to 3-tuples — the optional 4th "numeric-ok" flag was consumed
    # by validation; downstream unpacking expects [old, new, count].
    reps = [list(r[:3]) for r in reps]
    ctx = [list(c[:3]) for c in ctx]
    all_rep = reps + ctx

    # Cross-rule contamination guard (operational-adversarial 2026-07-12 H6):
    # if rule A's NEW contains rule B's OLD, applying A creates fresh matches
    # for B — the count-verify gate (checked against the ORIGINAL text) passes,
    # then apply corrupts silently. Fail loud; --force overrides deliberately.
    for i, (_old_i, new_i, *_r1) in enumerate(all_rep):
        for j, (old_j, _new_j, *_r2) in enumerate(all_rep):
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
        raw = target_path.read_bytes()
        src_sha = hashlib.sha256(raw).hexdigest()
        # decode (not open) — identical text, and the same bytes give src_sha
        original = raw.decode(enc)

        # Quick-scan — markers make it moot: marker insertion has nothing to do
        # with variant density, so a markers-only manifest used to "SKIP" with
        # rc 0 and silently insert nothing (codex v2 #4).
        if (args.quick_scan or qs_enabled) and not markers_list:
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

        # Marker cap (SKILL auto-marking contract — was prose-only, codex v2 #27)
        cap = marker_cap(len(original_lines))
        if len(markers_list) > cap and not args.force:
            print(f"HALT: {len(markers_list)} markers > cap {cap} "
                  f"(max(15, lines//16) for {len(original_lines)} lines) — trim or --force")
            sys.exit(1)
        # Out-of-range markers: fail loud pre-apply (silently ignoring them made
        # DONE lie about what happened — codex v2 #8/#9). --force drops them.
        oor = [ln for ln, _t in markers_list if not (1 <= ln <= len(original_lines))]
        if oor:
            if args.force:
                print(f"  FORCE: dropping out-of-range markers at lines {oor}")
                markers_list = [m for m in markers_list if 1 <= m[0] <= len(original_lines)]
            else:
                print(f"HALT: marker lines out of range {oor} (file has {len(original_lines)} lines)")
                sys.exit(1)

        # Backup
        bak_path = target_path.with_suffix(target_path.suffix + ".bak")
        if not args.dry_run:
            shutil.copy2(target_path, bak_path)

        # Mask comments; nested (*: Tier-C — fail-closed, not warn-and-continue
        # (codex v2 #10)
        masked, spans = U.mask_comments(original)
        if U.MASK_VIOLATIONS:
            for kind, pos in U.MASK_VIOLATIONS:
                print(f"  TIER-C: {kind} marker at position {pos}")
            if not args.force:
                print("HALT: Tier-C marker violations — verify spans manually or rerun with --force")
                sys.exit(1)
        # Mask speaker headers: replacements must never rewrite attribution
        # (SKILL Tier-C, codex v2 #1)
        hmasked, header_spans = mask_speaker_headers(masked)
        cs = CorrectionSet(reps=reps, ctx=ctx, markers=markers_list, spans=spans)

        # Log substring-risky pairs
        for old_str, new_str, _ in all_rep:
            if U.is_substring_of_either(old_str, new_str):
                print(f"  NOTE: substring-risky '{old_str}'↔'{new_str}' — using word-boundary regex")

        # Verify counts (headers masked — expected counts must be body-only)
        if verify_counts(hmasked, reps, ctx, args.force):
            print("HALT: count mismatches")
            sys.exit(1)

        # Apply: replacements on double-masked text → restore headers →
        # restore comments (dedup check needs real text) → markers
        changed = apply_replacements(hmasked, cs)
        changed = restore_spans(changed, header_spans)
        changed = restore_spans(changed, spans)
        changed, marker_stats = apply_markers(changed, markers_list)

        # Verify line count
        new_lines = changed.splitlines()
        if len(new_lines) != len(original_lines):
            print(f"LINE MISMATCH: {len(original_lines)} → {len(new_lines)}")
            if not args.dry_run:
                shutil.copy2(bak_path, target_path)
                print("RESTORED from .bak")
            sys.exit(1)
        print(f"Lines OK: {len(new_lines)}")

        # Speaker-header postcondition (belt & braces for codex v2 #1): every
        # header line must be byte-identical after all passes.
        for idx, orig_line in enumerate(original_lines):
            if SPEAKER_HEADER_RE.match(orig_line) and new_lines[idx] != orig_line:
                print(f"SPEAKER INVARIANT VIOLATION: L{idx + 1} "
                      f"'{orig_line}' → '{new_lines[idx]}'")
                print("HALT: refusing to write (speaker labels are immutable)")
                sys.exit(1)

        # Marker accounting (codex v2 #9 — report what actually happened)
        if marker_stats["skipped"]:
            detail = ", ".join(f"L{ln}:{why}" for ln, why in marker_stats["skipped"])
            print(f"  MARKER SUMMARY: {marker_stats['applied']}/{len(markers_list)} applied — skipped {detail}")

        # Output
        if args.dry_run:
            diffs = U.compute_line_diff(original, changed)
            print(f"\nDRY-RUN: {len(reps)} sets + {len(ctx)} ctx + "
                  f"{marker_stats['applied']}/{len(markers_list)} markers")
            for d in diffs:
                print(d)
        else:
            try:
                write_atomic(target_path, changed, enc, bak_path, reps, ctx,
                             markers_list, src_sha=src_sha,
                             markers_applied=marker_stats["applied"])
            except SourceChangedError as e:
                print(f"ERROR: {e}")
                sys.exit(1)
    finally:
        U.release_lock(target_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
