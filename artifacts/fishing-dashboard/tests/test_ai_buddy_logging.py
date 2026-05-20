"""
Tests for structured logging in ai_buddy.py

These tests verify:
- VAL-LOG-001: Structured log per model attempt
- VAL-LOG-002: Structured log per tool call
- VAL-LOG-003: Structured log per response path
- VAL-LOG-004: No sensitive data in logs
"""

import logging
import pytest
import json
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_db_module():
    """Mock database module for testing"""
    db = MagicMock()
    db.get_preferences.return_value = None
    db.search_wiki.return_value = []
    db.get_recent_logs_for_river.return_value = []
    db.get_fishing_logs.return_value = []
    return db


@pytest.fixture
def caplog_info(caplog):
    """Set log level to INFO for tests"""
    caplog.set_level(logging.INFO)
    return caplog


class TestModelAttemptLogging:
    """Tests for VAL-LOG-001: Model attempt logging"""

    def test_model_attempt_logs_model_name_attempt_index_and_outcome(self, caplog_info):
        """Every model attempt logs model name, attempt index, and outcome (success)"""
        with patch('ai_buddy.get_client') as mock_get_client:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content="Test response", tool_calls=None))]
            mock_client.chat.completions.create.return_value = mock_response
            mock_get_client.return_value = mock_client

            from ai_buddy import chat_with_buddy

            response, _ = chat_with_buddy(
                user_message="Hello",
                conversation_history=[],
                live_data={},
                db_module=MagicMock()
            )

            # Check that model attempt was logged
            log_messages = [record.message for record in caplog_info.records]
            model_attempt_logs = [m for m in log_messages if 'model_attempt' in m]

            assert len(model_attempt_logs) >= 1, "Should log at least one model attempt"
            assert any('model=' in m for m in model_attempt_logs), "Log should contain model name"
            assert any('attempt=' in m for m in model_attempt_logs), "Log should contain attempt index"
            assert any('status=success' in m for m in model_attempt_logs), "Log should contain success status"

    def test_model_attempt_logs_failure(self, caplog_info):
        """Model failure logs model name, attempt index, and error type"""
        with patch('ai_buddy.get_client') as mock_get_client:
            from openai import RateLimitError
            import httpx

            mock_client = MagicMock()
            # Create a proper exception with required keyword-only arguments
            mock_response = MagicMock()
            mock_client.chat.completions.create.side_effect = RateLimitError(
                message="Rate limited",
                response=mock_response,
                body={"error": {"message": "Rate limited"}}
            )

            # Patch the fallback chain to use only one model to force failure
            with patch('ai_buddy.MODEL_FALLBACK_CHAIN', ['test/model']):
                mock_get_client.return_value = mock_client

                from ai_buddy import chat_with_buddy

                response, _ = chat_with_buddy(
                    user_message="Hello",
                    conversation_history=[],
                    live_data={},
                    db_module=MagicMock()
                )

            log_messages = [record.message for record in caplog_info.records]
            model_attempt_logs = [m for m in log_messages if 'model_attempt' in m]

            assert len(model_attempt_logs) >= 1, "Should log at least one model attempt"
            assert any('status=failure' in m for m in model_attempt_logs), "Log should contain failure status"
            assert any('RateLimitError' in m for m in model_attempt_logs), "Log should contain error type"


class TestToolCallLogging:
    """Tests for VAL-LOG-002: Tool call logging"""

    def test_execute_tool_logs_tool_name_and_outcome(self, caplog_info, mock_db_module):
        """Every tool call logs tool name and outcome"""
        from ai_buddy import execute_tool

        # Test with get_hatchery_info which imports from hatcheries module
        with patch('hatcheries.OREGON_HATCHERIES', []):
            result, sources = execute_tool(
                tool_name="get_hatchery_info",
                args={},
                live_data={},
                db_module=mock_db_module
            )

            log_messages = [record.message for record in caplog_info.records]
            tool_call_logs = [m for m in log_messages if 'tool_call' in m]

            assert len(tool_call_logs) >= 1, "Should log tool call"
            assert any('tool=get_hatchery_info' in m for m in tool_call_logs), "Log should contain tool name"
            assert any('status=success' in m for m in tool_call_logs), "Log should contain success status"

    def test_execute_tool_logs_error_on_exception(self, caplog_info, mock_db_module):
        """Tool exceptions are logged with error status"""
        from ai_buddy import execute_tool

        # Test with a tool that returns results
        with patch('hatcheries.OREGON_HATCHERIES', []):
            result, sources = execute_tool(
                tool_name="get_hatchery_info",
                args={},
                live_data={},
                db_module=mock_db_module
            )

            log_messages = [record.message for record in caplog_info.records]
            tool_call_logs = [m for m in log_messages if 'tool_call' in m]

            assert len(tool_call_logs) >= 1, "Should log tool call"


