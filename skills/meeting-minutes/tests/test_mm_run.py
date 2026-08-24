# -*- coding: utf-8 -*-
"""CLI protocol tests for mm_run.py — the enforcement surface.

Every row here is an escape hatch the prose gate in pipeline.md could not close.
Exit codes: 0 ok · 2 usage/config · 3 source hash mismatch · 4 read-back
mismatch · 5 lock held · 6 illegal transition · 7 completeness failed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mm_run as R  # noqa: E402
import mm_state as S  # noqa: E402

RECEIPT_SECRET = "test-authenticated-adapter-secret"
ONTOLOGY_VALIDATOR_RECEIPT_SECRET = "test-ontology-validator-receipt-secret"
os.environ.setdefault(R.CONNECTOR_RECEIPT_SECRET_ENV, RECEIPT_SECRET)
os.environ.setdefault("MM_ONTOLOGY_VALIDATOR_RECEIPT_SECRET", ONTOLOGY_VALIDATOR_RECEIPT_SECRET)

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
def plain_doc(tmp_path):
    """A work MD with no frontmatter — the shape real daily minutes have, since
    the file is pasted into a team chat as-is (live run 2026-07-27)."""
    p = tmp_path / "work" / "260727_데일리이슈.md"
    p.parent.mkdir(parents=True)
    p.write_text("# Daily 이슈 회의록\n\n- 이슈 1\n", encoding="utf-8")
    return p


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "categories:\n"
        "  daily: {detail_md: true, share_md: false, canvas: true, gmail: true, vault: true}\n"
        "channels:\n"
        "  canvas: {editable: false, readback: semantic}\n"
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


def with_footer(doc, artifact, body):
    idem = manifest_of(doc)["artifacts"][artifact]["idem_key"]
    return body.rstrip("\n") + f"\n> mm:{idem}\n"


def authenticated_receipt(doc, artifact, body):
    external_id = manifest_of(doc)["artifacts"][artifact]["external_id"]
    now = S.iso(S.utcnow())
    receipt = {
        "schema": R.CONNECTOR_RECEIPT_SCHEMA,
        "artifact": artifact,
        "external_id": external_id,
        "fetched_at": now,
        "body": body,
        "remote": {
            "id": external_id,
            "url": f"https://connector.test/{artifact}/{external_id}",
            "retrieved_at": now,
        },
        "adapter": {
            "name": "test-authenticated-adapter",
            "auth": "hmac-sha256",
            "key_id": "test-key-v1",
            "signature": "",
        },
    }
    receipt["adapter"]["signature"] = R.connector_receipt_signature(receipt, RECEIPT_SECRET)
    return receipt


def authenticated_ontology_validator_receipt(ttl_text, meeting_iri, triple_count=1):
    """A test-only stand-in for a trusted parser capability receipt."""
    receipt = {
        "schema": "mm-ontology-validator-receipt/1",
        "ttl_sha256": S.body_hash(ttl_text),
        "meeting_iri": meeting_iri,
        "triple_count": triple_count,
        "validated_at": S.iso(S.utcnow()),
        "validator": {
            "name": "test-turtle-parser",
            "capability": "turtle-parse/1",
            "auth": "hmac-sha256",
            "key_id": "test-validator-key-v1",
            "signature": "",
        },
    }
    signed = json.loads(json.dumps(receipt))
    signed["validator"].pop("signature", None)
    payload = json.dumps(signed, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    receipt["validator"]["signature"] = hmac.new(
        ONTOLOGY_VALIDATOR_RECEIPT_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return receipt


def audit_evidence_file(doc, artifact, finding="remote read-back disproved"):
    external_id = manifest_of(doc)["artifacts"][artifact]["external_id"]
    evidence = doc.parent / f"audit-{artifact}.json"
    evidence.write_text(json.dumps({
        "schema": "mm-audit-evidence/1",
        "artifact": artifact,
        "external_id": external_id,
        "finding": finding,
        "observed_at": S.iso(S.utcnow()),
    }, ensure_ascii=False), encoding="utf-8")
    return evidence


# ---------------------------------------------------------------------------
# approve — immutable snapshot
# ---------------------------------------------------------------------------


def test_concurrent_approve_creates_no_losing_run_payload(monkeypatch, doc, cfg):
    """P0: losing an index CAS must not leave a second snapshot/manifest behind."""
    original_write = S.write_index_cas

    def delayed_write(*args, **kwargs):
        time.sleep(0.15)  # force both callers to create their pre-CAS payloads
        return original_write(*args, **kwargs)

    monkeypatch.setattr(S, "write_index_cas", delayed_write)
    start = threading.Barrier(2)
    results = []

    def worker(owner):
        start.wait(timeout=3)
        results.append(R.main([
            "approve", "--doc", str(doc), "--config", str(cfg), "--category", "daily",
            "--owner", owner,
        ]))

    workers = [threading.Thread(target=worker, args=(f"worker-{i}",)) for i in range(2)]
    for worker_thread in workers:
        worker_thread.start()
    for worker_thread in workers:
        worker_thread.join(timeout=5)
    assert all(not worker_thread.is_alive() for worker_thread in workers)
    assert sorted(results) == [0, 5]
    assert len(list((state_dir(doc) / "runs").glob("r-*"))) == 1


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


def test_approve_rejects_a_non_mapping_yaml_root(capsys, doc, tmp_path):
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("- not-a-mapping\n", encoding="utf-8")
    code, out = run(capsys, "approve", "--doc", doc, "--config", malformed, "--category", "daily")
    assert code == 2
    assert "mapping" in out["detail"]


def test_approve_rejects_invalid_declared_schema_v2(capsys, doc, cfg):
    doc.write_text("---\nschema_version: 2\nrecordings: raw.txt\naction_items: 3\nartifacts: {}\n---\n# 회의\n",
                   encoding="utf-8")
    code, out = run(capsys, "approve", "--doc", doc, "--config", cfg, "--category", "daily")
    assert code == 2
    assert "recordings must be a list" in out["detail"]
    assert not (doc.parent / ".mm").exists()


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
    assert out["footer"] == f"> mm:{out['idem_key']}"


def test_gate_mirrors_publishing_state_without_losing_runtime_metadata(capsys, doc, cfg):
    """A successful gate moves the run to publishing in both authoritative state and mirror."""
    lease = approve(capsys, doc, cfg)
    code, _ = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    assert code == 0
    assert manifest_of(doc)["status"] == "publishing"
    assert "mm_state: publishing" in doc.read_text(encoding="utf-8")


def test_gate_rejects_a_second_open_create_gate(capsys, doc, cfg):
    """M1: one artifact may have only one outstanding create authorization."""
    lease = approve(capsys, doc, cfg)
    first_code, first = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    second_code, second = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    assert first_code == 0 and first["gate_token"]
    assert second_code == 6
    assert "open gate" in second["detail"]
    assert manifest_of(doc)["artifacts"]["canvas"]["gate_token"] == first["gate_token"]


def test_concurrent_same_lease_gate_issues_only_one_create_token(monkeypatch, capsys, doc, cfg):
    """P0: concurrent gate calls need a per-artifact transaction boundary."""
    lease = approve(capsys, doc, cfg)
    original_save = R.Workspace.save_manifest
    write_lock = threading.Lock()

    def delayed_save(self, manifest):
        art = manifest.get("artifacts", {}).get("canvas", {})
        if art.get("gate_token"):
            time.sleep(0.12)
        with write_lock:
            return original_save(self, manifest)

    monkeypatch.setattr(R.Workspace, "save_manifest", delayed_save)
    start = threading.Barrier(2)
    results = []

    def worker():
        start.wait(timeout=3)
        results.append(R.main([
            "gate", "--doc", str(doc), "--config", str(cfg), "--lease", lease,
            "--artifact", "canvas",
        ]))

    workers = [threading.Thread(target=worker) for _ in range(2)]
    for worker_thread in workers:
        worker_thread.start()
    for worker_thread in workers:
        worker_thread.join(timeout=5)
    assert all(not worker_thread.is_alive() for worker_thread in workers)
    assert sorted(results) == [0, 5]
    intent = manifest_of(doc)["artifacts"]["canvas"]["create_intent"]
    assert intent["state"] == "open" and intent["token"]


def test_approve_refuses_a_doc_inside_the_canonical_store(capsys, tmp_path):
    """I2 is a guard, not a promise: run state must never land in the vault.

    `.mm/` holds source.md and rendered/*.md — inside a vault whose search index
    globs `**/*.md`, every snapshot would be indexed as another meeting note.
    """
    vault = tmp_path / "vault"
    (vault / "spp" / "meetings").mkdir(parents=True)
    note = vault / "spp" / "meetings" / "2026-07-27 daily.md"
    note.write_text(DOC, encoding="utf-8")
    conf = tmp_path / "config.yaml"
    conf.write_text(
        f'paths: {{vault: "{vault.as_posix()}"}}\n'
        "categories:\n"
        "  daily: {canvas: true, vault: true}\n",
        encoding="utf-8",
    )
    code, out = run(capsys, "approve", "--doc", note, "--config", conf,
                    "--category", "daily")
    assert code == 2
    assert not (note.parent / ".mm").exists()
    assert "vault" in json.dumps(out, ensure_ascii=False).lower()


def test_gate_after_edit_exits_3_and_creates_no_artifact(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    doc.write_text(DOC.replace("이슈 1", "이슈 1 수정"), encoding="utf-8")
    code, out = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    assert code == 3
    assert out["diff"]
    assert list(state_dir(doc).rglob("rendered/*")) == []


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

def _claim_create(capsys, doc, cfg, lease, artifact="canvas", gate_token=None):
    token = gate_token if gate_token is not None else manifest_of(doc)["artifacts"][artifact].get("gate_token")
    return run(capsys, "claim-create", "--doc", doc, "--config", cfg, "--lease", lease,
               "--artifact", artifact, "--gate-token", token or "")


def _record(capsys, doc, cfg, lease, artifact="canvas", body=None, ext_id="F09", gate_token=None,
            claim_id=None):
    rendered = doc.parent / f"rendered_{artifact}.md"
    # write_bytes, not write_text: on Windows text mode rewrites "\n" as "\r\n",
    # so a CRLF fixture would land as "\r\r\n" and fake a content change.
    footer = f"> mm:{manifest_of(doc)['artifacts'][artifact]['idem_key']}\n"
    rendered.write_bytes((body if body is not None else DOC + "\n" + footer).encode("utf-8"))
    token = gate_token if gate_token is not None else manifest_of(doc)["artifacts"][artifact].get("gate_token")
    if claim_id is None:
        claim_code, claim = _claim_create(capsys, doc, cfg, lease, artifact, token)
        if claim_code:
            return claim_code, claim
        claim_id = claim["claim_id"]
    return run(capsys, "record", "--doc", doc, "--lease", lease, "--artifact", artifact,
               "--id", ext_id, "--body-file", rendered, "--gate-token", token or "",
               "--claim-id", claim_id)


def test_record_stores_rendered_hash_and_id(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    code, out = _record(capsys, doc, cfg, lease)
    assert code == 0
    art = manifest_of(doc)["artifacts"]["canvas"]
    assert art["status"] == "created"
    assert art["external_id"] == "F09"
    assert art["rendered_sha256"] and art["attempts"] == 1


def test_claim_create_consumes_a_gate_token_once_before_external_create(capsys, doc, cfg):
    """P0: a bearer token must become one durable pre-create claim, not two creates."""
    lease = approve(capsys, doc, cfg)
    _, gate = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")

    first_code, first = run(capsys, "claim-create", "--doc", doc, "--config", cfg,
                            "--lease", lease, "--artifact", "canvas",
                            "--gate-token", gate["gate_token"])
    second_code, _ = run(capsys, "claim-create", "--doc", doc, "--config", cfg,
                         "--lease", lease, "--artifact", "canvas",
                         "--gate-token", gate["gate_token"])

    assert first_code == 0
    assert first["claim_id"]
    assert first["provider_idempotency_key"] == gate["idem_key"]
    assert second_code == 6
    art = manifest_of(doc)["artifacts"]["canvas"]
    assert art["gate_token"] is None
    assert art["create_intent"]["state"] == "claimed"
    assert art["create_intent"]["claim_id"] == first["claim_id"]


def test_concurrent_claim_create_issues_one_provider_authorization(monkeypatch, capsys, doc, cfg):
    """P0: lock contention must deny the second pre-create claimant."""
    lease = approve(capsys, doc, cfg)
    _, gate = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    original_save = R.Workspace.save_manifest
    start = threading.Barrier(2)
    results = []

    def delayed_save(self, manifest):
        if manifest["artifacts"]["canvas"].get("create_intent", {}).get("state") == "claimed":
            time.sleep(0.12)
        return original_save(self, manifest)

    monkeypatch.setattr(R.Workspace, "save_manifest", delayed_save)

    def worker():
        start.wait(timeout=3)
        results.append(R.main([
            "claim-create", "--doc", str(doc), "--config", str(cfg), "--lease", lease,
            "--artifact", "canvas", "--gate-token", gate["gate_token"],
        ]))

    workers = [threading.Thread(target=worker) for _ in range(2)]
    for worker_thread in workers:
        worker_thread.start()
    for worker_thread in workers:
        worker_thread.join(timeout=5)
    assert all(not worker_thread.is_alive() for worker_thread in workers)
    assert sorted(results) == [0, 5]
    assert manifest_of(doc)["artifacts"]["canvas"]["create_intent"]["state"] == "claimed"


def test_gate_after_claim_crash_requires_manual_recovery_not_second_create(capsys, doc, cfg):
    """P0: a claimed-but-unrecorded provider create is never retried blindly."""
    lease = approve(capsys, doc, cfg)
    _, gate = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    claim_code, claim = _claim_create(capsys, doc, cfg, lease, gate_token=gate["gate_token"])
    assert claim_code == 0

    code, recovery = run(capsys, "gate", "--doc", doc, "--config", cfg,
                         "--lease", lease, "--artifact", "canvas")

    assert code == 0
    assert recovery["action"] == "manual_recovery"
    assert recovery["gate_token"] is None
    assert recovery["claim_id"] == claim["claim_id"]
    assert recovery["provider_idempotency_key"] == gate["idem_key"]


def test_concurrent_record_with_one_claim_persists_exactly_one_external_id(monkeypatch, capsys, doc, cfg):
    """P0: even duplicate provider responses cannot overwrite the first record."""
    lease = approve(capsys, doc, cfg)
    _, gate = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _, claim = _claim_create(capsys, doc, cfg, lease, gate_token=gate["gate_token"])
    body = doc.parent / "canvas.md"
    body.write_text(with_footer(doc, "canvas", DOC), encoding="utf-8")
    original_save = R.Workspace.save_manifest
    start = threading.Barrier(2)
    results = []

    def delayed_save(self, manifest):
        if manifest["artifacts"]["canvas"].get("external_id"):
            time.sleep(0.12)
        return original_save(self, manifest)

    monkeypatch.setattr(R.Workspace, "save_manifest", delayed_save)

    def worker(external_id):
        start.wait(timeout=3)
        results.append(R.main([
            "record", "--doc", str(doc), "--config", str(cfg), "--lease", lease,
            "--artifact", "canvas", "--id", external_id, "--body-file", str(body),
            "--gate-token", gate["gate_token"], "--claim-id", claim["claim_id"],
        ]))

    workers = [threading.Thread(target=worker, args=(external_id,))
               for external_id in ("canvas-race-A", "canvas-race-B")]
    for worker_thread in workers:
        worker_thread.start()
    for worker_thread in workers:
        worker_thread.join(timeout=5)
    assert all(not worker_thread.is_alive() for worker_thread in workers)
    assert sorted(results) in ([0, 5], [0, 6])
    art = manifest_of(doc)["artifacts"]["canvas"]
    assert art["external_id"] in {"canvas-race-A", "canvas-race-B"}
    assert art["attempts"] == 1 and art["create_intent"]["state"] == "recorded"


def test_record_rejects_an_unclaimed_gate_before_provider_side_effect(capsys, doc, cfg):
    """P0: record cannot substitute for the atomic pre-create claim operation."""
    lease = approve(capsys, doc, cfg)
    _, gate = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    body = doc.parent / "canvas.md"
    body.write_text(with_footer(doc, "canvas", DOC), encoding="utf-8")

    code, _ = run(capsys, "record", "--doc", doc, "--lease", lease, "--artifact", "canvas",
                  "--id", "F09", "--body-file", body, "--gate-token", gate["gate_token"],
                  "--claim-id", "not-a-claim")

    assert code == 6
    assert manifest_of(doc)["artifacts"]["canvas"]["status"] == "pending"


def test_record_rejects_a_gate_token_from_another_create_intent(capsys, doc, cfg):
    """P0: record must be bound to the exact durable authorization it consumes."""
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    body = doc.parent / "canvas.md"
    body.write_text(with_footer(doc, "canvas", DOC), encoding="utf-8")

    _, claim = _claim_create(capsys, doc, cfg, lease, gate_token=manifest_of(doc)["artifacts"]["canvas"]["gate_token"])
    code, _ = run(capsys, "record", "--doc", doc, "--lease", lease, "--artifact", "canvas",
                  "--id", "F09", "--body-file", body, "--gate-token", "wrong-token",
                  "--claim-id", claim["claim_id"])

    assert code == 6
    assert manifest_of(doc)["artifacts"]["canvas"]["status"] == "pending"


def test_record_rejects_a_body_without_its_exact_idempotency_footer(capsys, doc, cfg):
    """P0: the supplied body must carry the current gate's discoverable footer."""
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    code, out = _record(capsys, doc, cfg, lease, body=DOC)
    assert code == 2
    assert "footer" in out["detail"]
    art = manifest_of(doc)["artifacts"]["canvas"]
    assert art["status"] == "pending" and art["external_id"] is None


def test_record_mirrors_external_artifact_id_without_changing_approval_hash(capsys, doc, cfg):
    """Canvas IDs are runtime metadata, not a post-verify canonical-body edit."""
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease, ext_id="F09")
    mirrored = doc.read_text(encoding="utf-8")
    assert "mm_artifacts:" in mirrored and "canvas: F09" in mirrored
    assert S.source_hash(mirrored) == S.source_hash(DOC)


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
    assert out["gate_token"] is None, "readback must not authorize a replacement record"


# ---------------------------------------------------------------------------
# verify — created is not done (I4)
# ---------------------------------------------------------------------------

def _verify(capsys, doc, lease, artifact="canvas", body=None):
    back = doc.parent / f"readback_{artifact}.md"
    # write_bytes, not write_text: Windows text mode rewrites "\n" as "\r\n", so a
    # CRLF fixture would land on disk as "\r\r\n" and fake a content change.
    footer = f"> mm:{manifest_of(doc)['artifacts'][artifact]['idem_key']}\n"
    back.write_bytes((body if body is not None else DOC + "\n" + footer).encode("utf-8"))
    if artifact in R.EXTERNAL_RECEIPT_REQUIRED:
        receipt = doc.parent / f"receipt_{artifact}.json"
        receipt.write_text(json.dumps(authenticated_receipt(doc, artifact, back.read_text(encoding="utf-8")),
                                      ensure_ascii=False), encoding="utf-8")
        return run(capsys, "verify", "--doc", doc, "--lease", lease,
                   "--artifact", artifact, "--connector-receipt", receipt)
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


def test_verify_missing_readback_file_returns_structured_failure_and_logs(capsys, doc, cfg):
    """M3: a local readback I/O error is an auditable protocol failure, not a traceback."""
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "vault")
    _record(capsys, doc, cfg, lease, artifact="vault", ext_id="v1")
    missing = doc.parent / "not-present.md"
    code, out = run(capsys, "verify", "--doc", doc, "--lease", lease,
                    "--artifact", "vault", "--readback-file", missing)
    assert code == 4
    assert out["error"] == "readback_input_error"
    events = S.read_events(state_dir(doc) / "runs.jsonl")
    assert any(e.get("root_cause_key") == "vault.readback_input_error" for e in events)


def test_external_raw_readback_is_held_for_manual_confirmation(capsys, doc, cfg):
    """P0: a local body copy is not evidence of a Canvas/Gmail remote read-back."""
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    copy = doc.parent / "copied_canvas.md"
    copy.write_text(with_footer(doc, "canvas", DOC), encoding="utf-8")
    code, out = run(capsys, "verify", "--doc", doc, "--lease", lease,
                    "--artifact", "canvas", "--readback-file", copy)
    assert code == 0
    assert out["status"] == "manual_required"
    close_code, close_out = run(capsys, "close", "--doc", doc, "--lease", lease)
    assert close_code == 7
    assert any("canvas" in blocker for blocker in close_out["blockers"])


def test_unsigned_connector_receipt_is_manual_required_not_readback_verified(capsys, doc, cfg):
    """P0: schema-looking local JSON is not an authenticated remote retrieval."""
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    receipt = doc.parent / "forged-canvas.json"
    receipt.write_text(json.dumps({
        "schema": "mm-connector-receipt/1", "artifact": "canvas", "external_id": "F09",
        "fetched_at": "2026-08-24T00:00:00+00:00", "body": with_footer(doc, "canvas", DOC),
    }), encoding="utf-8")

    code, out = run(capsys, "verify", "--doc", doc, "--lease", lease,
                    "--artifact", "canvas", "--connector-receipt", receipt)

    assert code == 0
    assert out["status"] == "manual_required"
    assert manifest_of(doc)["artifacts"]["canvas"]["status"] == "manual_required"


def test_semantic_channel_accepts_the_renderers_own_rewrite(capsys, doc, cfg):
    """Slack canvas rewrites `-` bullets to `*` and wraps dates in an embed
    (measured on a live canvas). Byte comparison there would fail every run."""
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease, body=with_footer(
        doc, "canvas", "# 회의\n- [ ] 확인 필요 항목\n- 2026-07-28 Beta 회의\n"))
    code, _ = _verify(capsys, doc, lease, body=with_footer(
        doc, "canvas", "# 회의\n\n* [ ] 확인 필요 항목\n\n"
        "* ![](slack_date:2026-07-28) Beta 회의\n"))
    assert code == 0
    art = manifest_of(doc)["artifacts"]["canvas"]
    assert art["status"] == "readback_verified" and art["readback_mode"] == "semantic"
    assert (state_dir(doc) / "runs" / manifest_of(doc)["run_id"] / "readback" /
            "canvas.receipt.json").exists()


def test_semantic_channel_still_catches_truncation(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease, body=with_footer(
        doc, "canvas", "# 회의\n- 첫 항목\n- 잘려나갈 항목\n"))
    code, out = _verify(capsys, doc, lease, body=with_footer(doc, "canvas", "# 회의\n\n* 첫 항목\n"))
    assert code == 4
    assert out["missing_lines"] == ["잘려나갈 항목"]
    assert manifest_of(doc)["artifacts"]["canvas"]["status"] == "created"


def test_exact_channel_is_unchanged_by_the_semantic_option(capsys, doc, cfg):
    """vault declares no readback mode -> byte comparison stays in force."""
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "vault")
    _record(capsys, doc, cfg, lease, artifact="vault",
            body=with_footer(doc, "vault", "- 항목\n"), ext_id="v1")
    code, _ = _verify(capsys, doc, lease, artifact="vault",
                      body=with_footer(doc, "vault", "* 항목\n"))
    assert code == 4, "exact channels must not absorb a bullet rewrite"


def test_verify_ignores_crlf_only_difference(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    code, _ = _verify(capsys, doc, lease,
                      body=with_footer(doc, "canvas", DOC).replace("\n", "\r\n"))
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


def test_required_ontology_blocks_close_until_ttl_or_graph_readback(capsys, doc, cfg):
    """M2: config-level required ontology must be a real completion blocker."""
    with cfg.open("a", encoding="utf-8") as handle:
        handle.write("ontology: {required: true}\n")
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease, artifacts=("vault", "canvas", "gmail"))
    code, out = run(capsys, "close", "--doc", doc, "--lease", lease)
    assert code == 7
    assert any("ontology" in blocker for blocker in out["blockers"])


def test_required_ontology_rejects_generic_prose_recording(capsys, doc, cfg):
    """P0: a required graph cannot become verified through generic MD read-back."""
    with cfg.open("a", encoding="utf-8") as handle:
        handle.write("ontology: {required: true}\n")
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "ontology")

    code, _ = _record(capsys, doc, cfg, lease, artifact="ontology",
                      body=with_footer(doc, "ontology", "arbitrary prose"), ext_id="local-claim")

    assert code == 2
    assert manifest_of(doc)["artifacts"]["ontology"]["status"] == "pending"


def test_ontology_runner_validates_loads_and_queries_before_verification(capsys, doc, cfg):
    """P0: a configured runner must complete TTL validate→load→query read-back."""
    runner = doc.parent / "fake_ontology_runner.py"
    calls = runner.with_suffix(".calls")
    runner.write_text(
        "from pathlib import Path\n"
        "import json, sys\n"
        "with Path(__file__).with_suffix('.calls').open('a', encoding='utf-8') as out:\n"
        "    out.write(sys.argv[1] + '\\n')\n"
        "print(json.dumps({'count': 1} if sys.argv[1] == 'query' else {'ok': True}))\n",
        encoding="utf-8",
    )
    command = f'\"{sys.executable}\" \"{runner}\"'
    with cfg.open("a", encoding="utf-8") as handle:
        handle.write("ontology:\n  required: true\n  runner: " + json.dumps(command) + "\n")
    lease = approve(capsys, doc, cfg)
    ttl = doc.parent / "meeting.ttl"
    iri = "urn:meeting:260727"
    ttl.write_text(f"<{iri}> <urn:predicate:decision> \"approved\" .\n", encoding="utf-8")

    code, _ = run(capsys, "ontology", "--doc", doc, "--config", cfg, "--lease", lease,
                  "--ttl-file", ttl, "--meeting-iri", iri)

    assert code == 0
    assert calls.read_text(encoding="utf-8").splitlines() == ["validate", "load", "query"]
    art = manifest_of(doc)["artifacts"]["ontology"]
    assert art["status"] == "readback_verified"
    assert art["provenance"]["mode"] == "runner"


def _approve_ontology_only(capsys, doc, cfg):
    cfg.write_text(
        "categories:\n"
        "  ontology_only: {vault: false, canvas: false, gmail: false, share_md: false}\n"
        "runtime: {state_dir: .mm, lease_ttl_min: 30}\n"
        "ontology: {required: true, runner: null}\n",
        encoding="utf-8",
    )
    code, approved = run(capsys, "approve", "--doc", doc, "--config", cfg,
                         "--category", "ontology_only")
    assert code == 0, approved
    return approved["lease"]


@pytest.mark.parametrize("label,ttl_text", [
    ("unknown-escape", '<urn:meeting:invalid> <urn:predicate:test> "bad \\q" .\n'),
    ("malformed-unicode", '<urn:meeting:invalid> <urn:predicate:test> "bad \\u12G4" .\n'),
    ("unterminated-literal", '<urn:meeting:invalid> <urn:predicate:test> "bad .\n'),
    ("malformed-iri", '<urn:meeting:invalid> <urn:predicate bad> "ok" .\n'),
    ("broken-directive", '@prefix ex <urn:example:> .\n<urn:meeting:invalid> ex:p "ok" .\n'),
])
def test_runnerless_ontology_rejects_invalid_turtle_syntax_and_keeps_close_blocked(
        capsys, doc, cfg, label, ttl_text):
    """P1: lexical shape is only a rejection filter, never a promotion proof."""
    lease = _approve_ontology_only(capsys, doc, cfg)
    ttl = doc.parent / f"{label}.ttl"
    ttl.write_text(ttl_text, encoding="utf-8")

    code, _ = run(capsys, "ontology", "--doc", doc, "--config", cfg, "--lease", lease,
                  "--ttl-file", ttl, "--meeting-iri", "urn:meeting:invalid",
                  "--degraded-reason", "runner unavailable in test environment")

    assert code == 2
    assert manifest_of(doc)["artifacts"]["ontology"]["status"] == "pending"
    assert run(capsys, "close", "--doc", doc, "--lease", lease)[0] == 7


def test_runnerless_valid_turtle_without_trusted_validator_is_manual_required(capsys, doc, cfg):
    """P1: saving a syntactically plausible TTL cannot self-attest completion."""
    lease = _approve_ontology_only(capsys, doc, cfg)
    iri = "urn:meeting:260727"
    ttl_text = f"<{iri}> <urn:predicate:decision> \"approved\" .\n"
    ttl = doc.parent / "meeting.ttl"
    ttl.write_text(ttl_text, encoding="utf-8")

    code, out = run(capsys, "ontology", "--doc", doc, "--config", cfg, "--lease", lease,
                    "--ttl-file", ttl, "--meeting-iri", iri,
                    "--degraded-reason", "runner unavailable in test environment")

    assert code == 0 and out["status"] == "manual_required"
    assert manifest_of(doc)["artifacts"]["ontology"]["status"] == "manual_required"
    assert run(capsys, "close", "--doc", doc, "--lease", lease)[0] == 7


def test_runnerless_valid_turtle_requires_authenticated_validator_receipt(capsys, doc, cfg):
    """P1: only a hash-bound trusted parser receipt can prove degraded completion."""
    lease = _approve_ontology_only(capsys, doc, cfg)
    iri = "urn:meeting:260727"
    ttl_text = f"<{iri}> <urn:predicate:decision> \"approved\" .\n"
    ttl = doc.parent / "meeting.ttl"
    ttl.write_text(ttl_text, encoding="utf-8")
    receipt = doc.parent / "validator-receipt.json"
    receipt.write_text(json.dumps(authenticated_ontology_validator_receipt(ttl_text, iri)),
                       encoding="utf-8")

    code, out = run(capsys, "ontology", "--doc", doc, "--config", cfg, "--lease", lease,
                    "--ttl-file", ttl, "--meeting-iri", iri,
                    "--degraded-reason", "trusted parser capability receipt",
                    "--validator-receipt", receipt)

    assert code == 0 and out["status"] == "readback_verified"
    assert out["provenance"]["mode"] == "validator_receipt"
    assert run(capsys, "close", "--doc", doc, "--lease", lease)[0] == 0


def test_runnerless_forged_validator_receipt_is_manual_required(capsys, doc, cfg):
    """P1: unsigned parser claims are local JSON, not validation proof."""
    lease = _approve_ontology_only(capsys, doc, cfg)
    iri = "urn:meeting:260727"
    ttl_text = f"<{iri}> <urn:predicate:decision> \"approved\" .\n"
    ttl = doc.parent / "meeting.ttl"
    ttl.write_text(ttl_text, encoding="utf-8")
    forged = authenticated_ontology_validator_receipt(ttl_text, iri)
    forged["validator"]["signature"] = "forged"
    receipt = doc.parent / "forged-validator-receipt.json"
    receipt.write_text(json.dumps(forged), encoding="utf-8")

    code, out = run(capsys, "ontology", "--doc", doc, "--config", cfg, "--lease", lease,
                    "--ttl-file", ttl, "--meeting-iri", iri,
                    "--degraded-reason", "untrusted parser claim",
                    "--validator-receipt", receipt)

    assert code == 0 and out["status"] == "manual_required"
    assert manifest_of(doc)["artifacts"]["ontology"]["status"] == "manual_required"
    assert run(capsys, "close", "--doc", doc, "--lease", lease)[0] == 7


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


def test_close_preserves_mirrored_external_artifact_ids(capsys, doc, cfg):
    """Closing updates state only; it must retain IDs required for later audit/recovery."""
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease)
    code, _ = run(capsys, "close", "--doc", doc, "--lease", lease)
    assert code == 0
    mirrored = doc.read_text(encoding="utf-8")
    assert "mm_state: complete" in mirrored
    assert "mm_artifacts:" in mirrored
    assert "canvas: id-canvas" in mirrored
    assert "vault: id-vault" in mirrored
    assert "gmail: id-gmail" in mirrored


def test_close_rejects_source_edits_after_artifact_verification(capsys, doc, cfg):
    """P0: close must not convert artifacts derived from stale source into complete."""
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease)
    doc.write_text(doc.read_text(encoding="utf-8").replace("이슈 1", "이슈 2"), encoding="utf-8")
    code, _ = run(capsys, "close", "--doc", doc, "--lease", lease)
    assert code == 3
    assert manifest_of(doc)["status"] == "superseded"


def test_manual_done_unblocks_close(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease)
    run(capsys, "manual", "--doc", doc, "--lease", lease, "--add", "구본 삭제")
    run(capsys, "manual", "--doc", doc, "--lease", lease, "--done", "m1")
    code, _ = run(capsys, "close", "--doc", doc, "--lease", lease)
    assert code == 0


def test_abort_mirrors_terminal_state(capsys, doc, cfg):
    """An aborted run must not leave the human-readable mirror at approved."""
    lease = approve(capsys, doc, cfg)
    code, _ = run(capsys, "abort", "--doc", doc, "--lease", lease, "--reason", "operator cancelled")
    assert code == 0
    assert manifest_of(doc)["status"] == "aborted"
    assert "mm_state: aborted" in doc.read_text(encoding="utf-8")


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
    assert out["orphan_runs"] == []


def test_approve_leaves_a_frontmatterless_doc_byte_identical(capsys, plain_doc, cfg):
    """No frontmatter -> no mirror. The MD is pasted into a team chat as-is, so
    it must never gain internal state (mm_doc_id/mm_run)."""
    before = plain_doc.read_bytes()
    approve(capsys, plain_doc, cfg)
    assert plain_doc.read_bytes() == before


def test_status_surfaces_an_orphan_run_after_a_rename(capsys, plain_doc, cfg):
    """Without a mirror, doc_id lookup falls back to the path — a rename would
    otherwise report plain 'unmanaged' and hide the run sitting in .mm/."""
    approve(capsys, plain_doc, cfg)
    renamed = plain_doc.parent / "260727_데일리이슈_최종.md"
    plain_doc.rename(renamed)

    code, out = run(capsys, "status", "--doc", renamed)
    assert code == 0 and out["state"] == "unmanaged"
    assert len(out["orphan_runs"]) == 1
    assert out["orphan_runs"][0]["doc_path"].endswith(plain_doc.name)
    assert out["orphan_runs"][0]["current_run"].startswith("r-")


def test_fail_logs_without_a_lease(capsys, doc, cfg):
    approve(capsys, doc, cfg)
    code, out = run(capsys, "fail", "--doc", doc, "--artifact", "canvas",
                    "--class", "transient", "--key", "canvas.rate_limit",
                    "--detail", "429")
    assert code == 0 and out["state_changed"] is False
    assert manifest_of(doc)["artifacts"]["canvas"]["status"] == "pending"
    assert S.read_events(state_dir(doc) / "runs.jsonl")[-1]["event"] == "tool_error"


def test_unsubstantiated_fail_on_complete_run_logs_only_and_does_not_reopen(capsys, doc, cfg):
    """P1: generic failure reports are observations, not revoke authority."""
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease)
    assert run(capsys, "close", "--doc", doc, "--lease", lease)[0] == 0

    code, out = run(capsys, "fail", "--doc", doc, "--artifact", "vault",
                    "--class", "contract", "--key", "vault.unverified_claim",
                    "--impact", "manual_recovery", "--detail", "no attached audit evidence")

    assert code == 0 and out["state_changed"] is False
    assert manifest_of(doc)["status"] == "complete"
    assert manifest_of(doc)["artifacts"]["vault"]["status"] == "readback_verified"
    assert S.read_events(state_dir(doc) / "runs.jsonl")[-1]["event"] == "tool_error"


def test_evidenced_revoke_is_the_only_path_that_invalidates_a_verified_artifact(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    _verify(capsys, doc, lease)
    evidence = audit_evidence_file(doc, "canvas", "remote read-back disproved the artifact")

    code, out = run(capsys, "revoke", "--doc", doc, "--config", cfg, "--lease", lease,
                    "--artifact", "canvas", "--evidence-file", evidence,
                    "--key", "canvas.audit_invalidated")

    assert code == 0 and out["revoked"] is True and out["evidence_sha256"]
    art = manifest_of(doc)["artifacts"]["canvas"]
    assert art["status"] == "failed" and art["audit_evidence"]["sha256"] == out["evidence_sha256"]


def test_audit_failure_revokes_verified_artifact_and_recovery_is_readback_only(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    _verify(capsys, doc, lease)

    evidence = audit_evidence_file(doc, "canvas", "read-back was self-derived")
    code, out = run(capsys, "revoke", "--doc", doc, "--config", cfg, "--lease", lease,
                    "--artifact", "canvas", "--evidence-file", evidence,
                    "--key", "canvas.audit_invalidated")
    assert code == 0 and out["revoked"] is True
    assert manifest_of(doc)["artifacts"]["canvas"]["status"] == "failed"

    code, out = run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    assert code == 0
    assert out["action"] == "readback" and out["gate_token"] is None

    code, _ = _verify(capsys, doc, lease)
    assert code == 0
    art = manifest_of(doc)["artifacts"]["canvas"]
    assert art["status"] == "readback_verified" and art["attempts"] == 1


def test_post_close_audit_failure_reopens_with_a_recovery_lease(capsys, doc, cfg):
    """M4: evidenced post-close audit reopens, leases, re-reads, and re-closes."""
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease)
    close_code, _ = run(capsys, "close", "--doc", doc, "--lease", lease)
    assert close_code == 0

    evidence = audit_evidence_file(doc, "vault", "post-close audit")
    revoke_code, revoke_out = run(
        capsys, "revoke", "--doc", doc, "--config", cfg, "--artifact", "vault",
        "--evidence-file", evidence, "--key", "vault.audit_invalidated",
    )
    assert revoke_code == 0
    recovery_lease = revoke_out["recovery_lease"]
    manifest = manifest_of(doc)
    assert manifest["status"] == "reopened"
    assert manifest["artifacts"]["vault"]["status"] == "failed"
    assert "mm_state: reopened" in doc.read_text(encoding="utf-8")

    gate_code, gate_out = run(
        capsys, "gate", "--doc", doc, "--lease", recovery_lease, "--artifact", "vault",
    )
    assert gate_code == 0 and gate_out["action"] == "readback"
    verify_code, _ = _verify(capsys, doc, recovery_lease, artifact="vault")
    assert verify_code == 0
    close_code, _ = run(capsys, "close", "--doc", doc, "--lease", recovery_lease)
    assert close_code == 0
    assert manifest_of(doc)["status"] == "complete"


def test_record_rejects_an_existing_external_id_even_if_called_after_readback_gate(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")

    code, _ = _record(capsys, doc, cfg, lease, ext_id="F10")
    assert code == 6
    assert manifest_of(doc)["artifacts"]["canvas"]["external_id"] == "F09"


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


# ---------------------------------------------------------------------------
# verify --readback-unavailable — a named gap instead of a manufactured green
# ---------------------------------------------------------------------------
#
# Some channels hand their response back through a tool result that never
# reaches disk (Slack canvas over MCP). RUNTIME-PROTOCOL rule 2 says: say so,
# do not rebuild the read-back from the body you sent. Twice now the prose lost
# — gmail 2026-07-29, canvas 2026-08-07 — so the escape hatch is a command.

def test_readback_unavailable_does_not_reach_verified(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    code, out = run(capsys, "verify", "--doc", doc, "--lease", lease,
                    "--artifact", "canvas",
                    "--readback-unavailable", "MCP returns markdown in the tool result only")
    assert code == 0, out
    art = manifest_of(doc)["artifacts"]["canvas"]
    assert art["status"] == "manual_required"
    assert art.get("readback_sha256") is None


def test_readback_unavailable_blocks_close_until_a_human_confirms(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    _full_publish(capsys, doc, cfg, lease, artifacts=("vault", "gmail"))
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    run(capsys, "verify", "--doc", doc, "--lease", lease, "--artifact", "canvas",
        "--readback-unavailable", "no mechanical read-back")
    code, out = run(capsys, "close", "--doc", doc, "--lease", lease)
    assert code == 7
    assert any("canvas" in b for b in out["blockers"])


def test_readback_unavailable_records_the_reason_for_audit(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    run(capsys, "verify", "--doc", doc, "--lease", lease, "--artifact", "canvas",
        "--readback-unavailable", "MCP tool result only")
    events = S.read_events(state_dir(doc) / "runs.jsonl")
    gap = [e for e in events if e["event"] == "readback_unavailable"]
    assert len(gap) == 1
    assert "MCP tool result only" in gap[0]["detail"]
    assert gap[0]["root_cause_key"] == "canvas.readback_unavailable"


def test_readback_unavailable_needs_a_reason(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    code, _ = run(capsys, "verify", "--doc", doc, "--lease", lease,
                  "--artifact", "canvas", "--readback-unavailable", "   ")
    assert code == 2


def test_readback_file_and_readback_unavailable_are_mutually_exclusive(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    back = doc.parent / "rb.md"
    back.write_bytes(DOC.encode("utf-8"))
    code, _ = run(capsys, "verify", "--doc", doc, "--lease", lease, "--artifact", "canvas",
                  "--readback-file", back, "--readback-unavailable", "reason")
    assert code == 2


def test_verify_with_neither_source_exits_2(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    code, _ = run(capsys, "verify", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    assert code == 2


def test_a_real_readback_after_a_named_gap_still_verifies(capsys, doc, cfg):
    """The gap is a hold, not a dead end — a later genuine read-back clears it."""
    lease = approve(capsys, doc, cfg)
    run(capsys, "gate", "--doc", doc, "--lease", lease, "--artifact", "canvas")
    _record(capsys, doc, cfg, lease)
    run(capsys, "verify", "--doc", doc, "--lease", lease, "--artifact", "canvas",
        "--readback-unavailable", "no mechanical read-back")
    code, _ = _verify(capsys, doc, lease)
    assert code == 0
    assert manifest_of(doc)["artifacts"]["canvas"]["status"] == "readback_verified"


# =========================================================================
# Lease refresh — a live lease can be extended without superseding the run
# =========================================================================

def _index_of(doc):
    return json.loads((state_dir(doc) / "index.json").read_text(encoding="utf-8"))


def test_refresh_extends_the_lease_without_minting_a_new_run(capsys, doc, cfg):
    lease = approve(capsys, doc, cfg)
    before = _index_of(doc)
    doc_id = next(iter(before["docs"]))
    run_before = before["docs"][doc_id]["current_run"]

    code, out = run(capsys, "refresh", "--doc", str(doc), "--config", str(cfg),
                    "--lease", lease, "--ttl-min", "90")

    assert code == 0
    after = _index_of(doc)
    lock = after["docs"][doc_id]["lock"]
    assert after["docs"][doc_id]["current_run"] == run_before, "refresh must not supersede the run"
    assert lock["lease"] == lease, "refresh must keep the same bearer token"
    remaining = datetime.fromisoformat(lock["expires_at"]) - S.utcnow()
    assert remaining > timedelta(minutes=60), "ttl was not extended"
    assert out["lease"] == lease


def test_refresh_with_a_foreign_lease_is_rejected(capsys, doc, cfg):
    approve(capsys, doc, cfg)

    code, _ = run(capsys, "refresh", "--doc", str(doc), "--config", str(cfg),
                  "--lease", "0" * 32, "--ttl-min", "90")

    assert code == 5, "a non-holder must not be able to extend someone else's lease"
