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
        self.assertEqual(config.auth.session_ttl_seconds, 43200)
        self.assertEqual(config.auth.login_attempts_per_minute, 10)
        self.assertEqual(config.network.profile, "offline")
        self.assertTrue(config.audit.security_enabled)
        self.assertFalse(config.audit.conversation_enabled)
        self.assertFalse(config.audit.store_prompt_content)
        self.assertFalse(config.audit.store_response_content)
        self.assertEqual(config.audit.retention_days, 180)

    def test_toml_and_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                '[server]\nhost = "0.0.0.0"\nport = 9000\n'
                'request_timeout_seconds = 20\nmax_connections = 32\n'
                '[storage]\nsqlite_path = "./state.db"\n'
                '[auth]\nsession_ttl_seconds = 7200\n'
                'login_attempts_per_minute = 20\n'
                '[audit]\nsecurity_enabled = true\n'
                'conversation_enabled = true\n'
                'store_prompt_content = true\n'
                'store_response_content = false\n'
                'retention_days = 90\n'
                'max_metadata_bytes = 32768\n'
                'max_content_bytes = 2097152\n',
                encoding="utf-8",
            )
            config = load_config(
                path,
                env={
                    "PRIVATE_AI_PORT": "9100",
                    "PRIVATE_AI_MAX_CONNECTIONS": "48",
                    "PRIVATE_AI_SQLITE_PATH": "./override.db",
                    "PRIVATE_AI_LOGIN_ATTEMPTS_PER_MINUTE": "25",
                    "PRIVATE_AI_NETWORK_PROFILE": "offline",
                    "PRIVATE_AI_AUDIT_CONVERSATION_ENABLED": "false",
                    "PRIVATE_AI_AUDIT_RETENTION_DAYS": "30",
                },
            )
            self.assertEqual(config.server.host, "0.0.0.0")
            self.assertEqual(config.server.port, 9100)
            self.assertEqual(config.server.request_timeout_seconds, 20)
            self.assertEqual(config.server.max_connections, 48)
            self.assertEqual(config.storage.sqlite_path, Path("./override.db"))
            self.assertEqual(config.auth.session_ttl_seconds, 7200)
            self.assertEqual(config.auth.login_attempts_per_minute, 25)
            self.assertEqual(config.network.profile, "offline")
            self.assertTrue(config.audit.security_enabled)
            self.assertFalse(config.audit.conversation_enabled)
            self.assertTrue(config.audit.store_prompt_content)
            self.assertFalse(config.audit.store_response_content)
            self.assertEqual(config.audit.retention_days, 30)
            self.assertEqual(config.audit.max_metadata_bytes, 32768)
            self.assertEqual(config.audit.max_content_bytes, 2097152)

    def test_rejects_invalid_port(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(env={"PRIVATE_AI_PORT": "70000"})

    def test_rejects_fractional_toml_port(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[server]\nport = 8787.5\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path, env={})

    def test_rejects_invalid_auth_limits(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(env={"PRIVATE_AI_SESSION_TTL_SECONDS": "10"})
        with self.assertRaises(ConfigError):
            load_config(env={"PRIVATE_AI_LOGIN_ATTEMPTS_PER_MINUTE": "0"})

    def test_rejects_invalid_network_profile(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(env={"PRIVATE_AI_NETWORK_PROFILE": "open-internet"})

    def test_rejects_invalid_audit_settings(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(env={"PRIVATE_AI_AUDIT_SECURITY_ENABLED": "maybe"})
        with self.assertRaises(ConfigError):
            load_config(env={"PRIVATE_AI_AUDIT_RETENTION_DAYS": "5000"})
        with self.assertRaises(ConfigError):
            load_config(env={"PRIVATE_AI_AUDIT_MAX_METADATA_BYTES": "1"})

    def test_unreadable_config_path_is_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigError):
                load_config(Path(directory), env={})


if __name__ == "__main__":
    unittest.main()
