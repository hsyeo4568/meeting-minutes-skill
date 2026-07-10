# -*- coding: utf-8 -*-
"""fixstamp -- re-run skip gate for transcript correction. v2.1

Commands:
  check       exit 0=skip, 1=new, 2=file-changed, 3=glossary/version-changed, 4=error
  write       record hashes after correction; verifies file modification
  batch       folder-level check (quick-scan pre-filters clean files)
  quick-scan  rapid variant density check (0=skip, 1=proceed)
  --threshold N   override quick-scan density threshold (default 0.0003)
  --dry-run       no side effects

Sidecar: <transcript.txt>.fixstamp (JSON w/ skill_version).
Lock: <transcript.txt>.lock (stale-lock auto-clean after 10min).
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _utils as U

SKILL_VERSION = "2.1"

if sys.stdout:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


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

    enc = U.detect_encoding(target)
    if enc != 'utf-8':
        print(f"NOTE: encoding={enc} — {target.name}")

    if not stamp.exists():
        pfx = "DRY-RUN " if dry_run else ""
        print(f"{pfx}RUN: {target.name} — new file (no stamp)")
        return 1

    try:
        old = json.loads(stamp.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        pfx = "DRY-RUN " if dry_run else ""
        print(f"{pfx}RUN: {target.name} — corrupt stamp")
        return 1

    fm = old.get("file_sha256") == cur["file_sha256"]
    gm = old.get("glossary_sha256") == cur["glossary_sha256"]
    vm = old.get("skill_version") == SKILL_VERSION

    if not vm:
        pfx = "DRY-RUN " if dry_run else ""
        print(f"{pfx}RUN: {target.name} — skill v{old.get('skill_version','?')}→v{SKILL_VERSION}")
        return 3

    if fm and gm:
        pfx = "DRY-RUN " if dry_run else ""
        print(f"{pfx}SKIP: {target.name} — unchanged")
        return 0
    if fm and not gm:
        pfx = "DRY-RUN " if dry_run else ""
        print(f"{pfx}RUN: {target.name} — glossary changed")
        return 3
    if not fm and gm:
        pfx = "DRY-RUN " if dry_run else ""
        print(f"{pfx}RUN: {target.name} — file changed")
        return 2
    pfx = "DRY-RUN " if dry_run else ""
    print(f"{pfx}RUN: {target.name} — both changed")
    return 2


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
        except Exception:
            pass

    if prev_hash and prev_hash == cur_hash:
        print(f"WARNING: {target.name} — file unchanged since last stamp (stamping anyway)")

    if not U.acquire_lock(target):
        print(f"ERROR: could not lock {target.name}")
        return 4

    cur = {"file_sha256": cur_hash, "glossary_sha256": sha256(glossary),
           "skill_version": SKILL_VERSION}
    stamp.write_text(json.dumps(cur), encoding="utf-8")
    print(f"STAMPED: {target.name}")
    U.release_lock(target)
    return 0


def quick_scan(target: Path, glossary: Path, threshold: float = 0.0003) -> int:
    if not target.exists():
        print(f"ERROR: transcript not found: {target}")
        return 4
    if not glossary.exists():
        print(f"ERROR: glossary not found: {glossary}")
        return 4

    enc = U.detect_encoding(target)
    with open(target, "r", encoding=enc) as f:
        text = f.read()

    glossary_text = glossary.read_text(encoding="utf-8")
    sm, em = "## 1.", "## 2."
    variants_section = ""
    if sm in glossary_text:
        s = glossary_text.index(sm) + len(sm)
        if em in glossary_text[s:]:
            variants_section = glossary_text[s:glossary_text.index(em, s)]

    total_hits = 0
    for line in variants_section.split("\n"):
        if "←" in line:
            vp = line.split("←")[1] if "←" in line else ""
            vp = re.sub(r'\([^)]*\)', '', vp)  # strip (문맥)(절단) etc
            for sep in [",", ";", "/"]:
                vp = vp.replace(sep, " ")
            for token in vp.split():
                token = token.strip().rstrip(',;')
                if token and len(token) >= 2:
                    c = text.count(token)
                    if c > 0:
                        total_hits += c

    density = total_hits / max(len(text), 1)
    print(f"QUICK-SCAN: {total_hits} hits, density={density:.5f} (threshold={threshold})")
    if density < threshold:
        print(f"RESULT: low density — skip full pass")
        return 0
    print(f"RESULT: proceed with full correction")
    return 1


def print_sections(glossary: Path) -> int:
    """Print only the correction-relevant glossary sections (§1 table, §7 people,
    §8 ownership) to stdout — lets the agent load evidence without Read-ing the
    whole file (§2-6/§9-10 are context-only per SKILL, ~38% of the file)."""
    if not glossary.exists():
        print(f"ERROR: glossary not found: {glossary}")
        return 4
    t = glossary.read_text(encoding="utf-8")

    def slice_section(start_marker: str, end_marker: str) -> str:
        i = t.find(start_marker)
        if i < 0:
            return ""
        j = t.find(end_marker, i + 1) if end_marker else len(t)
        if j < 0:
            j = len(t)
        return t[i:j].rstrip()

    out = []
    for sm, em in (("## 1.", "## 2."), ("## 7.", "## 8."), ("## 8.", "## 9.")):
        seg = slice_section(sm, em)
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
    sm, em = "## 1.", "## 2."
    variants_section = ""
    if sm in glossary_text:
        s = glossary_text.index(sm) + len(sm)
        if em in glossary_text[s:]:
            variants_section = glossary_text[s:glossary_text.index(em, s)]
    U.set_glossary_variants_cache(variants_section)

    skip_count, new_count, run_count, qs_skip = 0, 0, 0, 0
    total = len(txt_files)
    for i, f in enumerate(txt_files):
        pct = (i + 1) * 100 // total
        # Use cached glossary for quick-scan
        enc = U.detect_encoding(f)
        try:
            with open(f, "r", encoding=enc) as fh:
                text = fh.read()
        except Exception:
            print(f"  [{pct}%] ERROR reading: {f.name}")
            continue

        # Quick-scan with cached variants
        total_hits = 0
        for line in variants_section.split("\n"):
            if "←" in line:
                vp = line.split("←")[1] if "←" in line else ""
                vp = re.sub(r'\([^)]*\)', '', vp)
                for sep in [",", ";", "/"]:
                    vp = vp.replace(sep, " ")
                for token in vp.split():
                    token = token.strip().rstrip(',;')
                    if token and len(token) >= 2:
                        total_hits += text.count(token)

        density = total_hits / max(len(text), 1)
        if density < 0.0003:
            qs_skip += 1
            print(f"  [{pct}%] QS-SKIP: {f.name} (d={density:.4f})")
            continue

        rc = check_file(f, glossary, dry_run=dry_run)
        if rc == 0:
            skip_count += 1
        elif rc == 1:
            new_count += 1
        elif rc in (2, 3):
            run_count += 1
        print(f"  [{pct}%] {'SKIP' if rc==0 else 'RUN'}: {f.name}")

    U.set_glossary_variants_cache(None)
    label = "DRY-RUN " if dry_run else ""
    print(f"\n{label}SUMMARY: {new_count} new, {run_count} changed, {skip_count} unchanged, "
          f"{qs_skip} QS-filtered, {total} total")
    return 0 if (new_count + run_count) == 0 else 1


def migrate_stamps(folder: Path, glossary: Path) -> int:
    """Re-stamp all .fixstamp files in folder to current skill version."""
    if not folder.is_dir():
        print(f"ERROR: not a directory: {folder}")
        return 4
    stamp_files = sorted(folder.glob("*.fixstamp"))
    if not stamp_files:
        print("No .fixstamp files found")
        return 0
    updated = 0
    for sf in stamp_files:
        target = sf.with_name(sf.name.replace(".fixstamp", ""))
        if target.exists():
            write_stamp(target, glossary)
            updated += 1
    print(f"MIGRATED: {updated} stamp files updated to v{SKILL_VERSION}")
    return 0


def main() -> int:
    args = sys.argv[1:]

    if "--version" in args or "-V" in args:
        print(f"fixstamp v{SKILL_VERSION}")
        return 0

    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    threshold = None
    if "--threshold" in args:
        idx = args.index("--threshold")
        try:
            threshold = float(args[idx + 1])
            args = args[:idx] + args[idx + 2:]
        except (ValueError, IndexError):
            print("ERROR: --threshold requires a float value")
            return 4

    # sections: cmd + glossary only (2 args) — print §1/§7/§8 to stdout
    if args and args[0] == "sections":
        if len(args) < 2:
            print("usage: fixstamp.py sections <glossary.md>")
            return 4
        return print_sections(Path(args[1]))

    if len(args) < 3 or args[0] not in ("check", "write", "batch", "quick-scan", "migrate"):
        print(
            "fixstamp v" + SKILL_VERSION + "\n"
            "usage: fixstamp.py check|write|batch|quick-scan|migrate [--dry-run] [--threshold N] <target> <glossary.md>\n"
            "       fixstamp.py sections <glossary.md>\n"
            "  check:      exit 0=skip 1=new 2=file-changed 3=version/glossary-changed 4=error\n"
            "  write:      record hashes after correction (verifies modification)\n"
            "  batch:      folder check with quick-scan pre-filter + progress\n"
            "  quick-scan: rapid variant density check\n"
            "  migrate:    re-stamp all .fixstamp files in folder to current version\n"
            "  sections:   print correction-relevant glossary sections (§1/§7/§8) only\n"
            "  --version:  print version and exit"
        )
        return 4

    cmd, target, glossary = args[0], Path(args[1]), Path(args[2])

    if cmd == "batch":
        return batch_check(target, glossary, dry_run=dry_run)
    if cmd == "migrate":
        return migrate_stamps(target, glossary)
    if cmd == "quick-scan":
        return quick_scan(target, glossary, threshold=threshold or 0.0003)
    if dry_run and cmd == "check":
        return check_file(target, glossary, dry_run=True)
    if cmd == "check":
        return check_file(target, glossary)
    if cmd == "write":
        return write_stamp(target, glossary)
    return 4


if __name__ == "__main__":
    sys.exit(main())
