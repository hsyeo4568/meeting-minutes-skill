#!/usr/bin/env python3
"""Schema-v2 validator for new meeting work-MD frontmatter.

Legacy notes intentionally remain readable: validation is strict only when the
note explicitly declares ``schema_version: 2``.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - surfaced by CLI / runtime
    yaml = None

SCHEMA_VERSION = 2
_ACTION_KEYS = ("id", "org", "owner", "due", "status", "text")


def parse_frontmatter(text: str) -> dict:
    """Return YAML frontmatter without round-tripping or changing the source."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML is required for schema-v2 validation")
    loaded = yaml.safe_load(text[4:end]) or {}
    if not isinstance(loaded, dict):
        raise ValueError("frontmatter must be a mapping")
    return loaded


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_metadata(data: dict) -> list[str]:
    """Return human-readable errors; absent schema_version means legacy-compatible."""
    if "schema_version" not in data:
        return []
    if data.get("schema_version") != SCHEMA_VERSION:
        return [f"schema_version must be {SCHEMA_VERSION}"]

    errors: list[str] = []
    recordings = data.get("recordings")
    if not isinstance(recordings, list):
        errors.append("recordings must be a list")
    elif not recordings:
        errors.append("recordings must not be empty")
    else:
        for index, item in enumerate(recordings, start=1):
            if not isinstance(item, dict):
                errors.append(f"recordings[{index}] must be a mapping")
                continue
            if not _text(item.get("path")):
                errors.append(f"recordings[{index}].path must be a non-empty string")
            for optional in ("corrected_path", "review_path"):
                if optional in item and not _text(item[optional]):
                    errors.append(f"recordings[{index}].{optional} must be a non-empty string")

    actions = data.get("action_items")
    if not isinstance(actions, list):
        errors.append("action_items must be a list")
    else:
        seen_ids = set()
        for index, item in enumerate(actions, start=1):
            if not isinstance(item, dict):
                errors.append(f"action_items[{index}] must be a mapping")
                continue
            missing = [key for key in _ACTION_KEYS if key not in item]
            if missing:
                errors.append(f"action_items[{index}] missing: {', '.join(missing)}")
                continue
            for key in ("id", "org", "owner", "status", "text"):
                if not _text(item[key]):
                    errors.append(f"action_items[{index}].{key} must be a non-empty string")
            if not isinstance(item["due"], (str, date)):
                errors.append(f"action_items[{index}].due must be an ISO date string or date")
            if item.get("id") in seen_ids:
                errors.append(f"action_items[{index}].id duplicates {item['id']!r}")
            seen_ids.add(item.get("id"))

    artifacts = data.get("artifacts")
    if not isinstance(artifacts, dict):
        errors.append("artifacts must be a mapping")
    else:
        for name, item in artifacts.items():
            if not isinstance(item, dict) or not _text(item.get("status")):
                errors.append(f"artifacts.{name} must be a mapping with non-empty status")
    return errors


def validate_text(text: str) -> list[str]:
    try:
        return validate_metadata(parse_frontmatter(text))
    except (RuntimeError, ValueError, OSError) as exc:
        return [str(exc)]


def validate_path(path: Path) -> list[str]:
    return validate_text(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("doc")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    errors = validate_path(Path(args.doc))
    payload = {"path": args.doc, "valid": not errors, "errors": errors}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print("VALID" if not errors else "INVALID: " + "; ".join(errors))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
