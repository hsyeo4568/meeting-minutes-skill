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
import fixstamp as FS  # noqa: E402

FIX_TEMPLATE = SCRIPTS / "fix_template.py"


def run_fix(args, timeout=60):
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, str(FIX_TEMPLATE), *[str(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=timeout,
    )


FIXSTAMP = SCRIPTS / "fixstamp.py"


def run_fixstamp(args, timeout=60):
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, str(FIXSTAMP), *[str(a) for a in args]],
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


def test_mask_comments_over_200_chars_cut_freezes_line(capsys):
    body = "a" * 250
    text = "(*" + body + ") 뒤따르는 본문"
    masked, spans = U.mask_comments(text)
    out = capsys.readouterr().out
    assert "WARNING" in out and "200" in out and "frozen" in out
    assert len(spans) == 1
    # fail-closed (SKILL.md contract): span extends to end-of-line — the tail
    # after the forced cut is masked too, so it cannot be corrected.
    assert spans[0][1] == text
    restored = masked
    for p, s in spans:
        restored = restored.replace(p, s)
    assert restored == text


def test_mask_comments_forced_cut_freeze_stops_at_newline(capsys):
    text = "(*" + "b" * 250 + "\n다음 줄은 자유"
    masked, spans = U.mask_comments(text)
    capsys.readouterr()
    assert len(spans) == 1
    assert "\n" not in spans[0][1]          # freeze is line-scoped
    assert masked.endswith("\n다음 줄은 자유")  # next line NOT frozen
    restored = masked
    for p, s in spans:
        restored = restored.replace(p, s)
    assert restored == text


def test_mask_comments_200_char_cut_tight(capsys):
    """Document exact cut semantics for the > 200 guard (fail-closed variant).

    The guard fires after j += 1 on a non-closing char (scanned distance 201),
    then extends the span to end-of-line (line freeze). A legitimate (*body)
    where body is exactly 198 chars (total span 201) closes normally before
    the guard can fire.
    """
    # 198-char body + closing `)` = 201-char span: closes before guard fires.
    body_ok = "b" * 198
    text_ok = "(*" + body_ok + ")"
    masked_ok, spans_ok = U.mask_comments(text_ok)
    capsys.readouterr()  # discard any incidental output
    assert len(spans_ok) == 1
    assert spans_ok[0][1] == text_ok  # fully captured, no cut

    # 200-char body with no closing `)`: guard MUST fire; span freezes to EOL
    # (here: whole text — no newline follows).
    body_cut = "c" * 200
    text_cut = "(*" + body_cut  # deliberately unclosed
    masked_cut, spans_cut = U.mask_comments(text_cut)
    out = capsys.readouterr().out
    assert "WARNING" in out and "200" in out
    assert len(spans_cut) == 1
    assert spans_cut[0][1] == text_cut  # line-frozen to EOF


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


def test_safe_replace_risky_paren_edge_with_korean_particle():
    """Regression (bottleneck_report_260710 ①): risky annotation whose `old` ends
    in ')' must still match when a Korean particle attaches directly after it.

    Old behaviour: trailing lookahead after ')' saw the particle '에'/'이' as a
    word char and refused the match → COUNT MISMATCH on all such pairs.
    """
    # old ends in ')', new is a substring of old → risky → boundary path.
    old, new = "춘전(충전)", "충전"
    assert U.is_substring_risky(old, new)
    text = "그래서 춘전(충전)에 대한 논의를 했다"
    assert U.count_variant(text, old, new) == 1
    assert U.safe_replace(text, old, new) == "그래서 충전에 대한 논의를 했다"

    # multi-char new that itself ends in punctuation, particle-adjacent.
    old2, new2 = "실효용량(실효용량)", "실효용량"
    assert U.is_substring_risky(old2, new2)
    text2 = "실효용량(실효용량)이 기준이다"
    assert U.count_variant(text2, old2, new2) == 1
    assert U.safe_replace(text2, old2, new2) == "실효용량이 기준이다"


def test_safe_replace_leading_boundary_still_blocks_midword():
    """The leading lookbehind must survive — a risky old with a word-char start
    must NOT match when glued to a preceding word char."""
    old, new = "피던스", "임피던스"
    # standalone matches, embedded inside 임피던스 does not.
    assert U.count_variant("임피던스 유지", old, new) == 0
    assert U.safe_replace("임피던스 유지", old, new) == "임피던스 유지"


