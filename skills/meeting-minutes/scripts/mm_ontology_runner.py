"""Adapter: mm_run's ontology-runner contract onto the vault's Oxigraph CLI.

mm_run calls `<runner> validate <ttl>`, `<runner> load <ttl>`, and
`<runner> query <iri>`, and requires a JSON object on stdout with an integer
`count` on the query response. The vault CLI has all three subcommands but its
`query` takes SPARQL, not an IRI. Only that translation happens here; validate
and load pass straight through, so the vault CLI stays the single
implementation rather than being partly reimplemented.

The CLI to drive is read from MM_ONTOLOGY_CLI, supplied through the skill's
`ontology.runner_env` config, so no machine path is hardcoded here.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys

PASSTHROUGH = ("validate", "load")


def build_query(iri: str) -> str:
    """Every triple whose subject is the meeting; the row count is the triple count."""
    return f"SELECT ?p ?o WHERE {{ <{iri}> ?p ?o }}"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: mm_ontology_runner.py {validate|load|query} <ttl-path|iri>",
              file=sys.stderr)
        return 2
    action, target = argv
    cli = os.environ.get("MM_ONTOLOGY_CLI")
    if not cli:
        print("MM_ONTOLOGY_CLI is unset - set it in ontology.runner_env", file=sys.stderr)
        return 2

    if action in PASSTHROUGH:
        args = [action, target]
    elif action == "query":
        args = ["query", build_query(target)]
    else:
        print(f"unsupported action {action!r}", file=sys.stderr)
        return 2

    proc = subprocess.run([*shlex.split(cli), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
