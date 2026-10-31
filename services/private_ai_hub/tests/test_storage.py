from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from private_ai_hub.storage import connect, current_version, initialize, is_ready, target_version


class StorageTests(unittest.TestCase):
    def test_migration_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            self.assertEqual(initialize(path), target_version())
            self.assertEqual(initialize(path), target_version())
            self.assertTrue(is_ready(path))
            with connect(path) as connection:
                self.assertEqual(current_version(connection), target_version())
                rows = connection.execute(
                    "SELECT COUNT(*) FROM schema_migrations"
                ).fetchone()[0]
                self.assertEqual(rows, target_version())


if __name__ == "__main__":
    unittest.main()