def test_safe_replace_truncation_edge_with_korean_particle():
    """Regression (1p practice, 2026-07-12): new⊂old truncation where `old` ends
    in a Hangul char must still match when a Korean particle glues after it.

    The `else` branch set trail=True for any Hangul-final old, so the trailing
    lookahead rejected '부가세트에서' / '임임피던스를' → COUNT MISMATCH → HALT.
    Mirror of the codex v2 #7 fix that only covered the old⊂new direction.
    """
    # new is a prefix of old (trailing chars = STT noise), particle '에서' after.
    old, new = "부가세트", "부가세"
    assert U.is_substring_risky(old, new)
    text = "이제 부가세트에서 10%냐"
    assert U.count_variant(text, old, new) == 1
    assert U.safe_replace(text, old, new) == "이제 부가세에서 10%냐"

    # new is a suffix of old (accumulation cleanup), particle '를' after.
    old2, new2 = "임임피던스", "임피던스"
    assert U.is_substring_risky(old2, new2)
    text2 = "임임피던스를 측정"
    assert U.count_variant(text2, old2, new2) == 1
    assert U.safe_replace(text2, old2, new2) == "임피던스를 측정"


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
# 2b. quick_scan_variants >= count_variant for risky pairs (Finding #5)
# =========================================================================

def test_quick_scan_at_least_count_variant_for_risky_pair():
    """quick_scan_variants uses plain text.count() (over-counts risky pairs).

    For a substring-risky pair, quick_scan_variants must count >= count_variant.
    This is deliberate: false-positives (extra passes) are acceptable; false-negatives
    (skipped files with actual variants) are not.
    """
    old, new = "피던스", "임피던스"
    assert U.is_substring_of_either(old, new), "precondition: pair must be risky"

    # Text has 2 standalone occurrences and 1 embedded in 임피던스 (not a real variant).
    text = "피던스 확인 임피던스 유지 피던스 재측정"

    qs_count = sum(text.count(o) for o, _, _ in [(old, new, 0)])
    cv_count = U.count_variant(text, old, new)

    # quick_scan counts the plain occurrences (includes the embedded one inside 임피던스).
    assert qs_count >= cv_count, (
        f"quick_scan ({qs_count}) must be >= count_variant ({cv_count}) for risky pairs"
    )
    # Sanity: word-boundary count_variant is strictly less (it excludes the embedded hit).
    assert cv_count == 2
    assert qs_count == 3  # plain count includes "피던스" inside "임피던스"


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
    cs = FT.CorrectionSet(reps=reps, ctx=[], markers=[], spans=spans)
    changed = FT.apply_corrections(masked, cs, original, "\n")
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
    cs = FT.CorrectionSet(reps=[], ctx=[], markers=markers, spans=spans)
    changed = FT.apply_corrections(masked, cs, original, "\n")
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


def test_detect_encoding_cp949(tmp_path):
    """Codex review #3: CP949 bytes often decode 'successfully' as UTF-8/UTF-16
    mojibake. Hangul-ratio arbitration must pick cp949."""
    p = tmp_path / "cp949.txt"
    p.write_bytes("회의 녹취록 내용입니다. 충전기 점검.\n".encode("cp949"))
    assert U.detect_encoding(p) == "cp949"


def test_detect_encoding_bare_utf16_le(tmp_path):
    # no BOM; ASCII space/newline produce NUL bytes → utf-16 candidate set
    p = tmp_path / "bare16.txt"
    p.write_bytes("한글 텍스트 회의\n".encode("utf-16-le"))
    assert U.detect_encoding(p) == "utf-16-le"


def test_detect_encoding_undecodable_raises(tmp_path):
    # 0xFF invalid as UTF-8 lead and CP949 lead; no NUL → nothing decodes
    p = tmp_path / "junk.txt"
    p.write_bytes(b"\xff\xff\xff\xff")
    with pytest.raises(UnicodeError, match="fail-closed"):
        U.detect_encoding(p)


# =========================================================================
# 7b. codex review 2026-07-12 regressions
# =========================================================================

def test_apply_corrections_longest_old_first():
    """#6: shorter overlapping rule must not destroy a longer target first."""
    original = "변동성 관련 운동폭 확인과 운동 지시"
    masked, spans = U.mask_comments(original)
    reps = [["운동", "응동", 2], ["운동폭", "변동폭", 1]]  # deliberately short-first order
    cs = FT.CorrectionSet(reps=reps, ctx=[], markers=[], spans=spans)
    changed = FT.apply_corrections(masked, cs, original, "\n")
    assert "변동폭" in changed
    assert "응동폭" not in changed
    assert "응동 지시" in changed


def test_main_missing_json_path_fails_loud(tmp_path):
    """Extra finding: nonexistent --json must not report success."""
    transcript = tmp_path / "t.txt"
    transcript.write_text("내용\n", encoding="utf-8")
    r = run_fix([transcript, "--json", tmp_path / "nope.json"])
    assert r.returncode == 1
    assert "ERROR" in r.stdout and "not found" in r.stdout


