#!/usr/bin/env python3
"""Create and validate the STT-to-meeting-minutes handoff sidecar.

The two skills remain independent: this script only consumes a stamped
transcript, a glossary, and a structured review-state JSON document. A handoff
is eligible for composition only when both source hashes still match and no
Tier-B or Tier-C review items remain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCHEMA = "meeting-transcript-handoff/1"


class HandoffError(ValueError):
    """Malformed or untrustworthy handoff input."""


def sha256_file(path: Path) -> str:
    path = Path(path)
    if not path.is_file():
        raise HandoffError(f"file not found: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HandoffError(f"unreadable {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HandoffError(f"{label} must be a JSON object: {path}")
    return value


def _stamp_path(transcript: Path) -> Path:
    return transcript.with_name(transcript.name + ".fixstamp")


def _verified_stamp(transcript: Path, glossary: Path) -> dict[str, Any]:
    """Return a stamp only if it attests to the current source bytes."""
    stamp = _read_json(_stamp_path(transcript), "fixstamp")
    actual = {
        "file_sha256": sha256_file(transcript),
        "glossary_sha256": sha256_file(glossary),
    }
    for field, current in actual.items():
        if stamp.get(field) != current:
            raise HandoffError(f"fixstamp {field} does not match current source")
    if not isinstance(stamp.get("skill_version"), str) or not stamp["skill_version"]:
        raise HandoffError("fixstamp missing skill_version")
    return stamp


def _review_state(value: Any) -> tuple[list[Any], list[Any], dict[str, Any]]:
    if not isinstance(value, dict):
        raise HandoffError("review state must be a JSON object")
    tier_b = value.get("tier_b_pending", [])
    tier_c = value.get("tier_c_holds", [])
    markers = value.get("marker_summary", {})
    if not isinstance(tier_b, list):
        raise HandoffError("review.tier_b_pending must be a list")
    if not isinstance(tier_c, list):
        raise HandoffError("review.tier_c_holds must be a list")
    if not isinstance(markers, dict):
        raise HandoffError("marker_summary must be an object")
    for key in ("existing", "inserted"):
        if key not in markers or not isinstance(markers[key], int) or markers[key] < 0:
            raise HandoffError(f"marker_summary.{key} must be a non-negative integer")
    return tier_b, tier_c, markers


def build_handoff(transcript: Path, glossary: Path, review_state: dict[str, Any]) -> dict[str, Any]:
    """Bind one stamped, corrected transcript to its review disposition."""
    transcript = Path(transcript).resolve()
    glossary = Path(glossary).resolve()
    stamp = _verified_stamp(transcript, glossary)
    tier_b, tier_c, markers = _review_state(review_state)
    return {
        "schema": SCHEMA,
        "transcript": {"path": str(transcript), "sha256": sha256_file(transcript)},
        "glossary": {"path": str(glossary), "sha256": sha256_file(glossary)},
        "fixstamp_version": stamp["skill_version"],
        "review": {"tier_b_pending": tier_b, "tier_c_holds": tier_c},
        "marker_summary": markers,
    }


def validate_handoff(handoff: dict[str, Any], transcript: Path, glossary: Path) -> dict[str, Any]:
    """Return publish eligibility and every reason a handoff is not trustworthy."""
    blockers: list[str] = []
    transcript = Path(transcript).resolve()
    glossary = Path(glossary).resolve()

    if not isinstance(handoff, dict) or handoff.get("schema") != SCHEMA:
        blockers.append("unsupported handoff schema")
        return {"eligible": False, "blockers": blockers}

    for name, path in (("transcript", transcript), ("glossary", glossary)):
        recorded = handoff.get(name)
        if not isinstance(recorded, dict):
            blockers.append(f"{name} metadata missing")
            continue
        try:
            actual = sha256_file(path)
        except HandoffError as exc:
            blockers.append(str(exc))
            continue
        if recorded.get("sha256") != actual:
            blockers.append(f"{name}_sha256 mismatch")

    version = handoff.get("fixstamp_version")
    if not isinstance(version, str) or not version:
        blockers.append("fixstamp_version missing")
    else:
        try:
            stamp = _verified_stamp(transcript, glossary)
        except HandoffError as exc:
            blockers.append(str(exc))
        else:
            if stamp["skill_version"] != version:
                blockers.append("fixstamp_version mismatch")

    review = handoff.get("review")
    if not isinstance(review, dict):
        blockers.append("review metadata missing")
    else:
        tier_b = review.get("tier_b_pending")
        tier_c = review.get("tier_c_holds")
        if not isinstance(tier_b, list):
            blockers.append("review.tier_b_pending invalid")
        elif tier_b:
            blockers.append(f"tier_b_pending: {len(tier_b)}")
        if not isinstance(tier_c, list):
            blockers.append("review.tier_c_holds invalid")
        elif tier_c:
            blockers.append(f"tier_c_holds: {len(tier_c)}")

    try:
        _review_state(
            {
                "tier_b_pending": [],
                "tier_c_holds": [],
                "marker_summary": handoff.get("marker_summary"),
            }
        )
    except HandoffError as exc:
        blockers.append(str(exc))

    return {"eligible": not blockers, "blockers": blockers}


def write_handoff(path: Path, handoff: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    temporary.write_text(json.dumps(handoff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _cmd_create(args: argparse.Namespace) -> int:
    handoff = build_handoff(Path(args.transcript), Path(args.glossary), _read_json(Path(args.review_state), "review state"))
    write_handoff(Path(args.out), handoff)
    print(json.dumps({"handoff": str(Path(args.out)), "eligibility": validate_handoff(handoff, Path(args.transcript), Path(args.glossary))}, ensure_ascii=False))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    verdict = validate_handoff(_read_json(Path(args.handoff), "handoff"), Path(args.transcript), Path(args.glossary))
    print(json.dumps(verdict, ensure_ascii=False))
    return 0 if verdict["eligible"] else 7


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="transcript_handoff", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="write a stamped transcript handoff JSON")
    create.add_argument("--transcript", required=True)
    create.add_argument("--glossary", required=True)
    create.add_argument("--review-state", required=True)
    create.add_argument("--out", required=True)
    create.set_defaults(func=_cmd_create)

    validate = commands.add_parser("validate", help="check whether a handoff is publish-eligible")
    validate.add_argument("--handoff", required=True)
    validate.add_argument("--transcript", required=True)
    validate.add_argument("--glossary", required=True)
    validate.set_defaults(func=_cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except HandoffError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
