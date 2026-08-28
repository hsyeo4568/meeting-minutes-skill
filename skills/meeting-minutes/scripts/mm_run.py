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
    fail / status / promote-check / gc / share-check / render-share

Exit codes: 0 ok · 2 usage/config · 3 source hash mismatch · 4 read-back
mismatch · 5 lock held · 6 illegal transition · 7 completeness failed
· 8 share blocked (bot DM canvas / unconfirmed Gmail draft).
Design contract: 2026-07-27-mm-runtime-protocol-design.md
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import pathlib
import re
import secrets
import shutil
import socket
import stat
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mm_readback  # noqa: E402
import mm_state as S  # noqa: E402
import share_guard  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    yaml = None

DEFAULT_STATE_DIR = ".mm"
DEFAULT_TTL_MIN = 30
DEFAULT_RETENTION_DAYS = 90
TERMINAL_RUN = {"complete", "aborted", "superseded"}
# Channels that cannot be edited after publishing leave orphans -> manual cleanup.
DEFAULT_EDITABLE = {"vault": True, "share_md": True, "gmail": True, "canvas": False}
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


def load_config(path: str | None) -> dict:
    if not path:
        return {}
    if yaml is None:
        raise S.ConfigError("PyYAML not installed (pip install pyyaml)")
    return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}


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

def write_mirror(ws: Workspace, doc_id: str, run_id: str, state: str) -> None:
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
    source = ws.text()
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

    if manifest["status"] == "approved":
        S.assert_run_transition("approved", "publishing")
        manifest["status"] = "publishing"

    # An external id is an idempotency boundary: even a previously verified
    # artifact may be invalidated by a later audit, but it must be read back
    # rather than silently recreated.
    readback = bool(art["external_id"])
    token = secrets.token_hex(4) if not readback else None
    art["gate_token"] = token
    art["updated_at"] = S.iso(S.utcnow())
    ws.save_manifest(manifest)

    snapshot = ws.run_dir(run_id) / "source.md"
    ws.log(doc_id=doc_id, run_id=run_id, event="gate_pass", artifact=a.artifact,
           impact="none", detail="readback" if readback else "create")
    emit({"action": "readback" if readback else "create",
          "artifact": a.artifact, "snapshot_path": str(snapshot),
          "idem_key": art["idem_key"], "external_id": art["external_id"],
          "artifact_status": art["status"], "gate_token": token},
         ("read back the existing artifact instead of creating a second one"
          if readback else f"cleared to create {a.artifact} from {snapshot}"))
    return 0



def enforce_share(a, cfg: dict) -> None:
    """Fail-closed for canvas/gmail when config knows Slack ids (2026-08-26)."""
    if a.artifact not in ("canvas", "gmail"):
        return
    channels = (cfg or {}).get("channels") or {}
    slack_user = str(channels.get("slack_user_id") or "").strip()
    bot_dm = str(channels.get("slack_bot_dm_id") or "").strip()
    if a.artifact == "canvas" and not (slack_user or bot_dm):
        return
    dest = getattr(a, "dest", None) or ""
    user_ids = getattr(a, "user_ids", None) or ""
    confirmed = bool(getattr(a, "confirmed", False))
    plan = {
        "slack_user_id": slack_user,
        "slack_bot_dm_id": bot_dm,
        "canvas": None,
        "gmail": None,
    }
    if a.artifact == "canvas":
        plan["canvas"] = {
            "attempted": True,
            "canvas_id": a.id,
            "destination": dest,
            "user_ids": user_ids,
            "user_asked_channel": bool(getattr(a, "user_asked_channel", False)),
            "claim_success": False,
        }
    else:
        plan["gmail"] = {
            "attempted": True,
            "draft_id": a.id,
            "confirmed": confirmed,
            "claim_inbox": False,
            "eml_path": "",
        }
    ignore = {
        share_guard.GMAIL_UNCONFIRMED,
        share_guard.CANVAS_FALSE_SUCCESS,
        share_guard.GMAIL_NO_ID_NO_EML,
    }
    viol = [x for x in share_guard.check_plan(plan) if x not in ignore]
    if viol:
        raise S.ShareBlocked(f"{a.artifact} share blocked: {', '.join(viol)}")


def cmd_share_check(a) -> int:
    cfg = load_config(a.config)
    plan = share_guard.merge_config(share_guard.load_plan(a.plan), cfg)
    viol = share_guard.check_plan(plan)
    emit({"ok": not viol, "violations": viol},
         "share-check PASS" if not viol else f"share-check BLOCKED: {', '.join(viol)}")
    if viol:
        raise S.ShareBlocked(", ".join(viol))
    return 0


