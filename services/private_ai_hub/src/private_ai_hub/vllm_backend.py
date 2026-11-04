from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import logging
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import sys
import time
from typing import Iterator, Mapping

from .inference import (
    BackendState,
    BackendUnavailable,
    ChatRequest,
    ChatResult,
    HealthReport,
    InferenceCapabilities,
    InferenceError,
    StreamDelta,
    TokenUsage,
)


logger = logging.getLogger(__name__)

REVIEWED_VLLM_VERSION = "0.33.0"
_VERSION_PATTERN = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

_SAFE_ENV_KEYS = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "LD_LIBRARY_PATH",
        "CUDA_VISIBLE_DEVICES",
        "NVIDIA_VISIBLE_DEVICES",
        "ROCR_VISIBLE_DEVICES",
        "HIP_VISIBLE_DEVICES",
        "HSA_OVERRIDE_GFX_VERSION",
    }
)

_MAX_JSON_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_SSE_LINE_BYTES = 256 * 1024


class RuntimeSecurityError(InferenceError):
    """Raised when a runtime violates the reviewed security envelope."""


class RuntimeVersionError(RuntimeSecurityError):
    """Raised when the installed vLLM version is not the reviewed version."""


class RuntimeStartError(InferenceError):
    """Raised when a worker cannot start safely."""


