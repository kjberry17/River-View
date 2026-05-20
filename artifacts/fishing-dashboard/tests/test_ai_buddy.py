"""
Unit tests for the fallback chain and exception handling in ai_buddy.py.

These tests verify:
- VAL-FB-001: Per-call model tracking
- VAL-FB-002: All models tried on total failure
- VAL-FB-003: No shared mutable state between calls
- VAL-FB-004: Deduplicated candidates
- VAL-FB-005: Graceful degradation on exhaustion
- VAL-EH-001: APITimeoutError caught and retried
- VAL-EH-002: APIConnectionError caught and retried
- VAL-EH-003: BadRequestError caught and retried
- VAL-EH-004: Existing exceptions still caught (PermissionDeniedError, RateLimitError, APIStatusError)
- VAL-EH-005: No raise None on empty candidate list
- VAL-EH-006: Malformed tool arguments guard (non-streaming)
- VAL-UT-001: Fallback chain unit tests pass
- VAL-UT-002: Exception handling unit tests pass
- VAL-UT-006: Malformed tool arguments unit tests pass
"""

import json
import threading
import pytest
from unittest.mock import MagicMock, patch, call
from openai import (
    PermissionDeniedError,
    RateLimitError,
    APIStatusError,
    APITimeoutError,
    APIConnectionError,
    BadRequestError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db_module():
    """Mock database module for testing"""
    db = MagicMock()
    db.get_preferences.return_value = None
    db.search_wiki.return_value = []
    db.get_recent_logs_for_river.return_value = []
    db.get_fishing_logs.return_value = []
    return db


def _make_exception(cls, message="test error"):
    """Factory for creating OpenAI exception instances with required kwargs.

    Different OpenAI exception classes have different signatures:
    - APITimeoutError: (request,)
    - APIConnectionError: (message, request) — message is keyword-only
    - BadRequestError: (message, response, body) — response/body are keyword-only
    - PermissionDeniedError, RateLimitError, APIStatusError: same as BadRequestError
    """
    import httpx

    request = MagicMock(spec=httpx.Request)
    response = MagicMock(spec=httpx.Response)
    response.status_code = 429  # default for rate limit errors
    # headers is accessed as response.headers.get("x-request-id")
    response.headers = MagicMock()
    response.headers.get = lambda key: "test-request-id"
    body = {"error": {"message": message}}

    if cls is APITimeoutError:
        return cls(request)
    elif cls is APIConnectionError:
        return cls(message=message, request=request)
    else:
        # BadRequestError, PermissionDeniedError, RateLimitError, APIStatusError
        return cls(message=message, response=response, body=body)


def _mock_response(content="Test response", tool_calls=None, finish_reason="stop"):
    """Factory for creating a mock chat completion response."""
    response = MagicMock()
    response.choices = [
        MagicMock(
            message=MagicMock(content=content, tool_calls=tool_calls),
            finish_reason=finish_reason,
        )
    ]
    return response


# ---------------------------------------------------------------------------
# Fallback Chain Tests
# ---------------------------------------------------------------------------

class TestFallbackChain:
    """Tests for VAL-FB-001 through VAL-FB-005"""

    def test_fallback_single_success(self):
        """First model succeeds, no fallback needed."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response("Great fishing!")

        candidates = ["model/a", "model/b"]
        result, used_model = _create_completion_with_fallback(
            mock_client, candidates, messages=[{"role": "user", "content": "hi"}]
        )

        assert result is not None
        assert used_model == "model/a"
        assert mock_client.chat.completions.create.call_count == 1

    def test_fallback_first_failure_then_success(self):
        """First model fails, second succeeds."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_exception(RateLimitError, "rate limited"),
            _mock_response("Success!"),
        ]

        candidates = ["model/fail", "model/succeed"]
        result, used_model = _create_completion_with_fallback(
            mock_client, candidates, messages=[{"role": "user", "content": "hi"}]
        )

        assert "Success!" in result.choices[0].message.content
        assert used_model == "model/succeed"
        assert mock_client.chat.completions.create.call_count == 2

    def test_fallback_all_failures(self):
        """All models fail, graceful error returned."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_exception(RateLimitError, "rate limited"),
            _make_exception(PermissionDeniedError, "denied"),
            _make_exception(APIStatusError, "server error"),
        ]

        candidates = ["model/a", "model/b", "model/c"]
        with pytest.raises(APIStatusError):
            _create_completion_with_fallback(
                mock_client,
                candidates,
                messages=[{"role": "user", "content": "hi"}],
            )

        assert mock_client.chat.completions.create.call_count == 3

    def test_fallback_deduplication(self):
        """Duplicate models only attempted once."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response("Done")

        # When selected model is same as fallback model
        candidates = ["deepseek/deepseek-v4-flash:free", "deepseek/deepseek-v4-flash:free"]
        result, used_model = _create_completion_with_fallback(
            mock_client, candidates, messages=[{"role": "user", "content": "hi"}]
        )

        # Should only be called once (deduplicated)
        assert mock_client.chat.completions.create.call_count == 1
        assert used_model == "deepseek/deepseek-v4-flash:free"

    def test_fallback_concurrent_calls(self):
        """Concurrent calls don't share failure state."""
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        call_log = []

        def mock_create(*args, **kwargs):
            model = kwargs.get("model")
            with lock:
                call_log.append(model)
            barrier.wait(timeout=5)
            return _mock_response("Done")

        mock_client1 = MagicMock()
        mock_client1.chat.completions.create.side_effect = mock_create

        mock_client2 = MagicMock()
        mock_client2.chat.completions.create.side_effect = [
            _make_exception(RateLimitError, "rate limited"),
            _mock_response("Done"),
        ]

        results = {}

        def call_with_client1():
            from ai_buddy import _create_completion_with_fallback

            result, _ = _create_completion_with_fallback(
                mock_client1,
                ["model/shared", "model/fallback"],
                messages=[{"role": "user", "content": "hi"}],
            )
            results["client1"] = result

        def call_with_client2():
            barrier.wait(timeout=5)
            from ai_buddy import _create_completion_with_fallback

            result, _ = _create_completion_with_fallback(
                mock_client2,
                ["model/shared", "model/fallback"],
                messages=[{"role": "user", "content": "hi"}],
            )
            results["client2"] = result

        t1 = threading.Thread(target=call_with_client1)
        t2 = threading.Thread(target=call_with_client2)

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert t1.is_alive() is False, "Thread 1 did not complete"
        assert t2.is_alive() is False, "Thread 2 did not complete"
        # Both calls should have succeeded — no shared state
        assert "client1" in results
        assert "client2" in results

    def test_all_models_tried_on_total_failure(self):
        """Every model in chain is attempted exactly once on total failure."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        models_called = []

        def track_create(*args, **kwargs):
            models_called.append(kwargs.get("model"))
            raise _make_exception(RateLimitError, "rate limited")

        mock_client.chat.completions.create.side_effect = track_create

        candidates = ["model/1", "model/2", "model/3"]
        with pytest.raises(RateLimitError):
            _create_completion_with_fallback(
                mock_client,
                candidates,
                messages=[{"role": "user", "content": "hi"}],
            )

        assert models_called == ["model/1", "model/2", "model/3"]
        assert mock_client.chat.completions.create.call_count == 3


# ---------------------------------------------------------------------------
# Exception Handling Tests
# ---------------------------------------------------------------------------

class TestExceptionHandling:
    """Tests for VAL-EH-001 through VAL-EH-006"""

    def test_catch_api_timeout_error(self):
        """APITimeoutError triggers fallback to next model."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_exception(APITimeoutError, "timed out"),
            _mock_response("Recovered via fallback"),
        ]

        result, used_model = _create_completion_with_fallback(
            mock_client,
            ["model/will_timeout", "model/recover"],
            messages=[{"role": "user", "content": "hi"}],
        )

        assert "Recovered via fallback" in result.choices[0].message.content
        assert used_model == "model/recover"
        assert mock_client.chat.completions.create.call_count == 2

    def test_catch_api_connection_error(self):
        """APIConnectionError triggers fallback to next model."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_exception(APIConnectionError, "connection failed"),
            _mock_response("Recovered via fallback"),
        ]

        result, used_model = _create_completion_with_fallback(
            mock_client,
            ["model/bad_conn", "model/recover"],
            messages=[{"role": "user", "content": "hi"}],
        )

        assert "Recovered via fallback" in result.choices[0].message.content
        assert used_model == "model/recover"
        assert mock_client.chat.completions.create.call_count == 2

    def test_catch_bad_request_error(self):
        """BadRequestError triggers fallback to next model."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_exception(BadRequestError, "bad request"),
            _mock_response("Recovered via fallback"),
        ]

        result, used_model = _create_completion_with_fallback(
            mock_client,
            ["model/bad_req", "model/recover"],
            messages=[{"role": "user", "content": "hi"}],
        )

        assert "Recovered via fallback" in result.choices[0].message.content
        assert used_model == "model/recover"
        assert mock_client.chat.completions.create.call_count == 2

    def test_catch_permission_denied_error(self):
        """PermissionDeniedError triggers fallback to next model."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_exception(PermissionDeniedError, "permission denied"),
            _mock_response("Recovered via fallback"),
        ]

        result, used_model = _create_completion_with_fallback(
            mock_client,
            ["model/denied", "model/recover"],
            messages=[{"role": "user", "content": "hi"}],
        )

        assert "Recovered via fallback" in result.choices[0].message.content
        assert used_model == "model/recover"
        assert mock_client.chat.completions.create.call_count == 2

    def test_catch_rate_limit_error(self):
        """RateLimitError triggers fallback to next model."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_exception(RateLimitError, "rate limited"),
            _mock_response("Recovered via fallback"),
        ]

        result, used_model = _create_completion_with_fallback(
            mock_client,
            ["model/rate_limited", "model/recover"],
            messages=[{"role": "user", "content": "hi"}],
        )

        assert "Recovered via fallback" in result.choices[0].message.content
        assert used_model == "model/recover"
        assert mock_client.chat.completions.create.call_count == 2

    def test_catch_api_status_error(self):
        """APIStatusError triggers fallback to next model."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_exception(APIStatusError, "server error"),
            _mock_response("Recovered via fallback"),
        ]

        result, used_model = _create_completion_with_fallback(
            mock_client,
            ["model/status_err", "model/recover"],
            messages=[{"role": "user", "content": "hi"}],
        )

        assert "Recovered via fallback" in result.choices[0].message.content
        assert used_model == "model/recover"
        assert mock_client.chat.completions.create.call_count == 2

    def test_no_raise_none_empty_candidates(self):
        """Empty candidate list raises ValueError, not TypeError from raise None."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        with pytest.raises(ValueError, match="No model candidates"):
            _create_completion_with_fallback(
                mock_client, [], messages=[{"role": "user", "content": "hi"}]
            )


