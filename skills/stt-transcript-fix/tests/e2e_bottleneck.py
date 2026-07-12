# -*- coding: utf-8 -*-
"""E2E: replay the 260710 bottleneck manifest through the full fix_template pipeline.

Simulates a fresh run on the real failing data: paren-edged risky annotations with
Korean particles attached (the ① bug), plus masking/speaker/line-invariant coverage.
Exits 0 on PASS, 1 on FAIL. Self-contained (builds its own transcript + JSON).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
FIX = SCRIPTS / "fix_template.py"

# Each (old, new): old is the STT error, new the correction. Particle appended in body
# so every risky case is the exact shape that HALTed before the fix (')' + 조사).
# Names are synthetic — this file syncs to a public repo; the bug repro only needs the
# structural shape "X(Y)" (risky, ')'-edged) + a glued Korean particle, never real data.
REPS = [
    # risky + paren-edged (the ① bug: ')' followed by a particle)
    ("가나(다라)", "다라"),
    ("마바(사아)", "사아"),
    ("자차용량(자차용량)", "자차용량"),
    ("카타(파하)", "파하"),
    ("어카운트(account)", "account"),
    ("Abbrev(abbreviation)", "abbreviation"),
    ("긴 오인식 문장입니다(정정된 문장.)", "정정된 문장."),
    # non-risky plain-replace cases (no substring relation)
    ("AAA", "BBB"),
    ("Xyz", "XYZ"),
    ("두루미", "기러기"),
    ("MDA", "NDA"),
]
CTX = [
    ("느을(느낌)", "느낌"),
    ("시뮬레전(시뮬레이션)", "시뮬레이션"),
]

PARTICLE = "에"  # Korean particle glued directly after — the thing that broke ')' cases


def build(tmp: Path):
    lines = ["09:29 화자A 회의 시작"]           # L1 speaker header (marker must skip)
    for old, _ in REPS + CTX:
        lines.append(f"그래서 {old}{PARTICLE} 대한 논의를 진행했다")
    # masked-protection line: a risky old INSIDE a (*..) span must survive verbatim
    guard_old = REPS[0][0]  # 춘전(충전)
    lines.append(f"원문 보존 확인 (*{guard_old} 원문 유지)")
    body_line = len(lines)                       # marker target: last body line (not speaker)
    transcript = tmp / "meeting.txt"
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")

    corr = {
        "replacements": [[o, n, 1] for o, n in REPS],
        "contextual": [[o, n, 1] for o, n in CTX],
        "markers": [[body_line, "(*to-do_E2E 검증 마커 : QA)"]],
    }
    cjson = tmp / "corr.json"
    cjson.write_text(json.dumps(corr, ensure_ascii=False), encoding="utf-8")
    return transcript, cjson, guard_old, body_line


def run(args):
    return subprocess.run(
        [sys.executable, str(FIX), *[str(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={"PYTHONUTF8": "1", **__import__("os").environ},
        timeout=60,
    )


def main() -> int:
    fails = []
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        transcript, cjson, guard_old, body_line = build(tmp)
        original = transcript.read_text(encoding="utf-8")
        orig_line_count = len(original.splitlines())

        # --- Phase 1: dry-run must NOT halt and every count OK ---
        dry = run([transcript, "--json", cjson, "--dry-run"])
        if "HALT" in dry.stdout:
            fails.append("dry-run HALTed (count mismatch — bug still present)")
        if "COUNT MISMATCH" in dry.stdout:
            fails.append("dry-run reported COUNT MISMATCH")
        if dry.returncode != 0:
            fails.append(f"dry-run exit {dry.returncode}")

        # --- Phase 2: real apply ---
        app = run([transcript, "--json", cjson])
        if app.returncode != 0:
            fails.append(f"apply exit {app.returncode}: {app.stdout[-400:]}")
        result = transcript.read_text(encoding="utf-8")

        # every correction landed, no error token remains outside the masked span
        for old, new in REPS + CTX:
            if new not in result:
                fails.append(f"correction missing: {old}->{new}")
        # masked span survived verbatim (guard_old still present inside the comment)
        if f"(*{guard_old} 원문 유지)" not in result:
            fails.append("masked (*..) span not preserved verbatim")
        # marker appended to the body line, speaker header L1 untouched
        if "(*to-do_E2E 검증 마커 : QA)" not in result:
            fails.append("marker not inserted")
        if not result.splitlines()[0].startswith("09:29 화자A"):
            fails.append("speaker header L1 was mutated")
        # line-count invariant
        if len(result.splitlines()) != orig_line_count:
            fails.append(f"line count changed {orig_line_count}->{len(result.splitlines())}")
        # .bak created
        if not (transcript.with_suffix(".txt.bak")).exists():
            fails.append(".bak not created")

    if fails:
        print("E2E FAIL:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print(f"E2E PASS: {len(REPS)} reps + {len(CTX)} ctx applied, "
          f"masking/speaker/marker/line-invariant all green ({orig_line_count} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