@dataclass(frozen=True)
class VllmBackendConfig:
    executable: Path
    model_store_root: Path
    model_path: Path
    model_id: str
    runtime_dir: Path
    isolation_prefix: tuple[str, ...] = (
        "/usr/bin/unshare",
        "--net",
        "--",
    )
    startup_timeout_seconds: int = 180
    shutdown_timeout_seconds: int = 15
    max_num_seqs: int = 8
    max_num_queued_requests: int = 16
    max_model_len: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.executable, Path):
            object.__setattr__(self, "executable", Path(self.executable))
        if not isinstance(self.model_store_root, Path):
            object.__setattr__(
                self,
                "model_store_root",
                Path(self.model_store_root),
            )
        if not isinstance(self.model_path, Path):
            object.__setattr__(self, "model_path", Path(self.model_path))
        if not isinstance(self.runtime_dir, Path):
            object.__setattr__(self, "runtime_dir", Path(self.runtime_dir))

        if not isinstance(self.model_id, str) or not _MODEL_ID_PATTERN.fullmatch(
            self.model_id
        ):
            raise ValueError("model_id contains unsupported characters")

        for name, value, minimum, maximum in (
            ("startup_timeout_seconds", self.startup_timeout_seconds, 1, 1800),
            ("shutdown_timeout_seconds", self.shutdown_timeout_seconds, 1, 300),
            ("max_num_seqs", self.max_num_seqs, 1, 1024),
            (
                "max_num_queued_requests",
                self.max_num_queued_requests,
                0,
                65536,
            ),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if not minimum <= value <= maximum:
                raise ValueError(
                    f"{name} must be between {minimum} and {maximum}"
                )

        if self.max_model_len is not None:
            if (
                isinstance(self.max_model_len, bool)
                or not isinstance(self.max_model_len, int)
                or not 128 <= self.max_model_len <= 1_048_576
            ):
                raise ValueError(
                    "max_model_len must be between 128 and 1048576"
                )

        if not isinstance(self.isolation_prefix, tuple) or not self.isolation_prefix:
            raise ValueError(
                "isolation_prefix is required; refusing an unisolated worker"
            )
        if any(
            not isinstance(part, str) or not part
            for part in self.isolation_prefix
        ):
            raise ValueError("isolation_prefix entries must be non-empty strings")


@dataclass(frozen=True)
class RuntimeInspection:
    version: str
    executable: Path


def parse_vllm_version(output: str) -> str:
    if not isinstance(output, str):
        raise RuntimeVersionError("vLLM version output must be text")
    match = _VERSION_PATTERN.search(output)
    if match is None:
        raise RuntimeVersionError("could not parse vLLM version")
    return ".".join(match.groups())


def require_reviewed_vllm_version(output: str) -> str:
    version = parse_vllm_version(output)
    if version != REVIEWED_VLLM_VERSION:
        raise RuntimeVersionError(
            f"vLLM {version} is not the reviewed runtime "
            f"{REVIEWED_VLLM_VERSION}; review security before changing it"
        )
    return version


def _resolved_regular_executable(path: Path) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise RuntimeSecurityError(
            f"vLLM executable does not exist: {path}"
        ) from exc
    if not resolved.is_file():
        raise RuntimeSecurityError("vLLM executable must be a regular file")
    if not os.access(resolved, os.X_OK):
        raise RuntimeSecurityError("vLLM executable is not executable")
    return resolved


def _resolved_model_path(root: Path, model_path: Path) -> tuple[Path, Path]:
    try:
        resolved_root = root.expanduser().resolve(strict=True)
        resolved_model = model_path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise RuntimeSecurityError("model store or model path is unavailable") from exc
    if not resolved_root.is_dir():
        raise RuntimeSecurityError("model store root must be a directory")
    if not resolved_model.is_dir():
        raise RuntimeSecurityError("model path must be a directory")
    try:
        resolved_model.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeSecurityError(
            "model path escapes the configured model store"
        ) from exc
    return resolved_root, resolved_model


def _prepare_private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    resolved = path.resolve(strict=True)
    info = os.lstat(resolved)
    if not stat.S_ISDIR(info.st_mode):
        raise RuntimeSecurityError("runtime path must be a directory")
    if stat.S_IMODE(info.st_mode) & 0o077:
        os.chmod(resolved, 0o700)
    if stat.S_IMODE(os.stat(resolved).st_mode) & 0o077:
        raise RuntimeSecurityError("runtime directory is not private")
    return resolved


def _socket_path(runtime_dir: Path) -> Path:
    path = runtime_dir / "vllm.sock"
    if len(os.fsencode(path)) > 100:
        raise RuntimeSecurityError("Unix socket path is too long")
    if path.exists() or path.is_symlink():
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            raise RuntimeSecurityError("refusing a symlink at the Unix socket path")
        if not stat.S_ISSOCK(info.st_mode):
            raise RuntimeSecurityError(
                "refusing to replace a non-socket runtime path"
            )
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise RuntimeSecurityError(
                "refusing to remove a socket owned by another user"
            )
        path.unlink()
    return path


def build_runtime_environment(
    *,
    base_environment: Mapping[str, str],
    runtime_home: Path,
) -> dict[str, str]:
    environment = {
        key: value
        for key, value in base_environment.items()
        if key in _SAFE_ENV_KEYS and isinstance(value, str)
    }
    environment.update(
        {
            "HOME": str(runtime_home),
            "XDG_CACHE_HOME": str(runtime_home / ".cache"),
            "HF_HOME": str(runtime_home / ".cache" / "huggingface"),
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "VLLM_SERVER_DEV_MODE": "0",
            # Empty allowlist matches no discovered vLLM plugin name.
            "VLLM_PLUGINS": "",
            "VLLM_MAX_N_SEQUENCES": "1",
            "VLLM_MAX_COMPLETION_PROMPTS": "1",
            "VLLM_HTTP_MAX_REQUEST_BODY_SIZE": str(5 * 1024 * 1024),
            "VLLM_MEDIA_URL_ALLOW_REDIRECTS": "0",
            "VLLM_LOGGING_LEVEL": "WARNING",
            "VLLM_REQUEST_BODY_LOG_LEVEL": "CRITICAL",
            # No proxy configuration is inherited into the worker.
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
    )
    return environment


def inspect_vllm_runtime(
    executable: Path,
    *,
    base_environment: Mapping[str, str],
    runtime_home: Path,
) -> RuntimeInspection:
    resolved = _resolved_regular_executable(executable)
    environment = build_runtime_environment(
        base_environment=base_environment,
        runtime_home=runtime_home,
    )
    try:
        completed = subprocess.run(
            [str(resolved), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            env=environment,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeVersionError("could not inspect vLLM runtime") from exc

    if completed.returncode != 0:
        raise RuntimeVersionError(
            f"vLLM --version failed with exit code {completed.returncode}"
        )
    version = require_reviewed_vllm_version(completed.stdout)
    return RuntimeInspection(version=version, executable=resolved)


def _reviewed_isolation_prefix(prefix: tuple[str, ...]) -> tuple[str, ...]:
    if len(prefix) != 3 or prefix[1:] != ("--net", "--"):
        raise RuntimeSecurityError(
            "vLLM worker isolation must use exactly: unshare --net --"
        )
    launcher = Path(prefix[0])
    if not launcher.is_absolute() or launcher.name != "unshare":
        raise RuntimeSecurityError(
            "vLLM worker isolation launcher must be an absolute unshare path"
        )
    return prefix


def _inspect_isolation_launcher(prefix: tuple[str, ...]) -> tuple[str, ...]:
    reviewed = _reviewed_isolation_prefix(prefix)
    try:
        resolved = Path(reviewed[0]).resolve(strict=True)
    except OSError as exc:
        raise RuntimeSecurityError("unshare launcher is unavailable") from exc
    if resolved != Path("/usr/bin/unshare"):
        raise RuntimeSecurityError(
            "only the reviewed /usr/bin/unshare launcher is accepted"
        )
    info = os.stat(resolved)
    if not stat.S_ISREG(info.st_mode) or not os.access(resolved, os.X_OK):
        raise RuntimeSecurityError("unshare launcher is not executable")
    if hasattr(info, "st_uid") and info.st_uid != 0:
        raise RuntimeSecurityError("unshare launcher must be root-owned")
    return (str(resolved), "--net", "--")


def build_vllm_command(
    config: VllmBackendConfig,
    *,
    executable: Path,
    model_path: Path,
    socket_path: Path,
    isolation_prefix: tuple[str, ...] | None = None,
) -> list[str]:
    prefix = (
        _reviewed_isolation_prefix(config.isolation_prefix)
        if isolation_prefix is None
        else isolation_prefix
    )
    command = [
        *prefix,
        str(executable),
        "serve",
        str(model_path),
        "--uds",
        str(socket_path),
        "--served-model-name",
        config.model_id,
        "--no-trust-remote-code",
        "--language-model-only",
        "--disable-log-requests",
        "--disable-uvicorn-access-log",
        "--max-num-seqs",
        str(config.max_num_seqs),
        "--max-num-active-seqs",
        str(config.max_num_seqs),
        "--max-num-queued-reqs",
        str(config.max_num_queued_requests),
    ]
    if config.max_model_len is not None:
        command.extend(["--max-model-len", str(config.max_model_len)])
    return command


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: Path, *, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(str(self.socket_path))
        except Exception:
            sock.close()
            raise
        self.sock = sock


class OpenAICompatibleUnixClient:
    def __init__(
        self,
        socket_path: Path,
        *,
        timeout_seconds: int = 120,
        max_response_bytes: int = _MAX_JSON_RESPONSE_BYTES,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, int
        ):
            raise ValueError("timeout_seconds must be an integer")
        if not 1 <= timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be between 1 and 3600")
        if isinstance(max_response_bytes, bool) or not isinstance(
            max_response_bytes, int
        ):
            raise ValueError("max_response_bytes must be an integer")
        if not 1024 <= max_response_bytes <= 64 * 1024 * 1024:
            raise ValueError("max_response_bytes is outside the safe range")
        self.socket_path = socket_path
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def _connection(self) -> _UnixHTTPConnection:
        return _UnixHTTPConnection(
            self.socket_path,
            timeout=float(self.timeout_seconds),
        )

    def _request_payload(self, request: ChatRequest, *, stream: bool) -> bytes:
        payload: dict[str, object] = {
            "model": request.model_id,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "n": 1,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def _open_chat(
        self,
        request: ChatRequest,
        *,
        stream: bool,
    ) -> tuple[_UnixHTTPConnection, http.client.HTTPResponse]:
        connection = self._connection()
        payload = self._request_payload(request, stream=stream)
        try:
            connection.request(
                "POST",
                "/v1/chat/completions",
                body=payload,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(payload)),
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            connection.close()
            raise BackendUnavailable("vLLM Unix socket is unavailable") from exc
        return connection, response

    def _bounded_json(
        self,
        response: http.client.HTTPResponse,
    ) -> dict[str, object]:
        body = response.read(self.max_response_bytes + 1)
        if len(body) > self.max_response_bytes:
            raise InferenceError("vLLM response exceeded configured size limit")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InferenceError("vLLM returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise InferenceError("vLLM returned an invalid JSON object")
        return payload

    def _raise_for_status(
        self,
        response: http.client.HTTPResponse,
    ) -> None:
        if response.status < 400:
            return
        payload = self._bounded_json(response)
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message:
                raise InferenceError(
                    f"vLLM request failed with HTTP {response.status}: "
                    f"{message[:512]}"
                )
        raise InferenceError(
            f"vLLM request failed with HTTP {response.status}"
        )

    @staticmethod
    def _usage(value: object) -> TokenUsage:
        if not isinstance(value, dict):
            return TokenUsage()

        def token(name: str) -> int:
            raw = value.get(name, 0)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                return 0
            return raw

        return TokenUsage(
            prompt_tokens=token("prompt_tokens"),
            completion_tokens=token("completion_tokens"),
            total_tokens=token("total_tokens"),
        )

    def chat(self, request: ChatRequest) -> ChatResult:
        connection, response = self._open_chat(request, stream=False)
        try:
            self._raise_for_status(response)
            payload = self._bounded_json(response)
        finally:
            response.close()
            connection.close()

        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise InferenceError("vLLM returned an unexpected choices payload")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise InferenceError("vLLM returned an invalid choice")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise InferenceError("vLLM returned an invalid message")
        content = message.get("content")
        if not isinstance(content, str):
            raise InferenceError("vLLM returned non-text content")
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            finish_reason = None

        return ChatResult(
            content=content,
            finish_reason=finish_reason,
            usage=self._usage(payload.get("usage")),
        )

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamDelta]:
        connection, response = self._open_chat(request, stream=True)
        try:
            self._raise_for_status(response)
            while True:
                line = response.readline(_MAX_SSE_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > _MAX_SSE_LINE_BYTES:
                    raise InferenceError("vLLM stream line exceeded size limit")
                stripped = line.strip()
                if not stripped or stripped.startswith(b":"):
                    continue
                if not stripped.startswith(b"data:"):
                    continue
                data = stripped[5:].strip()
                if data == b"[DONE]":
                    return
                try:
                    payload = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise InferenceError("vLLM returned invalid SSE JSON") from exc
                if not isinstance(payload, dict):
                    raise InferenceError("vLLM returned invalid SSE object")

                usage = None
                if payload.get("usage") is not None:
                    usage = self._usage(payload.get("usage"))

                choices = payload.get("choices")
                if not isinstance(choices, list):
                    if usage is not None:
                        yield StreamDelta(usage=usage)
                    continue

                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta")
                    content = ""
                    if isinstance(delta, dict):
                        raw_content = delta.get("content")
                        if raw_content is not None:
                            if not isinstance(raw_content, str):
                                raise InferenceError(
                                    "vLLM returned non-text stream content"
                                )
                            content = raw_content
                    finish_reason = choice.get("finish_reason")
                    if finish_reason is not None and not isinstance(
                        finish_reason, str
                    ):
                        finish_reason = None
                    if content or finish_reason is not None or usage is not None:
                        yield StreamDelta(
                            content=content,
                            finish_reason=finish_reason,
                            usage=usage,
                        )
        finally:
            response.close()
            connection.close()

    def models(self) -> frozenset[str]:
        connection = self._connection()
        try:
            connection.request(
                "GET",
                "/v1/models",
                headers={"Connection": "close"},
            )
            response = connection.getresponse()
            try:
                self._raise_for_status(response)
                payload = self._bounded_json(response)
            finally:
                response.close()
        except (OSError, http.client.HTTPException) as exc:
            raise BackendUnavailable("vLLM Unix socket is unavailable") from exc
        finally:
            connection.close()

        data = payload.get("data")
        if not isinstance(data, list):
            raise InferenceError("vLLM returned invalid model catalog")
        models: set[str] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if isinstance(model_id, str):
                models.add(model_id)
        return frozenset(models)


class VllmBackend:
    """vLLM 0.33.0 adapter over a private Unix-domain socket."""

    def __init__(
        self,
        config: VllmBackendConfig,
        *,
        base_environment: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config
        self._base_environment = (
            dict(os.environ) if base_environment is None else dict(base_environment)
        )
        self._state = BackendState.STOPPED
        self._process: subprocess.Popen[bytes] | None = None
        self._log_handle = None
        self._client: OpenAICompatibleUnixClient | None = None
        self._socket: Path | None = None
        self._runtime_dir: Path | None = None
        self._capabilities = InferenceCapabilities(
            text=True,
            streaming=True,
            vision=False,
            tool_calling=False,
            max_context_tokens=config.max_model_len,
        )

    @property
    def capabilities(self) -> InferenceCapabilities:
        return self._capabilities

    def _require_linux(self) -> None:
        if not sys.platform.startswith("linux"):
            raise RuntimeSecurityError(
                "the reviewed vLLM backend currently requires Linux "
                "so the worker can run in a no-egress network namespace"
            )

    def _prepare(self) -> tuple[RuntimeInspection, Path, Path, Path, dict[str, str]]:
        self._require_linux()
        runtime_dir = _prepare_private_directory(self.config.runtime_dir)
        runtime_home = _prepare_private_directory(runtime_dir / "home")
        isolation_prefix = _inspect_isolation_launcher(
            self.config.isolation_prefix
        )
        inspection = inspect_vllm_runtime(
            self.config.executable,
            base_environment=self._base_environment,
            runtime_home=runtime_home,
        )
        _root, model_path = _resolved_model_path(
            self.config.model_store_root,
            self.config.model_path,
        )
        socket_path = _socket_path(runtime_dir)
        environment = build_runtime_environment(
            base_environment=self._base_environment,
            runtime_home=runtime_home,
        )
        return (
            inspection,
            model_path,
            socket_path,
            runtime_dir,
            environment,
            isolation_prefix,
        )

    def start(self) -> None:
        if self._state is not BackendState.STOPPED:
            raise RuntimeStartError(
                f"cannot start vLLM backend from state {self._state.value}"
            )
        self._state = BackendState.STARTING

        try:
            (
                inspection,
                model_path,
                socket_path,
                runtime_dir,
                environment,
                isolation_prefix,
            ) = self._prepare()
            command = build_vllm_command(
                self.config,
                executable=inspection.executable,
                model_path=model_path,
                socket_path=socket_path,
                isolation_prefix=isolation_prefix,
            )

            log_path = runtime_dir / "worker.log"
            log_handle = log_path.open("ab", buffering=0)
            os.chmod(log_path, 0o600)
            self._log_handle = log_handle

            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    close_fds=True,
                    start_new_session=True,
                    umask=0o077,
                )
            except Exception:
                log_handle.close()
                self._log_handle = None
                raise

            self._process = process
            self._socket = socket_path
            self._runtime_dir = runtime_dir
            self._client = OpenAICompatibleUnixClient(
                socket_path,
                timeout_seconds=min(
                    self.config.startup_timeout_seconds,
                    120,
                ),
            )

            deadline = time.monotonic() + self.config.startup_timeout_seconds
            last_error: Exception | None = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeStartError(
                        f"vLLM exited during startup with code {process.returncode}"
                    )
                if socket_path.exists():
                    info = os.lstat(socket_path)
                    if stat.S_ISLNK(info.st_mode) or not stat.S_ISSOCK(info.st_mode):
                        raise RuntimeSecurityError(
                            "vLLM Unix socket path is not a socket"
                        )
                    if hasattr(os, "getuid") and info.st_uid != os.getuid():
                        raise RuntimeSecurityError(
                            "vLLM Unix socket is owned by another user"
                        )
                    os.chmod(socket_path, 0o600)
                    try:
                        models = self._client.models()
                        if self.config.model_id not in models:
                            raise RuntimeStartError(
                                "vLLM model catalog does not contain the configured model"
                            )
                        self._state = BackendState.READY
                        return
                    except (InferenceError, OSError) as exc:
                        last_error = exc
                time.sleep(0.2)

            raise RuntimeStartError(
                "vLLM did not become ready before the startup timeout"
            ) from last_error
        except Exception:
            self._state = BackendState.UNHEALTHY
            self.stop()
            raise

    def stop(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except OSError:
                process.terminate()
            try:
                process.wait(timeout=self.config.shutdown_timeout_seconds)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    process.kill()
                process.wait(timeout=5)

        self._process = None
        self._client = None

        if self._socket is not None and self._socket.exists():
            try:
                info = os.lstat(self._socket)
                if stat.S_ISSOCK(info.st_mode) and (
                    not hasattr(os, "getuid") or info.st_uid == os.getuid()
                ):
                    self._socket.unlink()
            except OSError:
                logger.warning(
                    "could not remove stale vLLM Unix socket %s",
                    self._socket,
                )
        self._socket = None

        if self._log_handle is not None:
            try:
                self._log_handle.close()
            finally:
                self._log_handle = None

        self._state = BackendState.STOPPED

    def _require_client(self) -> OpenAICompatibleUnixClient:
        if self._state is not BackendState.READY or self._client is None:
            raise BackendUnavailable("vLLM backend is not ready")
        process = self._process
        if process is not None and process.poll() is not None:
            self._state = BackendState.UNHEALTHY
            raise BackendUnavailable("vLLM worker exited")
        return self._client

    def health(self) -> HealthReport:
        if self._state is not BackendState.READY:
            return HealthReport(
                ready=False,
                state=self._state,
                detail=f"vLLM backend is {self._state.value}",
            )
        try:
            models = self._require_client().models()
        except InferenceError as exc:
            self._state = BackendState.UNHEALTHY
            return HealthReport(
                ready=False,
                state=self._state,
                detail=f"vLLM health check failed: {exc}",
            )
        ready = self.config.model_id in models
        if not ready:
            self._state = BackendState.UNHEALTHY
        return HealthReport(
            ready=ready,
            state=self._state,
            detail=(
                "vLLM backend ready"
                if ready
                else "configured model is missing from vLLM catalog"
            ),
        )

    def _validate_request_model(self, request: ChatRequest) -> None:
        if request.model_id != self.config.model_id:
            raise InferenceError(
                "request model does not match this backend instance"
            )

    def chat(self, request: ChatRequest) -> ChatResult:
        self._validate_request_model(request)
        return self._require_client().chat(request)

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamDelta]:
        self._validate_request_model(request)
        yield from self._require_client().stream_chat(request)

    def __enter__(self) -> "VllmBackend":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()
