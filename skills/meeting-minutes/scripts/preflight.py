#!/usr/bin/env python3
"""Preflight doctor — checks the MACHINE is ready (deps/tools), separate from dry_run.py
(which checks config correctness). Prints OK/MISSING per item + an install hint. Never errors out."""
import sys, shutil, subprocess, importlib.util, pathlib
sys.stdout.reconfigure(encoding="utf-8")
ROOT = pathlib.Path(__file__).resolve().parent.parent

def has_mod(m): return importlib.util.find_spec(m) is not None
OK, MISS = "  OK   ", "  MISS "
missing_required = 0

print("== meeting-minutes preflight ==\n")

# 1. Python version
v = sys.version_info
ok = v >= (3, 9)
print(f"{OK if ok else MISS}python {v.major}.{v.minor}  (need >=3.9)")
missing_required += 0 if ok else 1

# 2. Required + recommended python deps
DEPS = [
    ("yaml",        "REQUIRED",    "pip install pyyaml"),
    ("pptx",        "recommended", "pip install python-pptx   (슬라이드 파싱; 없으면 PPTX 회의자료 못 읽음)"),
    ("openpyxl",    "recommended", "pip install openpyxl      (xlsx 교차검증; 없으면 식별자 대조 생략)"),
    ("whisper",     "optional",    "pip install openai-whisper (오디오 STT; 텍스트/PDF만 쓰면 불필요)"),
]
for mod, tier, hint in DEPS:
    ok = has_mod(mod)
    line = f"{OK if ok else MISS}{mod:10} [{tier}]"
    if not ok:
        line += f"  -> {hint}"
        if tier == "REQUIRED": missing_required += 1
    print(line)

# 3. bash (verify.sh needs >=4; macOS ships 3.2)
print()
bash = shutil.which("bash")
if bash:
    try:
        out = subprocess.run([bash, "-c", "echo ${BASH_VERSINFO[0]}"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        major = int(out or 0)
        ok = major >= 4
        print(f"{OK if ok else MISS}bash {out}  (verify.sh needs >=4; macOS: brew install bash)")
    except Exception:
        print(f"{MISS}bash found but version check failed")
else:
    print(f"{MISS}bash  -> verify.sh 못 돌림 (Windows: Git Bash, macOS: brew install bash)")

# 4. config + profile presence (points at dry_run for deeper check)
print()
cfg = ROOT / "config.yaml"
print(f"{OK if cfg.exists() else MISS}config.yaml  " +
      ("present -> run: python scripts/dry_run.py" if cfg.exists()
       else "-> cp config.example.yaml config.yaml 후 값 채우기"))

# 5. Integrations (runtime-detected by the skill; preflight only informs)
print("\n== integrations (선택 — 없으면 .md 파일 fallback, 실패 아님) ==")
print("  Gmail      : claude.ai 커넥터(있으면 메일 초안 자동) / 없으면 메일본문 .md 출력")
print("  Slack/qmd/ontology : 작성자 bespoke 로컬 도구 — 팀원 보통 없음. 없으면 .md/스킵.")

print("\n" + ("PREFLIGHT: READY" if missing_required == 0
              else f"PREFLIGHT: {missing_required} REQUIRED item(s) missing — install above, re-run"))
sys.exit(1 if missing_required else 0)
