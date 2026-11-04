from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterator, Protocol


class InferenceError(RuntimeError):
    """Base error for inference backend failures."""


class BackendUnavailable(InferenceError):
    """Raised when an inference backend is not ready to serve."""


class InvalidInferenceRequest(ValueError):
    """Raised when a request is invalid before reaching a runtime."""


class BackendState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    UNHEALTHY = "unhealthy"


_ALLOWED_ROLES = frozenset({"system", "user", "assistant"})


def _non_empty(value: object, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInferenceRequest(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise InvalidInferenceRequest(f"{field} is too long")
    return normalized


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        role = _non_empty(self.role, field="message role", maximum=32).casefold()
        if role not in _ALLOWED_ROLES:
            raise InvalidInferenceRequest(f"unsupported message role: {role}")
        if not isinstance(self.content, str):
            raise InvalidInferenceRequest("message content must be a string")
        if len(self.content.encode("utf-8")) > 1024 * 1024:
            raise InvalidInferenceRequest("message content is too large")
        object.__setattr__(self, "role", role)


@dataclass(frozen=True)
class ChatRequest:
    model_id: str
    messages: tuple[ChatMessage, ...]
    max_tokens: int = 1024
    temperature: float = 0.2

    def __post_init__(self) -> None:
        model_id = _non_empty(self.model_id, field="model_id", maximum=128)
        if not self.messages:
            raise InvalidInferenceRequest("at least one message is required")
        if len(self.messages) > 256:
            raise InvalidInferenceRequest("too many messages")
        if any(not isinstance(message, ChatMessage) for message in self.messages):
            raise InvalidInferenceRequest("messages must contain ChatMessage values")

        total_bytes = sum(len(message.content.encode("utf-8")) for message in self.messages)
        if total_bytes > 4 * 1024 * 1024:
            raise InvalidInferenceRequest("combined message content is too large")

        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int):
            raise InvalidInferenceRequest("max_tokens must be an integer")
        if not 1 <= self.max_tokens <= 65536:
            raise InvalidInferenceRequest("max_tokens must be between 1 and 65536")

        if isinstance(self.temperature, bool) or not isinstance(
            self.temperature, (int, float)
        ):
            raise InvalidInferenceRequest("temperature must be numeric")
        temperature = float(self.temperature)
        if not 0.0 <= temperature <= 2.0:
            raise InvalidInferenceRequest("temperature must be between 0 and 2")

        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "temperature", temperature)


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class ChatResult:
    content: str
    finish_reason: str | None = None
    usage: TokenUsage = TokenUsage()


@dataclass(frozen=True)
class StreamDelta:
    content: str = ""
    finish_reason: str | None = None
    usage: TokenUsage | None = None


@dataclass(frozen=True)
class InferenceCapabilities:
    text: bool = True
    streaming: bool = True
    vision: bool = False
    tool_calling: bool = False
    max_context_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_context_tokens is not None:
            if (
                isinstance(self.max_context_tokens, bool)
                or not isinstance(self.max_context_tokens, int)
                or self.max_context_tokens < 1
            ):
                raise ValueError("max_context_tokens must be a positive integer")


@dataclass(frozen=True)
class HealthReport:
    ready: bool
    state: BackendState
    detail: str


class InferenceBackend(Protocol):
    @property
    def capabilities(self) -> InferenceCapabilities:
        ...

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def health(self) -> HealthReport:
        ...

    def chat(self, request: ChatRequest) -> ChatResult:
        ...

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamDelta]:
        ...


class MockInferenceBackend:
    """Small deterministic backend for contract and gateway tests."""

    def __init__(self, *, response_text: str = "mock response") -> None:
        self._state = BackendState.STOPPED
        self.response_text = response_text
        self._capabilities = InferenceCapabilities(
            text=True,
            streaming=True,
            vision=False,
            tool_calling=False,
            max_context_tokens=4096,
        )

    @property
    def capabilities(self) -> InferenceCapabilities:
        return self._capabilities

    def start(self) -> None:
        self._state = BackendState.READY

    def stop(self) -> None:
        self._state = BackendState.STOPPED

    def health(self) -> HealthReport:
        ready = self._state is BackendState.READY
        return HealthReport(
            ready=ready,
            state=self._state,
            detail="mock backend ready" if ready else "mock backend stopped",
        )

    def _require_ready(self) -> None:
        if self._state is not BackendState.READY:
            raise BackendUnavailable("mock backend is not ready")

    def chat(self, request: ChatRequest) -> ChatResult:
        self._require_ready()
        if not isinstance(request, ChatRequest):
            raise InvalidInferenceRequest("request must be ChatRequest")
        return ChatResult(
            content=self.response_text,
            finish_reason="stop",
            usage=TokenUsage(),
        )

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamDelta]:
        self._require_ready()
        if not isinstance(request, ChatRequest):
            raise InvalidInferenceRequest("request must be ChatRequest")
        midpoint = max(1, len(self.response_text) // 2)
        yield StreamDelta(content=self.response_text[:midpoint])
        yield StreamDelta(content=self.response_text[midpoint:])
        yield StreamDelta(finish_reason="stop", usage=TokenUsage())
