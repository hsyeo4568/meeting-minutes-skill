# -*- coding: utf-8 -*-
"""Unit tests for stt-transcript-fix scripts (_utils.py, fix_template.py)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _utils as U  # noqa: E402
import fix_template as FT  # noqa: E402

FIX_TEMPLATE = SCRIPTS / "fix_template.py"


def run_fix(args, timeout=60):
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, str(FIX_TEMPLATE), *[str(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=timeout,
    )


# =========================================================================
# 1. mask_comments
# =========================================================================

def test_mask_comments_simple_span():
    text = "앞부분 (*정리) 뒷부분"
    masked, spans = U.mask_comments(text)
    assert len(spans) == 1
    ph, span = spans[0]
    assert span == "(*정리)"
    assert ph in masked
    assert "(*정리)" not in masked
    # restore mapping round-trips to original
    restored = masked
    for p, s in spans:
        restored = restored.replace(p, s)
    assert restored == text


def test_mask_comments_plain_nested_parens_full_span():
    text = "지표 (*가동률(오류/24h) 낮음) 끝"
    masked, spans = U.mask_comments(text)
    assert len(spans) == 1
    assert spans[0][1] == "(*가동률(오류/24h) 낮음)"
    restored = masked
    for p, s in spans:
        restored = restored.replace(p, s)
    assert restored == text


def test_mask_comments_nested_marker_full_outer_span_and_warning(capsys):
    text = "(*a (*b) c)"
    masked, spans = U.mask_comments(text)
    out = capsys.readouterr().out
    # recently fixed bug: full outer span must be captured
    assert len(spans) == 1
    assert spans[0][1] == "(*a (*b) c)"
    assert "WARNING" in out and "nested" in out
    restored = masked
    for p, s in spans:
        restored = restored.replace(p, s)
    assert restored == text


def test_mask_comments_imbalanced_cut_at_blank_line(capsys):
    text = "(*열림\n\n다음 문단"
    masked, spans = U.mask_comments(text)
    out = capsys.readouterr().out
    assert "WARNING" in out and "imbalanced" in out
    assert len(spans) == 1
    span = spans[0][1]
    assert span.startswith("(*열림")
    assert "\n\n" not in span  # cut before the blank line
    # text after the cut point survives verbatim
    assert masked.endswith("\n\n다음 문단")
    restored = masked
    for p, s in spans:
        restored = restored.replace(p, s)
    assert restored == text


def test_mask_comments_over_200_chars_cut_with_warning(capsys):
    body = "a" * 250
    text = "(*" + body + ")"
    masked, spans = U.mask_comments(text)
    out = capsys.readouterr().out
    assert "WARNING" in out and "200" in out
    assert len(spans) == 1
    assert len(spans[0][1]) <= 202  # cut near the 200-char limit
    restored = masked
    for p, s in spans:
        restored = restored.replace(p, s)
    assert restored == text


def test_mask_comments_no_markers_unchanged():
    text = "일반 텍스트 (그냥 괄호) 포함\n둘째 줄"
    masked, spans = U.mask_comments(text)
    assert masked == text
    assert spans == []


# =========================================================================
# 2. safe_replace + count_variant
# =========================================================================

def test_safe_replace_substring_risky_word_boundary_and_idempotence():
    old, new = "피던스", "임피던스"
    assert U.is_substring_risky(old, new)
    text = "피던스 측정값과 임피던스 비교, 그리고 피던스 재측정"
    once = U.safe_replace(text, old, new)
    # standalone occurrences replaced, existing 임피던스 untouched
    assert once == "임피던스 측정값과 임피던스 비교, 그리고 임피던스 재측정"
    assert "임임피던스" not in once
    # idempotence: applying twice == once
    twice = U.safe_replace(once, old, new)
    assert twice == once
    assert "임임피던스" not in twice


def test_safe_replace_non_risky_plain():
    old, new = "구정", "규정"
    assert not U.is_substring_risky(old, new)
    text = "구정 검토 후 구정 개정"
    result = U.safe_replace(text, old, new)
    assert result == "규정 검토 후 규정 개정"
    assert old not in result


def test_count_variant_parity_risky():
    old, new = "피던스", "임피던스"
    text = "피던스 확인, 임피던스 유지, 피던스 끝"
    reported = U.count_variant(text, old, new)
    assert reported == 2
    result = U.safe_replace(text, old, new)
    actually_replaced = result.count(new) - text.count(new)
    assert reported == actually_replaced


def test_count_variant_parity_non_risky():
    old, new = "구정", "규정"
    text = "구정 하나 구정 둘 구정 셋"
    reported = U.count_variant(text, old, new)
    assert reported == 3
    result = U.safe_replace(text, old, new)
    assert result.count(new) - text.count(new) == reported
    assert old not in result


# =========================================================================
# 3. verify_counts
# =========================================================================

def test_verify_counts_matching_no_halt():
    masked = "피던스 하나와 피던스 둘"
    reps = [["피던스", "임피던스", 2]]
    assert FT.verify_counts(masked, reps, [], force=False) is False


def test_verify_counts_mismatch_halts():
    masked = "피던스 하나"
    reps = [["피던스", "임피던스", 5]]
    assert FT.verify_counts(masked, reps, [], force=False) is True


def test_verify_counts_mismatch_with_force_no_halt():
    masked = "피던스 하나"
    reps = [["피던스", "임피던스", 5]]
    assert FT.verify_counts(masked, reps, [], force=True) is False


# =========================================================================
# 4. apply_corrections
# =========================================================================

def test_apply_corrections_replaces_and_restores_spans_verbatim():
    original = "피던스 문제 발생 (*피던스 원문 유지)\n다음 줄\n"
    masked, spans = U.mask_comments(original)
    reps = [["피던스", "임피던스", 1]]
    changed = FT.apply_corrections(masked, spans, reps, [], [], original, "\n")
    # replacement applied outside the comment
    assert changed.startswith("임피던스 문제 발생")
    # comment span restored verbatim (variant inside NOT corrected)
    assert "(*피던스 원문 유지)" in changed
    assert "(*임피던스" not in changed
    assert "__CMT" not in changed


def test_apply_corrections_markers_speaker_skip_and_dedup(capsys):
    original = "06:12 발표자 발언 내용\n일반 내용 줄\n이미 표시된 줄 (*확인)\n"
    masked, spans = U.mask_comments(original)
    markers = [(1, "(*마커1)"), (2, "(*마커2)"), (3, "(*확인)")]
    changed = FT.apply_corrections(masked, spans, [], [], markers, original, "\n")
    out = capsys.readouterr().out
    lines = changed.splitlines()
    # L1 speaker header — skipped
    assert lines[0] == "06:12 발표자 발언 내용"
    assert "MARKER WARN" in out and "SKIPPED" in out
    # L2 marker appended at line end
    assert lines[1] == "일반 내용 줄 (*마커2)"
    # L3 already has marker — deduped (appears exactly once)
    assert lines[2].count("(*확인)") == 1
    assert "MARKER DUP" in out
    # line count preserved, trailing newline preserved
    assert len(lines) == len(original.splitlines())
    assert changed.endswith("\n")


# =========================================================================
# 5. write_atomic
# =========================================================================

def test_write_atomic_success(tmp_path):
    target = tmp_path / "t.txt"
    target.write_text("old content", encoding="utf-8")
    bak = tmp_path / "t.txt.bak"
    shutil.copy2(target, bak)
    FT.write_atomic(target, "new content", "utf-8", bak, [], [], [])
    assert target.read_text(encoding="utf-8") == "new content"
    # no leftover temp files (prefix fix_)
    assert list(tmp_path.glob("fix_*")) == []


def test_write_atomic_failure_restores_bak_and_reraises(tmp_path, monkeypatch):
    target = tmp_path / "t.txt"
    target.write_text("original", encoding="utf-8")
    bak = tmp_path / "t.txt.bak"
    shutil.copy2(target, bak)

    def boom(self, other):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="simulated"):
        FT.write_atomic(target, "would-be new", "utf-8", bak, [], [], [])
    monkeypatch.undo()
    # original restored from .bak
    assert target.read_text(encoding="utf-8") == "original"
    # temp file cleaned up
    assert list(tmp_path.glob("fix_*")) == []


# =========================================================================
# 6. Lock lifecycle
# =========================================================================

def test_lock_acquire_creates_and_release_removes(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("x", encoding="utf-8")
    lock = tmp_path / "t.txt.lock"
    assert U.acquire_lock(p, timeout=5) is True
    assert lock.exists()
    U.release_lock(p)
    assert not lock.exists()


def test_lock_acquire_fails_when_held(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("x", encoding="utf-8")
    lock = tmp_path / "t.txt.lock"
    lock.write_text("", encoding="utf-8")  # fresh lock, held by "someone"
    assert U.acquire_lock(p, timeout=1) is False
    assert lock.exists()


def _write_fixture(tmp_path, expected_count):
    transcript = tmp_path / "t.txt"
    transcript.write_text("피던스 확인 필요\n둘째 줄 내용\n", encoding="utf-8")
    corr = tmp_path / "corr.json"
    corr.write_text(json.dumps({
        "replacements": [["피던스", "임피던스", expected_count]],
        "markers": [], "contextual": [],
    }, ensure_ascii=False), encoding="utf-8")
    return transcript, corr


def test_main_releases_lock_on_success(tmp_path):
    transcript, corr = _write_fixture(tmp_path, expected_count=1)
    r = run_fix([transcript, "--json", corr])
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (tmp_path / "t.txt.lock").exists()
    assert "임피던스" in transcript.read_text(encoding="utf-8")
    assert (tmp_path / "t.txt.bak").exists()


def test_main_releases_lock_on_count_mismatch_halt(tmp_path):
    transcript, corr = _write_fixture(tmp_path, expected_count=5)
    r = run_fix([transcript, "--json", corr])
    assert r.returncode == 1
    assert "HALT" in r.stdout
    assert not (tmp_path / "t.txt.lock").exists()
    # file untouched
    assert "임피던스" not in transcript.read_text(encoding="utf-8")


def test_main_dry_run_leaves_no_lock_no_write(tmp_path):
    transcript, corr = _write_fixture(tmp_path, expected_count=1)
    r = run_fix([transcript, "--json", corr, "--dry-run"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DRY-RUN" in r.stdout
    assert not (tmp_path / "t.txt.lock").exists()
    assert not (tmp_path / "t.txt.bak").exists()
    assert "임피던스" not in transcript.read_text(encoding="utf-8")


# =========================================================================
# 7. detect_encoding
# =========================================================================

def test_detect_encoding_utf8(tmp_path):
    p = tmp_path / "u8.txt"
    p.write_bytes("한글 텍스트 내용".encode("utf-8"))
    assert U.detect_encoding(p) == "utf-8"


def test_detect_encoding_utf16_le_bom(tmp_path):
    p = tmp_path / "u16.txt"
    p.write_bytes(b"\xff\xfe" + "한글 텍스트".encode("utf-16-le"))
    assert U.detect_encoding(p) == "utf-16-le"


# =========================================================================
# 8. quick_scan_variants
# =========================================================================

def test_quick_scan_density_above_threshold():
    text = "피던스 관련 회의 내용 " * 50
    variants = [("피던스", "임피던스", 0)]
    assert U.quick_scan_variants(text, variants, U.QUICK_SCAN_MIN_DENSITY) is True


def test_quick_scan_density_below_threshold():
    text = "정상적인 회의 내용 반복 " * 500
    variants = [("피던스", "임피던스", 0)]
    assert U.quick_scan_variants(text, variants, U.QUICK_SCAN_MIN_DENSITY) is False