# ---------------------------------------------------------------------------
# Malformed Tool Arguments Tests (Non-Streaming)
# ---------------------------------------------------------------------------

class TestMalformedToolArguments:
    """Tests for VAL-EH-006: Malformed tool arguments in non-streaming mode"""

    def test_malformed_tool_arguments_invalid_json(self, mock_db_module):
        """Invalid JSON in tool function.arguments is handled gracefully."""
        from ai_buddy import chat_with_buddy

        mock_client = MagicMock()

        # First response: model wants to call a tool with bad JSON
        tool_call_response = _mock_response(
            content="Let me check...",
            tool_calls=[
                MagicMock(
                    id="call_bad_json",
                    function=MagicMock(
                        name="get_live_data",
                        arguments="{ bad json",  # malformed JSON
                    ),
                )
            ],
            finish_reason="tool_calls",
        )

        # Second response: text response after malformed tool call
        text_response = _mock_response(content="Here is the info you need.")

        mock_client.chat.completions.create.side_effect = [tool_call_response, text_response]

        with patch("ai_buddy.get_client", return_value=mock_client):
            response, wiki_proposals = chat_with_buddy(
                user_message="What are the flows on the McKenzie?",
                conversation_history=[],
                live_data={},
                db_module=mock_db_module,
            )

            # Should not raise; should return a text response
            assert isinstance(response, str)
            assert len(response) > 0

    def test_malformed_tool_arguments_none_function(self, mock_db_module):
        """None function object on tool call is handled gracefully."""
        from ai_buddy import chat_with_buddy

        mock_client = MagicMock()

        # First response: model wants to call a tool with None function
        tool_call_response = _mock_response(
            content="Let me check...",
            tool_calls=[MagicMock(id="call_none_func", function=None)],
            finish_reason="tool_calls",
        )

        # Second response: text response
        text_response = _mock_response(content="Here is the info you need.")

        mock_client.chat.completions.create.side_effect = [tool_call_response, text_response]

        with patch("ai_buddy.get_client", return_value=mock_client):
            response, wiki_proposals = chat_with_buddy(
                user_message="What are the flows on the McKenzie?",
                conversation_history=[],
                live_data={},
                db_module=mock_db_module,
            )

            assert isinstance(response, str)
            assert len(response) > 0

    def test_malformed_tool_arguments_empty_arguments_string(self, mock_db_module):
        """Empty string arguments are handled gracefully."""
        from ai_buddy import chat_with_buddy

        mock_client = MagicMock()

        tool_call_response = _mock_response(
            content="Let me check...",
            tool_calls=[
                MagicMock(
                    id="call_empty_args",
                    function=MagicMock(name="get_live_data", arguments=""),
                )
            ],
            finish_reason="tool_calls",
        )

        text_response = _mock_response(content="Here is the info you need.")

        mock_client.chat.completions.create.side_effect = [tool_call_response, text_response]

        with patch("ai_buddy.get_client", return_value=mock_client):
            response, wiki_proposals = chat_with_buddy(
                user_message="What are the flows on the McKenzie?",
                conversation_history=[],
                live_data={},
                db_module=mock_db_module,
            )

            assert isinstance(response, str)
            assert len(response) > 0

    def test_malformed_tool_arguments_none_arguments(self, mock_db_module):
        """None arguments are handled gracefully."""
        from ai_buddy import chat_with_buddy

        mock_client = MagicMock()

        tool_call_response = _mock_response(
            content="Let me check...",
            tool_calls=[
                MagicMock(
                    id="call_none_args",
                    function=MagicMock(name="get_live_data", arguments=None),
                )
            ],
            finish_reason="tool_calls",
        )

        text_response = _mock_response(content="Here is the info you need.")

        mock_client.chat.completions.create.side_effect = [tool_call_response, text_response]

        with patch("ai_buddy.get_client", return_value=mock_client):
            response, wiki_proposals = chat_with_buddy(
                user_message="What are the flows on the McKenzie?",
                conversation_history=[],
                live_data={},
                db_module=mock_db_module,
            )

            assert isinstance(response, str)
            assert len(response) > 0


