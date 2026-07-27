# -*- coding: utf-8 -*-
"""CLI protocol tests for mm_run.py — the enforcement surface.

Every row here is an escape hatch the prose gate in pipeline.md could not close.
Exit codes: 0 ok · 2 usage/config · 3 source hash mismatch · 4 read-back
mismatch · 5 lock held · 6 illegal transition · 7 completeness failed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mm_run as R  # noqa: E402
import mm_state as S  # noqa: E402

DOC = """---
date: 2026-07-27
attendees: [A, B]
---

# 개요

- 이슈 1
"""


def run(capsys, *argv):
    """Invoke the CLI; return (exit_code, parsed_stdout_json)."""
    code = R.main([str(a) for a in argv])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip() else {})


@pytest.fixture
def doc(tmp_path):
    p = tmp_path / "work" / "260727_데일리이슈.md"
    p.parent.mkdir(parents=True)
    p.write_text(DOC, encoding="utf-8")
    return p


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "categories:\n"
        "  daily: {detail_md: true, share_md: false, canvas: true, gmail: true, vault: true}\n"
        "channels:\n"
        "  canvas: {editable: false}\n"
        "  gmail: {editable: true}\n"
        "  vault: {editable: true}\n"
        "runtime: {state_dir: .mm, lease_ttl_min: 30, retention_days: 90}\n",
        encoding="utf-8",
    )
    return p


def approve(capsys, doc, cfg, **kw):
    code, out = run(capsys, "approve", "--doc", doc, "--config", cfg,
                    "--category", "daily", *sum(([k, v] for k, v in kw.items()), []))
    assert code == 0, out
    return out["lease"]


def state_dir(doc):
    return doc.parent / ".mm"


def manifest_of(doc):
    idx = S.read_index(state_dir(doc) / "index.json")
    doc_id = next(iter(idx["docs"]))
    run_id = idx["docs"][doc_id]["current_run"]
    return json.loads(
        (state_dir(doc) / "runs" / run_id / "manifest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# approve — immutable snapshot
# ---------------------------------------------------------------------------

def test_approve_writes_snapshot_and_manifest(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    m = manifest_of(doc)
    assert len(lease) == 32
    assert m["status"] == "approved"
    assert m["plan"] == ["vault", "canvas", "gmail"]
    assert m["source_sha256"] == S.source_hash(DOC)
    snap = state_dir(doc) / m["source_snapshot"]
    assert snap.read_text(encoding="utf-8") == DOC


def test_approve_mirrors_pointer_into_work_md_without_changing_its_hash(capsys, doc, cfg):
    approve(capsys, doc, cfg)
    after = doc.read_text(encoding="utf-8")
    assert "mm_doc_id:" in after and "mm_run:" in after
    assert S.source_hash(after) == S.source_hash(DOC), "mirror must not void the approval"


def test_approve_state_dir_is_beside_the_doc_not_in_a_vault(capsys, doc, cfg):
    approve(capsys, doc, cfg)
    assert (doc.parent / ".mm" / "index.json").exists()


def test_approve_unknown_category_exits_2(capsys, doc, cfg):
    code, _ = run(capsys, "approve", "--doc", doc, "--config", cfg, "--category", "nope")
    assert code == 2


# ---------------------------------------------------------------------------
# gate — the choke point (I3)
# ---------------------------------------------------------------------------

def test_gate_pass_returns_snapshot_path_and_create_action(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    code, out = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    assert code == 0
    assert out["action"] == "create"
    assert Path(out["snapshot_path"]).read_text(encoding="utf-8") == DOC
    assert len(out["idem_key"]) == 16


def test_gate_after_edit_exits_3_and_creates_no_artifact(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    doc.write_text(DOC.replace("이슈 1", "이슈 1 수정"), encoding="utf-8")
    code, out = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    assert code == 3
    assert out["diff"]
    assert not (state_dir(doc) / "runs").glob("*/rendered/*")or True
    assert list((state_dir(doc)).rglob("rendered/*")) == []


def test_gate_after_edit_supersedes_run_and_stales_artifacts(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    doc.write_text(DOC.replace("이슈 1", "이슈 2"), encoding="utf-8")
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    m = manifest_of(doc)
    assert m["status"] == "superseded"
    assert all(a["status"] == "stale" for a in m["artifacts"].values())
    events = S.read_events(state_dir(doc) / "runs.jsonl")
    assert any(e["event"] == "gate_blocked" for e in events)


def test_gate_requires_valid_lease(capsys, doc, cfg):
    approve(capsys, doc, cfg)
    code, _ = run(capsys, "gate", "--doc", doc, "--lease", "0" * 32, "--artifact", "canvas")
    assert code == 5


def test_gate_rejects_artifact_outside_the_frozen_plan(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    code, _ = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "share_md")
    assert code == 2


# ---------------------------------------------------------------------------
# record — second, independent hash check (I3)
# ---------------------------------------------------------------------------

def _record(capsys, doc, cfg, lease, artifact="canvas", body=None, ext_id="F09"):
    rendered = doc.parent / f"rendered_{artifact}.md"
    rendered.write_text(body if body is not None else DOC + "\n> mm:abc\n", encoding="utf-8")
    return run(capsys, "record", "--doc", doc, "--lease", lease, "--artifact", artifact,
               "--id", ext_id, "--body-file", rendered)


def test_record_stores_rendered_hash_and_id(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    code, out = _record(capsys, doc, cfg, lease)
    assert code == 0
    art = manifest_of(doc)["artifacts"]["canvas"]
    assert art["status"] == "created"
    assert art["external_id"] == "F09"
    assert art["rendered_sha256"] and art["attempts"] == 1


def test_record_after_edit_during_creation_exits_3_and_does_not_mark_created(capsys, doc, cfg):
    """The race the design exists for: edit lands between gate and create."""
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    doc.write_text(DOC.replace("이슈 1", "이슈 3"), encoding="utf-8")
    code, _ = _record(capsys, doc, cfg, lease)
    assert code == 3
    assert manifest_of(doc)["artifacts"]["canvas"]["status"] == "stale"


def test_record_without_prior_gate_exits_6(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    code, _ = _record(capsys, doc, cfg, lease)
    assert code == 6


# ---------------------------------------------------------------------------
# retry prefers read-back over create (I5)
# ---------------------------------------------------------------------------

def test_gate_returns_readback_action_once_an_id_exists(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    code, out = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    assert code == 0
    assert out["action"] == "readback"
    assert out["external_id"] == "F09"


# ---------------------------------------------------------------------------
# verify — created is not done (I4)
# ---------------------------------------------------------------------------

def _verify(capsys, doc, lease, artifact="canvas", body=None):
    back = doc.parent / f"readback_{artifact}.md"
    back.write_text(body if body is not None else DOC + "\n> mm:abc\n", encoding="utf-8")
    return run(capsys, "verify", "--doc", doc, "--lease", lease,
               "--artifact", artifact, "--readback-file", back)


def test_verify_matching_readback_marks_verified(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    code, _ = _verify(capsys, doc, lease)
    assert code == 0
    assert manifest_of(doc)["artifacts"]["canvas"]["status"] == "readback_verified"


def test_verify_mismatch_exits_4_and_leaves_artifact_created(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    code, out = _verify(capsys, doc, lease, body="본문이 잘렸음")
    assert code == 4
    assert manifest_of(doc)["artifacts"]["canvas"]["status"] == "created"
    events = S.read_events(state_dir(doc) / "runs.jsonl")
    assert any(e["event"] == "readback_mismatch" for e in events)


def test_verify_ignores_crlf_only_difference(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    code, _ = _verify(capsys, doc, lease, body=(DOC + "\n> mm:abc\n").replace("\n", "\r\n"))
    assert code == 0


# ---------------------------------------------------------------------------
# close — completeness (exit 7)
# ---------------------------------------------------------------------------

def _full_publish(capsys, doc, cfg, lease, artifacts=("vault", "canvas", "gmail")):
    for a in artifacts:
        run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", a)
        _record(capsys, doc, cfg, lease, artifact=a, ext_id=f"id-{a}")
        _verify(capsys, doc, lease, artifact=a)


def test_close_exits_7_while_an_artifact_is_unverified(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease, artifacts=("vault", "canvas"))
    code, out = run(capsys, "close", "--doc", doc, "--lease", lease)
    assert code == 7
    assert any("gmail" in b for b in out["blockers"])


def test_close_exits_7_on_open_blocking_manual_item(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease)
    run(capsys, "manual", "--doc", doc, "--lease", lease, "--add", "구본 canvas 삭제")
    code, _ = run(capsys, "close", "--doc", doc, "--lease", lease)
    assert code == 7


def test_close_completes_and_releases_the_lease(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease)
    code, _ = run(capsys, "close", "--doc", doc, "--lease", lease)
    assert code == 0
    assert manifest_of(doc)["status"] == "complete"
    idx = S.read_index(state_dir(doc) / "index.json")
    assert next(iter(idx["docs"].values()))["lock"] is None


def test_manual_done_unblocks_close(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease)
    run(capsys, "manual", "--doc", doc, "--lease", lease, "--add", "구본 삭제")
    run(capsys, "manual", "--doc", doc, "--lease", lease, "--done", "m1")
    code, _ = run(capsys, "close", "--doc", doc, "--lease", lease)
    assert code == 0


def test_manual_waive_is_logged_as_promotable(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease)
    run(capsys, "manual", "--doc", doc, "--lease", lease, "--add", "구본 삭제")
    run(capsys, "manual", "--doc", doc, "--lease", lease, "--waive", "m1",
        "--reason", "canvas 삭제 권한 없음")
    code, _ = run(capsys, "close", "--doc", doc, "--lease", lease)
    assert code == 0
    verdict = S.promotion_verdict(S.read_events(state_dir(doc) / "runs.jsonl"))
    assert verdict["promote"] is True


# ---------------------------------------------------------------------------
# lock (I7)
# ---------------------------------------------------------------------------

def test_second_owner_denied_but_status_still_works(capsys, doc, cfg):
    approve(capsys, doc, cfg)
    code, _ = run(capsys, "approve", "--doc", doc, "--config", cfg,
                  "--category", "daily", "--owner", "other:1")
    assert code == 5
    code, out = run(capsys, "status", "--doc", doc)
    assert code == 0 and out["run"]["status"] == "approved"


def test_reapprove_with_same_lease_creates_new_run_that_supersedes(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    first = manifest_of(doc)["run_id"]
    doc.write_text(DOC.replace("이슈 1", "이슈 1 수정"), encoding="utf-8")
    code, out = run(capsys, "approve", "--doc", doc, "--config", cfg,
                    "--category", "daily", "--lease", lease)
    assert code == 0
    m = manifest_of(doc)
    assert m["run_id"] != first and m["supersedes"] == first
    old = json.loads((state_dir(doc) / "runs" / first / "manifest.json").read_text("utf-8"))
    assert old["superseded_by"] == m["run_id"]


def test_wrong_lease_on_record_exits_5(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    code, _ = _record(capsys, doc, cfg, lease="f" * 32)
    assert code == 5


# ---------------------------------------------------------------------------
# status / fail / promote-check / gc
# ---------------------------------------------------------------------------

def test_status_on_unmanaged_doc_is_not_an_error(capsys, doc, cfg):
    code, out = run(capsys, "status", "--doc", doc)
    assert code == 0 and out["state"] == "unmanaged"


def test_fail_logs_without_a_lease(capsys, doc, cfg):
    approve(capsys, doc, cfg)
    code, _ = run(capsys, "fail", "--doc", doc, "--artifact", "canvas",
                  "--class", "transient", "--key", "canvas.rate_limit",
                  "--detail", "429")
    assert code == 0
    assert manifest_of(doc)["artifacts"]["canvas"]["status"] == "failed"


def test_promote_check_defaults_to_no_vault_write(capsys, doc, cfg):
    approve(capsys, doc, cfg)
    run(capsys, "fail", "--doc", doc, "--artifact", "canvas", "--class", "transient",
        "--key", "canvas.rate_limit", "--detail", "429")
    code, out = run(capsys, "promote-check", "--doc", doc)
    assert code == 0 and out["promote"] is False


def test_promote_check_flags_recurrence_across_runs(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "fail", "--doc", doc, "--artifact", "canvas", "--class", "transient",
        "--key", "canvas.rate_limit", "--detail", "429")
    doc.write_text(DOC.replace("이슈 1", "이슈 9"), encoding="utf-8")
    run(capsys, "approve", "--doc", doc, "--config", cfg, "--category", "daily",
        "--lease", lease)
    run(capsys, "fail", "--doc", doc, "--artifact", "canvas", "--class", "transient",
        "--key", "canvas.rate_limit", "--detail", "429")
    code, out = run(capsys, "promote-check", "--doc", doc)
    assert code == 0 and out["promote"] is True
    assert out["stub"], "must hand the agent a ready-to-paste note, not write the vault"


def test_gc_prunes_terminal_payload_but_keeps_manifest_and_log(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease)
    run(capsys, "close", "--doc", doc, "--lease", lease)
    run_id = manifest_of(doc)["run_id"]
    code, out = run(capsys, "gc", "--doc", doc, "--days", "0")
    assert code == 0 and run_id in out["pruned"]
    rd = state_dir(doc) / "runs" / run_id
    assert not (rd / "source.md").exists()
    assert (rd / "manifest.json").exists()
    assert (state_dir(doc) / "runs.jsonl").exists()


def test_gc_never_touches_a_live_run(capsys, doc, cfg):
    approve(capsys, doc, cfg)
    run_id = manifest_of(doc)["run_id"]
    code, out = run(capsys, "gc", "--doc", doc, "--days", "0")
    assert code == 0 and out["pruned"] == []
    assert (state_dir(doc) / "runs" / run_id / "source.md").exists()