def test_batch_new_low_density_file_still_reported(tmp_path, capsys):
    """#1: a NEW file with zero glossary variants must surface as RUN (rc 1),
    never be silently QS-filtered to rc 0."""
    glossary = tmp_path / "g.md"
    glossary.write_text("## 1. STT\n규정 ← 구정\n## 2. end\n", encoding="utf-8")
    target = tmp_path / "new.txt"
    target.write_text("변형이 전혀 없는 정상 회의 내용 반복 " * 50, encoding="utf-8")
    rc = FS.batch_check(tmp_path, glossary)
    out = capsys.readouterr().out
    assert rc == 1
    assert "RUN: new.txt" in out
    assert "QS-SKIP" not in out
    assert "1 new" in out


def test_migrate_command_removed():
    """codex v2 #3: migrate forged 'reviewed under new rules' without a pass —
    the command must not exist anymore (re-stamp only via `write`)."""
    assert not hasattr(FS, "migrate_stamps")
    r = run_stamp(["migrate", "x", "y"])
    assert r.returncode == 2  # argparse: invalid choice


def test_release_lock_foreign_pid_left_alone(tmp_path, capsys):
    """#4: release_lock must not delete a lock owned by another process."""
    p = tmp_path / "t.txt"
    p.write_text("x", encoding="utf-8")
    lock = tmp_path / "t.txt.lock"
    lock.write_text("999999999", encoding="ascii")  # foreign owner token
    U.release_lock(p)
    assert lock.exists()
    assert "not us" in capsys.readouterr().out
    lock.unlink()


# =========================================================================
# 7c. operational-adversarial round (self-review 2026-07-12, TDD RED-first)
# =========================================================================

def test_detect_encoding_utf8_bom_returns_sig(tmp_path):
    """H1: Notepad/phone exports write UTF-8 WITH BOM. Plain 'utf-8' leaves
    \\ufeff glued to line 1 → speaker-header regex fails → header unprotected.
    Contract: line 1 speaker header must be protected regardless of BOM."""
    p = tmp_path / "bom.txt"
    p.write_bytes(b"\xef\xbb\xbf" + "09:29 화자A 발언\n본문 줄\n".encode("utf-8"))
    assert U.detect_encoding(p) == "utf-8-sig"


def test_bom_file_speaker_header_protected_end_to_end(tmp_path):
    p = tmp_path / "bom_e2e.txt"
    p.write_bytes(b"\xef\xbb\xbf" + "09:29 화자A 발언\n본문 줄\n".encode("utf-8"))
    corr = tmp_path / "c.json"
    corr.write_text(json.dumps({
        "replacements": [], "contextual": [],
        "markers": [[1, "(*마커)"]],
    }, ensure_ascii=False), encoding="utf-8")
    r = run_fix([p, "--json", corr])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIPPED" in r.stdout            # L1 recognized as speaker header
    raw = p.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")   # BOM preserved on write
    assert "(*마커)" not in raw.decode("utf-8-sig").splitlines()[0]


def test_detect_encoding_latin1_utf8_not_misread_as_cp949(tmp_path):
    """H2: English transcript with one accented char (é). Hangul-only scoring
    gives utf-8 ratio 0 vs cp949 accidental-Hangul 1.0 → cp949 chosen → mojibake.
    Contract: valid UTF-8 European text stays utf-8."""
    p = tmp_path / "latin.txt"
    p.write_bytes("Café meeting notes with José\n".encode("utf-8"))
    assert U.detect_encoding(p) == "utf-8"


def test_cross_rule_contamination_halts(tmp_path):
    """H6: rule A's NEW containing rule B's OLD chains replacements —
    verify passes on the original text, then apply corrupts silently.
    Contract (count-verify gate honesty): refuse to apply, exit 1."""
    t = tmp_path / "t.txt"
    t.write_text("가나 라마 내용\n", encoding="utf-8")
    corr = tmp_path / "c.json"
    corr.write_text(json.dumps({
        "replacements": [["가나", "다라마", 1], ["라마", "XX", 1]],
        "contextual": [], "markers": [],
    }, ensure_ascii=False), encoding="utf-8")
    r = run_fix([t, "--json", corr])
    assert r.returncode == 1, f"should HALT on cross-rule risk, got rc={r.returncode}\n{r.stdout}"
    assert "CROSS-RULE" in r.stdout
    # file untouched
    assert t.read_text(encoding="utf-8") == "가나 라마 내용\n"


