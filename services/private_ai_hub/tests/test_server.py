from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request

from private_ai_hub.server import build_server
from private_ai_hub.storage import initialize


class ServerTests(unittest.TestCase):
    def test_health_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage_path = Path(directory) / "state.sqlite3"
            initialize(storage_path)
            server = build_server("127.0.0.1", 0, storage_path)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/healthz", timeout=2
                ) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response), {"status": "ok"})
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/readyz", timeout=2
                ) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response), {"status": "ready"})
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
