from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest

from private_ai_hub.inference import ChatMessage, ChatRequest
from private_ai_hub.vllm_backend import (
    OpenAICompatibleUnixClient,
    REVIEWED_VLLM_VERSION,
    RuntimeSecurityError,
    RuntimeVersionError,
    VllmBackendConfig,
    _resolved_model_path,
    build_runtime_environment,
    build_vllm_command,
    parse_vllm_version,
    require_reviewed_vllm_version,
)


class UnixScriptedServer:
    def __init__(self, socket_path: Path, responses: list[bytes]) -> None:
        self.socket_path = socket_path
        self.responses = deque(responses)
        self.requests: list[bytes] = []
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(socket_path))
        self._server.listen(8)
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.close()
        self._thread.join(timeout=2)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

    def _run(self) -> None:
        while self.responses:
            try:
                connection, _address = self._server.accept()
            except OSError:
                return
            with connection:
                request = b""
                header_end = -1
                content_length = 0
                while True:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    request += chunk
                    if header_end < 0:
                        header_end = request.find(b"\r\n\r\n")
                        if header_end >= 0:
                            headers = request[:header_end].decode(
                                "latin-1",
                                errors="replace",
                            )
                            for line in headers.split("\r\n")[1:]:
                                name, separator, value = line.partition(":")
                                if separator and name.casefold() == "content-length":
                                    content_length = int(value.strip(), 10)
                    if header_end >= 0:
                        body_bytes = len(request) - (header_end + 4)
                        if body_bytes >= content_length:
                            break
                self.requests.append(request)
                connection.sendall(self.responses.popleft())


def http_response(
    payload: object,
    *,
    status: str = "200 OK",
    content_type: str = "application/json",
) -> bytes:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body


