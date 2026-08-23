from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import package_release  # noqa: E402


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_contains_license_and_public_guides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = package_release.build_archive(Path(temporary))
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())

        prefix = f"{package_release.SKILL_NAME}/"
        for relative in (
            "SKILL.md",
            "LICENSE",
            "README.md",
            "README.en.md",
            "SECURITY.md",
            "SECURITY.en.md",
            "docs/INSTALLATION.md",
            "docs/INSTALLATION.en.md",
        ):
            self.assertIn(f"{prefix}{relative}", names)
        self.assertFalse(any(name.startswith(f"{prefix}tests/") for name in names))
        self.assertFalse(any("/.git/" in name or "/dist/" in name for name in names))

    def test_release_archive_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_archive = package_release.build_archive(Path(first))
            second_archive = package_release.build_archive(Path(second))
            first_hash = hashlib.sha256(first_archive.read_bytes()).hexdigest()
            second_hash = hashlib.sha256(second_archive.read_bytes()).hexdigest()
        self.assertEqual(first_hash, second_hash)


if __name__ == "__main__":
    unittest.main()
