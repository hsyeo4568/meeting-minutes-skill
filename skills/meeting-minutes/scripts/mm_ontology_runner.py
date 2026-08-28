#!/usr/bin/env python3
"""Adapter: meeting-minutes phase 7 -> vault ontology CLI.

validate <ttl> / load <ttl> / query <meeting IRI> / sync [--ttl|--iri]
load: vault load THEN targeted sync of IRIs in that TTL (entity md mint).
query IRI -> who, then fail-close if the meeting instance note is missing.
Missing MM_ONTOLOGY_CLI or cli.py/sync_to_vault.py -> exit 2 (not skip).
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ENTITY_BASE = "https://notes.justin.vault/entity/"


def cli_base() -> tuple[list[str], Path]:
    raw = os.environ.get("MM_ONTOLOGY_CLI", "").strip()
    if not raw:
        print("mm_ontology_runner: MM_ONTOLOGY_CLI is unset", file=sys.stderr)
        sys.exit(2)
    parts = shlex.split(raw, posix=True)
    script = None
    for part in parts:
        if part.replace("\\", "/").endswith("cli.py"):
            script = Path(part)
            break
    if script is None or not script.is_file():
        print("mm_ontology_runner: cli.py missing", script, file=sys.stderr)
        sys.exit(2)
    sync = script.with_name("sync_to_vault.py")
    if not sync.is_file():
        print("mm_ontology_runner: sync_to_vault.py missing", sync, file=sys.stderr)
        sys.exit(2)
    return parts, script.parent


def run(args: list[str], cwd: Path) -> int:
    return subprocess.run(args, cwd=str(cwd)).returncode


def looks_like_sparql(s: str) -> bool:
    u = s.lstrip().upper()
    return u.startswith(("SELECT", "ASK", "CONSTRUCT", "DESCRIBE", "@"))


def normalize_iri(raw: str) -> str:
    t = raw.strip().strip("<>")
    if t.startswith("v:"):
        return ENTITY_BASE + t[2:]
    return t


def local_name(iri: str) -> str:
    iri = normalize_iri(iri)
    if iri.startswith(ENTITY_BASE):
        return iri[len(ENTITY_BASE):].replace("/", "-")
    return iri.rsplit("/", 1)[-1]


def vault_root(cwd: Path) -> Path:
    # cwd = <vault>/_vault/scripts/ontology
    return cwd.parents[2]


def instance_path(cwd: Path, iri: str) -> Path:
    name = local_name(iri)
    # meetings (and other untyped) land in entities/; decisions in decisions/
    if "/decision/" in normalize_iri(iri) or normalize_iri(iri).startswith(ENTITY_BASE + "decision/"):
        sub = "ontology/instances/decisions"
    else:
        sub = "ontology/instances/entities"
    if normalize_iri(iri).startswith(ENTITY_BASE + "meeting/") or "/meeting/" in normalize_iri(iri):
        sub = "ontology/instances/entities"
    return vault_root(cwd) / sub / f"{name}.md"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: mm_ontology_runner.py validate|load|query|sync ...", file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    base, cwd = cli_base()
    if cmd == "validate":
        if len(rest) != 1:
            print("validate <ttl>", file=sys.stderr)
            return 2
        return run(base + ["validate", rest[0]], cwd)
    if cmd == "load":
        if len(rest) != 1:
            print("load <ttl>", file=sys.stderr)
            return 2
        rc = run(base + ["load", rest[0]], cwd)
        if rc != 0:
            return rc
        rc = run(base + ["sync", "--ttl", rest[0]], cwd)
        if rc != 0:
            print("mm_ontology_runner: sync after load failed", file=sys.stderr)
            return rc
        return 0
    if cmd == "query":
        if not rest:
            print("query <meeting-iri-or-sparql>", file=sys.stderr)
            return 2
        target = rest[0]
        if looks_like_sparql(target):
            return run(base + ["query", target, *rest[1:]], cwd)
        rc = run(base + ["who", target], cwd)
        if rc != 0:
            return rc
        note = instance_path(cwd, target)
        if not note.is_file():
            print("mm_ontology_runner: instance note missing after query", note, file=sys.stderr)
            return 4
        return 0
    if cmd == "sync":
        return run(base + ["sync", *rest], cwd)
    return run(base + argv, cwd)


if __name__ == "__main__":
    raise SystemExit(main())
