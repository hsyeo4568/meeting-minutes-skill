# -*- coding: utf-8 -*-
"""fixstamp -- re-run skip gate for transcript correction.

check: exit 0 if BOTH the transcript and the glossary are unchanged since the
       last correction (skip the whole run), exit 1 otherwise (proceed).
write: record current hashes to the sidecar right after a correction pass
       (including a confirmed no-change pass).

sidecar: <transcript.txt>.fixstamp (JSON). Adding glossary rows changes the
glossary hash, which forces a full re-review by design -- new variants may
exist in older transcripts too.
"""
import hashlib
import json
import sys
from pathlib import Path

if sys.stdout:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] not in ("check", "write"):
        print("usage: fixstamp.py check|write <transcript.txt> <glossary.md>")
        return 2
    cmd, target, glossary = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    if not target.exists() or not glossary.exists():
        print(f"missing file: {target if not target.exists() else glossary}")
        return 2
    stamp = target.with_name(target.name + ".fixstamp")
    cur = {"file_sha256": sha256(target), "glossary_sha256": sha256(glossary)}

    if cmd == "write":
        stamp.write_text(json.dumps(cur), encoding="utf-8")
        print("STAMPED")
        return 0

    if stamp.exists():
        try:
            old = json.loads(stamp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            old = {}
        if old.get("file_sha256") == cur["file_sha256"] and \
           old.get("glossary_sha256") == cur["glossary_sha256"]:
            print("SKIP: transcript and glossary unchanged since last fix")
            return 0
    print("RUN: no stamp or hash mismatch - full correction pass required")
    return 1


if __name__ == "__main__":
    sys.exit(main())
