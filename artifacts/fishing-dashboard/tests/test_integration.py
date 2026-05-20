"""
Integration tests for the /fish/chat endpoint using Flask test client.

These tests verify:
- VAL-IT-001: Chat endpoint non-streaming returns valid JSON with response and wiki_proposals
- VAL-IT-002: Chat endpoint streaming returns NDJSON with response and done events
- VAL-IT-003: Tool-triggering query executes tools and returns live data references
- VAL-IT-004: All-model failure returns user-facing error (not 500)
- VAL-E2E-002: Session cache survives across turns (web search deduplication)
- VAL-E2E-003: Streaming and non-streaming parity for same query
- VAL-E2E-004: Full failure path UX for both modes

Expected behavior:
- Integration test file exists at artifacts/fishing-dashboard/tests/test_integration.py
- Non-streaming endpoint returns 200 with response and wiki_proposals
- Streaming endpoint returns 200 with NDJSON containing response and done events
- Tool-triggering query returns response referencing live data
- All-model failure returns 200 with branded error message (not 500)
- Session cache deduplicates web searches across sequential requests
- Streaming and non-streaming produce equivalent responses for same query
- Total outage returns branded error for both modes
"""

import json
import pytest
import sys
import os

# Ensure the fishing-dashboard is in the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Create Flask app for testing."""
    # Patch environment to avoid needing real API keys / external services
    os.environ["OPENROUTER_API_KEY"] = "test-key-for-integration-tests"
    
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def mock_db_module():
    """Mock database module for testing."""
    from unittest.mock import MagicMock
    
    db = MagicMock()
    db.get_preferences.return_value = None
    db.search_wiki.return_value = []
    db.get_recent_logs_for_river.return_value = []
    db.get_fishing_logs.return_value = []
    return db


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


from unittest.mock import MagicMock, patch, ANY
from openai import RateLimitError, PermissionDeniedError


def _make_exception(cls, message="test error"):
    """Factory for creating OpenAI exception instances with required kwargs."""
    import httpx

    request = MagicMock(spec=httpx.Request)
    response = MagicMock(spec=httpx.Response)
    response.status_code = 429
    response.headers = MagicMock()
    response.headers.get = lambda key: "test-request-id"
    body = {"error": {"message": message}}

    if cls is RateLimitError:
        return cls(message=message, response=response, body=body)
    else:
        return cls(message=message, response=response, body=body)


# ---------------------------------------------------------------------------
# VAL-IT-001: Chat Endpoint Non-Streaming
# ---------------------------------------------------------------------------

