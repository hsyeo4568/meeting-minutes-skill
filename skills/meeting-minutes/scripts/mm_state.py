#!/usr/bin/env python3
"""Runtime state primitives for the meeting-minutes publish protocol.

Pure-ish core behind ``mm_run.py``: hashing, the artifact/run transition table,
the lock lease with compare-and-swap, manifest construction, the append-only
event log, and the vault-promotion verdict.

Design contract: ``2026-07-27-mm-runtime-protocol-design.md``.
Every mutating helper returns a NEW dict — callers never see in-place edits.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import secrets
from datetime import datetime, timedelta, timezone

SCHEMA_INDEX = "mm-index/1"
SCHEMA_MANIFEST = "mm-manifest/1"

# Frontmatter namespace the runner owns. Excluded from the source hash so the
# runner can refresh its own mirror without invalidating its own approval.
MM_KEY = re.compile(r"^mm_[A-Za-z0-9_]*\s*:")
_FM_FENCE = "---"

# Derivative outputs, in publish order. ``detail_md`` is deliberately absent:
# that IS the work MD (the source), not a derivative of it.
ARTIFACT_KEYS = ("vault", "share_md", "canvas", "gmail")

RUN_TRANSITIONS = {
    "open":       {"approved", "aborted"},
    "approved":   {"publishing", "superseded", "aborted"},
    "publishing": {"complete", "superseded", "aborted"},
    "complete":   set(),
    "superseded": set(),
    "aborted":    set(),
}

ARTIFACT_TRANSITIONS = {
    "pending":           {"created", "failed", "manual_required", "stale"},
    "created":           {"readback_verified", "failed", "manual_required", "stale"},
    # A later audit can invalidate what was previously marked verified.  That
    # must block close, while an actual fresh read-back can restore the state
    # without re-creating the external artifact.
    "readback_verified": {"readback_verified", "failed", "manual_required", "stale"},
    "failed":            {"failed", "created", "readback_verified", "manual_required", "stale"},
    "manual_required":   {"manual_required", "created", "readback_verified", "stale"},
    "stale":             set(),
}

HIGH_IMPACT = {"external_share_error", "data_loss", "manual_recovery"}

# Bookkeeping the runner emits itself — never candidates for failure triage.
PROTOCOL_EVENTS = {
    "approve", "gate_pass", "artifact_created", "artifact_verified",
    "manual_added", "manual_done", "close", "abort", "gc",
}


# ---------------------------------------------------------------------------
# errors — the exit-code surface of the CLI
# ---------------------------------------------------------------------------

class MmError(Exception):
    exit_code = 1


class ConfigError(MmError):
    exit_code = 2


class HashMismatch(MmError):
    exit_code = 3


class ReadbackMismatch(MmError):
    exit_code = 4


class LockHeld(MmError):
    exit_code = 5


class IllegalTransition(MmError):
    exit_code = 6


class IncompleteRun(MmError):
    exit_code = 7


# ---------------------------------------------------------------------------
# hash domain
# ---------------------------------------------------------------------------

def canon(text: str) -> str:
    """Normalise away differences no human made: BOM, line endings, trailing blanks."""
    if text.startswith("﻿"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip() + "\n"


def strip_mm_keys(text: str) -> str:
    """Drop ``mm_*`` keys (and their indented continuations) from the frontmatter block.

    Line-based on purpose: a YAML round-trip would reorder and requote the
    user's own frontmatter, which has corrupted vault notes before.
    """
    lines = text.split("\n")
    start = 1 if lines and lines[0].strip() == _FM_FENCE else None
    if start is None:
        return text
    end = next(
        (i for i in range(start, len(lines)) if lines[i].strip() == _FM_FENCE),
        None,
    )
    if end is None:
        return text

    kept, skipping = [], False
    for line in lines[start:end]:
        if MM_KEY.match(line):
            skipping = True
            continue
        if skipping and (line.startswith((" ", "\t")) or not line.strip()):
            continue
        skipping = False
        kept.append(line)
    return "\n".join(lines[:start] + kept + lines[end:])


def source_hash(text: str) -> str:
    """Approval identity of the work MD: canonical bytes minus the runner's own keys.

    canon() runs FIRST: a BOM or CRLF would otherwise hide the frontmatter fence
    from strip_mm_keys, silently re-including the runner's own mirror keys.
    """
    return hashlib.sha256(canon(strip_mm_keys(canon(text))).encode("utf-8")).hexdigest()


def body_hash(text: str) -> str:
    """Byte-faithful (post-canon) hash — used for rendered vs read-back comparison."""
    return hashlib.sha256(canon(text).encode("utf-8")).hexdigest()


def idem_key(doc_id: str, src_sha: str, artifact: str) -> str:
    raw = f"{doc_id}|{src_sha}|{artifact}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# category plan
# ---------------------------------------------------------------------------

def plan_artifacts(cfg: dict, category: str, include_optional: bool = False) -> list[str]:
    """Derivatives this category must produce, in publish order.

    Single source shared by ``dry_run.py`` and ``mm_run.py approve`` so the
    declared matrix and the runtime plan cannot drift apart.
    """
    categories = cfg.get("categories") or {}
    row = categories.get(category)
    if row is None:
        raise ConfigError(
            f"unknown category {category!r} — config declares {sorted(categories)}"
        )
    plan = []
    for key in ARTIFACT_KEYS:
        value = row.get(key)
        if value is True or (value == "optional" and include_optional):
            plan.append(key)
    return plan


# ---------------------------------------------------------------------------
# transitions
# ---------------------------------------------------------------------------

def assert_run_transition(current: str, target: str) -> None:
    if target not in RUN_TRANSITIONS.get(current, set()):
        raise IllegalTransition(f"run: {current} -> {target} is not allowed")


def assert_artifact_transition(current: str, target: str) -> None:
    if target not in ARTIFACT_TRANSITIONS.get(current, set()):
        raise IllegalTransition(f"artifact: {current} -> {target} is not allowed")


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


# ---------------------------------------------------------------------------
# index + lock lease
# ---------------------------------------------------------------------------

def new_index() -> dict:
    return {"schema": SCHEMA_INDEX, "version": 0, "docs": {}}


def read_index(path: pathlib.Path) -> dict:
    path = pathlib.Path(path)
    if not path.exists():
        return new_index()
    return json.loads(path.read_text(encoding="utf-8"))


def write_index_cas(path: pathlib.Path, index: dict, expected_version: int) -> dict:
    """Atomically publish ``index`` iff the on-disk version still matches.

    A losing writer means another agent moved the state underneath us — that is
    a lock conflict, not a retry-until-you-win situation.
    """
    path = pathlib.Path(path)
    on_disk = read_index(path)
    if on_disk["version"] != expected_version:
        raise LockHeld(
            f"index changed underneath us (disk v{on_disk['version']} != v{expected_version})"
        )
    out = dict(index, version=expected_version + 1)
    _atomic_write(path, json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    return out


def _atomic_write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _lock_live(lock: dict | None, now: datetime) -> bool:
    return bool(lock) and _parse(lock["expires_at"]) > now


def acquire_lease(index: dict, doc_id: str, owner: str, ttl_min: int,
                  now: datetime) -> tuple[dict, str]:
    """Take (or refresh) the publish lease for ``doc_id``. Returns (new_index, lease)."""
    docs = json.loads(json.dumps(index["docs"]))
    entry = docs.setdefault(doc_id, {"doc_path": None, "current_run": None, "lock": None})
    lock = entry.get("lock")

    if _lock_live(lock, now) and lock["owner"] != owner:
        raise LockHeld(
            f"{doc_id} leased by {lock['owner']} until {lock['expires_at']}"
        )

    same_owner = bool(lock) and lock["owner"] == owner and _lock_live(lock, now)
    lease = lock["lease"] if same_owner else secrets.token_hex(16)
    entry["lock"] = {
        "lease": lease,
        "owner": owner,
        "acquired_at": lock["acquired_at"] if same_owner else iso(now),
        "expires_at": iso(now + timedelta(minutes=ttl_min)),
        "version": (lock or {}).get("version", 0) + 1,
    }
    return dict(index, docs=docs), lease


def check_lease(index: dict, doc_id: str, lease: str, now: datetime) -> None:
    lock = (index.get("docs", {}).get(doc_id) or {}).get("lock")
    if not _lock_live(lock, now):
        raise LockHeld(f"{doc_id}: no live lease — re-acquire with `approve` or `adopt`")
    if lock["lease"] != lease:
        raise LockHeld(f"{doc_id} leased by {lock['owner']} until {lock['expires_at']}")


def release_lease(index: dict, doc_id: str) -> dict:
    docs = json.loads(json.dumps(index["docs"]))
    if doc_id in docs:
        docs[doc_id]["lock"] = None
    return dict(index, docs=docs)


def refresh_lease(index: dict, doc_id: str, ttl_min: int, now: datetime) -> dict:
    docs = json.loads(json.dumps(index["docs"]))
    lock = (docs.get(doc_id) or {}).get("lock")
    if lock:
        lock["expires_at"] = iso(now + timedelta(minutes=ttl_min))
    return dict(index, docs=docs)


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------

def new_manifest(doc_id: str, run_id: str, doc_path: str, category: str,
                 source_sha256: str, plan: list[str], now: datetime,
                 approval_mode: str, readback_modes: dict | None = None) -> dict:
    """Freeze the run. Per-artifact read-back mode is frozen with the plan, so a
    later config edit — or a command invoked without --config — cannot silently
    downgrade a rendering channel to byte comparison."""
    modes = readback_modes or {}
    return {
        "schema": SCHEMA_MANIFEST,
        "doc_id": doc_id,
        "run_id": run_id,
        "doc_path": str(doc_path),
        "category": category,
        "created_at": iso(now),
        "approved_at": iso(now),
        "approval_mode": approval_mode,
        "source_sha256": source_sha256,
        "source_snapshot": f"runs/{run_id}/source.md",
        "status": "approved",
        "supersedes": None,
        "superseded_by": None,
        "plan": list(plan),
        "artifacts": {
            key: {
                "status": "pending",
                "idem_key": idem_key(doc_id, source_sha256, key),
                "external_id": None,
                "url": None,
                "rendered_sha256": None,
                "readback_sha256": None,
                "readback_mode": modes.get(key, "exact"),
                "attempts": 0,
                "waived": False,
                "updated_at": iso(now),
                "last_error": None,
            }
            for key in plan
        },
        "manual_required": [],
    }


def supersede(manifest: dict, now: datetime, editable: dict[str, bool]) -> dict:
    """Source moved on: void the run, stale every derivative, mint cleanup duties.

    A published artifact on a channel that cannot be edited (canvas, sent mail)
    leaves an orphan the user must reconcile — that becomes a blocking item, not
    a log line.
    """
    out = json.loads(json.dumps(manifest))
    out["status"] = "superseded"
    out["superseded_at"] = iso(now)
    for name, art in out["artifacts"].items():
        was_published = art["status"] in ("created", "readback_verified")
        if art["status"] != "stale":
            art["status"] = "stale"
            art["updated_at"] = iso(now)
        if was_published and not editable.get(name, False):
            out["manual_required"].append({
                "id": f"m{len(out['manual_required']) + 1}",
                "text": (
                    f"supersede stale {name} {art['external_id']} "
                    "— mark it superseded and point at the new artifact"
                ),
                "blocking": True,
                "done": False,
                "done_at": None,
            })
    return out


def completeness_blockers(manifest: dict) -> list[str]:
    """What still stands between this run and ``complete``."""
    blockers = []
    for name in manifest["plan"]:
        art = manifest["artifacts"].get(name, {})
        if art.get("waived"):
            continue
        if art.get("status") != "readback_verified":
            blockers.append(f"{name}: {art.get('status')} (needs readback_verified)")
    for item in manifest.get("manual_required", []):
        if item["blocking"] and not item["done"]:
            blockers.append(f"manual {item['id']}: {item['text']}")
    return blockers


# ---------------------------------------------------------------------------
# event log
# ---------------------------------------------------------------------------

def log_event(path: pathlib.Path, record: dict, now: datetime | None = None) -> None:
    """Append one JSON object as exactly one line, in one write() call."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault("ts", iso(now or utcnow()))
    line = json.dumps(payload, ensure_ascii=False).replace("\n", "\\n") + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)


