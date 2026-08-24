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
import hmac
import json
import os
import pathlib
import secrets
import shlex
import shutil
import socket
import stat
import subprocess
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
CONNECTOR_RECEIPT_SCHEMA = "mm-connector-receipt/2"
CONNECTOR_RECEIPT_SECRET_ENV = "MM_CONNECTOR_RECEIPT_SECRET"
ONTOLOGY_VALIDATOR_RECEIPT_SCHEMA = "mm-ontology-validator-receipt/1"
ONTOLOGY_VALIDATOR_RECEIPT_SECRET_ENV = "MM_ONTOLOGY_VALIDATOR_RECEIPT_SECRET"
AUDIT_EVIDENCE_SCHEMA = "mm-audit-evidence/1"
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


@contextmanager
def gate_operation_lock(ws: Workspace, artifact: str):
    """Serialize a single artifact's create authorization across processes."""
    key = hashlib.sha256(f"{ws.doc}|{artifact}".encode("utf-8")).hexdigest()[:24]
    lock_path = ws.root / "locks" / f"gate-{key}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise S.LockHeld(f"{ws.doc.name}: {artifact} gate transaction is already in progress") from exc
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


_TURTLE_SIMPLE_ESCAPES = frozenset({"t", "b", "n", "r", "f", chr(92), '"', "'"})
_TURTLE_IRI_FORBIDDEN = frozenset('<>"{}|^`')
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _scan_turtle_string(text: str, start: int) -> tuple[int, str | None]:
    """Return the first byte after a Turtle string or a lexical error.

    This deliberately recognizes only tokens that are unambiguously malformed
    (bad escapes, broken string delimiters). It is a reject-only prefilter; a
    successful scan is *not* Turtle validation and can never establish trust.
    """
    quote = text[start]
    triple = text.startswith(quote * 3, start)
    index = start + (3 if triple else 1)
    limit = len(text)
    while index < limit:
        char = text[index]
        if char == chr(92):
            if index + 1 >= limit:
                return index, "truncated Turtle escape"
            escape = text[index + 1]
            if escape in _TURTLE_SIMPLE_ESCAPES:
                index += 2
                continue
            if escape in {"u", "U"}:
                width = 4 if escape == "u" else 8
                digits = text[index + 2:index + 2 + width]
                if len(digits) != width or any(digit not in _HEX_DIGITS for digit in digits):
                    return index, f"malformed Turtle \\{escape} escape"
                index += 2 + width
                continue
            return index, f"unknown Turtle escape \\{escape}"
        if triple and text.startswith(quote * 3, index):
            return index + 3, None
        if not triple and char == quote:
            return index + 1, None
        if not triple and char in {chr(13), chr(10)}:
            return index, "unterminated Turtle string literal"
        index += 1
    return index, "unterminated Turtle string literal"


def _turtle_rejection_reason(text: str, meeting_iri: str) -> str | None:
    """Reject objectively broken runnerless input without pretending to parse it.

    The fallback formerly promoted an approximate regex match. This scanner is
    intentionally narrower: it blocks known malformed lexical forms and checks
    that the historical direct-meeting shape is present, but only a configured
    runner or an authenticated parser receipt can attest successful validation.
    """
    index = 0
    line = 1
    limit = len(text)
    while index < limit:
        char = text[index]
        if char == chr(10):
            line += 1
            index += 1
            continue
        if char == "#":
            next_newline = text.find(chr(10), index)
            index = limit if next_newline < 0 else next_newline
            continue
        if char in {"'", '"'}:
            next_index, error = _scan_turtle_string(text, index)
            if error:
                return f"line {line}: {error}"
            line += text[index:next_index].count(chr(10))
            index = next_index
            continue
        if char == "<":
            end = index + 1
            while end < limit and text[end] != ">":
                candidate = text[end]
                if candidate in {chr(13), chr(10)} or candidate.isspace() or candidate in _TURTLE_IRI_FORBIDDEN:
                    return f"line {line}: malformed Turtle IRI"
                end += 1
            if end >= limit:
                return f"line {line}: unterminated Turtle IRI"
            if end == index + 1:
                return f"line {line}: empty Turtle IRI"
            index = end + 1
            continue
        index += 1

    saw_direct_meeting_statement = False
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        words = stripped.split()
        directive = words[0].lower()
        if directive in {"@prefix", "prefix"}:
            valid = (len(words) == (4 if directive == "@prefix" else 3)
                     and words[1].endswith(":") and words[2].startswith("<")
                     and words[2].endswith(">")
                     and (directive != "@prefix" or words[3] == "."))
            if not valid:
                return f"line {line_number}: malformed Turtle prefix directive"
            continue
        if directive in {"@base", "base"}:
            valid = (len(words) == (3 if directive == "@base" else 2)
                     and words[1].startswith("<") and words[1].endswith(">")
                     and (directive != "@base" or words[2] == "."))
            if not valid:
                return f"line {line_number}: malformed Turtle base directive"
            continue
        direct_subject = f"<{meeting_iri}>"
        if stripped.startswith(direct_subject):
            remainder = stripped[len(direct_subject):].strip()
            if remainder and remainder.endswith("."):
                saw_direct_meeting_statement = True
    if not saw_direct_meeting_statement:
        return "TTL lacks a direct complete statement for the requested meeting IRI"
    return None


