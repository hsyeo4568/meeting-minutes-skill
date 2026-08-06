# -*- coding: utf-8 -*-
"""Read-back comparison across a rendering channel.

Fixtures below are the real transformations a live Slack canvas applied to a
sent body (measured 2026-07-27, canvas F0BKYK01A7L): `-` bullets rewritten to
`*`, dates wrapped as `![](slack_date:…)`, blank lines inserted after headings.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mm_readback as RB  # noqa: E402

SENT = """# Daily 7/27 (월)
## 1. min SoC 하향 관련 분석
- 5/13~7/10 394건 중 출차 SoC 충족 98.7%, 미충족 1.3%(5건)
- 대표(3512): 늦은 입차 → 기존 방전 우선 스케줄 잔존
# Action Items
**Acme**
- [ ] min SoC 잔여 4건 알고리즘팀 분석 후 협의
# 일정
- 2026-07-28 고객별 이슈 발생 현황 회의 (내부, 10시)
"""

CANVAS_READBACK = """# Daily 7/27 (월)

## 1. min SoC 하향 관련 분석

* 5/13~7/10 394건 중 출차 SoC 충족 98.7%, 미충족 1.3%(5건)
* 대표(3512): 늦은 입차 → 기존 방전 우선 스케줄 잔존

# Action Items

**Acme**

* [ ] min SoC 잔여 4건 알고리즘팀 분석 후 협의

# 일정

* ![](slack_date:2026-07-28) 고객별 이슈 발생 현황 회의 (내부, 10시)
"""


# ---------------------------------------------------------------------------
# normalization
# ---------------------------------------------------------------------------

def test_bullet_style_is_not_a_difference():
    assert RB.normalize_line("- 항목") == RB.normalize_line("* 항목")


def test_checkbox_and_heading_marks_are_stripped():
    assert RB.normalize_line("- [ ] 할 일") == "할 일"
    assert RB.normalize_line("## 제목") == "제목"


def test_slack_date_embed_unwraps_to_its_value():
    assert RB.normalize_line("* ![](slack_date:2026-07-28) 회의") == "2026-07-28 회의"


def test_emphasis_and_whitespace_runs_collapse():
    assert RB.normalize_line("**Acme**") == "Acme"
    assert RB.normalize_line("a    b\t c") == "a b c"


def test_blank_lines_are_not_content():
    assert RB.content_lines("a\n\n\nb\n") == ["a", "b"]


# ---------------------------------------------------------------------------
# presence check — what read-back exists to catch
# ---------------------------------------------------------------------------

def test_live_canvas_rendering_is_not_reported_as_loss():
    assert RB.missing_lines(SENT, CANVAS_READBACK) == []


def test_truncation_is_caught():
    truncated = CANVAS_READBACK.split("# Action Items")[0]
    missing = RB.missing_lines(SENT, truncated)
    assert any("min SoC 잔여 4건" in m for m in missing)
    assert any("2026-07-28" in m for m in missing)


def test_empty_readback_reports_every_line():
    assert len(RB.missing_lines(SENT, "")) == len(RB.content_lines(SENT))


def test_wrong_document_is_caught():
    assert RB.missing_lines(SENT, "# 다른 회의\n* 관계없는 내용\n")


def test_duplicate_line_dropped_once_is_still_missing():
    """Set comparison would hide this: two identical items, one delivered."""
    sent = "- 확인 필요\n- 확인 필요\n"
    assert RB.missing_lines(sent, "* 확인 필요\n") == ["확인 필요"]


def test_extra_lines_in_readback_are_not_a_loss():
    """The renderer may add its own scaffolding; only omissions matter."""
    assert RB.missing_lines("- a\n", "* a\n* 편집자가 덧붙인 줄\n") == []


# --- Gmail hard-wraps a plaintext body near 78 columns (measured 2026-07-27) ---

GMAIL_SENT = """- 대표 케이스(3512): 계획 대비 늦은 입차 → 기존 스케줄(방전 우선) 잔존 → 타겟 SoC 미달. 배차(출차) 조기 변동이 원인 추정
- 조기 출차 시 SoC 미달 세션 로그 분석 후 min_SoC 50% 하향 관련 Beta 협의
"""

GMAIL_READBACK = """- 대표 케이스(3512): 계획 대비 늦은 입차 → 기존 스케줄(방전 우선) 잔존 → 타겟 SoC 미달. 배차(출차) 조기 변동이
원인 추정
- 조기 출차 시 SoC 미달 세션 로그 분석 후 min_SoC 50% 하향 관련 Beta 협의
"""


def test_hard_wrap_in_the_readback_is_not_a_loss():
    assert RB.missing_lines(GMAIL_SENT, GMAIL_READBACK) == []


def test_hard_wrap_does_not_mask_a_real_omission():
    """Wrapping tolerance must not become 'anything goes'."""
    lost = GMAIL_READBACK.replace(
        "- 조기 출차 시 SoC 미달 세션 로그 분석 후 min_SoC 50% 하향 관련 Beta 협의\n", "")
    missing = RB.missing_lines(GMAIL_SENT, lost)
    assert len(missing) == 1 and "조기 출차 시" in missing[0]


def test_mention_chip_expansion_is_not_a_loss():
    """Gmail appends the address to a mention chip: an addition, not an omission."""
    sent = "- 로그 분석 @김단아 책임\n"
    back = "- 로그 분석 @김단아 책임 <danakim@example.com>\n"
    assert RB.missing_lines(sent, back) == []


def test_strikethrough_marker_dropped_by_the_renderer_is_not_a_loss():
    assert RB.missing_lines("- ~~완료된 항목~~\n", "- 완료된 항목\n") == []


# ---------------------------------------------------------------------------
# mode selection
# ---------------------------------------------------------------------------

def test_mode_defaults_to_exact():
    assert RB.mode_for({}, "vault") == RB.EXACT
    assert RB.mode_for({"channels": {"vault": {"editable": True}}}, "vault") == RB.EXACT


def test_mode_reads_the_channel_declaration():
    cfg = {"channels": {"canvas": {"readback": "semantic"}}}
    assert RB.mode_for(cfg, "canvas") == RB.SEMANTIC


def test_unknown_mode_is_a_config_error_not_a_silent_default():
    cfg = {"channels": {"canvas": {"readback": "loose"}}}
    with pytest.raises(ValueError):
        RB.mode_for(cfg, "canvas")