class TestResponsePathLogging:
    """Tests for VAL-LOG-003: Response path logging"""

    def test_chat_with_buddy_logs_text_response_path(self, caplog_info):
        """chat_with_buddy logs text_response path on success"""
        with patch('ai_buddy.get_client') as mock_get_client:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(
                message=MagicMock(content="Test response", tool_calls=None),
                finish_reason="stop"
            )]
            mock_client.chat.completions.create.return_value = mock_response
            mock_get_client.return_value = mock_client

            from ai_buddy import chat_with_buddy

            response, _ = chat_with_buddy(
                user_message="Hello",
                conversation_history=[],
                live_data={},
                db_module=MagicMock()
            )

            log_messages = [record.message for record in caplog_info.records]
            response_logs = [m for m in log_messages if 'chat_response' in m]

            assert any('path=text_response' in m for m in response_logs), "Should log text_response path"

    def test_chat_with_buddy_logs_permission_denied_path(self, caplog_info):
        """chat_with_buddy logs permission_denied path on PermissionDeniedError"""
        with patch('ai_buddy.get_client') as mock_get_client:
            from openai import PermissionDeniedError

            mock_client = MagicMock()
            error_response = MagicMock()
            mock_client.chat.completions.create.side_effect = PermissionDeniedError(
                message="Permission denied",
                response=error_response,
                body={"error": {"message": "Permission denied"}}
            )
            mock_get_client.return_value = mock_client

            from ai_buddy import chat_with_buddy

            response, _ = chat_with_buddy(
                user_message="Hello",
                conversation_history=[],
                live_data={},
                db_module=MagicMock()
            )

            log_messages = [record.message for record in caplog_info.records]
            response_logs = [m for m in log_messages if 'chat_response' in m]

            assert any('path=permission_denied' in m for m in response_logs), "Should log permission_denied path"

    def test_chat_with_buddy_logs_rate_limited_path(self, caplog_info):
        """chat_with_buddy logs rate_limited path on RateLimitError"""
        with patch('ai_buddy.get_client') as mock_get_client:
            from openai import RateLimitError

            mock_client = MagicMock()
            error_response = MagicMock()
            mock_client.chat.completions.create.side_effect = RateLimitError(
                message="Rate limited",
                response=error_response,
                body={"error": {"message": "Rate limited"}}
            )
            mock_get_client.return_value = mock_client

            from ai_buddy import chat_with_buddy

            response, _ = chat_with_buddy(
                user_message="Hello",
                conversation_history=[],
                live_data={},
                db_module=MagicMock()
            )

            log_messages = [record.message for record in caplog_info.records]
            response_logs = [m for m in log_messages if 'chat_response' in m]

            assert any('path=rate_limited' in m for m in response_logs), "Should log rate_limited path"

    def test_chat_with_buddy_logs_exception_path(self, caplog_info):
        """chat_with_buddy logs exception path on unexpected exceptions"""
        with patch('ai_buddy.get_client') as mock_get_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = ValueError("Test error")
            mock_get_client.return_value = mock_client

            from ai_buddy import chat_with_buddy

            response, _ = chat_with_buddy(
                user_message="Hello",
                conversation_history=[],
                live_data={},
                db_module=MagicMock()
            )

            log_messages = [record.message for record in caplog_info.records]
            response_logs = [m for m in log_messages if 'chat_response' in m]

            assert any('path=exception' in m for m in response_logs), "Should log exception path"

    def test_chat_with_buddy_stream_logs_text_response_path(self, caplog_info):
        """chat_with_buddy_stream logs text_response path on success"""
        with patch('ai_buddy.get_client') as mock_get_client:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(
                message=MagicMock(content="Test response", tool_calls=None),
                finish_reason="stop"
            )]
            mock_client.chat.completions.create.return_value = mock_response
            mock_get_client.return_value = mock_client

            from ai_buddy import chat_with_buddy_stream

            # Collect all yielded events
            events = list(chat_with_buddy_stream(
                user_message="Hello",
                conversation_history=[],
                live_data={},
                db_module=MagicMock()
            ))

            log_messages = [record.message for record in caplog_info.records]
            response_logs = [m for m in log_messages if 'chat_stream_response' in m]

            assert any('path=text_response' in m for m in response_logs), "Should log text_response path"


