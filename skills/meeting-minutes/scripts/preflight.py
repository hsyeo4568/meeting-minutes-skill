#!/usr/bin/env python3
"""Preflight doctor — checks the MACHINE is ready (deps/tools), separate from dry_run.py
(which checks config correctness). Prints OK/MISSING per item + an install hint. Never errors out."""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent.parent

_OK = "  OK   "
_MISS = "  MISS "

# (import_name, tier, install_hint)
_DEPS: list[tuple[str, str, str]] = [
    ("yaml",     "REQUIRED",    "pip install pyyaml"),
    ("pptx",     "recommended", "pip install python-pptx   (슬라이드 파싱; 없으면 PPTX 회의자료 못 읽음)"),
    ("openpyxl", "recommended", "pip install openpyxl      (xlsx 교차검증; 없으면 식별자 대조 생략)"),
    ("whisper",  "optional",    "pip install openai-whisper (오디오 STT; 텍스트/PDF만 쓰면 불필요)"),
]

_MIN_PYTHON = (3, 9)
_MIN_BASH = 4


def _has_mod(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def check_python_version() -> int:
    """Print Python version status; return 1 if below minimum, else 0."""
    v = sys.version_info
    ok = v >= _MIN_PYTHON
    print(
        f"{_OK if ok else _MISS}python {v.major}.{v.minor}  "
        f"(need >={_MIN_PYTHON[0]}.{_MIN_PYTHON[1]})"
    )
    return 0 if ok else 1


def check_deps() -> int:
    """Print status for each listed dependency; return count of missing REQUIRED deps."""
    missing_required = 0
    for mod, tier, hint in _DEPS:
        ok = _has_mod(mod)
        line = f"{_OK if ok else _MISS}{mod:10} [{tier}]"
        if not ok:
            line += f"  -> {hint}"
            if tier == "REQUIRED":
                missing_required += 1
        print(line)
    return missing_required


def check_bash() -> int:
    """Print bash version status; return 1 if below minimum or absent, else 0."""
    bash = shutil.which("bash")
    if not bash:
        print(f"{_MISS}bash  -> verify.sh 못 돌림 (Windows: Git Bash, macOS: brew install bash)")
        return 1
    try:
        result = subprocess.run(
            [bash, "-c", "echo ${BASH_VERSINFO[0]}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        major = int(result.stdout.strip() or 0)
        ok = major >= _MIN_BASH
        print(
            f"{_OK if ok else _MISS}bash {result.stdout.strip()}  "
            f"(verify.sh needs >={_MIN_BASH}; macOS: brew install bash)"
        )
        return 0 if ok else 1
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"{_MISS}bash found but version check failed ({exc!r})")
        return 1


def check_config(root: pathlib.Path) -> int:
    """Print config.yaml presence; return 1 if missing, else 0."""
    cfg = root / "config.yaml"
    if cfg.exists():
        print(f"{_OK}config.yaml  present -> run: python scripts/dry_run.py")
        return 0
    print(f"{_MISS}config.yaml  -> cp config.example.yaml config.yaml 후 값 채우기")
    return 1


def main() -> int:
    """Run all preflight checks; return total count of REQUIRED missing items."""
    print("== meeting-minutes preflight ==\n")

    missing_required = check_python_version()
    missing_required += check_deps()

    print()
    check_bash()  # informational only — bash absence doesn't block Python-based flows

    print()
    check_config(ROOT)  # informational only — dry_run.py does the deep config check

    print("\n== integrations (선택 — 없으면 .md 파일 fallback, 실패 아님) ==")
    print("  Gmail      : claude.ai 커넥터(있으면 메일 초안 자동) / 없으면 메일본문 .md 출력")
    print("  Slack/qmd/ontology : 작성자 bespoke 로컬 도구 — 팀원 보통 없음. 없으면 .md/스킵.")

    print(
        "\n"
        + (
            "PREFLIGHT: READY"
            if missing_required == 0
            else f"PREFLIGHT: {missing_required} REQUIRED item(s) missing — install above, re-run"
        )
    )
    return missing_required


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
