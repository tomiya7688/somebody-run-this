from __future__ import annotations

import unittest

from private_ai_hub.inference import (
    BackendState,
    BackendUnavailable,
    ChatMessage,
    ChatRequest,
    InvalidInferenceRequest,
    MockInferenceBackend,
)


class InferenceContractTests(unittest.TestCase):
    def test_chat_request_is_bounded_and_text_only(self) -> None:
        request = ChatRequest(
            model_id="local-model",
            messages=(ChatMessage(role="user", content="hello"),),
            max_tokens=128,
            temperature=0.5,
        )
        self.assertEqual(request.model_id, "local-model")
        self.assertEqual(request.messages[0].role, "user")

        with self.assertRaises(InvalidInferenceRequest):
            ChatMessage(role="tool", content="not supported in v1")
        with self.assertRaises(InvalidInferenceRequest):
            ChatRequest(
                model_id="local-model",
                messages=(ChatMessage(role="user", content="hello"),),
                max_tokens=0,
            )

    def test_mock_backend_matches_lifecycle_and_stream_contract(self) -> None:
        backend = MockInferenceBackend(response_text="abcdef")
        self.assertEqual(backend.health().state, BackendState.STOPPED)

        request = ChatRequest(
            model_id="local-model",
            messages=(ChatMessage(role="user", content="hello"),),
        )
        with self.assertRaises(BackendUnavailable):
            backend.chat(request)

        backend.start()
        result = backend.chat(request)
        self.assertEqual(result.content, "abcdef")
        self.assertEqual(result.finish_reason, "stop")

        deltas = tuple(backend.stream_chat(request))
        self.assertEqual("".join(delta.content for delta in deltas), "abcdef")
        self.assertEqual(deltas[-1].finish_reason, "stop")

        backend.stop()
        self.assertFalse(backend.health().ready)


if __name__ == "__main__":
    unittest.main()
