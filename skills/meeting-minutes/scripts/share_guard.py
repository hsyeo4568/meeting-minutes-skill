#!/usr/bin/env python3
"""Share destination guard (2026-08-26 regression).

Slack canvases created in the Slack *app* DM are invisible to the user
("권한 없음"). Gmail drafts reported as 임시보관함 without a confirmed
draft id never actually land there.

This module is fail-closed: an attempted share with missing fields is a
violation, not a pass. The agent must run it before claiming canvas/gmail
success — `python scripts/mm_run.py share-check --plan <json> --config config.yaml`.

Exit 0 = may report success. Exit 8 = blocked; do not claim done.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


# Machine-readable codes. Tests and mm_run key off these strings.
CANVAS_BOT_DM = "canvas.bot_dm"
CANVAS_MISSING_USER_SHARE = "canvas.missing_user_share"
CANVAS_MISSING_DEST = "canvas.missing_dest"
CANVAS_MISSING_ID = "canvas.missing_id"
CANVAS_UNSOLICITED_CHANNEL = "canvas.unsolicited_channel"
CANVAS_FALSE_SUCCESS = "canvas.false_success"
GMAIL_UNCONFIRMED = "gmail.unconfirmed_inbox_claim"
GMAIL_NO_ID_NO_EML = "gmail.no_id_no_eml"
GMAIL_ID_LOOKS_LIKE_FILE = "gmail.id_looks_like_file"

EXIT_BLOCKED = 8


def _strip(value) -> str:
    return str(value or "").strip()


def _user_ids(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = raw.replace(";", ",").split(",")
    return [_strip(u) for u in raw if _strip(u)]


def check_plan(plan: dict) -> list[str]:
    """Return violation codes. Empty list = the share may be reported as done."""
    if not isinstance(plan, dict):
        return ["plan.not_object"]
    violations: list[str] = []
    slack_user = _strip(plan.get("slack_user_id"))
    bot_dm = _strip(plan.get("slack_bot_dm_id"))
    canvas = plan.get("canvas")
    gmail = plan.get("gmail")

    if isinstance(canvas, dict) and canvas.get("attempted"):
        # dest is destination / dm_user_id / channel_id — never user_ids.
        dest = _strip(
            canvas.get("destination")
            or canvas.get("dm_user_id")
            or canvas.get("channel_id")
        )
        ids = _user_ids(canvas.get("user_ids"))
        canvas_id = _strip(canvas.get("canvas_id"))
        claim = bool(canvas.get("claim_success"))
        user_asked_channel = bool(canvas.get("user_asked_channel"))

        if not dest:
            violations.append(CANVAS_MISSING_DEST)
        if bot_dm and dest == bot_dm:
            violations.append(CANVAS_BOT_DM)
        if dest.startswith("C") and not user_asked_channel:
            violations.append(CANVAS_UNSOLICITED_CHANNEL)
        if slack_user and slack_user not in ids:
            violations.append(CANVAS_MISSING_USER_SHARE)
        # canvas_id only required when claiming success (dest-check is pre-create).
        if claim and not canvas_id:
            violations.append(CANVAS_MISSING_ID)
        if claim and (
            CANVAS_BOT_DM in violations
            or CANVAS_MISSING_USER_SHARE in violations
            or CANVAS_MISSING_ID in violations
            or CANVAS_MISSING_DEST in violations
        ):
            violations.append(CANVAS_FALSE_SUCCESS)

    if isinstance(gmail, dict) and gmail.get("attempted"):
        draft_id = _strip(gmail.get("draft_id"))
        eml = _strip(gmail.get("eml_path"))
        confirmed = bool(gmail.get("confirmed"))
        claim = bool(gmail.get("claim_inbox") or gmail.get("claim_success"))
        if draft_id.lower().endswith((".eml", ".md", ".txt")):
            violations.append(GMAIL_ID_LOOKS_LIKE_FILE)
        if not draft_id and not eml:
            violations.append(GMAIL_NO_ID_NO_EML)
        if claim and not (draft_id and confirmed):
            violations.append(GMAIL_UNCONFIRMED)

    return violations


def merge_config(plan: dict, cfg: dict | None) -> dict:
    """Fill slack ids from config.channels when the plan omitted them."""
    out = dict(plan)
    channels = (cfg or {}).get("channels") or {}
    if not _strip(out.get("slack_user_id")):
        out["slack_user_id"] = _strip(channels.get("slack_user_id"))
    if not _strip(out.get("slack_bot_dm_id")):
        out["slack_bot_dm_id"] = _strip(channels.get("slack_bot_dm_id"))
    return out


def load_config(path: str | None) -> dict:
    if not path:
        return {}
    if yaml is None:
        raise SystemExit("PyYAML not installed (pip install pyyaml)")
    return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}


def load_plan(path: str) -> dict:
    if path == "-":
        return json.loads(sys.stdin.read() or "{}")
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8-sig"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="share_guard", description=__doc__)
    p.add_argument("--plan", required=True, help="JSON file, or - for stdin")
    p.add_argument("--config", help="config.yaml — fills slack_user_id / slack_bot_dm_id")
    args = p.parse_args(argv)
    plan = merge_config(load_plan(args.plan), load_config(args.config))
    violations = check_plan(plan)
    payload = {"ok": not violations, "violations": violations}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return 0 if not violations else EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