# ---------------------------------------------------------------------------
# Timeout Configuration Tests
# ---------------------------------------------------------------------------

class TestTimeoutConfiguration:
    """Tests for VAL-TO-001: Timeout is 120 seconds"""

    def test_timeout_is_120_seconds(self):
        """client.chat.completions.create is called with timeout=120."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response("Done")

        _create_completion_with_fallback(
            mock_client,
            ["model/a"],
            messages=[{"role": "user", "content": "hi"}],
        )

        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("timeout") == 120


# ---------------------------------------------------------------------------
# chat_with_buddy non-streaming tests
# ---------------------------------------------------------------------------

class TestChatWithBuddyNonStreaming:
    """Tests for VAL-NS-001 through VAL-NS-004"""

    def test_session_cache_parameter_accepted(self):
        """chat_with_buddy accepts session_cache parameter without TypeError."""
        from ai_buddy import chat_with_buddy

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response("Hello!")

        with patch("ai_buddy.get_client", return_value=mock_client):
            response, wiki_proposals = chat_with_buddy(
                user_message="Hello",
                conversation_history=[],
                live_data={},
                db_module=MagicMock(),
                session_cache={},
            )

            assert isinstance(response, str)
            assert isinstance(wiki_proposals, list)

    def test_valid_response_returned(self, mock_db_module):
        """Normal user message returns non-empty string response."""
        from ai_buddy import chat_with_buddy

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response("The fishing is great!")

        with patch("ai_buddy.get_client", return_value=mock_client):
            response, wiki_proposals = chat_with_buddy(
                user_message="Hello Fisher",
                conversation_history=[],
                live_data={},
                db_module=mock_db_module,
            )

            assert isinstance(response, str)
            assert len(response) > 0

    def test_tool_calling_loop_executes(self, mock_db_module):
        """Tool-calling response executes tools and continues loop."""
        from ai_buddy import chat_with_buddy

        mock_client = MagicMock()

        # First response: tool call
        tool_call_response = _mock_response(
            content="Let me check...",
            tool_calls=[
                MagicMock(
                    id="call_123",
                    function=MagicMock(name="get_live_data", arguments='{"river": "McKenzie"}'),
                )
            ],
            finish_reason="tool_calls",
        )

        # Second response: text response
        text_response = _mock_response(content="McKenzie is running at 250 CFS.")

        mock_client.chat.completions.create.side_effect = [tool_call_response, text_response]

        with patch("ai_buddy.get_client", return_value=mock_client):
            with patch("ai_buddy.execute_tool") as mock_execute:
                mock_execute.return_value = ("McKenzie River: 250 CFS", [])

                response, wiki_proposals = chat_with_buddy(
                    user_message="What are the flows on the McKenzie?",
                    conversation_history=[],
                    live_data={},
                    db_module=mock_db_module,
                )

                # Tool should have been called
                mock_execute.assert_called()


# ---------------------------------------------------------------------------
# Per-call model tracking (VAL-FB-001)
# ---------------------------------------------------------------------------

class TestPerCallModelTracking:
    """Tests that each chat call starts with a fresh tracking set."""

    def test_sequential_calls_both_attempt_first_model(self):
        """Two sequential calls both attempt Model A even if Model A failed in first call."""
        from ai_buddy import _create_completion_with_fallback

        mock_client = MagicMock()
        call_count = [0]

        def create_side_effect(*args, **kwargs):
            call_count[0] += 1
            model = kwargs.get("model")
            if call_count[0] == 1:
                # First call: Model A fails, Model B succeeds
                if model == "model/a":
                    raise _make_exception(RateLimitError, "rate limited")
                else:
                    return _mock_response("Done from B")
            else:
                # Second call: Model A should still be attempted (fresh state)
                if model == "model/a":
                    return _mock_response("Done from A")
                else:
                    return _mock_response("Done from B")

        mock_client.chat.completions.create.side_effect = create_side_effect

        # First call: Model A fails, Model B succeeds
        result1, used_model1 = _create_completion_with_fallback(
            mock_client,
            ["model/a", "model/b"],
            messages=[{"role": "user", "content": "hi"}],
        )
        assert used_model1 == "model/b"
        assert "Done from B" in result1.choices[0].message.content

        # Second call: Model A should still be tried (fresh state per call)
        result2, used_model2 = _create_completion_with_fallback(
            mock_client,
            ["model/a", "model/b"],
            messages=[{"role": "user", "content": "hi"}],
        )
        # Model A should have succeeded this time (fresh state)
        assert used_model2 == "model/a"
        assert "Done from A" in result2.choices[0].message.content

        # Verify Model A was attempted in both calls (3 total: fail→b, then a succeeds)
        assert mock_client.chat.completions.create.call_count == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
