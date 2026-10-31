from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from private_ai_hub.storage import connect, current_version, initialize, is_ready, migrate, target_version


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

    def test_readiness_does_not_create_missing_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing" / "state.sqlite3"
            self.assertFalse(is_ready(path))
            self.assertFalse(path.exists())
            self.assertFalse(path.parent.exists())

    def test_failed_migration_rolls_back_schema_changes(self) -> None:
        migrations = (
            (
                1,
                """
                CREATE TABLE atomic_test(id INTEGER PRIMARY KEY);
                THIS IS NOT VALID SQL;
                """,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with connect(path) as connection:
                with self.assertRaises(sqlite3.Error):
                    migrate(connection, migrations)
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='atomic_test'"
                ).fetchone()
                self.assertIsNone(exists)

    def test_concurrent_initialization_is_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            errors: list[BaseException] = []

            def run_initialize() -> None:
                try:
                    initialize(path)
                except BaseException as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=run_initialize) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

            self.assertEqual(errors, [])
            self.assertTrue(is_ready(path))

    def test_corrupt_database_returns_not_ready_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            path.write_bytes(b"not a sqlite database")
            with self.assertLogs("private_ai_hub.storage", level="WARNING"):
                self.assertFalse(is_ready(path))


if __name__ == "__main__":
    unittest.main()
