from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from demo_dashboard import (  # noqa: E402
    ACTIVE_ID,
    ARCHIVED_ID,
    COLD_ID,
    QUARANTINE_ID,
    create_demo_fixture,
)
from lib.core import scan_catalog  # noqa: E402


class DemoDashboardTests(unittest.TestCase):
    def test_demo_fixture_scans_without_real_user_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fixture = create_demo_fixture(Path(temp))
            catalog = scan_catalog(
                fixture["codex_home"],
                fixture["app_dir"],
                fixture["pinned_file"],
            )

        states = {item["id"]: item["actual_state"] for item in catalog["sessions"]}
        self.assertEqual("active", states[ACTIVE_ID])
        self.assertEqual("archived", states[ARCHIVED_ID])
        self.assertEqual("cold", states[COLD_ID])
        self.assertEqual("quarantine", states[QUARANTINE_ID])
        self.assertEqual("cold_archive", next(item for item in catalog["sessions"] if item["id"] == ARCHIVED_ID)["planned_action"])
        flattened = str(catalog)
        self.assertNotIn("/Users/wushijing", flattened)
        self.assertNotIn("吴大咪", flattened)


if __name__ == "__main__":
    unittest.main()