# ---------------------------------------------------------------------------
# render-share — mechanical canvas/gmail bodies from the snapshot (no MCP)
# ---------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_BULLET = re.compile(r"^\s*(?:[-*·]|\d+[.)])\s+")
_UNMENTIONED = "금일 미언급"
_DEFAULT_GREETING = "안녕하세요."
_DEFAULT_CLOSING = "감사합니다."
_CAT_LABEL = {
    "daily": "Daily 이슈 회의록",
    "regular": "정기 회의록",
    "workshop": "워크샵 회의록",
}


def _flatten_gt(text: str) -> str:
    while ">>" in text:
        text = text.replace(">>", ">")
    return text


def _strip_unmentioned(text: str) -> str:
    return "\n".join(
        line for line in text.split("\n")
        if not (_UNMENTIONED in line and _BULLET.match(line))
    )


def _split_fm(text: str) -> tuple[dict, str]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    meta = {}
    for line in lines[1:end]:
        if ":" in line and not line.startswith((" ", "\t")):
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip().strip("'\"")
    return meta, "\n".join(lines[end + 1:])


def _blocks(body: str) -> list[tuple[int, str, str]]:
    cur_level, cur_title, buf = 0, "", []
    out: list[tuple[int, str, str]] = []
    for line in body.split("\n"):
        m = _HEADING.match(line)
        if m:
            out.append((cur_level, cur_title, "\n".join(buf)))
            cur_level, cur_title, buf = len(m.group(1)), m.group(2).strip(), []
        else:
            buf.append(line)
    out.append((cur_level, cur_title, "\n".join(buf)))
    return out


def _kind(level: int, title: str) -> str:
    t = title.strip()
    if re.match(r"^개요$", t):
        return "overview"
    if re.match(r"^핵심\s*논의$", t):
        return "disc_banner"
    if re.match(r"^\d+\.", t):
        return "discussion"
    if re.match(r"^Action Items$", t, re.I):
        return "actions"
    if t == "일정" or t.startswith("일정 "):
        return "schedule"
    if t.startswith("이전 회의"):
        return "overview"
    if level == 1:
        return "title"
    return "keep"


def _join(parts: list[str]) -> str:
    return re.sub(r"\n{3,}", "\n\n", "\n".join(parts)).strip()


def _bucket(blocks: list[tuple[int, str, str]]) -> tuple[list[str], list[str], list[str], list[str], str]:
    overview, discussion, actions, schedule = [], [], [], []
    title = ""
    bucket = "overview"
    dests = {
        "overview": overview, "discussion": discussion,
        "actions": actions, "schedule": schedule,
    }
    for level, heading, content in blocks:
        if level == 0:
            if content.strip():
                overview.append(content)
            continue
        kind = _kind(level, heading)
        if kind == "title":
            title = heading
            bucket = "overview"
            if content.strip():
                overview.append(content)
            continue
        if kind == "overview":
            bucket = "overview"
            if heading != "개요":
                overview.append(f"{'#' * min(level, 2)} {heading}")
            if content.strip():
                overview.append(content)
            continue
        if kind == "disc_banner":
            bucket = "discussion"
            if content.strip():
                discussion.append(content)
            continue
        if kind == "discussion":
            bucket = "discussion"
            discussion.append(f"## {heading}")
            if content.strip():
                discussion.append(content)
            continue
        if kind == "actions":
            bucket = "actions"
            if content.strip():
                actions.append(content)
            continue
        if kind == "schedule":
            bucket = "schedule"
            if content.strip():
                schedule.append(content)
            continue
        dests[bucket].append(f"{'#' * level} {heading}")
        if content.strip():
            dests[bucket].append(content)
    return overview, discussion, actions, schedule, title


def _section(heading: str, body: str) -> str:
    body = body.strip()
    return f"{heading}\n{body}" if body else heading


def render_canvas(snap: str, category: str) -> tuple[str, str]:
    meta, body = _split_fm(snap)
    body = _strip_unmentioned(_flatten_gt(body.replace("\r\n", "\n").replace("\r", "\n")))
    overview, discussion, actions, schedule, title = _bucket(_blocks(body))
    chunks = [
        _section("# 개요", _join(overview)),
        _section("# 논의 내용", _join(discussion)),
        _section("# Action Items", _join(actions)),
    ]
    sched = _join(schedule)
    if sched:
        chunks.append(_section("# 일정", sched))
    md = _md_date(meta, title)
    label = _CAT_LABEL.get(category, f"{category} 회의록")
    canvas_title = title or (f"{label} ({md})" if md else label)
    return "\n\n".join(chunks).strip() + "\n", canvas_title


