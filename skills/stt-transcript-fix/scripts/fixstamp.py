# -*- coding: utf-8 -*-
"""fixstamp -- re-run skip gate for transcript correction. v2.2

Commands:
  check       exit 0=skip, 1=new, 2=file-changed, 3=glossary/version-changed, 4=error
  write       record hashes after correction; verifies file modification
  batch       folder-level check (stamp check first; density is advisory only)
  quick-scan  rapid variant density check (0=skip, 1=proceed)
  --threshold N   override quick-scan density threshold (default 0.0003)
  --dry-run       no side effects

Sidecar: <transcript.txt>.fixstamp (JSON w/ skill_version).
Lock: <transcript.txt>.lock (stale-lock auto-clean after 10min).
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _utils as U
from _utils import QUICK_SCAN_MIN_DENSITY

# _utils already reconfigures stdout at import time (guarded for pythonw/detached tasks).
# No duplicate reconfigure needed here.

# Bump whenever correction RULES change (not just this file) — stamps from older
# versions must invalidate so already-"reviewed" files get re-reviewed under the
# new rules (codex review 2026-07-12 #2). 2.2: boundary-regex particle fix,
# longest-first apply, encoding arbitration, fail-closed marker cuts.
SKILL_VERSION = "2.2"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _pfx(dry_run: bool) -> str:
    """Return 'DRY-RUN ' prefix when dry_run is True, else ''."""
    return "DRY-RUN " if dry_run else ""


def _decide(fm: bool, gm: bool, vm: bool, target_name: str, old: dict, dry_run: bool) -> int:
    """Derive check_file exit code and print result given hash-match flags."""
    pfx = _pfx(dry_run)
    if not vm:
        print(f"{pfx}RUN: {target_name} — skill v{old.get('skill_version', '?')}→v{SKILL_VERSION}")
        return 3
    if fm and gm:
        print(f"{pfx}SKIP: {target_name} — unchanged")
        return 0
    if fm and not gm:
        print(f"{pfx}RUN: {target_name} — glossary changed")
        return 3
    if not fm and gm:
        print(f"{pfx}RUN: {target_name} — file changed")
        return 2
    print(f"{pfx}RUN: {target_name} — both changed")
    return 2


def check_file(target: Path, glossary: Path, dry_run: bool = False) -> int:
    if not target.exists():
        print(f"ERROR: transcript not found: {target}")
        return 4
    if not glossary.exists():
        print(f"ERROR: glossary not found: {glossary}")
        return 4

    stamp = target.with_name(target.name + ".fixstamp")
    cur = {"file_sha256": sha256(target), "glossary_sha256": sha256(glossary),
           "skill_version": SKILL_VERSION}

    try:
        enc = U.detect_encoding(target)
    except UnicodeError as e:
        print(f"ERROR: {e}")
        return 4
    if enc != 'utf-8':
        print(f"NOTE: encoding={enc} — {target.name}")

    pfx = _pfx(dry_run)
    if not stamp.exists():
        print(f"{pfx}RUN: {target.name} — new file (no stamp)")
        return 1

    try:
        old = json.loads(stamp.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        print(f"{pfx}RUN: {target.name} — corrupt stamp")
        return 1

    fm = old.get("file_sha256") == cur["file_sha256"]
    gm = old.get("glossary_sha256") == cur["glossary_sha256"]
    vm = old.get("skill_version") == SKILL_VERSION

    return _decide(fm, gm, vm, target.name, old, dry_run)


def write_stamp(target: Path, glossary: Path) -> int:
    """Write stamp. Verifies file was modified since last check (warns if not)."""
    if not target.exists():
        print(f"ERROR: transcript not found: {target}")
        return 4
    if not glossary.exists():
        print(f"ERROR: glossary not found: {glossary}")
        return 4

    stamp = target.with_name(target.name + ".fixstamp")
    cur_hash = sha256(target)
    prev_hash = None
    if stamp.exists():
        try:
            prev_hash = json.loads(stamp.read_text(encoding="utf-8")).get("file_sha256")
        except (ValueError, OSError) as e:
            print(f"NOTE: prior stamp unreadable ({e}); skipping unchanged-file check")

    if prev_hash and prev_hash == cur_hash:
        print(f"WARNING: {target.name} — file unchanged since last stamp (stamping anyway)")

    if not U.acquire_lock(target):
        print(f"ERROR: could not lock {target.name}")
        return 4

    try:
        cur = {"file_sha256": cur_hash, "glossary_sha256": sha256(glossary),
               "skill_version": SKILL_VERSION}
        stamp.write_text(json.dumps(cur), encoding="utf-8")
        print(f"STAMPED: {target.name}")
        return 0
    finally:
        U.release_lock(target)  # release even if write_text raises (no lock leak)


def extract_section(text: str, start_marker: str, end_marker: str = "") -> str:
    """Slice a glossary section from start_marker to end_marker (start included,
    rstripped). '' if start_marker absent; to EOF if end_marker absent/unfound.
    Single source of truth for §-marker slicing (quick_scan/batch_check/print_sections)."""
    i = text.find(start_marker)
    if i < 0:
        return ""
    j = text.find(end_marker, i + len(start_marker)) if end_marker else len(text)
    if j < 0:
        j = len(text)
    return text[i:j].rstrip()


def _glossary_hits(text: str, variants_section: str) -> int:
    """Count occurrences of §1 glossary variant tokens in text.

    Single source of truth for the density scan (quick_scan / batch_check)."""
    total_hits = 0
    for line in variants_section.split("\n"):
        if "←" in line:
            vp = line.split("←")[1]
            vp = re.sub(r'\([^)]*\)', '', vp)  # strip (문맥)(절단) etc
            for sep in [",", ";", "/"]:
                vp = vp.replace(sep, " ")
            for token in vp.split():
                token = token.strip().rstrip(',;')
                if token and len(token) >= 2:
                    total_hits += text.count(token)
    return total_hits


def quick_scan(target: Path, glossary: Path, threshold: float = QUICK_SCAN_MIN_DENSITY) -> int:
    if not target.exists():
        print(f"ERROR: transcript not found: {target}")
        return 4
    if not glossary.exists():
        print(f"ERROR: glossary not found: {glossary}")
        return 4

    try:
        enc = U.detect_encoding(target)
    except UnicodeError as e:
        print(f"ERROR: {e}")
        return 4
    with open(target, "r", encoding=enc) as f:
        text = f.read()

    glossary_text = glossary.read_text(encoding="utf-8")
    variants_section = extract_section(glossary_text, "## 1.", "## 2.")

    total_hits = _glossary_hits(text, variants_section)
    density = total_hits / max(len(text), 1)
    print(f"QUICK-SCAN: {total_hits} hits, density={density:.5f} (threshold={threshold})")
    if density < threshold:
        print("RESULT: low density — skip full pass")
        return 0
    print("RESULT: proceed with full correction")
    return 1


def print_sections(glossary: Path) -> int:
    """Print only the correction-relevant glossary sections (§1 table, §7 people,
    §8 ownership) to stdout — lets the agent load evidence without Read-ing the
    whole file (§2-6/§9-10 are context-only per SKILL, ~38% of the file)."""
    if not glossary.exists():
        print(f"ERROR: glossary not found: {glossary}")
        return 4
    t = glossary.read_text(encoding="utf-8")

    out = []
    for sm, em in (("## 1.", "## 2."), ("## 7.", "## 8."), ("## 8.", "## 9.")):
        seg = extract_section(t, sm, em)
        if seg:
            out.append(seg)
    if not out:
        print("ERROR: no §1/§7/§8 sections found — glossary format changed; Read the file directly")
        return 4
    print("\n\n".join(out))
    return 0


def batch_check(folder: Path, glossary: Path, dry_run: bool = False) -> int:
    if not folder.is_dir():
        print(f"ERROR: not a directory: {folder}")
        return 4
    if not glossary.exists():
        print(f"ERROR: glossary not found: {glossary}")
        return 4

    txt_files = sorted(folder.glob("*.txt"))
    if not txt_files:
        print(f"No .txt files in {folder}")
        return 0

    # Cache glossary content once per batch
    glossary_text = glossary.read_text(encoding="utf-8")
    variants_section = extract_section(glossary_text, "## 1.", "## 2.")
    U.set_glossary_variants_cache(variants_section)

    skip_count, new_count, run_count, err_count, low_density = 0, 0, 0, 0, 0
    total = len(txt_files)
    for i, f in enumerate(txt_files):
        pct = (i + 1) * 100 // total
        # Stamp check FIRST. Quick-scan must never pre-filter: contextual
        # corrections, markers and number protection do not correlate with
        # glossary variant density, so a density skip on a new/changed file
        # silently marks unreviewed content as done (codex review 2026-07-12 #1).
        rc = check_file(f, glossary, dry_run=dry_run)
        if rc == 0:
            skip_count += 1
            print(f"  [{pct}%] SKIP: {f.name}")
            continue
        if rc == 4:
            err_count += 1
            print(f"  [{pct}%] ERROR: {f.name}")
            continue

        # Density scan is ADVISORY only — annotates, never filters.
        note = ""
        try:
            enc = U.detect_encoding(f)
            with open(f, "r", encoding=enc) as fh:
                text = fh.read()
            density = _glossary_hits(text, variants_section) / max(len(text), 1)
            if density < QUICK_SCAN_MIN_DENSITY:
                low_density += 1
                note = f" (low variant density d={density:.4f} — contextual/markers still need review)"
        except (UnicodeError, OSError):
            note = " (density scan unreadable)"

        if rc == 1:
            new_count += 1
        else:
            run_count += 1
        print(f"  [{pct}%] RUN: {f.name}{note}")

    U.set_glossary_variants_cache(None)
    label = "DRY-RUN " if dry_run else ""
    print(f"\n{label}SUMMARY: {new_count} new, {run_count} changed, {skip_count} unchanged, "
          f"{err_count} errors, {low_density} low-density, {total} total")
    return 0 if (new_count + run_count + err_count) == 0 else 1


def migrate_stamps(folder: Path, glossary: Path) -> int:
    """Version-refresh stamps — ONLY when file and glossary are byte-identical
    to what the old stamp reviewed.

    Blind re-stamping forged "reviewed under the new version" for files that
    were never re-reviewed (codex review 2026-07-12 #2). Now: hashes must match
    the OLD stamp; anything changed is left stale so `check` returns RUN.
    Version-only refresh still requires the operator to assert the new rules
    don't change outcomes for these files — the warning below states that.
    """
    if not folder.is_dir():
        print(f"ERROR: not a directory: {folder}")
        return 4
    stamp_files = sorted(folder.glob("*.fixstamp"))
    if not stamp_files:
        print("No .fixstamp files found")
        return 0
    print(f"NOTE: migrate asserts v{SKILL_VERSION} rules do not change outcomes "
          "for unchanged files — if rules affect existing content, re-run correction instead")
    updated, needs_review = 0, 0
    glossary_hash = sha256(glossary)
    for sf in stamp_files:
        target = sf.with_name(sf.name.replace(".fixstamp", ""))
        if not target.exists():
            continue
        try:
            old = json.loads(sf.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            needs_review += 1
            print(f"  NEEDS-REVIEW: {target.name} — corrupt stamp")
            continue
        if (old.get("file_sha256") == sha256(target)
                and old.get("glossary_sha256") == glossary_hash):
            write_stamp(target, glossary)
            updated += 1
        else:
            needs_review += 1
            print(f"  NEEDS-REVIEW: {target.name} — content/glossary changed since stamp; not migrating")
    print(f"MIGRATED: {updated} version-refreshed to v{SKILL_VERSION}, {needs_review} need re-review")
    return 0 if needs_review == 0 else 1


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the argparse parser for fixstamp."""
    p = argparse.ArgumentParser(
        prog="fixstamp.py",
        description=(
            f"fixstamp v{SKILL_VERSION} — re-run skip gate for transcript correction.\n\n"
            "  check:      exit 0=skip 1=new 2=file-changed 3=version/glossary-changed 4=error\n"
            "  write:      record hashes after correction (verifies modification)\n"
            "  batch:      folder check with quick-scan pre-filter + progress\n"
            "  quick-scan: rapid variant density check\n"
            "  migrate:    re-stamp all .fixstamp files in folder to current version\n"
            "  sections:   print correction-relevant glossary sections (§1/§7/§8) only\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-V", "--version", action="version", version=f"fixstamp v{SKILL_VERSION}")
    # Options accepted BOTH before the subcommand (fixstamp.py --dry-run check ...)
    # and after it (fixstamp.py check ... --dry-run — the form SKILL.md documents).
    # The subparser copies use SUPPRESS defaults so an absent post-command flag does
    # not clobber a value set at the top level.
    p.add_argument("--dry-run", action="store_true", help="no side effects")
    p.add_argument(
        "--threshold", type=float, default=None, metavar="N",
        help=f"quick-scan density threshold (default {QUICK_SCAN_MIN_DENSITY})",
    )

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS,
                        help="no side effects")
    common.add_argument("--threshold", type=float, metavar="N", default=argparse.SUPPRESS,
                        help=f"quick-scan density threshold (default {QUICK_SCAN_MIN_DENSITY})")

    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    # check / write / quick-scan / migrate: target + glossary
    for cmd, help_text in (
        ("check", "check stamp; exit 0=skip 1=new 2=changed 3=glossary/version 4=error"),
        ("write", "write stamp after correction"),
        ("quick-scan", "rapid variant density check (0=skip, 1=proceed)"),
        ("migrate", "re-stamp all .fixstamp files in folder to current version"),
    ):
        sp = sub.add_parser(cmd, help=help_text, parents=[common])
        sp.add_argument("target", help="transcript file or folder (migrate/batch)")
        sp.add_argument("glossary", help="glossary .md file")

    # batch: folder + glossary
    sp_batch = sub.add_parser("batch", help="folder check with quick-scan pre-filter",
                              parents=[common])
    sp_batch.add_argument("target", help="folder containing .txt transcripts")
    sp_batch.add_argument("glossary", help="glossary .md file")

    # sections: glossary only
    sp_sect = sub.add_parser("sections", help="print §1/§7/§8 correction sections",
                             parents=[common])
    sp_sect.add_argument("glossary", help="glossary .md file")

    return p


def main() -> int:
    p = _build_parser()
    args = p.parse_args()

    if args.cmd is None:
        p.print_help()
        return 4

    dry_run = args.dry_run
    threshold = args.threshold or QUICK_SCAN_MIN_DENSITY

    if args.cmd == "sections":
        return print_sections(Path(args.glossary))

    target = Path(args.target)
    glossary = Path(args.glossary)

    if args.cmd == "batch":
        return batch_check(target, glossary, dry_run=dry_run)
    if args.cmd == "migrate":
        return migrate_stamps(target, glossary)
    if args.cmd == "quick-scan":
        return quick_scan(target, glossary, threshold=threshold)
    if args.cmd == "check":
        return check_file(target, glossary, dry_run=dry_run)
    if args.cmd == "write":
        return write_stamp(target, glossary)
    return 4


if __name__ == "__main__":
    sys.exit(main())