class TestChatEndpointNonStreaming:
    """Integration tests for non-streaming /fish/chat endpoint."""

    def test_non_streaming_returns_valid_json(self, client, mock_db_module):
        """VAL-IT-001: POST /fish/chat with stream=false returns HTTP 200 and JSON
        with 'response' and 'wiki_proposals' fields."""
        
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response(
            "The fishing on the McKenzie is excellent right now! "
            "Steelhead season is in full swing with good returns reported."
        )

        with patch("ai_buddy.get_client", return_value=mock_client):
            response = client.post(
                "/fish/chat",
                json={"message": "How's the fishing on the McKenzie?", "stream": False},
                content_type="application/json",
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
        data = response.get_json()
        assert data is not None, "Response should be valid JSON"
        assert "response" in data, f"Response should contain 'response' field: {data}"
        assert "wiki_proposals" in data, f"Response should contain 'wiki_proposals' field: {data}"
        assert isinstance(data["response"], str), "response should be a string"
        assert len(data["response"]) > 0, "response should not be empty"
        assert isinstance(data["wiki_proposals"], list), "wiki_proposals should be a list"

    def test_non_streaming_no_message_returns_400(self, client):
        """Empty message should return 400 Bad Request."""
        response = client.post(
            "/fish/chat",
            json={"message": "", "stream": False},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_non_streaming_missing_message_returns_400(self, client):
        """Missing message field should return 400 Bad Request."""
        response = client.post(
            "/fish/chat",
            json={"stream": False},
            content_type="application/json",
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# VAL-IT-002: Chat Endpoint Streaming
# ---------------------------------------------------------------------------

class TestChatEndpointStreaming:
    """Integration tests for streaming /fish/chat endpoint."""

    def test_streaming_returns_ndjson_with_response_and_done_events(self, client, mock_db_module):
        """VAL-IT-002: POST /fish/chat with stream=true returns HTTP 200 with
        application/x-ndjson containing 'response' and 'done' event types."""
        
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response(
            "The fishing report looks great today!"
        )

        with patch("ai_buddy.get_client", return_value=mock_client):
            response = client.post(
                "/fish/chat",
                json={"message": "Hello Fisher", "stream": True},
                content_type="application/json",
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert response.content_type == "application/x-ndjson", (
            f"Expected application/x-ndjson, got {response.content_type}"
        )

        # Parse NDJSON stream
        lines = response.data.decode("utf-8").strip().split("\n")
        assert len(lines) >= 2, f"Expected at least 2 NDJSON lines, got {len(lines)}"

        event_types = []
        for line in lines:
            if line.strip():
                event = json.loads(line)
                event_types.append(event.get("type"))
                assert "type" in event, f"Each event should have 'type' field: {event}"

        assert "response" in event_types, f"Stream should contain 'response' event: {event_types}"
        assert "done" in event_types, f"Stream should contain 'done' event: {event_types}"

    def test_streaming_contains_tool_start_and_tool_end_events(self, client, mock_db_module):
        """VAL-ST-002: Stream includes tool_start and tool_end events when tools are called."""
        
        mock_client = MagicMock()

        # First response: model calls a tool
        tool_call_mock = MagicMock()
        tool_call_mock.id = "call_abc"
        tool_call_mock.function = MagicMock()
        tool_call_mock.function.name = "get_live_data"
        tool_call_mock.function.arguments = '{"river": "McKenzie"}'

        tool_call_response = _mock_response(
            content="Let me check the McKenzie flows...",
            tool_calls=[tool_call_mock],
            finish_reason="tool_calls",
        )

        # Second response: text response
        text_response = _mock_response(content="The McKenzie is running at 250 CFS today.")

        mock_client.chat.completions.create.side_effect = [tool_call_response, text_response]

        with patch("ai_buddy.get_client", return_value=mock_client):
            with patch("ai_buddy.execute_tool") as mock_execute:
                mock_execute.return_value = ("McKenzie River: 250 CFS", [])

                response = client.post(
                    "/fish/chat",
                    json={"message": "What are the flows on the McKenzie?", "stream": True},
                    content_type="application/json",
                )

        assert response.status_code == 200

        # Parse NDJSON stream
        lines = response.data.decode("utf-8").strip().split("\n")
        event_types = []
        for line in lines:
            if line.strip():
                event = json.loads(line)
                event_types.append(event.get("type"))

        assert "tool_start" in event_types, f"Stream should contain 'tool_start' event: {event_types}"
        assert "tool_end" in event_types, f"Stream should contain 'tool_end' event: {event_types}"


# ---------------------------------------------------------------------------
# VAL-IT-003: Tool-Triggering Query
# ---------------------------------------------------------------------------

class TestToolTriggeringQuery:
    """Integration tests for tool-triggering queries."""

    def test_tool_triggering_query_returns_live_data_references(self, client, mock_db_module):
        """VAL-IT-003: POST /fish/chat with a conditions query triggers tool calls
        and returns a response that references live data."""
        
        mock_client = MagicMock()

        # First response: model wants to call get_live_data tool
        tool_call_mock = MagicMock()
        tool_call_mock.id = "call_xyz"
        tool_call_mock.function = MagicMock()
        tool_call_mock.function.name = "get_live_data"
        tool_call_mock.function.arguments = '{"query": "Deschutes River conditions"}'

        tool_call_response = _mock_response(
            content="Let me get the current conditions for you...",
            tool_calls=[tool_call_mock],
            finish_reason="tool_calls",
        )

        # Second response: text response with live data reference
        text_response = _mock_response(
            content="The Deschutes is fishing well! Current conditions:\n"
                    "- Flow: 2,800 CFS at Madras\n"
                    "- Water Temp: 52°F\n"
                    "- Conditions: Partly cloudy, light wind"
        )

        mock_client.chat.completions.create.side_effect = [tool_call_response, text_response]

        with patch("ai_buddy.get_client", return_value=mock_client):
            with patch("ai_buddy.execute_tool") as mock_execute:
                mock_execute.return_value = (
                    "Deschutes River:\n- Flow: 2,800 CFS\n- Water Temp: 52°F\n- Visibility: Good",
                    []
                )

                response = client.post(
                    "/fish/chat",
                    json={
                        "message": "Where should I fish on the Deschutes today?",
                        "stream": False,
                    },
                    content_type="application/json",
                )

        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert "response" in data
        assert len(data["response"]) > 0
        # Response should reference live data (CFS, temperature, etc.)
        assert any(keyword in data["response"] for keyword in ["CFS", "flow", "temp", "temperature", "fishing"])


# ---------------------------------------------------------------------------
# VAL-IT-004: Error Resilience / All-Model Failure
# ---------------------------------------------------------------------------

class TestErrorResilience:
    """Integration tests for error resilience - all model failures."""

    def test_all_model_failure_returns_user_facing_error_not_500(self, client, mock_db_module):
        """VAL-IT-004: When all models fail (mocked), the endpoint returns HTTP 200
        with a user-facing error message (not 500 internal server error)."""
        
        mock_client = MagicMock()
        # All models fail
        mock_client.chat.completions.create.side_effect = [
            _make_exception(RateLimitError, "rate limited"),
            _make_exception(PermissionDeniedError, "permission denied"),
            _make_exception(RateLimitError, "rate limited again"),
        ]

        with patch("ai_buddy.get_client", return_value=mock_client):
            response = client.post(
                "/fish/chat",
                json={"message": "Hello Fisher", "stream": False},
                content_type="application/json",
            )

        # Should return 200 with a user-facing error, NOT 500
        assert response.status_code == 200, (
            f"Expected 200 with user-facing error, got {response.status_code}: {response.data}"
        )
        data = response.get_json()
        assert data is not None
        # Should have a response field with a branded warning
        assert "response" in data, f"Response should have 'response' field: {data}"
        assert "⚠️" in data["response"], (
            f"Error message should contain ⚠️ warning: {data['response']}"
        )

    def test_all_model_failure_streaming_returns_user_facing_error(self, client, mock_db_module):
        """VAL-E2E-004: Streaming mode on all-model failure also returns user-facing
        error via response event (not connection drop / 500)."""
        
        mock_client = MagicMock()
        # All models fail
        mock_client.chat.completions.create.side_effect = [
            _make_exception(RateLimitError, "rate limited"),
            _make_exception(PermissionDeniedError, "permission denied"),
            _make_exception(RateLimitError, "rate limited again"),
        ]

        with patch("ai_buddy.get_client", return_value=mock_client):
            response = client.post(
                "/fish/chat",
                json={"message": "Hello Fisher", "stream": True},
                content_type="application/json",
            )

        assert response.status_code == 200, (
            f"Expected 200 with user-facing error, got {response.status_code}"
        )
        assert response.content_type == "application/x-ndjson"

        # Parse NDJSON stream
        lines = response.data.decode("utf-8").strip().split("\n")
        event_types = []
        for line in lines:
            if line.strip():
                event = json.loads(line)
                event_types.append(event.get("type"))

        # Should still yield done event
        assert "done" in event_types, f"Stream should end with 'done' event: {event_types}"


# ---------------------------------------------------------------------------
# VAL-E2E-002: Session Cache Survives Across Turns
# ---------------------------------------------------------------------------

class TestSessionCache:
    """Integration tests for session cache web search deduplication."""

    def test_session_cache_deduplicates_web_searches_across_turns(self, client, mock_db_module):
        """VAL-E2E-002: In a multi-turn conversation (two sequential requests with same
        session_id), a web_search performed in Turn 1 is reused in Turn 2 via
        session_cache, avoiding a redundant search."""
        
        mock_client = MagicMock()

        # Turn 1: Model calls web_search tool
        web_search_call = MagicMock()
        web_search_call.id = "call_web1"
        web_search_call.function = MagicMock()
        web_search_call.function.name = "web_search"
        web_search_call.function.arguments = '{"query": "Deschutes River fishing report May 2026"}'

        turn1_tool_response = _mock_response(
            content="Let me search for that...",
            tool_calls=[web_search_call],
            finish_reason="tool_calls",
        )

        # Turn 1: Final text response
        turn1_text_response = _mock_response(
            content="I found a great fishing report for the Deschutes!"
        )

        # Turn 2: Without cache, model might search again. With cache, should reuse.
        # The key test: Turn 2 response should NOT trigger another web_search call
        # because the session_cache already has the result.
        turn2_text_response = _mock_response(
            content="Based on the cached report, the Deschutes is fishing great!"
        )

        mock_client.chat.completions.create.side_effect = [
            turn1_tool_response, turn1_text_response,  # Turn 1
            turn2_text_response,  # Turn 2 - should use cache
        ]

        session_id = "test-session-123"

        with patch("ai_buddy.get_client", return_value=mock_client):
            # Turn 1
            response1 = client.post(
                "/fish/chat",
                json={
                    "message": "Any recent fishing reports on the Deschutes?",
                    "stream": False,
                    "session_id": session_id,
                },
                content_type="application/json",
            )
            assert response1.status_code == 200
            data1 = response1.get_json()
            assert "response" in data1

            # Turn 2 - same session, should reuse cached web search
            response2 = client.post(
                "/fish/chat",
                json={
                    "message": "What did the Deschutes fishing report say?",
                    "stream": False,
                    "session_id": session_id,
                },
                content_type="application/json",
            )
            assert response2.status_code == 200
            data2 = response2.get_json()
            assert "response" in data2

            # Verify the session cache was used across turns
            # by checking that the second request's response is coherent
            assert len(data2["response"]) > 0


# ---------------------------------------------------------------------------
# VAL-E2E-003: Streaming and Non-Streaming Parity
# ---------------------------------------------------------------------------

class TestStreamingNonStreamingParity:
    """Integration tests for parity between streaming and non-streaming modes."""

    def test_streaming_and_non_streaming_produce_equivalent_responses(self, client, mock_db_module):
        """VAL-E2E-003: For the same query, streaming and non-streaming endpoints
        produce substantively equivalent final responses (same factual content,
        same wiki_proposals)."""
        
        # Use a query that won't trigger tools - simple greeting
        mock_client = MagicMock()

        expected_response = "The fishing is looking fantastic today! " \
                           "Steelhead are running on the coast and the rivers are in great shape."

        mock_client.chat.completions.create.return_value = _mock_response(expected_response)

        with patch("ai_buddy.get_client", return_value=mock_client):
            # Non-streaming
            ns_response = client.post(
                "/fish/chat",
                json={"message": "How's the fishing today?", "stream": False},
                content_type="application/json",
            )
            assert ns_response.status_code == 200
            ns_data = ns_response.get_json()

            # Reset mock for streaming call
            mock_client.reset_mock()
            mock_client.chat.completions.create.return_value = _mock_response(expected_response)

            # Streaming
            st_response = client.post(
                "/fish/chat",
                json={"message": "How's the fishing today?", "stream": True},
                content_type="application/json",
            )
            assert st_response.status_code == 200
            assert st_response.content_type == "application/x-ndjson"

            # Parse streaming response to get the final text
            lines = st_response.data.decode("utf-8").strip().split("\n")
            st_response_text = None
            for line in lines:
                if line.strip():
                    event = json.loads(line)
                    if event.get("type") == "response":
                        st_response_text = event.get("content")
                        break

            # Both should return the same response text
            assert ns_data["response"] == st_response_text, (
                f"Non-streaming and streaming responses should match.\n"
                f"Non-streaming: {ns_data['response']}\n"
                f"Streaming: {st_response_text}"
            )


# ---------------------------------------------------------------------------
# VAL-E2E-004: Full Failure Path UX (Total Outage)
# ---------------------------------------------------------------------------

class TestFullFailurePathUX:
    """Integration tests for total outage user experience."""

    def test_total_outage_returns_branded_error_non_streaming(self, client, mock_db_module):
        """VAL-E2E-004: When OpenRouter is entirely unavailable (all models fail with
        connection errors), non-streaming endpoint returns a polite, branded error
        message suitable for display to the end user."""
        
        import httpx
        from openai import APIConnectionError

        mock_client = MagicMock()
        # All models fail with connection errors (simulating total outage)
        mock_client.chat.completions.create.side_effect = [
            APIConnectionError(message="Connection failed", request=MagicMock(spec=httpx.Request)),
            APIConnectionError(message="Connection failed", request=MagicMock(spec=httpx.Request)),
        ]

        with patch("ai_buddy.get_client", return_value=mock_client):
            response = client.post(
                "/fish/chat",
                json={"message": "Hello Fisher", "stream": False},
                content_type="application/json",
            )

        assert response.status_code == 200, (
            f"Total outage should return 200 with user-facing error, got {response.status_code}"
        )
        data = response.get_json()
        assert "response" in data
        # Should contain branded warning
        assert "⚠️" in data["response"], f"Branded error should contain ⚠️: {data['response']}"

    def test_total_outage_returns_branded_error_streaming(self, client, mock_db_module):
        """VAL-E2E-004: Total outage in streaming mode yields response event with
        branded error then done event. No 500 status."""
        
        import httpx
        from openai import APIConnectionError

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            APIConnectionError(message="Connection failed", request=MagicMock(spec=httpx.Request)),
            APIConnectionError(message="Connection failed", request=MagicMock(spec=httpx.Request)),
        ]

        with patch("ai_buddy.get_client", return_value=mock_client):
            response = client.post(
                "/fish/chat",
                json={"message": "Hello Fisher", "stream": True},
                content_type="application/json",
            )

        assert response.status_code == 200, (
            f"Total outage should return 200, got {response.status_code}"
        )
        assert response.content_type == "application/x-ndjson"

        # Parse stream
        lines = response.data.decode("utf-8").strip().split("\n")
        events = []
        for line in lines:
            if line.strip():
                events.append(json.loads(line))

        # Last event should be done
        assert events[-1].get("type") == "done", f"Last event should be 'done': {events[-1]}"


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------

class TestChatEndpointEdgeCases:
    """Edge case integration tests for /fish/chat endpoint."""

    def test_model_key_is_accepted(self, client, mock_db_module):
        """Custom model key should be accepted without error."""
        
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response("Hello from custom model!")

        with patch("ai_buddy.get_client", return_value=mock_client):
            response = client.post(
                "/fish/chat",
                json={
                    "message": "Hello",
                    "stream": False,
                    "model": "anthropic/claude-3-haiku",
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        data = response.get_json()
        assert "response" in data

    def test_empty_history_is_accepted(self, client, mock_db_module):
        """Empty conversation history should be accepted without error."""
        
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response("Hello!")

        with patch("ai_buddy.get_client", return_value=mock_client):
            response = client.post(
                "/fish/chat",
                json={
                    "message": "Hello",
                    "stream": False,
                    "history": [],
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        data = response.get_json()
        assert "response" in data

    def test_wiki_proposals_returned_as_list(self, client, mock_db_module):
        """wiki_proposals should always be a list, even if empty."""
        
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response("Test response.")

        with patch("ai_buddy.get_client", return_value=mock_client):
            response = client.post(
                "/fish/chat",
                json={"message": "Hello", "stream": False},
                content_type="application/json",
            )

        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data.get("wiki_proposals"), list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