def _md_date(meta: dict, title: str) -> str:
    raw = (meta.get("date") or "").strip()
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if m:
        return f"{int(m.group(2))}/{int(m.group(3))}"
    m = re.search(r"\((\d{1,2})/(\d{1,2})\)", title or "")
    if m:
        return f"{int(m.group(1))}/{int(m.group(2))}"
    return ""


def _csv(val) -> str:
    if not val:
        return ""
    if isinstance(val, list):
        return ", ".join(str(x).strip() for x in val if str(x).strip())
    return str(val).strip()


def _fill(template: str, tokens: dict[str, str]) -> str:
    out = template
    for key, val in tokens.items():
        out = out.replace("{{" + key + "}}", val)
    return out


def _envelope(cfg: dict, category: str) -> dict:
    row = (cfg.get("categories") or {}).get(category) or {}
    env = row.get("gmail_envelope") or cfg.get("gmail_envelope") or {}
    return env if isinstance(env, dict) else {}


def _subject(env: dict, cfg: dict, category: str, md: str, tokens: dict[str, str]) -> str:
    raw = env.get("subject") or env.get("subject_pattern") or ""
    if raw:
        filled = _fill(str(raw), tokens)
        if md:
            filled = filled.replace("(M/D)", f"({md})").replace("M/D", md)
        else:
            filled = filled.replace(" (M/D)", "").replace("(M/D)", "").replace("M/D", "")
        return filled.strip()
    label = _CAT_LABEL.get(category, f"{category} 회의록")
    name = str((cfg.get("project") or {}).get("name") or "").strip()
    core = f"[{name}] {label}" if name else label
    return f"{core} ({md})" if md else core


def _gmail_headings(text: str) -> str:
    out = []
    for line in text.split("\n"):
        m = _HEADING.match(line)
        if not m:
            out.append(line)
            continue
        level, title = len(m.group(1)), m.group(2).strip()
        out.append(f"[{title}]" if level >= 3 else f"■ {title}")
    return "\n".join(out)


def render_gmail(canvas: str, snap: str, cfg: dict, category: str,
                 canvas_title: str) -> tuple[str, str]:
    env = _envelope(cfg, category)
    meta, _ = _split_fm(snap)
    md = _md_date(meta, canvas_title)
    ident = cfg.get("identity") or {}
    proj = cfg.get("project") or {}
    tokens = {
        "project_name": str(proj.get("name") or ""),
        "me": str(ident.get("me") or ""),
        "org": str(ident.get("org") or ""),
    }
    subject = _subject(env, cfg, category, md, tokens)
    greeting = _fill(str(env.get("greeting") or _DEFAULT_GREETING), tokens).strip()
    closing = _fill(str(env.get("closing") or _DEFAULT_CLOSING), tokens).strip()
    header = [f"subject: {subject}"]
    to, cc = _csv(env.get("to")), _csv(env.get("cc"))
    if to:
        header.append(f"to: {to}")
    if cc:
        header.append(f"cc: {cc}")
    body = "\n".join(header + ["", greeting, "", _gmail_headings(canvas).strip(), "", closing])
    return body.strip() + "\n", subject