def _ontology_env(spec: dict) -> dict[str, str]:
    env = dict(os.environ)
    for key, value in (spec.get("runner_env") or {}).items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float)):
            raise S.ConfigError("ontology.runner_env must map strings to scalar values")
        env[key] = str(value)
    if spec.get("store"):
        env["ONTOLOGY_DB"] = str(spec["store"])
    return env


def _run_ontology(runner: str, env: dict[str, str], *args: str) -> dict:
    command = shlex.split(runner)
    if not command:
        raise S.ConfigError("ontology.runner must be a non-empty command")
    try:
        result = subprocess.run(
            [*command, *args], capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, check=False,
        )
    except (OSError, ValueError) as exc:
        raise FileNotFoundError(str(exc)) from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise S.ConfigError(f"ontology runner {args[0]} failed: {detail[:300]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise S.ConfigError(f"ontology runner {args[0]} did not return JSON") from exc
    if not isinstance(payload, dict):
        raise S.ConfigError(f"ontology runner {args[0]} returned a non-object JSON payload")
    return payload


def ontology_validator_receipt_signature(receipt: dict, secret: str) -> str:
    """Canonical HMAC payload emitted by a trusted Turtle parser adapter."""
    signed = json.loads(json.dumps(receipt))
    validator = signed.get("validator")
    if isinstance(validator, dict):
        validator.pop("signature", None)
    payload = json.dumps(signed, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _ontology_validator_receipt_reason(receipt: object, ttl_text: str, meeting_iri: str) -> str | None:
    """Return a fail-closed reason when a runnerless parser receipt lacks trust."""
    if not isinstance(receipt, dict) or receipt.get("schema") != ONTOLOGY_VALIDATOR_RECEIPT_SCHEMA:
        return f"validator receipt schema must be {ONTOLOGY_VALIDATOR_RECEIPT_SCHEMA}"
    if not isinstance(receipt.get("ttl_sha256"), str) or not hmac.compare_digest(
            receipt["ttl_sha256"], S.body_hash(ttl_text)):
        return "validator receipt TTL hash does not match the submitted Turtle"
    if receipt.get("meeting_iri") != meeting_iri:
        return "validator receipt meeting IRI does not match the requested meeting"
    if not isinstance(receipt.get("triple_count"), int) or receipt["triple_count"] < 1:
        return "validator receipt requires a positive parsed triple count"
    if not _valid_receipt_timestamp(receipt.get("validated_at")):
        return "validator receipt requires a timezone-aware validation timestamp"
    validator = receipt.get("validator")
    if (not isinstance(validator, dict) or not isinstance(validator.get("name"), str)
            or not validator["name"].strip() or validator.get("capability") != "turtle-parse/1"
            or validator.get("auth") != "hmac-sha256"
            or not isinstance(validator.get("key_id"), str) or not validator["key_id"].strip()
            or not isinstance(validator.get("signature"), str)):
        return "validator receipt requires authenticated turtle-parse/1 provenance"
    secret = os.environ.get(ONTOLOGY_VALIDATOR_RECEIPT_SECRET_ENV)
    if not secret:
        return f"{ONTOLOGY_VALIDATOR_RECEIPT_SECRET_ENV} is unavailable; parser trust boundary cannot be verified"
    expected = ontology_validator_receipt_signature(receipt, secret)
    if not hmac.compare_digest(validator["signature"], expected):
        return "validator receipt signature does not verify"
    return None


def cmd_ontology(a) -> int:
    """Verify a required graph only through the runner lifecycle or saved TTL fallback."""
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    doc_id, run_id, manifest = ws.load_run()
    require_lease(ws, doc_id, a.lease)
    art = require_planned(manifest, "ontology")
    if art.get("gate_token"):
        raise S.IllegalTransition("ontology: generic create gate is open — it cannot authorize graph verification")
    enforce_hash(ws, manifest, cfg, "ontology_blocked")
    try:
        ttl_text = pathlib.Path(a.ttl_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise S.ConfigError(f"ontology TTL cannot be read: {exc}") from exc
    if not a.meeting_iri.strip():
        raise S.ConfigError("ontology meeting IRI is required")
    syntax_reason = _turtle_rejection_reason(ttl_text, a.meeting_iri)
    if syntax_reason:
        raise S.ConfigError(f"ontology Turtle rejected before validation: {syntax_reason}")
    saved_ttl = ws.run_dir(run_id) / "ontology" / "ontology.ttl"
    S._atomic_write(saved_ttl, ttl_text)
    spec = cfg.get("ontology") or {}
    if not isinstance(spec, dict):
        raise S.ConfigError("ontology config must be a mapping")
    runner = spec.get("runner")
    provenance: dict
    if runner:
        if not isinstance(runner, str):
            raise S.ConfigError("ontology.runner must be a command string or null")
        env = _ontology_env(spec)
        _run_ontology(runner, env, "validate", str(pathlib.Path(a.ttl_file).resolve()))
        _run_ontology(runner, env, "load", str(pathlib.Path(a.ttl_file).resolve()))
        query = _run_ontology(runner, env, "query", a.meeting_iri)
        count = query.get("count", query.get("triple_count"))
        if not isinstance(count, int) or count < 1:
            raise S.ReadbackMismatch("ontology query returned no meeting triples")
        provenance = {
            "mode": "runner", "runner": runner, "ttl_path": str(saved_ttl),
            "ttl_sha256": S.body_hash(ttl_text), "meeting_iri": a.meeting_iri,
            "query_count": count, "validated_at": S.iso(S.utcnow()),
        }
    else:
        # A locally saved TTL has no independent validation/read-back evidence.
        # Keep it inspectable but incomplete unless a trusted parser signs a
        # hash-bound receipt for this exact Turtle and meeting IRI.
        if a.validator_receipt is None:
            return _record_readback_gap(
                ws, manifest, art, "ontology",
                "runnerless Turtle has no authenticated parser capability receipt",
                doc_id, run_id)
        try:
            receipt_path = pathlib.Path(a.validator_receipt)
            receipt_raw = receipt_path.read_bytes()
            receipt = json.loads(receipt_raw.decode("utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            return _record_readback_gap(
                ws, manifest, art, "ontology",
                f"validator receipt unreadable: {type(exc).__name__}", doc_id, run_id)
        receipt_reason = _ontology_validator_receipt_reason(receipt, ttl_text, a.meeting_iri)
        if receipt_reason:
            return _record_readback_gap(ws, manifest, art, "ontology", receipt_reason, doc_id, run_id)
        reason = (a.degraded_reason or "configured ontology runner unavailable").strip()
        if not reason:
            raise S.ConfigError("ontology degraded fallback requires a reason")
        saved_receipt = ws.run_dir(run_id) / "ontology" / "validator-receipt.json"
        S._atomic_write(saved_receipt, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        provenance = {
            "mode": "validator_receipt", "reason": reason,
            "ttl_path": str(saved_ttl), "ttl_sha256": S.body_hash(ttl_text),
            "meeting_iri": a.meeting_iri, "validated_at": receipt["validated_at"],
            "triple_count": receipt["triple_count"], "receipt_path": str(saved_receipt),
            "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "validator": {
                "name": receipt["validator"]["name"],
                "capability": receipt["validator"]["capability"],
                "key_id": receipt["validator"]["key_id"],
            },
        }
    S.assert_artifact_transition(art["status"], "created")
    S.assert_artifact_transition("created", "readback_verified")
    art.update(status="readback_verified", external_id=a.meeting_iri,
               rendered_sha256=S.body_hash(ttl_text), readback_sha256=S.body_hash(ttl_text),
               attempts=art["attempts"] + 1, updated_at=S.iso(S.utcnow()),
               last_error=None, provenance=provenance)
    ws.save_manifest(manifest)
    ws.log(doc_id=doc_id, run_id=run_id, event="ontology_verified", artifact="ontology",
           impact="none", detail=f"mode={provenance['mode']} iri={a.meeting_iri}")
    emit({"artifact": "ontology", "status": "readback_verified", "provenance": provenance},
         f"ontology {provenance['mode']} verification complete")
    return 0


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
    # Lock first, then reload the run: manifest observation and durable create
    # intent are one transaction rather than two uncoordinated snapshots.
    with gate_operation_lock(ws, a.artifact):
        doc_id, run_id, manifest = ws.load_run()
        require_lease(ws, doc_id, a.lease)
        art = require_planned(manifest, a.artifact)
        enforce_hash(ws, manifest, cfg, "gate_blocked")

        intent = art.get("create_intent")
        if isinstance(intent, dict) and intent.get("state") == "claimed":
            # The process may have crashed after an adapter performed its
            # provider-side create. A second gate must never mint a replacement
            # authorization: search/read back by the stable provider key, then
            # record the discovered id with this exact durable claim.
            snapshot = ws.run_dir(run_id) / "source.md"
            ws.log(doc_id=doc_id, run_id=run_id, event="create_recovery_required",
                   artifact=a.artifact, failure_class="external",
                   root_cause_key=f"{a.artifact}.claimed_create_unresolved",
                   impact="manual_recovery",
                   detail="claimed create has no recorded provider result")
            emit({"action": "manual_recovery", "artifact": a.artifact,
                  "snapshot_path": str(snapshot), "idem_key": art["idem_key"],
                  "footer": f"> mm:{art['idem_key']}", "external_id": None,
                  "artifact_status": art["status"], "gate_token": None,
                  "claim_id": intent.get("claim_id"),
                  "provider_idempotency_key": intent.get("provider_idempotency_key")},
                 f"{a.artifact} has an unresolved create claim — search/read back with its idempotency key; do not create again")
            return 0
        if art.get("gate_token") or (isinstance(intent, dict) and intent.get("state") == "open"):
            raise S.IllegalTransition(
                f"{a.artifact}: open gate already exists — record or abort the first create attempt")

        if manifest["status"] in {"approved", "reopened"}:
            S.assert_run_transition(manifest["status"], "publishing")
            manifest["status"] = "publishing"

        # An external id is an idempotency boundary: even a previously verified
        # artifact may be invalidated by a later audit, but it must be read back
        # rather than silently recreated.
        readback = bool(art["external_id"])
        token = secrets.token_hex(16) if not readback else None
        if token:
            art["create_intent"] = {
                "token": token, "state": "open", "issued_at": S.iso(S.utcnow()),
                "artifact": a.artifact,
                # Connector adapters must pass this stable value to their
                # provider's idempotency surface before making the side effect.
                "provider_idempotency_key": art["idem_key"],
            }
        art["gate_token"] = token
        art["updated_at"] = S.iso(S.utcnow())
        ws.save_manifest(manifest)
        write_mirror(ws, doc_id, run_id, manifest["status"], manifest["artifacts"])

        snapshot = ws.run_dir(run_id) / "source.md"
        ws.log(doc_id=doc_id, run_id=run_id, event="gate_pass", artifact=a.artifact,
               impact="none", detail="readback" if readback else "create")
        payload = {"action": "readback" if readback else "create",
                   "artifact": a.artifact, "snapshot_path": str(snapshot),
                   "idem_key": art["idem_key"], "footer": f"> mm:{art['idem_key']}",
                   "external_id": art["external_id"], "artifact_status": art["status"],
                   "gate_token": token}
    emit(payload,
         ("read back the existing artifact instead of creating a second one"
          if readback else f"cleared to create {a.artifact} from {snapshot}"))
    return 0


def cmd_claim_create(a) -> int:
    """Atomically consume a gate token *before* an external provider create.

    A gate token authorizes exactly one durable claim.  Connector adapters must
    call this command, then pass the returned idempotency key to the provider;
    a crash after this point is deliberately manual/read-back recovery rather
    than a second create authorization.
    """
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    with gate_operation_lock(ws, a.artifact):
        doc_id, run_id, manifest = ws.load_run()
        require_lease(ws, doc_id, a.lease)
        art = require_planned(manifest, a.artifact)
        if a.artifact == "ontology":
            raise S.ConfigError("ontology uses the `ontology` TTL lifecycle, not create claims")
        enforce_hash(ws, manifest, cfg, "claim_create_blocked")
        intent = art.get("create_intent")
        if art.get("external_id"):
            raise S.IllegalTransition(
                f"{a.artifact}: existing id {art['external_id']} — read it back; do not recreate")
        if (not isinstance(intent, dict) or intent.get("state") != "open"
                or not isinstance(intent.get("token"), str)
                or not isinstance(art.get("gate_token"), str)
                or not hmac.compare_digest(a.gate_token, intent["token"])
                or not hmac.compare_digest(a.gate_token, art["gate_token"])):
            raise S.IllegalTransition(f"{a.artifact}: gate token is not an open create authorization")

        claim_id = secrets.token_hex(16)
        intent.update(state="claimed", claim_id=claim_id, claimed_at=S.iso(S.utcnow()))
        # The bearer token cannot authorize a second connector worker after
        # this durable transition. `record` is bound to the claim ID instead.
        art.update(gate_token=None, updated_at=S.iso(S.utcnow()))
        ws.save_manifest(manifest)
        write_mirror(ws, doc_id, run_id, manifest["status"], manifest["artifacts"])
        ws.log(doc_id=doc_id, run_id=run_id, event="create_claimed", artifact=a.artifact,
               impact="none", detail="provider create claim issued")
        payload = {
            "action": "create", "artifact": a.artifact, "claim_id": claim_id,
            "provider_idempotency_key": intent["provider_idempotency_key"],
            "snapshot_path": str(ws.run_dir(run_id) / "source.md"),
            "footer": f"> mm:{art['idem_key']}",
        }
    emit(payload,
         f"create claim recorded for {a.artifact}; pass provider_idempotency_key exactly once")
    return 0


def cmd_record(a) -> int:
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    # `record` is also a state transition: serialize it so a duplicated
    # connector response cannot overwrite the first external id in the manifest.
    with gate_operation_lock(ws, a.artifact):
        doc_id, run_id, manifest = ws.load_run()
        require_lease(ws, doc_id, a.lease)
        art = require_planned(manifest, a.artifact)
        if a.artifact == "ontology":
            raise S.ConfigError(
                "ontology: generic record is forbidden — use `ontology` with a TTL artifact")
        intent = art.get("create_intent")
        if art.get("external_id"):
            raise S.IllegalTransition(
                f"{a.artifact}: existing id {art['external_id']} — read it back; do not recreate")
        if (not isinstance(intent, dict) or intent.get("state") != "claimed"
                or not isinstance(intent.get("token"), str)
                or not isinstance(intent.get("claim_id"), str)
                or not hmac.compare_digest(a.gate_token, intent["token"])
                or not hmac.compare_digest(a.claim_id, intent["claim_id"])):
            raise S.IllegalTransition(
                f"{a.artifact}: record requires the exact claimed create authorization")
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
        intent.update(state="recorded", recorded_at=S.iso(S.utcnow()), external_id=a.id)
        art.update(status="created", external_id=a.id, url=a.url,
                   rendered_sha256=S.body_hash(body), attempts=art["attempts"] + 1,
                   updated_at=S.iso(S.utcnow()), last_error=None, gate_token=None)
        ws.save_manifest(manifest)
        write_mirror(ws, doc_id, run_id, manifest["status"], manifest["artifacts"])
        ws.log(doc_id=doc_id, run_id=run_id, event="artifact_created", artifact=a.artifact,
               impact="none", detail=f"id={a.id}")
        payload = {"artifact": a.artifact, "status": "created", "external_id": a.id,
                   "rendered_sha256": art["rendered_sha256"]}
    emit(payload,
         f"{a.artifact} created ({a.id}) — NOT done until `verify` reads it back")
    return 0


def connector_receipt_signature(receipt: dict, secret: str) -> str:
    """Canonical HMAC payload emitted by the authenticated connector adapter."""
    signed = json.loads(json.dumps(receipt))
    adapter = signed.get("adapter")
    if isinstance(adapter, dict):
        adapter.pop("signature", None)
    payload = json.dumps(signed, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _valid_receipt_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return S._parse(value).tzinfo is not None
    except (TypeError, ValueError):
        return False


def _connector_receipt_reason(receipt: object, artifact: str, external_id: str | None) -> str | None:
    """Return a fail-closed reason when local JSON lacks adapter trust provenance."""
    if not isinstance(receipt, dict) or receipt.get("schema") != CONNECTOR_RECEIPT_SCHEMA:
        return f"receipt schema must be {CONNECTOR_RECEIPT_SCHEMA}"
    if receipt.get("artifact") != artifact or receipt.get("external_id") != external_id:
        return "receipt artifact or external_id does not match the recorded artifact"
    if not isinstance(receipt.get("body"), str) or not _valid_receipt_timestamp(receipt.get("fetched_at")):
        return "receipt requires body and timezone-aware fetched_at"
    remote = receipt.get("remote")
    if (not isinstance(remote, dict) or remote.get("id") != external_id
            or not isinstance(remote.get("url"), str)
            or not remote["url"].startswith(("https://", "http://"))
            or not _valid_receipt_timestamp(remote.get("retrieved_at"))):
        return "receipt requires remote id, retrieval URL, and timezone-aware retrieval timestamp"
    adapter = receipt.get("adapter")
    if (not isinstance(adapter, dict) or not isinstance(adapter.get("name"), str)
            or not adapter["name"].strip() or adapter.get("auth") != "hmac-sha256"
            or not isinstance(adapter.get("key_id"), str) or not adapter["key_id"].strip()
            or not isinstance(adapter.get("signature"), str)):
        return "receipt requires authenticated adapter provenance"
    secret = os.environ.get(CONNECTOR_RECEIPT_SECRET_ENV)
    if not secret:
        return f"{CONNECTOR_RECEIPT_SECRET_ENV} is unavailable; connector trust boundary cannot be verified"
    expected = connector_receipt_signature(receipt, secret)
    if not hmac.compare_digest(adapter["signature"], expected):
        return "receipt adapter signature does not verify"
    return None


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
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            return _record_readback_gap(
                ws, manifest, art, a.artifact, f"connector receipt unreadable: {type(exc).__name__}",
                doc_id, run_id)
        reason = _connector_receipt_reason(receipt, a.artifact, art.get("external_id"))
        if reason:
            return _record_readback_gap(ws, manifest, art, a.artifact, reason, doc_id, run_id)
        back_text = receipt["body"]
        saved_receipt = ws.run_dir(run_id) / "readback" / f"{a.artifact}.receipt.json"
        S._atomic_write(saved_receipt, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
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
    """Append a failure observation; it is never revoke/reopen authority by itself."""
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    doc_id, run_id, _ = ws.load_run()
    ws.log(doc_id=doc_id, run_id=run_id, event="tool_error", artifact=a.artifact,
           failure_class=a.failure_class, root_cause_key=a.key, impact=a.impact,
           detail=a.detail)
    emit({"logged": True, "artifact": a.artifact, "root_cause_key": a.key,
          "state_changed": False},
         f"logged {a.key} ({a.failure_class}/{a.impact}); use revoke with audit evidence to change state")
    return 0


def _load_audit_evidence(path: str, artifact: str, external_id: str | None) -> tuple[dict, str, str]:
    """Read concrete audit evidence; CLI failure prose is deliberately insufficient."""
    try:
        raw = pathlib.Path(path).read_bytes()
        evidence = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise S.ConfigError(f"audit evidence cannot be read: {exc}") from exc
    if not isinstance(evidence, dict) or evidence.get("schema") != AUDIT_EVIDENCE_SCHEMA:
        raise S.ConfigError(f"audit evidence schema must be {AUDIT_EVIDENCE_SCHEMA}")
    if evidence.get("artifact") != artifact or evidence.get("external_id") != external_id:
        raise S.ConfigError("audit evidence artifact or external_id does not match the recorded artifact")
    if not isinstance(evidence.get("finding"), str) or not evidence["finding"].strip():
        raise S.ConfigError("audit evidence requires a non-empty finding")
    if not _valid_receipt_timestamp(evidence.get("observed_at")):
        raise S.ConfigError("audit evidence observed_at must be a timezone-aware ISO timestamp")
    return evidence, hashlib.sha256(raw).hexdigest(), raw.decode("utf-8")


def cmd_revoke(a) -> int:
    """The evidence-bearing authority for invalidating a verified artifact."""
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    doc_id, run_id, manifest = ws.load_run()
    art = require_planned(manifest, a.artifact)
    evidence, evidence_sha256, evidence_text = _load_audit_evidence(
        a.evidence_file, a.artifact, art.get("external_id"))
    if manifest["status"] != "complete":
        if not a.lease:
            raise S.LockHeld("a live run requires its current --lease for audit revoke")
        require_lease(ws, doc_id, a.lease)
    S.assert_artifact_transition(art["status"], "failed")
    evidence_path = ws.run_dir(run_id) / "evidence" / f"{a.artifact}-{evidence_sha256}.json"
    S._atomic_write(evidence_path, evidence_text)
    # Persist the evidence event before the mutating transition. The event log
    # is append-only and leaves a durable authority trail even on a later crash.
    ws.log(doc_id=doc_id, run_id=run_id, event="audit_revoke", artifact=a.artifact,
           failure_class="contract", root_cause_key=a.key, impact="manual_recovery",
           detail=evidence["finding"], evidence_sha256=evidence_sha256,
           evidence_path=str(evidence_path))
    art.update(status="failed", last_error=evidence["finding"], updated_at=S.iso(S.utcnow()),
               audit_evidence={"sha256": evidence_sha256, "path": str(evidence_path),
                               "observed_at": evidence["observed_at"]})
    recovery_lease = None
    if manifest["status"] == "complete":
        S.assert_run_transition("complete", "reopened")
        manifest.update(status="reopened", reopened_at=S.iso(S.utcnow()))
    ws.save_manifest(manifest)
    if manifest["status"] == "reopened":
        index = ws.index()
        recovered_index, recovery_lease = S.acquire_lease(
            index, doc_id, default_owner(),
            runtime_opt(cfg, "lease_ttl_min", DEFAULT_TTL_MIN), S.utcnow())
        S.write_index_cas(ws.index_path, recovered_index, index["version"])
        write_mirror(ws, doc_id, run_id, "reopened", manifest["artifacts"])
    payload = {"revoked": True, "artifact": a.artifact, "evidence_sha256": evidence_sha256}
    if recovery_lease:
        payload["recovery_lease"] = recovery_lease
    emit(payload, f"revoked {a.artifact} from audit evidence")
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

    c = common(sub.add_parser("claim-create"))
    c.add_argument("--artifact", required=True)
    c.add_argument("--gate-token", required=True,
                   help="one-time gate authorization to consume before provider create")
    c.set_defaults(func=cmd_claim_create)

    r = common(sub.add_parser("record"))
    r.add_argument("--artifact", required=True)
    r.add_argument("--id", required=True)
    r.add_argument("--body-file", required=True)
    r.add_argument("--gate-token", required=True,
                   help="gate authorization consumed by the prior `claim-create`")
    r.add_argument("--claim-id", required=True,
                   help="exact durable pre-create claim returned by `claim-create`")
    r.add_argument("--url")
    r.set_defaults(func=cmd_record)

    o = common(sub.add_parser("ontology"))
    o.add_argument("--ttl-file", required=True)
    o.add_argument("--meeting-iri", required=True)
    o.add_argument("--degraded-reason")
    o.add_argument("--validator-receipt",
                   help="authenticated, hash-bound Turtle parser capability receipt for runnerless completion")
    o.set_defaults(func=cmd_ontology)

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

    rv = common(sub.add_parser("revoke"), lease=False)
    rv.add_argument("--lease", help="required when revoking a live run")
    rv.add_argument("--artifact", required=True)
    rv.add_argument("--evidence-file", required=True)
    rv.add_argument("--key", default="audit.revoked")
    rv.set_defaults(func=cmd_revoke)

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
