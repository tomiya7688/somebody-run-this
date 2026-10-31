from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from private_ai_hub.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_safe_defaults(self) -> None:
        config = load_config(env={})
        self.assertEqual(config.server.host, "127.0.0.1")
        self.assertEqual(config.server.port, 8787)
        self.assertEqual(config.server.request_timeout_seconds, 10)
        self.assertEqual(config.server.max_connections, 64)
        self.assertEqual(config.storage.sqlite_path, Path("./data/private_ai_hub.sqlite3"))

    def test_toml_and_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                '[server]\nhost = "0.0.0.0"\nport = 9000\n'
                'request_timeout_seconds = 20\nmax_connections = 32\n'
                '[storage]\nsqlite_path = "./state.db"\n',
                encoding="utf-8",
            )
            config = load_config(
                path,
                env={
                    "PRIVATE_AI_PORT": "9100",
                    "PRIVATE_AI_MAX_CONNECTIONS": "48",
                    "PRIVATE_AI_SQLITE_PATH": "./override.db",
                },
            )
            self.assertEqual(config.server.host, "0.0.0.0")
            self.assertEqual(config.server.port, 9100)
            self.assertEqual(config.server.request_timeout_seconds, 20)
            self.assertEqual(config.server.max_connections, 48)
            self.assertEqual(config.storage.sqlite_path, Path("./override.db"))

    def test_rejects_invalid_port(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(env={"PRIVATE_AI_PORT": "70000"})

    def test_rejects_fractional_toml_port(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[server]\nport = 8787.5\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path, env={})

    def test_unreadable_config_path_is_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigError):
                load_config(Path(directory), env={})


if __name__ == "__main__":
    unittest.main()
