"""Adapter tests: mm_run's ontology-runner contract onto the vault Oxigraph CLI.

Hermetic on purpose -- these drive a fake CLI in tmp_path and never open the
real 149 MB Oxigraph store.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
ADAPTER = SCRIPTS / "mm_ontology_runner.py"

FAKE_CLI = '''\
import json, sys
print(json.dumps({"argv": sys.argv[1:], "rows": [{"p": "x"}], "count": 1}))
'''


def _run(tmp_path, *args):
    fake = tmp_path / "fake_cli.py"
    fake.write_text(FAKE_CLI, encoding="utf-8")
    env = {**os.environ, "MM_ONTOLOGY_CLI": f'"{sys.executable}" "{fake}"'}
    proc = subprocess.run([sys.executable, "-X", "utf8", str(ADAPTER), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)
    return proc.returncode, proc.stdout


def test_validate_passes_the_ttl_path_through(tmp_path):
    ttl = tmp_path / "meeting.ttl"
    code, out = _run(tmp_path, "validate", str(ttl))
    assert code == 0
    assert json.loads(out)["argv"] == ["validate", str(ttl)]


def test_load_passes_the_ttl_path_through(tmp_path):
    ttl = tmp_path / "meeting.ttl"
    code, out = _run(tmp_path, "load", str(ttl))
    assert code == 0
    assert json.loads(out)["argv"] == ["load", str(ttl)]


def test_query_translates_an_iri_into_sparql_and_keeps_the_count(tmp_path):
    iri = "https://v.example/meeting/2026-08-24"
    code, out = _run(tmp_path, "query", iri)
    assert code == 0
    payload = json.loads(out)
    assert payload["argv"][0] == "query"
    sparql = payload["argv"][1]
    assert f"<{iri}>" in sparql, "the IRI must be substituted into the SPARQL"
    assert sparql.upper().lstrip().startswith("SELECT")
    assert payload["count"] == 1, "mm_run reads `count` and requires >= 1"


def test_an_unknown_subcommand_fails_loudly(tmp_path):
    code, _ = _run(tmp_path, "delete-everything", "x")
    assert code != 0, "the adapter must not forward subcommands mm_run never asks for"


def test_a_missing_cli_env_var_fails_loudly(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "MM_ONTOLOGY_CLI"}
    proc = subprocess.run([sys.executable, "-X", "utf8", str(ADAPTER), "validate", "x.ttl"],
                          capture_output=True, text=True, encoding="utf-8", env=env)
    assert proc.returncode != 0, "an unset MM_ONTOLOGY_CLI must not be silently ignored"