def test_mask_comments_imbalanced_crlf_blank_line_cut(capsys):
    """H9: Windows CRLF transcripts — imbalance guard checks only '\\n\\n',
    so '\\r\\n\\r\\n' never triggers the cut and the span swallows the next
    paragraph. Contract: cut at blank line regardless of line-ending style."""
    text = "(*열림\r\n\r\n다음 문단"
    masked, spans = U.mask_comments(text)
    out = capsys.readouterr().out
    assert "imbalanced" in out
    assert len(spans) == 1
    assert "다음 문단" not in spans[0][1]     # next paragraph NOT frozen
    assert masked.endswith("\r\n\r\n다음 문단")
    restored = masked
    for ph, s in spans:
        restored = restored.replace(ph, s)
    assert restored == text


def test_marker_skips_bracketed_timestamp_header(capsys):
    """#7: widened header guard — [HH:MM:SS] and H:MM forms protected."""
    original = "[00:00:15] 홍길동 발언\n9:05 화자 발언\n일반 본문 줄\n"
    masked, spans = U.mask_comments(original)
    markers = [(1, "(*m1)"), (2, "(*m2)"), (3, "(*m3)")]
    cs = FT.CorrectionSet(reps=[], ctx=[], markers=markers, spans=spans)
    changed = FT.apply_corrections(masked, cs, original, "\n")
    out = capsys.readouterr().out
    lines = changed.splitlines()
    assert lines[0] == "[00:00:15] 홍길동 발언"
    assert lines[1] == "9:05 화자 발언"
    assert lines[2].endswith("(*m3)")
    assert out.count("SKIPPED") == 2


# =========================================================================
# 7d. codex v2 (2026-07-12) regressions — semantic invariants in the executor
# =========================================================================

def _run_manifest(tmp_path, text, manifest, extra_args=()):
    t = tmp_path / "t.txt"
    t.write_text(text, encoding="utf-8")
    c = tmp_path / "c.json"
    c.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return t, run_fix([t, "--json", c, *extra_args])


def test_speaker_header_never_rewritten_by_replacement(tmp_path):
    """v2 #1: a glossary name rule must correct the body but NEVER the header.
    Header hit hidden from counts → expected=2 now mismatches (fail loud)."""
    text = "00:00 박상우\n본문 박상우 발언\n"
    t, r = _run_manifest(tmp_path, text, {
        "replacements": [["박상우", "박상호", 2]], "contextual": [], "markers": []})
    assert r.returncode == 1
    assert "COUNT MISMATCH" in r.stdout
    # body-only count applies cleanly, header untouched
    t2, r2 = _run_manifest(tmp_path / "ok" if (tmp_path / "ok").mkdir() or True else tmp_path,
                           text, {"replacements": [["박상우", "박상호", 1]],
                                  "contextual": [], "markers": []})
    assert r2.returncode == 0, r2.stdout
    lines = t2.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "00:00 박상우"          # header immutable
    assert lines[1] == "본문 박상호 발언"        # body corrected


def test_numeric_rule_rejected_without_flag(tmp_path):
    """v2 #2: numbers are Tier-C — silent value edits must be refused."""
    _, r = _run_manifest(tmp_path, "이번 주 20.3대 확인\n", {
        "replacements": [["20.3대", "12.3대", 1]], "contextual": [], "markers": []})
    assert r.returncode == 1
    assert "numeric" in r.stdout.lower() or "NUMERIC" in r.stdout
    # explicit numeric-ok (user-confirmed) passes
    t2, r2 = _run_manifest(tmp_path / "ok" if (tmp_path / "ok").mkdir() or True else tmp_path,
                           "이번 주 20.3대 확인\n",
                           {"replacements": [["20.3대", "12.3대", 1, "numeric-ok"]],
                            "contextual": [], "markers": []})
    assert r2.returncode == 0, r2.stdout
    assert "12.3대" in t2.read_text(encoding="utf-8")


def test_duplicate_old_contradiction_rejected(tmp_path):
    """v2 #5: same old → different new is first-wins silent corruption."""
    _, r = _run_manifest(tmp_path, "오답 내용\n", {
        "replacements": [["오답", "정답A", 1], ["오답", "정답B", 1]],
        "contextual": [], "markers": []})
    assert r.returncode == 1
    assert "duplicate old" in r.stdout


def test_marker_only_quick_scan_still_inserts(tmp_path):
    """v2 #4: quick_scan=true + markers-only used to exit 0 doing nothing."""
    t, r = _run_manifest(tmp_path, "00:01 화자\n본문 발언 내용\n", {
        "replacements": [], "contextual": [],
        "markers": [[2, "(*결정_테스트)"]], "quick_scan": True})
    assert r.returncode == 0, r.stdout
    assert "(*결정_테스트)" in t.read_text(encoding="utf-8")