def sse_response(lines: list[bytes]) -> bytes:
    body = b"".join(lines)
    return (
        f"HTTP/1.1 200 OK\r\n"
        "Content-Type: text/event-stream\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body


class VllmSecurityTests(unittest.TestCase):
    def test_reviewed_version_is_exactly_pinned(self) -> None:
        self.assertEqual(
            parse_vllm_version("vLLM 0.33.0"),
            REVIEWED_VLLM_VERSION,
        )
        self.assertEqual(
            require_reviewed_vllm_version("vllm 0.33.0"),
            "0.33.0",
        )
        for output in ("vllm 0.32.0", "vllm 0.34.0", "unknown"):
            with self.subTest(output=output):
                with self.assertRaises(RuntimeVersionError):
                    require_reviewed_vllm_version(output)

    def test_model_path_must_resolve_inside_model_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "models"
            root.mkdir()
            model = root / "approved"
            model.mkdir()
            _root, resolved = _resolved_model_path(root, model)
            self.assertEqual(resolved, model.resolve())

            outside = Path(directory) / "outside"
            outside.mkdir()
            escape = root / "escape"
            escape.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(RuntimeSecurityError):
                _resolved_model_path(root, escape)

    def test_runtime_environment_drops_proxy_tokens_and_python_injection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_home = Path(directory)
            environment = build_runtime_environment(
                base_environment={
                    "PATH": "/usr/bin",
                    "LD_LIBRARY_PATH": "/opt/cuda/lib",
                    "HTTP_PROXY": "http://proxy.example",
                    "HTTPS_PROXY": "http://proxy.example",
                    "HF_TOKEN": "secret",
                    "OPENAI_API_KEY": "secret",
                    "PYTHONPATH": "/tmp/inject",
                    "LD_PRELOAD": "/tmp/inject.so",
                    "CUDA_VISIBLE_DEVICES": "0",
                },
                runtime_home=runtime_home,
            )
            self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
            self.assertEqual(environment["TRANSFORMERS_OFFLINE"], "1")
            self.assertEqual(environment["VLLM_SERVER_DEV_MODE"], "0")
            self.assertEqual(environment["VLLM_PLUGINS"], "")
            self.assertEqual(environment["VLLM_MAX_N_SEQUENCES"], "1")
            self.assertEqual(environment["CUDA_VISIBLE_DEVICES"], "0")
            for key in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "HF_TOKEN",
                "OPENAI_API_KEY",
                "PYTHONPATH",
                "LD_PRELOAD",
            ):
                self.assertNotIn(key, environment)

    def test_command_uses_uds_text_only_no_remote_code_and_no_host_port(self) -> None:
        config = VllmBackendConfig(
            executable=Path("/opt/private-ai/vllm/bin/vllm"),
            model_store_root=Path("/var/lib/private-ai/models"),
            model_path=Path("/var/lib/private-ai/models/qwen"),
            model_id="qwen",
            runtime_dir=Path("/run/private-ai/qwen"),
            max_num_seqs=4,
            max_num_queued_requests=8,
        )
        command = build_vllm_command(
            config,
            executable=config.executable,
            model_path=config.model_path,
            socket_path=config.runtime_dir / "vllm.sock",
        )
        joined = " ".join(command)
        self.assertIn("--net --", joined)
        self.assertIn("--uds", command)
        self.assertIn("--no-trust-remote-code", command)
        self.assertIn("--language-model-only", command)
        self.assertIn("--disable-log-requests", command)
        self.assertIn("--disable-uvicorn-access-log", command)
        self.assertNotIn("--host", command)
        self.assertNotIn("--port", command)

    def test_unix_client_chat_and_model_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vllm.sock"
            server = UnixScriptedServer(
                path,
                [
                    http_response(
                        {
                            "data": [
                                {"id": "qwen"},
                            ]
                        }
                    ),
                    http_response(
                        {
                            "choices": [
                                {
                                    "message": {"content": "hello back"},
                                    "finish_reason": "stop",
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 3,
                                "completion_tokens": 2,
                                "total_tokens": 5,
                            },
                        }
                    ),
                ],
            )
            server.start()
            try:
                client = OpenAICompatibleUnixClient(path, timeout_seconds=2)
                self.assertEqual(client.models(), frozenset({"qwen"}))
                result = client.chat(
                    ChatRequest(
                        model_id="qwen",
                        messages=(ChatMessage(role="user", content="hello"),),
                    )
                )
                self.assertEqual(result.content, "hello back")
                self.assertEqual(result.usage.total_tokens, 5)
                self.assertIn(
                    b"POST /v1/chat/completions HTTP/1.1",
                    server.requests[1],
                )
                self.assertNotIn(b"http://", server.requests[1])
            finally:
                server.close()

    def test_unix_client_streaming_is_bounded_text_only(self) -> None:
        first = {
            "choices": [
                {
                    "delta": {"content": "hello "},
                    "finish_reason": None,
                }
            ]
        }
        second = {
            "choices": [
                {
                    "delta": {"content": "world"},
                    "finish_reason": "stop",
                }
            ]
        }
        usage = {
            "choices": [],
            "usage": {
                "prompt_tokens": 2,
                "completion_tokens": 2,
                "total_tokens": 4,
            },
        }
        body = [
            b"data: " + json.dumps(first).encode() + b"\n\n",
            b"data: " + json.dumps(second).encode() + b"\n\n",
            b"data: " + json.dumps(usage).encode() + b"\n\n",
            b"data: [DONE]\n\n",
        ]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vllm.sock"
            server = UnixScriptedServer(path, [sse_response(body)])
            server.start()
            try:
                client = OpenAICompatibleUnixClient(path, timeout_seconds=2)
                deltas = tuple(
                    client.stream_chat(
                        ChatRequest(
                            model_id="qwen",
                            messages=(
                                ChatMessage(role="user", content="hello"),
                            ),
                        )
                    )
                )
                self.assertEqual(
                    "".join(delta.content for delta in deltas),
                    "hello world",
                )
                self.assertEqual(deltas[-2].finish_reason, "stop")
                self.assertEqual(deltas[-1].usage.total_tokens, 4)
            finally:
                server.close()


if __name__ == "__main__":
    unittest.main()
