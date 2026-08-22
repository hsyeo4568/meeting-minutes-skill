#!/usr/bin/env python3
"""mm_run — publish protocol runner for meeting-minutes.

Turns the MD-first approval rules from prose into exit codes. The agent may only
publish a body it received from `gate`, and only `verify` (read-back) can call an
artifact done.

    approve  snapshot the approved work MD, take the lease
    gate     re-hash before EVERY artifact -> create | readback (exit 3 = stop)
    record   re-hash again, store what was actually sent
    verify   compare the read-back against what was sent (exit 4 = not synced)
    manual   blocking human checklist (orphan cleanup after a supersede)
    close    complete only when everything is verified (exit 7 = not yet)
    fail / status / promote-check / gc

Exit codes: 0 ok · 2 usage/config · 3 source hash mismatch · 4 read-back
mismatch · 5 lock held · 6 illegal transition · 7 completeness failed.
Design contract: 2026-07-27-mm-runtime-protocol-design.md
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import pathlib
import secrets
import shutil
import socket
import stat
import sys
from contextlib import contextmanager

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mm_readback  # noqa: E402
import mm_schema  # noqa: E402
import mm_state as S  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    yaml = None

DEFAULT_STATE_DIR = ".mm"
DEFAULT_TTL_MIN = 30
DEFAULT_RETENTION_DAYS = 90
TERMINAL_RUN = {"complete", "aborted", "superseded"}
# Channels that cannot be edited after publishing leave orphans -> manual cleanup.
DEFAULT_EDITABLE = {"vault": True, "share_md": True, "gmail": True, "canvas": False,
                    "ontology": True}
EXTERNAL_RECEIPT_REQUIRED = frozenset({"canvas", "gmail"})
DIFF_MAX_LINES = 200


# ---------------------------------------------------------------------------
# workspace plumbing
# ---------------------------------------------------------------------------

class Workspace:
    """Everything addressable from a work MD path."""

    def __init__(self, doc: pathlib.Path, state_dir_name: str = DEFAULT_STATE_DIR):
        self.doc = pathlib.Path(doc).resolve()
        self.root = self.doc.parent / state_dir_name
        self.index_path = self.root / "index.json"
        self.jsonl = self.root / "runs.jsonl"

    def run_dir(self, run_id: str) -> pathlib.Path:
        return self.root / "runs" / run_id

    def text(self) -> str:
        return self.doc.read_text(encoding="utf-8")

    def index(self) -> dict:
        return S.read_index(self.index_path)

    def doc_id(self) -> str | None:
        """Prefer the frontmatter mirror (survives renames); fall back to path."""
        for line in self.text().split("\n"):
            if line.startswith("mm_doc_id:"):
                return line.split(":", 1)[1].strip()
        for doc_id, entry in self.index().get("docs", {}).items():
            if entry.get("doc_path") == str(self.doc):
                return doc_id
        return None

    def manifest_path(self, run_id: str) -> pathlib.Path:
        return self.run_dir(run_id) / "manifest.json"

    def load_run(self) -> tuple[str, str, dict]:
        doc_id = self.doc_id()
        entry = (self.index().get("docs") or {}).get(doc_id or "")
        if not entry or not entry.get("current_run"):
            raise S.ConfigError(f"{self.doc.name}: unmanaged — run `approve` first")
        run_id = entry["current_run"]
        return doc_id, run_id, json.loads(
            self.manifest_path(run_id).read_text(encoding="utf-8"))

    def save_manifest(self, manifest: dict) -> None:
        S._atomic_write(
            self.manifest_path(manifest["run_id"]),
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )

    def log(self, **record) -> None:
        S.log_event(self.jsonl, record)


@contextmanager
def approval_lock(ws: Workspace):
    """Serialize the approve transaction before it creates any run payload.

    ``index.json`` alone is not a transaction boundary: another process can
    create a snapshot and manifest between its version read and its CAS write.
    This per-document O_EXCL lock covers all pre-index artifacts and is removed
    in ``finally`` on every normal error path.
    """
    key = hashlib.sha256(str(ws.doc).encode("utf-8")).hexdigest()[:24]
    lock_path = ws.root / "locks" / f"approve-{key}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise S.LockHeld(
            f"{ws.doc.name}: an approve transaction is already in progress") from exc
    try:
        os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def load_config(path: str | None) -> dict:
    if not path:
        return {}
    if yaml is None:
        raise S.ConfigError("PyYAML not installed (pip install pyyaml)")
    try:
        config = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise S.ConfigError(f"cannot load config: {exc}") from exc
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise S.ConfigError("config root must be a mapping")
    return config


def editable_map(cfg: dict) -> dict[str, bool]:
    out = dict(DEFAULT_EDITABLE)
    for name, spec in (cfg.get("channels") or {}).items():
        if isinstance(spec, dict) and "editable" in spec:
            out[name] = bool(spec["editable"])
    return out


def runtime_opt(cfg: dict, key: str, fallback):
    return (cfg.get("runtime") or {}).get(key, fallback)


def default_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}"


def emit(payload: dict, human: str) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(human, file=sys.stderr)


# ---------------------------------------------------------------------------
# frontmatter mirror (human-readable; manifest stays authoritative)
# ---------------------------------------------------------------------------

def write_mirror(ws: Workspace, doc_id: str, run_id: str, state: str,
                 artifacts: dict | None = None) -> None:
    """Refresh the mm_* pointer block. Excluded from source_hash by design (§3)."""
    text = ws.text()
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return  # no frontmatter -> mirror skipped; index keys off the path instead
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return
    body = S.strip_mm_keys(text).split("\n")
    end = next((i for i in range(1, len(body)) if body[i].strip() == "---"), end)
    mirror = [f"mm_doc_id: {doc_id}", f"mm_run: {run_id}", f"mm_state: {state}"]
    external_ids = {
        name: art.get("external_id") for name, art in (artifacts or {}).items()
        if art.get("external_id")
    }
    if external_ids:
        mirror.append("mm_artifacts:")
        mirror.extend(f"  {name}: {value}" for name, value in sorted(external_ids.items()))
    ws.doc.write_text(
        "\n".join(body[:end] + mirror + body[end:]), encoding="utf-8", newline="\n")


def freeze(path: pathlib.Path) -> None:
    """Best-effort read-only bit on the snapshot — intent marker, not security."""
    try:
        path.chmod(stat.S_IREAD)
    except OSError:
        pass


def thaw(path: pathlib.Path) -> None:
    try:
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# shared guards
# ---------------------------------------------------------------------------

def orphan_runs(ws: Workspace) -> list[dict]:
    """Registered docs that no longer exist on disk — the rename signature.

    A work MD without frontmatter gets no mm_* mirror (it is pasted into a team
    chat as-is), so doc_id lookup falls back to the path. Renaming the file then
    reads as a plain "unmanaged" doc while its run sits in the state dir.
    """
    found = []
    for doc_id, entry in (ws.index().get("docs") or {}).items():
        path = entry.get("doc_path")
        if path and not pathlib.Path(path).exists():
            found.append({"doc_id": doc_id, "doc_path": path,
                          "current_run": entry.get("current_run")})
    return found


def require_lease(ws: Workspace, doc_id: str, lease: str) -> None:
    S.check_lease(ws.index(), doc_id, lease, S.utcnow())


def require_planned(manifest: dict, artifact: str) -> dict:
    if artifact not in manifest["artifacts"]:
        raise S.ConfigError(
            f"{artifact!r} is not in this run's frozen plan {manifest['plan']}")
    return manifest["artifacts"][artifact]


def refuse_canonical_store(ws: Workspace, cfg: dict) -> None:
    """I2 as a guard: run state may never be created inside the canonical store.

    The state dir holds ``source.md`` and ``rendered/*.md``. Inside a vault whose
    search index globs ``**/*.md`` every snapshot would be indexed as one more
    meeting note — exactly the pollution the MD-first gate exists to prevent.
    """
    vault = (cfg.get("paths") or {}).get("vault")
    if not vault:
        return
    root = pathlib.Path(str(vault)).expanduser().resolve()
    if ws.doc == root or root in ws.doc.parents:
        raise S.ConfigError(
            f"{ws.doc.name} lives inside the canonical store ({root}) — approve the "
            "work-folder draft instead; the vault copy is a derivative, not the source")


def enforce_hash(ws: Workspace, manifest: dict, cfg: dict, event: str) -> None:
    """The gate itself: current work MD must still be the approved one.

    On mismatch the run is superseded and every derivative marked stale — an
    edit after approval must never be silently absorbed into the remaining
    artifacts, and already-published orphans become blocking manual work.
    """
    current = S.source_hash(ws.text())
    if current == manifest["source_sha256"]:
        return
    snapshot = (ws.run_dir(manifest["run_id"]) / "source.md")
    old = snapshot.read_text(encoding="utf-8").splitlines() if snapshot.exists() else []
    diff = list(difflib.unified_diff(
        old, ws.text().splitlines(), "approved", "current", lineterm=""))[:DIFF_MAX_LINES]
    if manifest["status"] not in TERMINAL_RUN:
        ws.save_manifest(S.supersede(manifest, S.utcnow(), editable_map(cfg)))
    ws.log(doc_id=manifest["doc_id"], run_id=manifest["run_id"], event=event,
           failure_class="user", root_cause_key="source.edited_after_approval",
           impact="none", detail=f"{manifest['source_sha256'][:8]} -> {current[:8]}")
    emit({"error": "source_hash_mismatch", "approved": manifest["source_sha256"],
          "current": current, "diff": diff},
         "BLOCKING: work MD changed after approval — show the diff, re-approve, "
         "then re-derive every artifact already built from the stale content.")
    raise S.HashMismatch("source changed after approval")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_approve(a) -> int:
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    refuse_canonical_store(ws, cfg)
    schema_errors = mm_schema.validate_text(ws.text())
    if schema_errors:
        raise S.ConfigError("schema-v2 invalid: " + "; ".join(schema_errors))
    with approval_lock(ws):
        return _cmd_approve_locked(a, cfg, ws)


def _cmd_approve_locked(a, cfg: dict, ws: Workspace) -> int:
    source = ws.text()
    schema_errors = mm_schema.validate_text(source)
    if schema_errors:
        raise S.ConfigError("schema-v2 invalid: " + "; ".join(schema_errors))
    now = S.utcnow()
    plan = S.plan_artifacts(cfg, a.category, include_optional=a.include_optional)

    index = ws.index()
    doc_id = ws.doc_id() or f"d-{now:%Y%m%d}-{secrets.token_hex(3)}"
    owner = a.owner
    if not owner:
        lock = ((index.get("docs") or {}).get(doc_id) or {}).get("lock") or {}
        owner = lock["owner"] if a.lease and lock.get("lease") == a.lease else default_owner()

    index, lease = S.acquire_lease(
        index, doc_id, owner, runtime_opt(cfg, "lease_ttl_min", DEFAULT_TTL_MIN), now)

    prior = ((ws.index().get("docs") or {}).get(doc_id) or {}).get("current_run")
    run_id = f"r-{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(2)}"
    manifest = S.new_manifest(
        doc_id=doc_id, run_id=run_id, doc_path=str(ws.doc), category=a.category,
        source_sha256=S.source_hash(source), plan=plan, now=now,
        approval_mode="preapproved" if a.preapproved else "explicit",
        readback_modes={art: mm_readback.mode_for(cfg, art) for art in plan})

    if prior and ws.manifest_path(prior).exists():
        old = json.loads(ws.manifest_path(prior).read_text(encoding="utf-8"))
        if old["status"] not in TERMINAL_RUN:
            old = S.supersede(old, now, editable_map(cfg))
            manifest["manual_required"] = old["manual_required"]
        old["superseded_by"] = run_id
        manifest["supersedes"] = prior
        ws.save_manifest(old)

    snapshot = ws.run_dir(run_id) / "source.md"
    S._atomic_write(snapshot, source)
    freeze(snapshot)
    ws.save_manifest(manifest)

    docs = json.loads(json.dumps(index["docs"]))
    docs[doc_id].update(doc_path=str(ws.doc), current_run=run_id)
    S.write_index_cas(ws.index_path, dict(index, docs=docs), index["version"])

    write_mirror(ws, doc_id, run_id, "approved")
    ws.log(doc_id=doc_id, run_id=run_id, event="approve", impact="none",
           detail=f"plan={plan} sha={manifest['source_sha256'][:8]}")
    emit({"lease": lease, "doc_id": doc_id, "run_id": run_id, "plan": plan,
          "source_sha256": manifest["source_sha256"],
          "snapshot_path": str(snapshot), "supersedes": manifest["supersedes"]},
         f"approved {ws.doc.name} -> {run_id}; derive every artifact from snapshot_path only")
    return 0


def cmd_gate(a) -> int:
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    doc_id, run_id, manifest = ws.load_run()
    require_lease(ws, doc_id, a.lease)
    art = require_planned(manifest, a.artifact)
    enforce_hash(ws, manifest, cfg, "gate_blocked")

    if art.get("gate_token"):
        raise S.IllegalTransition(
            f"{a.artifact}: open gate already exists — record or abort the first create attempt")

    if manifest["status"] in {"approved", "reopened"}:
        S.assert_run_transition(manifest["status"], "publishing")
        manifest["status"] = "publishing"

    # An external id is an idempotency boundary: even a previously verified
    # artifact may be invalidated by a later audit, but it must be read back
    # rather than silently recreated.
    readback = bool(art["external_id"])
    token = secrets.token_hex(4) if not readback else None
    art["gate_token"] = token
    art["updated_at"] = S.iso(S.utcnow())
    ws.save_manifest(manifest)
    write_mirror(ws, doc_id, run_id, manifest["status"], manifest["artifacts"])

    snapshot = ws.run_dir(run_id) / "source.md"
    ws.log(doc_id=doc_id, run_id=run_id, event="gate_pass", artifact=a.artifact,
           impact="none", detail="readback" if readback else "create")
    emit({"action": "readback" if readback else "create",
          "artifact": a.artifact, "snapshot_path": str(snapshot),
          "idem_key": art["idem_key"], "footer": f"> mm:{art['idem_key']}",
          "external_id": art["external_id"],
          "artifact_status": art["status"], "gate_token": token},
         ("read back the existing artifact instead of creating a second one"
          if readback else f"cleared to create {a.artifact} from {snapshot}"))
    return 0


def cmd_record(a) -> int:
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    doc_id, run_id, manifest = ws.load_run()
    require_lease(ws, doc_id, a.lease)
    art = require_planned(manifest, a.artifact)
    if not art.get("gate_token"):
        raise S.IllegalTransition(
            f"{a.artifact}: no open gate — run `gate` immediately before creating")
    if art.get("external_id"):
        raise S.IllegalTransition(
            f"{a.artifact}: existing id {art['external_id']} — read it back; do not recreate")
    enforce_hash(ws, manifest, cfg, "record_blocked")
    S.assert_artifact_transition(art["status"], "created")

    body = pathlib.Path(a.body_file).read_text(encoding="utf-8")
    expected_footer = f"> mm:{art['idem_key']}"
    footer_count = sum(line == expected_footer for line in body.splitlines())
    if footer_count != 1:
        raise S.ConfigError(
            f"{a.artifact}: body must contain exactly one idempotency footer {expected_footer!r}")
    rendered = ws.run_dir(run_id) / "rendered" / f"{a.artifact}.md"
    S._atomic_write(rendered, body)
    art.update(status="created", external_id=a.id, url=a.url,
               rendered_sha256=S.body_hash(body), attempts=art["attempts"] + 1,
               updated_at=S.iso(S.utcnow()), last_error=None, gate_token=None)
    ws.save_manifest(manifest)
    write_mirror(ws, doc_id, run_id, manifest["status"], manifest["artifacts"])
    ws.log(doc_id=doc_id, run_id=run_id, event="artifact_created", artifact=a.artifact,
           impact="none", detail=f"id={a.id}")
    emit({"artifact": a.artifact, "status": "created", "external_id": a.id,
          "rendered_sha256": art["rendered_sha256"]},
         f"{a.artifact} created ({a.id}) — NOT done until `verify` reads it back")
    return 0


def _record_readback_gap(ws, manifest, art, artifact_name, reason, doc_id, run_id) -> int:
    """Hold an artifact open when a trustworthy read-back is unavailable.

    Some responses only exist inside a tool result (Slack canvas over MCP).
    Rebuilding the read-back from the sent body would compare the text with a
    copy of itself and pass every time, so the alternative to a real read-back
    is a *named gap*: the artifact stops at ``manual_required`` and a blocking
    manual item keeps ``close`` shut until a human confirms the artifact by eye.
    """
    reason = reason.strip()
    if not reason:
        raise S.ConfigError("--readback-unavailable needs a reason")

    S.assert_artifact_transition(art["status"], "manual_required")
    art.update(status="manual_required", updated_at=S.iso(S.utcnow()))
    items = manifest["manual_required"]
    item = {"id": f"m{len(items) + 1}",
            "text": f"{artifact_name}: 눈으로 대조 후 확인 — 기계 read-back 불가 ({reason})",
            "blocking": True, "done": False, "done_at": None}
    items.append(item)
    ws.save_manifest(manifest)
    ws.log(doc_id=doc_id, run_id=run_id, event="readback_unavailable",
           artifact=artifact_name, failure_class="external",
           root_cause_key=f"{artifact_name}.readback_unavailable",
           impact="manual_recovery", detail=reason)
    emit({"artifact": artifact_name, "status": "manual_required",
          "manual_item": item["id"], "reason": reason},
         f"{artifact_name} NOT verified — read-back unavailable, held as {item['id']}")
    return 0


def cmd_verify(a) -> int:
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    doc_id, run_id, manifest = ws.load_run()
    require_lease(ws, doc_id, a.lease)
    art = require_planned(manifest, a.artifact)
    enforce_hash(ws, manifest, cfg, "verify_blocked")

    if a.readback_unavailable is not None:
        return _record_readback_gap(
            ws, manifest, art, a.artifact, a.readback_unavailable, doc_id, run_id)

    if a.connector_receipt is not None:
        try:
            receipt_path = pathlib.Path(a.connector_receipt)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (not isinstance(receipt, dict)
                    or receipt.get("schema") != "mm-connector-receipt/1"
                    or receipt.get("artifact") != a.artifact
                    or receipt.get("external_id") != art.get("external_id")
                    or not isinstance(receipt.get("fetched_at"), str)
                    or not isinstance(receipt.get("body"), str)):
                raise ValueError("receipt schema, artifact, external_id, fetched_at, or body is invalid")
            back_text = receipt["body"]
            saved_receipt = ws.run_dir(run_id) / "readback" / f"{a.artifact}.receipt.json"
            S._atomic_write(saved_receipt, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            ws.log(doc_id=doc_id, run_id=run_id, event="readback_input_error",
                   artifact=a.artifact, failure_class="contract",
                   root_cause_key=f"{a.artifact}.connector_receipt_error",
                   impact="manual_recovery", detail=detail)
            emit({"error": "connector_receipt_error", "artifact": a.artifact,
                  "detail": detail},
                 f"{a.artifact} connector receipt is untrustworthy — artifact remains unverified")
            raise S.ReadbackInputError(a.artifact)
    elif a.artifact in EXTERNAL_RECEIPT_REQUIRED:
        return _record_readback_gap(
            ws, manifest, art, a.artifact,
            "untrusted local read-back file; connector receipt required or confirm manually",
            doc_id, run_id)
    else:
        try:
            back_text = pathlib.Path(a.readback_file).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            ws.log(doc_id=doc_id, run_id=run_id, event="readback_input_error",
                   artifact=a.artifact, failure_class="contract",
                   root_cause_key=f"{a.artifact}.readback_input_error",
                   impact="manual_recovery", detail=detail)
            emit({"error": "readback_input_error", "artifact": a.artifact,
                  "detail": detail},
                 f"{a.artifact} read-back could not be opened — artifact remains unverified")
            raise S.ReadbackInputError(a.artifact)
    back = S.body_hash(back_text)
    # Frozen at approve time; --config is optional on this command, and falling
    # back to a config-less default would silently downgrade a rendering channel.
    mode = art.get("readback_mode")
    if mode is None:
        try:
            mode = mm_readback.mode_for(cfg, a.artifact)
        except ValueError as exc:
            raise S.ConfigError(str(exc)) from exc

    if mode == mm_readback.SEMANTIC:
        sent_path = ws.run_dir(run_id) / "rendered" / f"{a.artifact}.md"
        if not sent_path.exists():
            raise S.ConfigError(f"{a.artifact}: nothing recorded as sent — run `record` first")
        missing = mm_readback.missing_lines(
            sent_path.read_text(encoding="utf-8"), back_text)
    else:
        missing = [] if back == art.get("rendered_sha256") else ["<byte mismatch>"]

    if missing:
        ws.log(doc_id=doc_id, run_id=run_id, event="readback_mismatch",
               artifact=a.artifact, failure_class="external",
               root_cause_key=f"{a.artifact}.readback_mismatch",
               impact="external_share_error",
               detail=f"mode={mode} missing={len(missing)} first={missing[0][:60]}")
        emit({"error": "readback_mismatch", "artifact": a.artifact, "mode": mode,
              "rendered_sha256": art.get("rendered_sha256"), "readback_sha256": back,
              "missing_lines": missing[:20]},
             f"{a.artifact} read-back is missing {len(missing)} sent line(s) — stays unsynced")
        raise S.ReadbackMismatch(a.artifact)

    S.assert_artifact_transition(art["status"], "readback_verified")
    art.update(status="readback_verified", readback_sha256=back,
               readback_mode=mode, updated_at=S.iso(S.utcnow()))
    ws.save_manifest(manifest)
    ws.log(doc_id=doc_id, run_id=run_id, event="artifact_verified",
           artifact=a.artifact, impact="none", detail=f"id={art['external_id']}")
    emit({"artifact": a.artifact, "status": "readback_verified"},
         f"{a.artifact} verified against the sent body")
    return 0


def cmd_manual(a) -> int:
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    doc_id, run_id, manifest = ws.load_run()
    require_lease(ws, doc_id, a.lease)
    items = manifest["manual_required"]

    if a.add:
        item = {"id": f"m{len(items) + 1}", "text": a.add,
                "blocking": not a.non_blocking, "done": False, "done_at": None}
        items.append(item)
        ws.log(doc_id=doc_id, run_id=run_id, event="manual_added", impact="none",
               detail=a.add)
    elif a.done or a.waive:
        target = a.done or a.waive
        item = next((i for i in items if i["id"] == target), None)
        if item is None:
            raise S.ConfigError(f"no manual item {target!r}")
        item.update(done=True, done_at=S.iso(S.utcnow()))
        if a.waive:
            item["waived_reason"] = a.reason or ""
            ws.log(doc_id=doc_id, run_id=run_id, event="manual_waived",
                   failure_class="user", root_cause_key="manual.waived",
                   impact="manual_recovery", detail=f"{item['text']} :: {a.reason}")
        else:
            ws.log(doc_id=doc_id, run_id=run_id, event="manual_done", impact="none",
                   detail=item["text"])
    else:
        raise S.ConfigError("manual needs --add / --done / --waive")

    ws.save_manifest(manifest)
    emit({"manual_required": items}, f"{len(items)} manual item(s) on {run_id}")
    return 0


def cmd_close(a) -> int:
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    doc_id, run_id, manifest = ws.load_run()
    require_lease(ws, doc_id, a.lease)
    enforce_hash(ws, manifest, cfg, "close_blocked")

    blockers = S.completeness_blockers(manifest)
    if blockers:
        emit({"error": "incomplete", "blockers": blockers},
             f"{run_id} not closable — {len(blockers)} blocker(s)")
        raise S.IncompleteRun(run_id)

    if manifest["status"] == "approved":
        manifest["status"] = "publishing"
    S.assert_run_transition(manifest["status"], "complete")
    manifest.update(status="complete", closed_at=S.iso(S.utcnow()))
    ws.save_manifest(manifest)

    index = ws.index()
    S.write_index_cas(ws.index_path, S.release_lease(index, doc_id), index["version"])
    write_mirror(ws, doc_id, run_id, "complete", manifest["artifacts"])
    ws.log(doc_id=doc_id, run_id=run_id, event="close", impact="none",
           detail=f"artifacts={list(manifest['artifacts'])}")
    emit({"run_id": run_id, "status": "complete"}, f"{run_id} complete; lease released")
    return 0


def cmd_abort(a) -> int:
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    doc_id, run_id, manifest = ws.load_run()
    require_lease(ws, doc_id, a.lease)
    S.assert_run_transition(manifest["status"], "aborted")
    manifest.update(status="aborted", closed_at=S.iso(S.utcnow()))
    ws.save_manifest(manifest)
    index = ws.index()
    S.write_index_cas(ws.index_path, S.release_lease(index, doc_id), index["version"])
    write_mirror(ws, doc_id, run_id, "aborted", manifest["artifacts"])
    ws.log(doc_id=doc_id, run_id=run_id, event="abort", failure_class="user",
           root_cause_key="run.aborted", impact="none", detail=a.reason or "")
    emit({"run_id": run_id, "status": "aborted"}, f"{run_id} aborted")
    return 0


def cmd_fail(a) -> int:
    """Log a failure and revoke a disproven verification without a lease.

    ``stale`` remains terminal, but a later audit must be able to move a
    previously verified artifact back to ``failed`` so ``close`` stays
    fail-closed.  If it invalidates a closed run, acquire a fresh recovery
    lease so the operator can perform a read-back-only repair without creating
    a new approval run.
    """
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    doc_id, run_id, manifest = ws.load_run()
    recovery_lease = None
    if a.artifact and a.artifact in manifest["artifacts"]:
        art = manifest["artifacts"][a.artifact]
        try:
            S.assert_artifact_transition(art["status"], "failed")
            art.update(status="failed", last_error=a.detail,
                       updated_at=S.iso(S.utcnow()))
            if manifest["status"] == "complete":
                S.assert_run_transition("complete", "reopened")
                manifest.update(status="reopened", reopened_at=S.iso(S.utcnow()))
        except S.IllegalTransition:
            pass  # terminal artifact: log the event, leave the state alone
        ws.save_manifest(manifest)
        if manifest["status"] == "reopened":
            index = ws.index()
            recovered_index, recovery_lease = S.acquire_lease(
                index, doc_id, default_owner(),
                runtime_opt(cfg, "lease_ttl_min", DEFAULT_TTL_MIN), S.utcnow(),
            )
            S.write_index_cas(ws.index_path, recovered_index, index["version"])
            write_mirror(ws, doc_id, run_id, "reopened", manifest["artifacts"])
    ws.log(doc_id=doc_id, run_id=run_id, event="tool_error", artifact=a.artifact,
           failure_class=a.failure_class, root_cause_key=a.key, impact=a.impact,
           detail=a.detail)
    payload = {"logged": True, "artifact": a.artifact, "root_cause_key": a.key}
    if recovery_lease:
        payload["recovery_lease"] = recovery_lease
    emit(payload, f"logged {a.key} ({a.failure_class}/{a.impact})")
    return 0


def cmd_status(a) -> int:
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    try:
        doc_id, run_id, manifest = ws.load_run()
    except S.ConfigError:
        orphans = orphan_runs(ws)
        note = "unmanaged doc — `approve` after the user signs off on the MD"
        if orphans:
            note += (f" · 등록된 doc {len(orphans)}건이 디스크에 없음 (rename 의심): "
                     + ", ".join(pathlib.Path(o["doc_path"]).name for o in orphans))
        emit({"state": "unmanaged", "doc": str(ws.doc), "orphan_runs": orphans}, note)
        return 0
    lock = ((ws.index().get("docs") or {}).get(doc_id) or {}).get("lock")
    drifted = S.source_hash(ws.text()) != manifest["source_sha256"]
    emit({"state": "managed", "doc_id": doc_id,
          "run": {"run_id": run_id, "status": manifest["status"],
                  "category": manifest["category"], "plan": manifest["plan"]},
          "artifacts": {k: v["status"] for k, v in manifest["artifacts"].items()},
          "source_drifted": drifted,
          "blockers": S.completeness_blockers(manifest),
          "lock": {"owner": lock["owner"], "expires_at": lock["expires_at"]} if lock else None,
          "manual_required": [i for i in manifest["manual_required"] if not i["done"]]},
         f"{run_id}: {manifest['status']}" + (" (SOURCE DRIFTED)" if drifted else ""))
    return 0


_STUB = """### {key}