def test_hangul_old_with_particle_corrected(tmp_path):
    """v2 #7: 피던스는/가/를 — particle glued after a Hangul old must match
    (only the leading side needs a guard for 피던스 ⊂ 임피던스)."""
    text = "00:01 화자\n피던스는 문제다\n임피던스 유지\n피던스를 확인\n"
    t, r = _run_manifest(tmp_path, text, {
        "replacements": [["피던스", "임피던스", 2]], "contextual": [], "markers": []})
    assert r.returncode == 0, r.stdout
    body = t.read_text(encoding="utf-8")
    assert "임피던스는 문제다" in body
    assert "임피던스를 확인" in body
    assert "임임피던스" not in body


def test_marker_out_of_range_halts(tmp_path):
    """v2 #8/#9: out-of-range marker must fail loud, not vanish into DONE."""
    t, r = _run_manifest(tmp_path, "00:01 화자\n본문\n", {
        "replacements": [], "contextual": [], "markers": [[999, "(*결정)"]]})
    assert r.returncode == 1
    assert "out of range" in r.stdout
    assert "(*결정)" not in t.read_text(encoding="utf-8")


def test_marker_blank_line_skipped(tmp_path):
    """v2 #8: a marker needs a host utterance — blank lines refused."""
    t, r = _run_manifest(tmp_path, "00:01 화자\n본문 발언\n\n다음 발언\n", {
        "replacements": [], "contextual": [], "markers": [[3, "(*결정)"]]})
    assert r.returncode == 0
    assert "blank" in r.stdout
    assert "(*결정)" not in t.read_text(encoding="utf-8")


def test_marker_cap_enforced(tmp_path):
    """v2 #27: cap max(15, lines//16) was prose-only — now enforced."""
    lines = "00:01 화자\n" + "본문 발언 줄\n" * 19        # 20 lines → cap 15
    markers = [[i, f"(*결정_{i})"] for i in range(2, 18)]  # 16 markers
    _, r = _run_manifest(tmp_path, lines, {
        "replacements": [], "contextual": [], "markers": markers})
    assert r.returncode == 1
    assert "cap" in r.stdout


def test_nested_marker_halts_run(tmp_path):
    """v2 #10: nested (* is Tier-C — warn-and-continue let the file be saved."""
    t, r = _run_manifest(tmp_path, "(*외부 (*내부) 끝) 구정 내용\n", {
        "replacements": [["구정", "규정", 1]], "contextual": [], "markers": []})
    assert r.returncode == 1
    assert "TIER-C" in r.stdout
    assert "구정" in t.read_text(encoding="utf-8")  # untouched


def test_placeholder_literal_collision_survives(tmp_path):
    """v2 #11: a literal __CMT...__ in the source must not be corrupted by
    the mask/restore round-trip (salted placeholders)."""
    text = "(*정리) 본문 __CMT00000000__ 그대로\n"
    masked, spans = U.mask_comments(text)
    restored = masked
    for ph, s in spans:
        restored = restored.replace(ph, s)
    assert restored == text
    assert restored.count("(*정리)") == 1


def test_mixed_line_endings_preserved_by_marker(tmp_path):
    """v2 #12: one marker must not normalize every line ending in the file."""
    raw = b"00:01 speaker\r\nbody line one\nbody line two\r\n"
    t = tmp_path / "mix.txt"
    t.write_bytes(raw)
    c = tmp_path / "c.json"
    c.write_text(json.dumps({"replacements": [], "contextual": [],
                             "markers": [[2, "(*결정)"]]}), encoding="utf-8")
    r = run_fix([t, "--json", c])
    assert r.returncode == 0, r.stdout
    out = t.read_bytes()
    assert b"body line one (*\xea\xb2\xb0\xec\xa0\x95)\n" in out   # LF kept on L2
    assert out.startswith(b"00:01 speaker\r\n")                    # CRLF kept on L1
    assert out.endswith(b"\r\n")                                   # CRLF kept on L3


def test_ctx_mismatch_does_not_halt(tmp_path):
    """v2 #25: contextual is the softer gate — its mismatch warns and skips,
    it must not block confirmed Tier-A rules."""
    t, r = _run_manifest(tmp_path, "00:01 화자\n구정 본문과 공가 내용\n", {
        "replacements": [["구정", "규정", 1]],
        "contextual": [["공가", "단가", 5]],   # wrong expected — soft skip
        "markers": []})
    assert r.returncode == 0, r.stdout
    body = t.read_text(encoding="utf-8")
    assert "규정" in body      # Tier-A applied
    assert "공가" in body      # ctx skipped (count mismatch at apply time)
    assert "CTX WARN" in r.stdout


def test_binary_nul_data_rejected(tmp_path):
    """v2 #24: NUL-bearing binary junk must not be 'detected' as UTF-16."""
    p = tmp_path / "junk.bin"
    p.write_bytes(b"\x00\x01\x02\x03")
    with pytest.raises(UnicodeError):
        U.detect_encoding(p)