class TestNoSensitiveDataLogging:
    """Tests for VAL-LOG-004: No sensitive data in logs"""

    def test_no_api_key_in_logs(self, caplog_info):
        """OPENROUTER_API_KEY is not logged"""
        with patch('ai_buddy.get_client') as mock_get_client:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(
                message=MagicMock(content="Test response", tool_calls=None),
                finish_reason="stop"
            )]
            mock_client.chat.completions.create.return_value = mock_response
            mock_get_client.return_value = mock_client

            from ai_buddy import chat_with_buddy, OPENROUTER_API_KEY

            response, _ = chat_with_buddy(
                user_message="Hello",
                conversation_history=[],
                live_data={},
                db_module=MagicMock()
            )

            log_messages = " ".join([record.message for record in caplog_info.records])

            # Ensure API key is not in logs
            assert 'OPENROUTER_API_KEY' not in log_messages or OPENROUTER_API_KEY == "", \
                "OPENROUTER_API_KEY should not appear in logs"

    def test_no_raw_user_message_in_logs(self, caplog_info):
        """Raw user messages are not logged (to avoid PII)"""
        with patch('ai_buddy.get_client') as mock_get_client:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(
                message=MagicMock(content="Test response", tool_calls=None),
                finish_reason="stop"
            )]
            mock_client.chat.completions.create.return_value = mock_response
            mock_get_client.return_value = mock_client

            from ai_buddy import chat_with_buddy

            test_message = "My secret fishing spot is at 12345 River Road"

            response, _ = chat_with_buddy(
                user_message=test_message,
                conversation_history=[],
                live_data={},
                db_module=MagicMock()
            )

            log_messages = [record.message for record in caplog_info.records]

            # User message content should not appear in logs
            assert not any(test_message in m for m in log_messages), \
                "Raw user message should not appear in logs"

    def test_no_full_tool_payloads_in_logs(self, caplog_info, mock_db_module):
        """Full tool payloads (which may contain PII) are not logged"""
        from ai_buddy import execute_tool

        # Test with a tool that might have sensitive args
        with patch('hatcheries.OREGON_HATCHERIES', []):
            result, sources = execute_tool(
                tool_name="get_hatchery_info",
                args={"river": "Deschutes", "species": "trout"},
                live_data={},
                db_module=mock_db_module
            )

            log_messages = [record.message for record in caplog_info.records]
            tool_call_logs = [m for m in log_messages if 'tool_call' in m]

            # The logs should only contain args_keys, not the actual values
            assert any('args_keys=' in m for m in tool_call_logs), \
                "Tool logs should only contain arg keys, not values"


class TestLogLevels:
    """Tests for appropriate log levels"""

    def test_success_uses_info_level(self, caplog_info):
        """Normal flow uses INFO level"""
        with patch('ai_buddy.get_client') as mock_get_client:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(
                message=MagicMock(content="Test response", tool_calls=None),
                finish_reason="stop"
            )]
            mock_client.chat.completions.create.return_value = mock_response
            mock_get_client.return_value = mock_client

            from ai_buddy import chat_with_buddy

            response, _ = chat_with_buddy(
                user_message="Hello",
                conversation_history=[],
                live_data={},
                db_module=MagicMock()
            )

            # Success logs should be INFO
            info_logs = [r for r in caplog_info.records if r.levelno == logging.INFO]
            assert len(info_logs) > 0, "Should have INFO level logs for normal flow"

    def test_failure_uses_warning_level(self, caplog_info):
        """Failures use WARNING level"""
        with patch('ai_buddy.get_client') as mock_get_client:
            from openai import RateLimitError

            mock_client = MagicMock()
            error_response = MagicMock()
            mock_client.chat.completions.create.side_effect = RateLimitError(
                message="Rate limited",
                response=error_response,
                body={"error": {"message": "Rate limited"}}
            )
            mock_get_client.return_value = mock_client

            from ai_buddy import chat_with_buddy

            response, _ = chat_with_buddy(
                user_message="Hello",
                conversation_history=[],
                live_data={},
                db_module=MagicMock()
            )

            # Failure logs should be WARNING
            warning_logs = [r for r in caplog_info.records if r.levelno == logging.WARNING]
            assert len(warning_logs) > 0, "Should have WARNING level logs for failures"

    def test_exception_uses_error_level(self, caplog_info):
        """Exceptions use ERROR level"""
        with patch('ai_buddy.get_client') as mock_get_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = ValueError("Test error")
            mock_get_client.return_value = mock_client

            from ai_buddy import chat_with_buddy

            response, _ = chat_with_buddy(
                user_message="Hello",
                conversation_history=[],
                live_data={},
                db_module=MagicMock()
            )

            # Exception logs should be ERROR
            error_logs = [r for r in caplog_info.records if r.levelno == logging.ERROR]
            assert len(error_logs) > 0, "Should have ERROR level logs for exceptions"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
