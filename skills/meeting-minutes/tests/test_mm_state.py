# -*- coding: utf-8 -*-
"""Unit tests for mm_state.py — the pure half of the runtime protocol.

Covers the design's §9 rows that need no CLI: hash domain, transition table,
lock CAS, supersede semantics, plan_artifacts, promotion verdict.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mm_state as S  # noqa: E402

NOW = datetime(2026, 7, 27, 14, 55, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# hash domain (§3) — the two silent-breakage guards
# ---------------------------------------------------------------------------

_DOC = """---
date: 2026-07-27
mm_doc_id: d-1
mm_run: r-1
attendees:
  - A
  - B
---

# 개요

- 본문
"""


def test_source_hash_ignores_mm_frontmatter_keys():
    """Runner refreshing its own mirror must not invalidate its own approval."""
    without = _DOC.replace("mm_doc_id: d-1\n", "").replace("mm_run: r-1\n", "")
    changed = _DOC.replace("mm_run: r-1", "mm_run: r-99")
    assert S.source_hash(_DOC) == S.source_hash(without)
    assert S.source_hash(_DOC) == S.source_hash(changed)


def test_source_hash_ignores_mm_key_continuation_lines():
    doc = _DOC.replace(
        "mm_run: r-1\n",
        "mm_artifacts:\n  canvas: F09\n  gmail: r-77\n",
    )
    assert S.source_hash(doc) == S.source_hash(_DOC.replace("mm_run: r-1\n", ""))


def test_source_hash_ignores_crlf_rewrite():
    assert S.source_hash(_DOC.replace("\n", "\r\n")) == S.source_hash(_DOC)


def test_source_hash_ignores_bom_and_trailing_blank_lines():
    assert S.source_hash("﻿" + _DOC + "\n\n  \n") == S.source_hash(_DOC)


def test_source_hash_detects_real_body_edit():
    assert S.source_hash(_DOC.replace("본문", "본문 수정")) != S.source_hash(_DOC)


def test_source_hash_detects_non_mm_frontmatter_edit():
    assert S.source_hash(_DOC.replace("- A", "- Z")) != S.source_hash(_DOC)


def test_strip_mm_keys_leaves_body_mm_lines_alone():
    """`mm_` is reserved in frontmatter only — a body line must still count."""
    doc = _DOC + "\nmm_note: 본문에 있는 줄\n"
    assert S.source_hash(doc) != S.source_hash(_DOC)


def test_doc_without_frontmatter_hashes_fine():
    assert S.source_hash("# 제목\n") == S.source_hash("# 제목")


def test_body_hash_does_not_strip_mm_keys():
    """Rendered/read-back comparison is byte-faithful apart from canon()."""
    changed = _DOC.replace("mm_run: r-1", "mm_run: r-99")
    assert S.body_hash(changed) != S.body_hash(_DOC)
    assert S.body_hash(_DOC.replace("\n", "\r\n")) == S.body_hash(_DOC)


def test_idem_key_is_stable_and_scoped():
    a = S.idem_key("d-1", "abc", "canvas")
    assert a == S.idem_key("d-1", "abc", "canvas")
    assert len(a) == 16
    assert a != S.idem_key("d-1", "abc", "gmail")
    assert a != S.idem_key("d-1", "abd", "canvas")


# ---------------------------------------------------------------------------
# plan_artifacts (§9 category contract)
# ---------------------------------------------------------------------------

_CFG = {
    "categories": {
        "daily": {"detail_md": True, "share_md": False, "canvas": True,
                  "gmail": True, "vault": True, "context_lookback": 3},
        "workshop": {"detail_md": True, "share_md": False, "canvas": True,
                     "gmail": "optional", "vault": True, "context_lookback": 2},
    }
}


def test_plan_daily_is_vault_canvas_gmail_without_share_md():
    plan = S.plan_artifacts(_CFG, "daily")
    assert plan == ["vault", "canvas", "gmail"]
    assert "share_md" not in plan


def test_plan_excludes_optional_by_default():
    assert S.plan_artifacts(_CFG, "workshop") == ["vault", "canvas"]


def test_plan_includes_optional_when_asked():
    assert S.plan_artifacts(_CFG, "workshop", include_optional=True) == [
        "vault", "canvas", "gmail"]


def test_plan_ignores_non_artifact_keys():
    assert "context_lookback" not in S.plan_artifacts(_CFG, "daily")
    assert "detail_md" not in S.plan_artifacts(_CFG, "daily")


def test_plan_unknown_category_raises():
    with pytest.raises(S.ConfigError):
        S.plan_artifacts(_CFG, "nope")


# ---------------------------------------------------------------------------
# transition table (§4)
# ---------------------------------------------------------------------------

def test_legal_run_transitions():
    S.assert_run_transition("approved", "publishing")
    S.assert_run_transition("publishing", "complete")
    S.assert_run_transition("approved", "superseded")


def test_illegal_run_transition_raises():
    with pytest.raises(S.IllegalTransition):
        S.assert_run_transition("complete", "publishing")


def test_artifact_created_cannot_skip_to_complete_without_readback():
    S.assert_artifact_transition("pending", "created")
    S.assert_artifact_transition("created", "readback_verified")
    with pytest.raises(S.IllegalTransition):
        S.assert_artifact_transition("pending", "readback_verified")


def test_artifact_failed_is_retryable_but_stale_is_terminal():
    S.assert_artifact_transition("failed", "created")
    with pytest.raises(S.IllegalTransition):
        S.assert_artifact_transition("stale", "created")


# ---------------------------------------------------------------------------
# lock lease + CAS (§5.2)
# ---------------------------------------------------------------------------

def test_acquire_lease_on_free_doc(tmp_path):
    idx = S.new_index()
    idx2, lease = S.acquire_lease(idx, "d-1", owner="host:1", ttl_min=30, now=NOW)
    assert lease and len(lease) == 32
    assert idx == S.new_index(), "acquire must not mutate the input index"
    assert idx2["docs"]["d-1"]["lock"]["version"] == 1


def test_second_owner_denied_while_lease_live():
    idx, _ = S.acquire_lease(S.new_index(), "d-1", owner="host:1", ttl_min=30, now=NOW)
    with pytest.raises(S.LockHeld):
        S.acquire_lease(idx, "d-1", owner="host:2", ttl_min=30,
                        now=NOW + timedelta(minutes=5))


def test_expired_lease_is_reclaimable():
    idx, _ = S.acquire_lease(S.new_index(), "d-1", owner="host:1", ttl_min=30, now=NOW)
    idx2, lease2 = S.acquire_lease(idx, "d-1", owner="host:2", ttl_min=30,
                                   now=NOW + timedelta(minutes=31))
    assert lease2 != idx["docs"]["d-1"]["lock"]["lease"]
    assert idx2["docs"]["d-1"]["lock"]["owner"] == "host:2"


def test_same_owner_reacquire_refreshes_same_lease():
    idx, lease = S.acquire_lease(S.new_index(), "d-1", owner="host:1", ttl_min=30, now=NOW)
    idx2, lease2 = S.acquire_lease(idx, "d-1", owner="host:1", ttl_min=30,
                                   now=NOW + timedelta(minutes=5))
    assert lease2 == lease
    assert idx2["docs"]["d-1"]["lock"]["expires_at"] > idx["docs"]["d-1"]["lock"]["expires_at"]


def test_check_lease_rejects_wrong_or_expired_token():
    idx, lease = S.acquire_lease(S.new_index(), "d-1", owner="host:1", ttl_min=30, now=NOW)
    S.check_lease(idx, "d-1", lease, now=NOW + timedelta(minutes=1))
    with pytest.raises(S.LockHeld):
        S.check_lease(idx, "d-1", "0" * 32, now=NOW)
    with pytest.raises(S.LockHeld):
        S.check_lease(idx, "d-1", lease, now=NOW + timedelta(minutes=31))


def test_write_index_cas_rejects_stale_version(tmp_path):
    path = tmp_path / "index.json"
    idx = S.new_index()
    S.write_index_cas(path, idx, expected_version=0)
    on_disk = S.read_index(path)
    S.write_index_cas(path, on_disk, expected_version=on_disk["version"])
    with pytest.raises(S.LockHeld):
        S.write_index_cas(path, on_disk, expected_version=on_disk["version"])


def test_read_index_missing_file_returns_empty(tmp_path):
    assert S.read_index(tmp_path / "nope.json") == S.new_index()


# ---------------------------------------------------------------------------
# supersede (§7)
# ---------------------------------------------------------------------------

def _manifest_with(canvas_status="readback_verified", gmail_status="pending"):
    m = S.new_manifest(
        doc_id="d-1", run_id="r-1", doc_path="/w/x.md", category="daily",
        source_sha256="a" * 64, plan=["vault", "canvas", "gmail"], now=NOW,
        approval_mode="explicit",
    )
    m["artifacts"]["canvas"].update(status=canvas_status, external_id="F09")
    m["artifacts"]["gmail"].update(status=gmail_status)
    return m


def test_supersede_marks_run_and_artifacts_stale():
    out = S.supersede(_manifest_with(), now=NOW, editable={"gmail": True, "canvas": False})
    assert out["status"] == "superseded"
    assert out["artifacts"]["canvas"]["status"] == "stale"
    assert out["artifacts"]["gmail"]["status"] == "stale"


def test_supersede_mints_blocking_manual_item_for_non_editable_published_artifact():
    out = S.supersede(_manifest_with(), now=NOW, editable={"gmail": True, "canvas": False})
    items = [i for i in out["manual_required"] if i["blocking"]]
    assert len(items) == 1
    assert "canvas" in items[0]["text"] and "F09" in items[0]["text"]


def test_supersede_no_manual_item_for_editable_or_unpublished():
    out = S.supersede(
        _manifest_with(canvas_status="pending", gmail_status="created"),
        now=NOW, editable={"gmail": True, "canvas": False},
    )
    assert out["manual_required"] == []


def test_supersede_is_pure():
    m = _manifest_with()
    before = json.dumps(m, sort_keys=True)
    S.supersede(m, now=NOW, editable={"canvas": False})
    assert json.dumps(m, sort_keys=True) == before


# ---------------------------------------------------------------------------
# completeness gate (§6 close / exit 7)
# ---------------------------------------------------------------------------

def test_close_blocked_when_artifact_not_readback_verified():
    m = _manifest_with(canvas_status="created", gmail_status="readback_verified")
    m["artifacts"]["vault"]["status"] = "readback_verified"
    blockers = S.completeness_blockers(m)
    assert any("canvas" in b for b in blockers)


def test_close_blocked_by_open_blocking_manual_item():
    m = _manifest_with(canvas_status="readback_verified", gmail_status="readback_verified")
    m["artifacts"]["vault"]["status"] = "readback_verified"
    m["manual_required"].append(
        {"id": "m1", "text": "구본 삭제", "blocking": True, "done": False, "done_at": None})
    assert S.completeness_blockers(m)


def test_close_allowed_when_all_verified():
    m = _manifest_with(canvas_status="readback_verified", gmail_status="readback_verified")
    m["artifacts"]["vault"]["status"] = "readback_verified"
    assert S.completeness_blockers(m) == []


# ---------------------------------------------------------------------------
# jsonl event log (§5.3)
# ---------------------------------------------------------------------------

def test_log_event_appends_one_line_per_record(tmp_path):
    p = tmp_path / "runs.jsonl"
    S.log_event(p, {"event": "approve", "doc_id": "d-1"}, now=NOW)
    S.log_event(p, {"event": "gate_blocked", "doc_id": "d-1"}, now=NOW)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["ts"].startswith("2026-07-27")


def test_log_event_rejects_embedded_newline(tmp_path):
    p = tmp_path / "runs.jsonl"
    S.log_event(p, {"event": "tool_error", "detail": "line1\nline2"}, now=NOW)
    assert len(p.read_text(encoding="utf-8").splitlines()) == 1


# ---------------------------------------------------------------------------
# promotion verdict (§8)
# ---------------------------------------------------------------------------

def _ev(**kw):
    base = {"ts": "2026-07-27T00:00:00+00:00", "doc_id": "d-1", "run_id": "r-1",
            "event": "tool_error", "failure_class": "transient",
            "root_cause_key": "canvas.rate_limit", "impact": "none"}
    base.update(kw)
    return base


def test_promotion_denied_for_single_transient_failure():
    assert S.promotion_verdict([_ev()])["promote"] is False


def test_promotion_on_high_impact():
    v = S.promotion_verdict([_ev(impact="external_share_error")])
    assert v["promote"] is True and "impact" in v["reasons"][0]


def test_promotion_on_recurrence_across_distinct_runs():
    evs = [_ev(run_id="r-1"), _ev(run_id="r-2")]
    assert S.promotion_verdict(evs)["promote"] is True


def test_recurrence_within_one_run_is_not_promotion():
    evs = [_ev(run_id="r-1"), _ev(run_id="r-1"), _ev(run_id="r-1")]
    assert S.promotion_verdict(evs)["promote"] is False


def test_promotion_on_contract_class_and_on_waiver():
    assert S.promotion_verdict([_ev(failure_class="contract")])["promote"] is True
    assert S.promotion_verdict([_ev(event="manual_waived")])["promote"] is True
