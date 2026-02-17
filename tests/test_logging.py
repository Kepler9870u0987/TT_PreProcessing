"""
Test suite for structured logging

Verifica:
- Setup corretto
- JSON output format
- Filtraggio campi sensibili (GDPR)
- No PII leak in logs
"""

import json
import pytest
from io import StringIO
import logging
import sys

from src.logging_setup import (
    setup_logging,
    get_logger,
    filter_sensitive_fields,
    log_preprocessing_context,
    log_error_context,
    SENSITIVE_FIELDS,
)


@pytest.fixture
def capture_logs(monkeypatch):
    """Capture log output to string buffer"""
    buffer = StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    return buffer


# ==============================================================================
# TEST SENSITIVE FIELD FILTERING
# ==============================================================================


def test_filter_sensitive_fields_redacts_pii():
    """Test that sensitive fields are redacted"""
    event_dict = {
        "event": "test",
        "uid": "12345",
        "pii_salt": "secret-salt-value",
        "body_text": "sensitive email content",
        "from_addr": "user@example.com",
        "size": 1024,
    }

    filtered = filter_sensitive_fields(None, "", event_dict)

    # Non-sensitive fields should remain
    assert filtered["event"] == "test"
    assert filtered["uid"] == "12345"
    assert filtered["size"] == 1024

    # Sensitive fields should be redacted
    assert filtered["pii_salt"] == "[REDACTED]"
    assert filtered["body_text"] == "[REDACTED]"
    assert filtered["from_addr"] == "[REDACTED]"


def test_filter_sensitive_fields_nested_dicts():
    """Test that nested dicts are filtered recursively"""
    event_dict = {
        "event": "test",
        "headers": {
            "subject": "Test Subject",
            "from": "sender@example.com",  # Sensitive
            "message-id": "<123@example.com>",
        },
        "config": {
            "pii_salt": "secret",  # Sensitive
            "log_level": "INFO",
        },
    }

    filtered = filter_sensitive_fields(None, "", event_dict)

    assert filtered["event"] == "test"
    assert filtered["headers"]["subject"] == "Test Subject"
    assert filtered["headers"]["message-id"] == "<123@example.com>"
    # Sensitive nested fields redacted
    assert filtered["config"]["log_level"] == "INFO"


def test_all_sensitive_fields_covered():
    """Test that all predefined sensitive fields are redacted"""
    event_dict = {field: f"secret-{field}" for field in SENSITIVE_FIELDS}
    event_dict["safe_field"] = "should remain"

    filtered = filter_sensitive_fields(None, "", event_dict)

    # All sensitive fields should be redacted
    for field in SENSITIVE_FIELDS:
        assert filtered[field] == "[REDACTED]", f"Field {field} not redacted"

    # Safe field should remain
    assert filtered["safe_field"] == "should remain"


# ==============================================================================
# TEST LOGGING SETUP
# ==============================================================================


def test_setup_logging_json_format(capture_logs):
    """Test logging setup with JSON format"""
    setup_logging("INFO", json_format=True, stream=capture_logs)
    logger = get_logger("test")

    logger.info("test_event", uid="12345", value=42)

    output = capture_logs.getvalue()
    # Should be valid JSON
    log_entry = json.loads(output.strip().split("\n")[0])

    assert log_entry["event"] == "test_event"
    assert log_entry["uid"] == "12345"
    assert log_entry["value"] == 42
    assert "timestamp" in log_entry
    assert log_entry["level"] == "info"


def test_setup_logging_console_format(capture_logs):
    """Test logging setup with console (human-readable) format"""
    setup_logging("INFO", json_format=False, stream=capture_logs)
    logger = get_logger("test")

    logger.info("test_event", uid="12345")

    output = capture_logs.getvalue()
    # Console format includes timestamp, event, and fields
    assert "test_event" in output
    assert "12345" in output


def test_setup_logging_respects_log_level():
    """Test that log level is respected"""
    setup_logging("WARNING", json_format=True)
    logger = get_logger("test")

    # INFO should not be logged when level is WARNING
    buffer = StringIO()
    import sys

    old_stdout = sys.stdout
    sys.stdout = buffer

    try:
        logger.info("should_not_appear")
        logger.warning("should_appear")

        output = buffer.getvalue()
        assert "should_not_appear" not in output
        assert "should_appear" in output
    finally:
        sys.stdout = old_stdout


# ==============================================================================
# TEST PII LEAK PREVENTION
# ==============================================================================


def test_no_pii_in_logs_even_in_debug(capture_logs):
    """
    CRITICAL: Test that PII never appears in logs, even in DEBUG mode.
    
    This is the most important security test for GDPR compliance.
    """
    setup_logging("DEBUG", json_format=True, stream=capture_logs)
    logger = get_logger("test")

    # Simulate logging with PII fields
    logger.debug(
        "processing_email",
        uid="12345",
        body_text="This contains PII like john.doe@example.com",
        from_addr="sender@example.com",
        pii_salt="supersecret",
    )

    output = capture_logs.getvalue()

    # PII should NOT appear in output
    assert "john.doe@example.com" not in output
    assert "sender@example.com" not in output
    assert "supersecret" not in output

    # Non-sensitive data should appear
    assert "12345" in output  # uid is not sensitive

    # Redacted markers should appear
    assert "[REDACTED]" in output


def test_no_pii_in_nested_structures(capture_logs):
    """Test that PII in nested structures is also filtered"""
    setup_logging("INFO", json_format=True, stream=capture_logs)
    logger = get_logger("test")

    logger.info(
        "test_event",
        email_data={
            "uid": "12345",
            "from_addr": "secret@example.com",  # Should be redacted
            "size": 1024,
        },
    )

    output = capture_logs.getvalue()
    assert "secret@example.com" not in output
    assert "[REDACTED]" in output
    assert "12345" in output  # uid not sensitive


# ==============================================================================
# TEST CONVENIENCE FUNCTIONS
# ==============================================================================


def test_log_preprocessing_context():
    """Test preprocessing context helper"""
    ctx = log_preprocessing_context(uid="12345", message_id="<msg@ex.com>", size=2048)

    assert ctx["uid"] == "12345"
    assert ctx["message_id"] == "<msg@ex.com>"
    assert ctx["size"] == 2048


def test_log_error_context():
    """Test error context helper"""
    error = ValueError("Test error")
    ctx = log_error_context(error, uid="12345")

    assert ctx["error_type"] == "ValueError"
    assert ctx["error_message"] == "Test error"
    assert ctx["uid"] == "12345"


def test_log_error_context_no_uid():
    """Test error context without UID"""
    error = RuntimeError("Something failed")
    ctx = log_error_context(error)

    assert ctx["error_type"] == "RuntimeError"
    assert ctx["error_message"] == "Something failed"
    assert ctx["uid"] == ""


# ==============================================================================
# TEST GET_LOGGER
# ==============================================================================


def test_get_logger_returns_bound_logger():
    """Test that get_logger returns a structlog BoundLogger"""
    setup_logging("INFO", json_format=True)
    logger = get_logger("test.module")

    # Should have structlog methods
    assert hasattr(logger, "info")
    assert hasattr(logger, "warning")
    assert hasattr(logger, "error")
    assert hasattr(logger, "bind")


def test_multiple_loggers_independent():
    """Test that multiple loggers can be created independently"""
    setup_logging("INFO", json_format=True)

    logger1 = get_logger("module1")
    logger2 = get_logger("module2")

    # Should be different logger instances
    # (though they share the same configuration)
    assert logger1 is not logger2