def read_events(path: pathlib.Path) -> list[dict]:
    path = pathlib.Path(path)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


# ---------------------------------------------------------------------------
# vault promotion verdict
# ---------------------------------------------------------------------------

def promotion_verdict(events: list[dict]) -> dict:
    """Decide whether failures earned a vault entry. Default answer is no.

    Writing every failure to the vault poisons search with noise and teaches the
    model that one-off exceptions are standard procedure.
    """
    reasons: list[str] = []

    for ev in events:
        if ev.get("impact") in HIGH_IMPACT:
            reasons.append(f"impact={ev['impact']} ({ev.get('root_cause_key')})")

    runs_by_cause: dict[str, set] = {}
    for ev in events:
        key = ev.get("root_cause_key")
        if key:
            runs_by_cause.setdefault(key, set()).add(ev.get("run_id"))
    for key, runs in runs_by_cause.items():
        if len(runs) >= 2:
            reasons.append(f"recurrence={key} across {len(runs)} runs")

    for ev in events:
        if ev.get("failure_class") == "contract":
            reasons.append(f"contract failure={ev.get('root_cause_key')}")
        if ev.get("event") == "manual_waived":
            reasons.append(f"waived manual step={ev.get('detail')}")

    # A failure logged without impact/root_cause_key matches no rule above, so it
    # would score promote=false with nothing saying it was skipped. Surface it as
    # triage instead of promoting it: unclassified noise in the canonical store is
    # the failure mode this whole policy exists to prevent.
    triage = [
        ev.get("event") for ev in events
        if ev.get("event") not in PROTOCOL_EVENTS
        and not ev.get("root_cause_key") and not ev.get("impact")
    ]

    deduped = list(dict.fromkeys(reasons))
    return {
        "promote": bool(deduped),
        "reasons": deduped,
        "needs_triage": list(dict.fromkeys(triage)),
    }
