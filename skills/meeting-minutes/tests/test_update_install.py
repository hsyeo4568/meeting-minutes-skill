"""Updating an existing install must never cost the user their setup.

Team members installed 1.0.0 and then spent an interview filling in
`config.yaml` and `profiles/<team>/`. A recursive copy over the top would
restore the shipped placeholders and silently undo that, which is worse for
them than staying on the old version. So the update is a script, not prose an
agent has to remember: engine files are replaced, everything the user authored
is out of its reach, and nothing is written at all without --apply.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "update_install.py"

ENGINE = {
    "SKILL.md": "engine v2\n",
    "config.example.yaml": "categories:\n  daily: {vault: true, body_mode: chronological}\nmaterials: {}\n",
    "references/engine/writing-principles.md": "rules v2\n",
    "scripts/mm_run.py": "print('v2')\n",
    "profiles/_template/structure.md": "template v2\n",
    "profiles/example-acme/structure.md": "acme v2\n",
}


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _source(root: Path) -> Path:
    src = root / "clone"
    for rel, text in ENGINE.items():
        _write(src, rel, text)
    return src


def _install(root: Path) -> Path:
    """An install as a team member would have it: v1 engine + their own data."""
    dst = root / "installed"
    for rel in ENGINE:
        _write(dst, rel, "v1\n")
    _write(dst, "config.yaml", "identity: {me: 홍길동}\ncategories:\n  daily: {vault: true}\n")
    _write(dst, "profiles/team-x/domain-glossary.md", "우리 팀 용어\n")
    _write(dst, "profiles/team-x/contacts.md", "실명 연락처\n")
    _write(dst, "verify-denylist.local", "우리회사\n")
    _write(dst, ".mm/run.json", "{}\n")
    return dst


def _run(src: Path, dst: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--source", str(src),
                           "--target", str(dst), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


class UserDataSurvives(unittest.TestCase):
    def test_config_yaml_is_never_touched(self):
        with TemporaryDirectory() as td:
            src, dst = _source(Path(td)), _install(Path(td))
            _run(src, dst, "--apply")
            self.assertIn("홍길동", (dst / "config.yaml").read_text(encoding="utf-8"))

    def test_the_users_own_profile_is_never_touched(self):
        with TemporaryDirectory() as td:
            src, dst = _source(Path(td)), _install(Path(td))
            _run(src, dst, "--apply")
            self.assertEqual((dst / "profiles/team-x/domain-glossary.md").read_text(encoding="utf-8"),
                             "우리 팀 용어\n")
            self.assertTrue((dst / "profiles/team-x/contacts.md").exists())

    def test_local_denylist_and_run_state_survive(self):
        with TemporaryDirectory() as td:
            src, dst = _source(Path(td)), _install(Path(td))
            _run(src, dst, "--apply")
            self.assertTrue((dst / "verify-denylist.local").exists())
            self.assertTrue((dst / ".mm/run.json").exists())

    def test_a_backup_is_taken_before_anything_changes(self):
        with TemporaryDirectory() as td:
            src, dst = _source(Path(td)), _install(Path(td))
            _run(src, dst, "--apply")
            backups = list(dst.parent.glob(dst.name + ".backup.*"))
            self.assertEqual(len(backups), 1)
            self.assertIn("홍길동", (backups[0] / "config.yaml").read_text(encoding="utf-8"))


class EngineIsReplaced(unittest.TestCase):
    def test_engine_files_move_to_the_new_version(self):
        with TemporaryDirectory() as td:
            src, dst = _source(Path(td)), _install(Path(td))
            _run(src, dst, "--apply")
            self.assertEqual((dst / "SKILL.md").read_text(encoding="utf-8"), "engine v2\n")
            self.assertEqual((dst / "references/engine/writing-principles.md").read_text(encoding="utf-8"),
                             "rules v2\n")

    def test_shipped_example_profiles_are_refreshed(self):
        with TemporaryDirectory() as td:
            src, dst = _source(Path(td)), _install(Path(td))
            _run(src, dst, "--apply")
            self.assertEqual((dst / "profiles/_template/structure.md").read_text(encoding="utf-8"),
                             "template v2\n")
            self.assertEqual((dst / "profiles/example-acme/structure.md").read_text(encoding="utf-8"),
                             "acme v2\n")

    def test_an_engine_file_dropped_upstream_is_removed_here_too(self):
        with TemporaryDirectory() as td:
            src, dst = _source(Path(td)), _install(Path(td))
            _write(dst, "references/engine/retired.md", "old rules\n")
            _run(src, dst, "--apply")
            self.assertFalse((dst / "references/engine/retired.md").exists())


class SafeByDefault(unittest.TestCase):
    def test_without_apply_nothing_is_written(self):
        with TemporaryDirectory() as td:
            src, dst = _source(Path(td)), _install(Path(td))
            r = _run(src, dst)
            self.assertEqual((dst / "SKILL.md").read_text(encoding="utf-8"), "v1\n")
            self.assertEqual(list(dst.parent.glob(dst.name + ".backup.*")), [])
            self.assertIn("SKILL.md", r.stdout)

    def test_a_target_that_is_not_an_install_is_refused(self):
        with TemporaryDirectory() as td:
            src = _source(Path(td))
            empty = Path(td) / "somewhere-else"
            empty.mkdir()
            r = _run(src, empty, "--apply")
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(list(empty.iterdir()), [])

    def test_new_config_keys_are_reported_so_the_user_can_opt_in(self):
        """body_mode/materials arrived in 1.1.0; an untouched config.yaml keeps
        working, but the user has to be told the keys exist."""
        with TemporaryDirectory() as td:
            src, dst = _source(Path(td)), _install(Path(td))
            r = _run(src, dst, "--apply")
            self.assertIn("body_mode", r.stdout)
            self.assertIn("materials", r.stdout)


if __name__ == "__main__":
    unittest.main()
