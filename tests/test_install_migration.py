from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import doctor  # noqa: E402
import install_skill  # noqa: E402


class InstallerMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "home"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_source(self, name: str) -> Path:
        source = self.home / ".agents" / "skills" / name
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: test\n---\n",
            encoding="utf-8",
        )
        return source

    def args(self, source: Path, **overrides: object) -> SimpleNamespace:
        values: dict[str, object] = {
            "source": source,
            "home": self.home,
            "targets": ["codex"],
            "dry_run": False,
            "verify": False,
            "migrate_legacy": False,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_command_line_defaults_to_codex_only(self) -> None:
        self.assertEqual(["codex"], install_skill.build_parser().parse_args([]).targets)

    def test_default_install_creates_only_the_codex_entry(self) -> None:
        source = self.make_source(install_skill.SKILL_NAME)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, install_skill.run(self.args(source)))

        codex = self.home / install_skill.TARGET_DIRS["codex"] / install_skill.SKILL_NAME
        self.assertTrue(codex.is_symlink())
        for name in ("claude", "antigravity", "workbuddy"):
            target = self.home / install_skill.TARGET_DIRS[name] / install_skill.SKILL_NAME
            self.assertFalse(os.path.lexists(target))

    def test_legacy_migration_preserves_existing_agent_selection(self) -> None:
        legacy_name = install_skill.LEGACY_SKILL_NAMES[0]
        source = self.make_source(legacy_name)
        for name in ("codex", "claude"):
            target = self.home / install_skill.TARGET_DIRS[name] / legacy_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source, target_is_directory=True)

        unrelated = self.home / install_skill.TARGET_DIRS["antigravity"] / legacy_name
        unrelated.mkdir(parents=True)
        (unrelated / "user-file.txt").write_text("preserve", encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            result = install_skill.run(
                self.args(source, migrate_legacy=True)
            )
        self.assertEqual(0, result)

        canonical = install_skill.canonical_source(self.home)
        self.assertTrue(canonical.is_dir())
        self.assertFalse(os.path.lexists(source))
        for name in ("codex", "claude"):
            old_target = self.home / install_skill.TARGET_DIRS[name] / legacy_name
            new_target = self.home / install_skill.TARGET_DIRS[name] / install_skill.SKILL_NAME
            self.assertFalse(os.path.lexists(old_target))
            self.assertTrue(new_target.is_symlink())
            self.assertEqual(canonical.resolve(), new_target.resolve(strict=True))
        self.assertEqual(
            "preserve",
            (unrelated / "user-file.txt").read_text(encoding="utf-8"),
        )

    def test_legacy_migration_dry_run_changes_nothing(self) -> None:
        legacy_name = install_skill.LEGACY_SKILL_NAMES[0]
        source = self.make_source(legacy_name)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(
                0,
                install_skill.run(
                    self.args(source, migrate_legacy=True, dry_run=True)
                ),
            )
        self.assertIn("MIGRATE", output.getvalue())
        self.assertTrue(source.is_dir())
        self.assertFalse(os.path.lexists(install_skill.canonical_source(self.home)))

    def test_migration_refuses_to_overwrite_a_new_source(self) -> None:
        legacy_name = install_skill.LEGACY_SKILL_NAMES[0]
        source = self.make_source(legacy_name)
        canonical = self.make_source(install_skill.SKILL_NAME)

        with self.assertRaisesRegex(ValueError, "migration_target_exists"):
            install_skill.run(self.args(source, migrate_legacy=True))
        self.assertTrue(source.is_dir())
        self.assertTrue(canonical.is_dir())

    def test_migration_refuses_to_overwrite_an_agent_entry(self) -> None:
        legacy_name = install_skill.LEGACY_SKILL_NAMES[0]
        source = self.make_source(legacy_name)
        old_target = self.home / install_skill.TARGET_DIRS["codex"] / legacy_name
        old_target.parent.mkdir(parents=True, exist_ok=True)
        old_target.symlink_to(source, target_is_directory=True)
        conflict = old_target.with_name(install_skill.SKILL_NAME)
        conflict.mkdir()
        (conflict / "user-file.txt").write_text("preserve", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "migration_entry_conflict"):
            install_skill.run(self.args(source, migrate_legacy=True))
        self.assertTrue(source.is_dir())
        self.assertTrue(old_target.is_symlink())
        self.assertEqual(
            "preserve",
            (conflict / "user-file.txt").read_text(encoding="utf-8"),
        )

    def test_doctor_treats_non_codex_entries_as_optional(self) -> None:
        source = self.make_source(install_skill.SKILL_NAME)
        codex = self.home / install_skill.TARGET_DIRS["codex"] / install_skill.SKILL_NAME
        codex.parent.mkdir(parents=True, exist_ok=True)
        codex.symlink_to(source, target_is_directory=True)

        with mock.patch.object(doctor, "ROOT", source):
            checks = doctor.installation_checks(self.home)
        self.assertFalse([check for check in checks if check.level == "fail"])
        optional = [
            check
            for check in checks
            if check.name.startswith("entry:") and "optional entry not installed" in check.detail
        ]
        self.assertEqual(3, len(optional))


if __name__ == "__main__":
    unittest.main()
