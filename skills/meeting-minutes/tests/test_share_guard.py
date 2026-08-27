# -*- coding: utf-8 -*-
"""2026-08-26 share regressions: bot-DM canvas and unconfirmed Gmail draft.

These cases actually happened (Claude Code / Hermes). The guard must fail-closed
so a later engine rewrite cannot report success for an unopenable canvas or a
draft that never landed in 임시보관함.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import share_guard as G  # noqa: E402

USER = "U0ACMEUSER01"
BOT_DM = "D0BOTDMCHAN1"
SELF_DM = "D0USERSAVED1"
CANVAS = "F0TESTCANVAS"
DRAFT = "r1650321974436598733"


def _canvas(**kw):
    base = {
        "attempted": True,
        "canvas_id": CANVAS,
        "destination": USER,
        "user_ids": [USER],
        "claim_success": True,
    }
    base.update(kw)
    return {
        "slack_user_id": USER,
        "slack_bot_dm_id": BOT_DM,
        "canvas": base,
    }


def _gmail(**kw):
    base = {
        "attempted": True,
        "draft_id": DRAFT,
        "confirmed": True,
        "claim_inbox": True,
    }
    base.update(kw)
    return {"gmail": base}


# ---------------------------------------------------------------------------
# the incidents
# ---------------------------------------------------------------------------

def test_bot_dm_canvas_is_blocked():
    """Canvas created in BOT_DM. User saw 권한 없음."""
    v = G.check_plan(_canvas(destination=BOT_DM, user_ids=[]))
    assert G.CANVAS_BOT_DM in v
    assert G.CANVAS_MISSING_USER_SHARE in v
    assert G.CANVAS_FALSE_SUCCESS in v


def test_bot_dm_even_with_user_ids_is_still_blocked():
    v = G.check_plan(_canvas(destination=BOT_DM, user_ids=[USER]))
    assert G.CANVAS_BOT_DM in v
    assert G.CANVAS_FALSE_SUCCESS in v


def test_missing_user_ids_is_blocked_even_on_a_good_dest():
    v = G.check_plan(_canvas(destination=USER, user_ids=[]))
    assert G.CANVAS_MISSING_USER_SHARE in v


def test_unsolicited_channel_post_is_blocked():
    v = G.check_plan(_canvas(destination="C0MINUTES01", user_ids=[USER]))
    assert G.CANVAS_UNSOLICITED_CHANNEL in v


def test_channel_ok_only_when_user_asked():
    v = G.check_plan(
        _canvas(destination="C0MINUTES01", user_ids=[USER], user_asked_channel=True)
    )
    assert G.CANVAS_UNSOLICITED_CHANNEL not in v
    assert v == []


def test_good_user_dm_share_passes():
    assert G.check_plan(_canvas()) == []


def test_user_ids_only_empty_dest_is_blocked():
    """08-25: empty dest + user_ids stuffed must not pass. user_ids is not dest."""
    v = G.check_plan(_canvas(destination="", user_ids=[USER]))
    assert G.CANVAS_MISSING_DEST in v
    assert G.CANVAS_FALSE_SUCCESS in v


def test_dest_check_before_create_does_not_require_canvas_id():
    """Dest share-check BEFORE Path create. canvas_id only after claim."""
    v = G.check_plan(_canvas(canvas_id="", claim_success=False, destination=USER, user_ids=[USER]))
    assert v == []


def test_precreate_empty_dest_blocks_without_claiming_id():
    v = G.check_plan(_canvas(canvas_id="", claim_success=False, destination="", user_ids=[USER]))
    assert G.CANVAS_MISSING_DEST in v
    assert G.CANVAS_MISSING_ID not in v
    assert G.CANVAS_FALSE_SUCCESS not in v


def test_missing_canvas_id_cannot_claim_success():
    v = G.check_plan(_canvas(canvas_id="", claim_success=True))
    assert G.CANVAS_MISSING_ID in v
    assert G.CANVAS_FALSE_SUCCESS in v


def test_gmail_claim_without_draft_id_is_blocked():
    """Claude Code said 임시보관함 without an id. Nothing landed."""
    v = G.check_plan(_gmail(draft_id="", confirmed=False, eml_path=""))
    assert G.GMAIL_NO_ID_NO_EML in v
    assert G.GMAIL_UNCONFIRMED in v


def test_gmail_id_without_confirm_cannot_claim_inbox():
    v = G.check_plan(_gmail(confirmed=False, claim_inbox=True))
    assert G.GMAIL_UNCONFIRMED in v


def test_gmail_eml_fallback_is_ok_if_not_claiming_inbox():
    v = G.check_plan(
        _gmail(draft_id="", confirmed=False, eml_path="work/draft.eml", claim_inbox=False,
               claim_success=False)
    )
    assert v == []


def test_gmail_file_path_as_id_is_blocked():
    v = G.check_plan(_gmail(draft_id="minutes.eml", confirmed=True))
    assert G.GMAIL_ID_LOOKS_LIKE_FILE in v


def test_gmail_confirmed_draft_passes():
    assert G.check_plan(_gmail()) == []


def test_skipped_share_is_not_a_violation():
    assert G.check_plan({"canvas": {"attempted": False}, "gmail": {"attempted": False}}) == []


# ---------------------------------------------------------------------------
# CLI / config merge
# ---------------------------------------------------------------------------

def test_merge_config_fills_ids(tmp_path):
    plan = {"canvas": {"attempted": True, "canvas_id": CANVAS, "destination": USER, "user_ids": [USER], "claim_success": True}}
    cfg = {"channels": {"slack_user_id": USER, "slack_bot_dm_id": BOT_DM}}
    merged = G.merge_config(plan, cfg)
    assert merged["slack_user_id"] == USER
    assert merged["slack_bot_dm_id"] == BOT_DM
    assert G.check_plan(merged) == []


def test_cli_bot_dm_exits_8(tmp_path, capsys):
    plan = _canvas(destination=BOT_DM, user_ids=[])
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    code = G.main(["--plan", str(p)])
    assert code == G.EXIT_BLOCKED
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert G.CANVAS_BOT_DM in out["violations"]


def test_cli_good_plan_exits_0(tmp_path, capsys):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(_canvas()), encoding="utf-8")
    code = G.main(["--plan", str(p)])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