def test_stale_lock_with_live_owner_not_stolen(tmp_path):
    """v2 #13: mtime-stale lock whose owner PID is alive must be respected."""
    p = tmp_path / "t.txt"
    p.write_text("x", encoding="utf-8")
    lock = tmp_path / "t.txt.lock"
    lock.write_text(str(os.getpid()), encoding="ascii")   # we are alive
    old = __import__("time").time() - 700
    os.utime(lock, (old, old))                            # mtime-stale
    assert U.acquire_lock(p, timeout=1) is False          # NOT stolen
    assert lock.exists()
    lock.unlink()


def test_stale_lock_with_dead_owner_cleaned(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("x", encoding="utf-8")
    lock = tmp_path / "t.txt.lock"
    lock.write_text("999999999", encoding="ascii")        # dead/bogus PID
    old = __import__("time").time() - 700
    os.utime(lock, (old, old))
    assert U.acquire_lock(p, timeout=5) is True           # stale + dead → cleaned
    U.release_lock(p)


def test_concurrent_edit_detected_before_write(tmp_path, monkeypatch):
    """v2 #14: target changed between read and replace → abort, keep newer file."""
    target = tmp_path / "t.txt"
    target.write_text("original", encoding="utf-8")
    bak = tmp_path / "t.txt.bak"
    shutil.copy2(target, bak)
    src_sha = __import__("hashlib").sha256(b"original").hexdigest()
    target.write_text("edited by user meanwhile", encoding="utf-8")  # concurrent edit
    with pytest.raises(FT.SourceChangedError):
        FT.write_atomic(target, "our stale output", "utf-8", bak, [], [], [],
                        src_sha=src_sha)
    # user's newer content kept, no restore, no temp litter
    assert target.read_text(encoding="utf-8") == "edited by user meanwhile"
    assert list(tmp_path.glob("fix_*")) == []


def test_unicode_encode_error_cleans_temp_and_restores(tmp_path):
    """v2 #16: UnicodeEncodeError (ValueError) must clean the temp file."""
    target = tmp_path / "t.txt"
    target.write_bytes("원본".encode("cp949"))
    bak = tmp_path / "t.txt.bak"
    shutil.copy2(target, bak)
    with pytest.raises(ValueError):
        # 'ê' not representable in cp949 → UnicodeEncodeError inside write
        FT.write_atomic(target, "contenu ê", "cp949", bak, [], [], [])
    assert list(tmp_path.glob("fix_*")) == []
    assert target.read_bytes() == "원본".encode("cp949")


def test_sections_partial_glossary_flagged(tmp_path, capsys):
    """v2 #19: §1-only glossary must not report rc 0 — name/ownership checks
    silently vanish."""
    g = tmp_path / "g.md"
    g.write_text("## 1. STT\n규정 ← 구정\n## 2. end\n", encoding="utf-8")
    rc = FS.print_sections(g)
    out = capsys.readouterr().out
    assert rc == 3
    assert "missing glossary sections" in out and "§7" in out


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


# =========================================================================
# 11. fixstamp CLI — --dry-run accepted in BOTH positions (SKILL.md contract)
# =========================================================================
# SKILL.md documents `fixstamp.py check <t> <g>` with `--dry-run` as status-only.
# Regression guard: the argparse rewrite must accept --dry-run AFTER the
# subcommand (documented form) as well as before it.

def _make_cli_fixture(tmp_path):
    target = tmp_path / "cli.txt"
    target.write_text("00:01 화자\n피던스 측정\n", encoding="utf-8")
    glossary = tmp_path / "g.md"
    glossary.write_text("## 1. 교정\n임피던스 ← 피던스\n## 2. x\n", encoding="utf-8")
    return target, glossary


def test_fixstamp_dry_run_flag_after_subcommand(tmp_path):
    target, glossary = _make_cli_fixture(tmp_path)
    r = run_fixstamp(["check", target, glossary, "--dry-run"])
    assert r.returncode == 1, r.stderr          # new file (no stamp)
    assert "DRY-RUN" in r.stdout
    assert "unrecognized arguments" not in r.stderr


def test_fixstamp_dry_run_flag_before_subcommand(tmp_path):
    target, glossary = _make_cli_fixture(tmp_path)
    r = run_fixstamp(["--dry-run", "check", target, glossary])
    assert r.returncode == 1, r.stderr
    assert "DRY-RUN" in r.stdout


def test_fixstamp_dry_run_does_not_write_stamp(tmp_path):
    target, glossary = _make_cli_fixture(tmp_path)
    run_fixstamp(["check", target, glossary, "--dry-run"])
    assert not target.with_name(target.name + ".fixstamp").exists()


# =========================================================================
# 9. fixstamp.write_stamp — lock leak regression
# =========================================================================

def test_write_stamp_releases_lock_when_write_fails(tmp_path, monkeypatch):
    target = tmp_path / "t.txt"
    target.write_text("녹취 내용", encoding="utf-8")
    glossary = tmp_path / "glossary.md"
    glossary.write_text("# glossary", encoding="utf-8")
    lock = target.with_name(target.name + ".lock")

    orig_write_text = Path.write_text

    def boom(self, *a, **k):
        if self.name.endswith(".fixstamp"):
            raise OSError("disk full")
        return orig_write_text(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", boom)

    with pytest.raises(OSError):
        FS.write_stamp(target, glossary)

    assert not lock.exists()  # finally must release even on write failure


# =========================================================================
# 10. fixstamp.extract_section — DRY single source of truth for §-slicing
# =========================================================================

def test_extract_section_returns_marker_inclusive_body():
    text = "## 1. tbl\na←b\n## 2. next\n"
    assert FS.extract_section(text, "## 1.", "## 2.") == "## 1. tbl\na←b"


def test_extract_section_empty_when_start_absent():
    assert FS.extract_section("no markers here", "## 1.", "## 2.") == ""


def test_extract_section_to_eof_when_end_absent():
    assert FS.extract_section("## 1. only\nrest", "## 1.", "## 2.") == "## 1. only\nrest"


def test_extract_section_default_end_is_eof():
    assert FS.extract_section("## 1. x\ny", "## 1.") == "## 1. x\ny"


def test_quick_scan_header_line_not_counted(tmp_path):
    # §1 header "## 1. STT 교정표" is now included in the slice; it must NOT inflate hits
    glossary = tmp_path / "g.md"
    glossary.write_text("## 1. STT 교정표\n임피던스 ← 피던스\n## 2. 기타\n", encoding="utf-8")
    target = tmp_path / "t.txt"
    target.write_text("피던스 " * 40, encoding="utf-8")  # high density of the variant
    assert FS.quick_scan(target, glossary, threshold=0.0001) == 1  # proceed


# =========================================================================
# 11. fixstamp.check_file decision paths (#11 _decide helper)
# =========================================================================

def _make_stamp(target: Path, glossary: Path, *, version=FS.SKILL_VERSION):
    """Write a .fixstamp sidecar for target using real sha256 values."""
    import hashlib
    data = {
        "file_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "glossary_sha256": hashlib.sha256(glossary.read_bytes()).hexdigest(),
        "skill_version": version,
    }
    stamp = target.with_name(target.name + ".fixstamp")
    stamp.write_text(json.dumps(data), encoding="utf-8")
    return stamp


def test_check_file_skip_when_unchanged(tmp_path, capsys):
    target = tmp_path / "t.txt"
    target.write_text("녹취 내용", encoding="utf-8")
    glossary = tmp_path / "g.md"
    glossary.write_text("# glossary", encoding="utf-8")
    _make_stamp(target, glossary)
    assert FS.check_file(target, glossary) == 0
    assert "SKIP" in capsys.readouterr().out


def test_check_file_new_when_no_stamp(tmp_path, capsys):
    target = tmp_path / "t.txt"
    target.write_text("녹취 내용", encoding="utf-8")
    glossary = tmp_path / "g.md"
    glossary.write_text("# glossary", encoding="utf-8")
    assert FS.check_file(target, glossary) == 1
    assert "new file" in capsys.readouterr().out


def test_check_file_file_changed(tmp_path, capsys):
    target = tmp_path / "t.txt"
    target.write_text("원본 내용", encoding="utf-8")
    glossary = tmp_path / "g.md"
    glossary.write_text("# glossary", encoding="utf-8")
    _make_stamp(target, glossary)
    target.write_text("수정된 내용", encoding="utf-8")  # modify after stamp
    assert FS.check_file(target, glossary) == 2
    assert "file changed" in capsys.readouterr().out


def test_check_file_glossary_changed(tmp_path, capsys):
    target = tmp_path / "t.txt"
    target.write_text("녹취 내용", encoding="utf-8")
    glossary = tmp_path / "g.md"
    glossary.write_text("# original glossary", encoding="utf-8")
    _make_stamp(target, glossary)
    glossary.write_text("# updated glossary", encoding="utf-8")  # change glossary
    assert FS.check_file(target, glossary) == 3
    assert "glossary changed" in capsys.readouterr().out


def test_check_file_version_changed(tmp_path, capsys):
    target = tmp_path / "t.txt"
    target.write_text("녹취 내용", encoding="utf-8")
    glossary = tmp_path / "g.md"
    glossary.write_text("# glossary", encoding="utf-8")
    _make_stamp(target, glossary, version="1.0")  # old version
    assert FS.check_file(target, glossary) == 3
    assert "skill v1.0" in capsys.readouterr().out


def test_check_file_dry_run_prefix(tmp_path, capsys):
    target = tmp_path / "t.txt"
    target.write_text("녹취 내용", encoding="utf-8")
    glossary = tmp_path / "g.md"
    glossary.write_text("# glossary", encoding="utf-8")
    assert FS.check_file(target, glossary, dry_run=True) == 1
    assert "DRY-RUN" in capsys.readouterr().out


def test_check_file_missing_target_returns_4(tmp_path, capsys):
    assert FS.check_file(tmp_path / "missing.txt", tmp_path / "g.md") == 4
    assert "ERROR" in capsys.readouterr().out


# =========================================================================
# 12. fixstamp.batch_check — happy path and empty folder (#13)
# =========================================================================

def test_batch_check_empty_folder(tmp_path, capsys):
    glossary = tmp_path / "g.md"
    glossary.write_text("## 1. STT\na ← b\n## 2. end\n", encoding="utf-8")
    result = FS.batch_check(tmp_path, glossary)
    assert result == 0
    assert "No .txt files" in capsys.readouterr().out


def test_batch_check_all_new_returns_1(tmp_path, capsys):
    glossary = tmp_path / "g.md"
    glossary.write_text("## 1. STT\n규정 ← 구정\n## 2. end\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("구정 내용이 있는 녹취 파일 " * 20, encoding="utf-8")
    result = FS.batch_check(tmp_path, glossary)
    out = capsys.readouterr().out
    assert result == 1  # has new files
    assert "SUMMARY" in out


def test_batch_check_all_stamped_returns_0(tmp_path, capsys):
    glossary = tmp_path / "g.md"
    glossary.write_text("## 1. STT\n규정 ← 구정\n## 2. end\n", encoding="utf-8")
    target = tmp_path / "a.txt"
    target.write_text("정상 내용 반복 " * 200, encoding="utf-8")
    _make_stamp(target, glossary)
    result = FS.batch_check(tmp_path, glossary)
    out = capsys.readouterr().out
    assert result == 0
    assert "SUMMARY" in out


# =========================================================================
# 13. fixstamp.main argparse routing (#13)
# =========================================================================

FIXSTAMP = Path(__file__).resolve().parent.parent / "scripts" / "fixstamp.py"


def run_stamp(args, timeout=60):
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, str(FIXSTAMP), *[str(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=timeout,
    )


def test_main_version_flag():
    r = run_stamp(["--version"])
    assert r.returncode == 0
    assert "fixstamp" in r.stdout and FS.SKILL_VERSION in r.stdout


def test_main_no_args_returns_4():
    r = run_stamp([])
    assert r.returncode == 4


def test_main_sections_routing(tmp_path):
    glossary = tmp_path / "g.md"
    glossary.write_text(
        "## 1. STT\na ← b\n## 2. x\n## 7. 인명\n홍길동\n## 8. 담당\n조직A\n## 9. end\n",
        encoding="utf-8")
    r = run_stamp(["sections", str(glossary)])
    assert r.returncode == 0     # complete glossary → rc 0 (partial → rc 3)
    assert "## 1." in r.stdout and "## 7." in r.stdout


def test_main_check_routing_new_file(tmp_path):
    target = tmp_path / "t.txt"
    target.write_text("내용", encoding="utf-8")
    glossary = tmp_path / "g.md"
    glossary.write_text("# g", encoding="utf-8")
    r = run_stamp(["check", str(target), str(glossary)])
    assert r.returncode == 1
    assert "new file" in r.stdout


def test_main_check_dry_run(tmp_path):
    target = tmp_path / "t.txt"
    target.write_text("내용", encoding="utf-8")
    glossary = tmp_path / "g.md"
    glossary.write_text("# g", encoding="utf-8")
    r = run_stamp(["--dry-run", "check", str(target), str(glossary)])
    assert r.returncode == 1
    assert "DRY-RUN" in r.stdout


def test_main_write_then_check_skip(tmp_path):
    target = tmp_path / "t.txt"
    target.write_text("내용", encoding="utf-8")
    glossary = tmp_path / "g.md"
    glossary.write_text("# g", encoding="utf-8")
    r_write = run_stamp(["write", str(target), str(glossary)])
    assert r_write.returncode == 0
    assert "STAMPED" in r_write.stdout
    r_check = run_stamp(["check", str(target), str(glossary)])
    assert r_check.returncode == 0
    assert "SKIP" in r_check.stdout