def cmd_render_share(a) -> int:
    """Write rendered/canvas.md + rendered/gmail.md from the run snapshot only."""
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    _doc_id, run_id, manifest = ws.load_run()
    if manifest["status"] not in ("approved", "publishing"):
        raise S.ConfigError(
            f"{run_id} is {manifest['status']} — render-share needs approved/publishing")
    snapshot = ws.run_dir(run_id) / "source.md"
    if not snapshot.exists():
        raise S.ConfigError(f"{run_id}: no snapshot (source.md)")
    enforce_hash(ws, manifest, cfg, "render_share_blocked")
    snap_text = snapshot.read_text(encoding="utf-8")
    if S.source_hash(snap_text) != manifest["source_sha256"]:
        emit({"error": "source_hash_mismatch", "approved": manifest["source_sha256"],
              "current": S.source_hash(snap_text)},
             "BLOCKING: snapshot does not match approved hash")
        raise S.HashMismatch("snapshot does not match approved hash")
    category = manifest.get("category") or "daily"
    canvas_body, canvas_title = render_canvas(snap_text, category)
    gmail_body, gmail_subject = render_gmail(
        canvas_body, snap_text, cfg, category, canvas_title)
    out_dir = ws.run_dir(run_id) / "rendered"
    canvas_path = out_dir / "canvas.md"
    gmail_path = out_dir / "gmail.md"
    S._atomic_write(canvas_path, canvas_body)
    S._atomic_write(gmail_path, gmail_body)
    emit({"canvas_path": str(canvas_path), "gmail_path": str(gmail_path),
          "canvas_title": canvas_title, "gmail_subject": gmail_subject,
          "snapshot_path": str(snapshot)},
         f"rendered share bodies from {snapshot.name}")
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
    enforce_share(a, cfg)
    S.assert_artifact_transition(art["status"], "created")

    body = pathlib.Path(a.body_file).read_text(encoding="utf-8")
    rendered = ws.run_dir(run_id) / "rendered" / f"{a.artifact}.md"
    S._atomic_write(rendered, body)
    art.update(status="created", external_id=a.id, url=a.url,
               rendered_sha256=S.body_hash(body), attempts=art["attempts"] + 1,
               updated_at=S.iso(S.utcnow()), last_error=None, gate_token=None)
    ws.save_manifest(manifest)
    ws.log(doc_id=doc_id, run_id=run_id, event="artifact_created", artifact=a.artifact,
           impact="none", detail=f"id={a.id}")
    emit({"artifact": a.artifact, "status": "created", "external_id": a.id,
          "rendered_sha256": art["rendered_sha256"]},
         f"{a.artifact} created ({a.id}) — NOT done until `verify` reads it back")
    return 0


def cmd_verify(a) -> int:
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    doc_id, run_id, manifest = ws.load_run()
    require_lease(ws, doc_id, a.lease)
    art = require_planned(manifest, a.artifact)
    enforce_hash(ws, manifest, cfg, "verify_blocked")

    back_text = pathlib.Path(a.readback_file).read_text(encoding="utf-8")
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
    write_mirror(ws, doc_id, run_id, "complete")
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
    ws.log(doc_id=doc_id, run_id=run_id, event="abort", failure_class="user",
           root_cause_key="run.aborted", impact="none", detail=a.reason or "")
    emit({"run_id": run_id, "status": "aborted"}, f"{run_id} aborted")
    return 0


def cmd_fail(a) -> int:
    """Log a failure and revoke a disproven verification without a lease.

    ``stale`` remains terminal, but a later audit must be able to move a
    previously verified artifact back to ``failed`` so ``close`` stays
    fail-closed.
    """
    cfg = load_config(a.config)
    ws = Workspace(a.doc, runtime_opt(cfg, "state_dir", DEFAULT_STATE_DIR))
    doc_id, run_id, manifest = ws.load_run()
    if a.artifact and a.artifact in manifest["artifacts"]:
        art = manifest["artifacts"][a.artifact]
        try:
            S.assert_artifact_transition(art["status"], "failed")
            art.update(status="failed", last_error=a.detail,
                       updated_at=S.iso(S.utcnow()))
        except S.IllegalTransition:
            pass  # terminal artifact: log the event, leave the state alone
        ws.save_manifest(manifest)
    ws.log(doc_id=doc_id, run_id=run_id, event="tool_error", artifact=a.artifact,
           failure_class=a.failure_class, root_cause_key=a.key, impact=a.impact,
           detail=a.detail)
    emit({"logged": True, "artifact": a.artifact, "root_cause_key": a.key},
         f"logged {a.key} ({a.failure_class}/{a.impact})")
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
    r.add_argument("--dest", help="canvas destination (user id or channel id)")
    r.add_argument("--user-ids", help="comma-separated Slack user ids the canvas is shared with")
    r.add_argument("--confirmed", action="store_true",
                   help="gmail: get_draft confirmed this id")
    r.add_argument("--user-asked-channel", action="store_true")
    r.set_defaults(func=cmd_record)

    v = common(sub.add_parser("verify"))
    v.add_argument("--artifact", required=True)
    v.add_argument("--readback-file", required=True)
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

    sc = sub.add_parser("share-check")
    sc.add_argument("--plan", required=True)
    sc.add_argument("--config")
    sc.set_defaults(func=cmd_share_check)

    rs = common(sub.add_parser("render-share"), lease=False)
    rs.set_defaults(func=cmd_render_share)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except S.MmError as exc:
        if not isinstance(exc, (S.HashMismatch, S.ReadbackMismatch,
                                S.IncompleteRun, S.ShareBlocked)):
            emit({"error": type(exc).__name__, "detail": str(exc)}, f"ERROR: {exc}")
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