- 발생: {runs} run(s), 최종 {ts}
- 승격 사유: {reasons}
- 조치: (계약/코드/config 변경 내용을 여기에 기록)
"""


def cmd_promote_check(a) -> int:
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    events = S.read_events(ws.jsonl)
    verdict = S.promotion_verdict(events)
    keys = {e.get("root_cause_key") for e in events if e.get("root_cause_key")}
    stub = ""
    if verdict["promote"]:
        stub = _STUB.format(
            key=", ".join(sorted(k for k in keys if k)) or "(unclassified)",
            runs=len({e.get("run_id") for e in events}),
            ts=events[-1]["ts"] if events else "-",
            reasons="; ".join(verdict["reasons"]))
    triage = verdict.get("needs_triage") or []
    human = "승격 대상" if verdict["promote"] else "JSONL only — 지식 노트 불필요"
    if triage:
        human += f" · 분류 없는 실패 이벤트 {len(triage)}종 triage 필요: {', '.join(triage)}"
    emit({**verdict, "events": len(events), "stub": stub}, human)
    return 0


def cmd_gc(a) -> int:
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    days = a.days if a.days is not None else runtime_opt(
        cfg, "retention_days", DEFAULT_RETENTION_DAYS)
    cutoff = S.utcnow().timestamp() - days * 86400
    pruned = []
    for run_dir in sorted((ws.root / "runs").glob("r-*")):
        mpath = run_dir / "manifest.json"
        if not mpath.exists():
            continue
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        if manifest["status"] not in TERMINAL_RUN:
            continue
        stamp = manifest.get("closed_at") or manifest.get("superseded_at") \
            or manifest["created_at"]
        if S._parse(stamp).timestamp() > cutoff:
            continue
        if not a.dry_run:
            snapshot = run_dir / "source.md"
            if snapshot.exists():
                thaw(snapshot)
                snapshot.unlink()
            for sub in ("rendered", "readback"):
                shutil.rmtree(run_dir / sub, ignore_errors=True)
        pruned.append(manifest["run_id"])
    if pruned and not a.dry_run:
        ws.log(event="gc", impact="none", detail=f"pruned={pruned}")
    emit({"pruned": pruned, "days": days, "dry_run": bool(a.dry_run)},
         f"gc: {len(pruned)} terminal run payload(s) pruned (manifests + log kept)")
    return 0


# ---------------------------------------------------------------------------
# argument wiring
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mm_run", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, lease=True):
        sp.add_argument("--doc", required=True)
        sp.add_argument("--config")
        if lease:
            sp.add_argument("--lease", required=True)
        return sp

    ap = common(sub.add_parser("approve"), lease=False)
    ap.add_argument("--category", required=True)
    ap.add_argument("--lease")
    ap.add_argument("--owner")
    ap.add_argument("--preapproved", action="store_true")
    ap.add_argument("--include-optional", action="store_true")
    ap.set_defaults(func=cmd_approve)

    g = common(sub.add_parser("gate"))
    g.add_argument("--artifact", required=True)
    g.set_defaults(func=cmd_gate)

    r = common(sub.add_parser("record"))
    r.add_argument("--artifact", required=True)
    r.add_argument("--id", required=True)
    r.add_argument("--body-file", required=True)
    r.add_argument("--url")
    r.set_defaults(func=cmd_record)

    v = common(sub.add_parser("verify"))
    v.add_argument("--artifact", required=True)
    # Exactly one source. Neither is not a shortcut to done, and both together
    # would let a manufactured file ride in beside a declared gap.
    src = v.add_mutually_exclusive_group(required=True)
    src.add_argument("--readback-file")
    src.add_argument("--connector-receipt",
                     help="connector-owned JSON receipt with remote body and external id")
    src.add_argument("--readback-unavailable", metavar="REASON",
                     help="the channel cannot hand its response to disk; hold "
                          "the artifact open instead of faking a read-back")
    v.set_defaults(func=cmd_verify)

    m = common(sub.add_parser("manual"))
    m.add_argument("--add")
    m.add_argument("--done")
    m.add_argument("--waive")
    m.add_argument("--reason")
    m.add_argument("--non-blocking", action="store_true")
    m.set_defaults(func=cmd_manual)

    common(sub.add_parser("close")).set_defaults(func=cmd_close)

    ab = common(sub.add_parser("abort"))
    ab.add_argument("--reason")
    ab.set_defaults(func=cmd_abort)

    f = common(sub.add_parser("fail"), lease=False)
    f.add_argument("--artifact")
    f.add_argument("--class", dest="failure_class", default="transient",
                   choices=["transient", "contract", "external", "user"])
    f.add_argument("--key", required=True)
    f.add_argument("--detail", default="")
    f.add_argument("--impact", default="none",
                   choices=["none", "external_share_error", "data_loss", "manual_recovery"])
    f.set_defaults(func=cmd_fail)

    common(sub.add_parser("status"), lease=False).set_defaults(func=cmd_status)
    common(sub.add_parser("promote-check"), lease=False).set_defaults(func=cmd_promote_check)

    gc = common(sub.add_parser("gc"), lease=False)
    gc.add_argument("--days", type=int)
    gc.add_argument("--dry-run", action="store_true")
    gc.set_defaults(func=cmd_gc)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        # argparse exits the process on a usage error (and on --help). Route it
        # through the same int-returning contract as every other exit code, so
        # a usage error is exit 2 whether it came from argparse or ConfigError.
        return int(exc.code or 0)
    try:
        return args.func(args)
    except S.MmError as exc:
        if not isinstance(exc, (S.HashMismatch, S.ReadbackMismatch, S.IncompleteRun)):
            emit({"error": type(exc).__name__, "detail": str(exc)}, f"ERROR: {exc}")
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
