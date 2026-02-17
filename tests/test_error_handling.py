"""
Test suite for error handling & graceful degradation

Verifica:
- Fallback chain (full → regex_only → no_canon → minimal)
- Error classification (CRITICAL, HIGH, MEDIUM, LOW)
- Retry logic
- Safety utilities (truncation, validation)
"""

import pytest
import os
from unittest.mock import patch, Mock

from src.error_handling import (
    preprocess_email_safe,
    preprocess_email_regex_only,
    preprocess_email_no_canon,
    create_minimal_document,
    classify_error,
    should_retry,
    truncate_for_safety,
    is_email_processable,
    ErrorSeverity,
)
from src.models import InputEmail, EmailDocument, PreprocessingError
from src.config import reset_config_cache


@pytest.fixture
def valid_env():
    """Valid environment for config"""
    return {
        "PREPROCESSING_PII_SALT": "test-salt-for-error-handling-tests-123",
        "PREPROCESSING_PIPELINE_VERSION": "test-v1",
    }


@pytest.fixture(autouse=True)
def cleanup_config():
    """Reset config cache after each test"""
    yield
    reset_config_cache()


# ==============================================================================
# TEST FALLBACK CHAIN
# ==============================================================================


def test_preprocess_email_safe_success(valid_env):
    """Test that safe preprocessing succeeds for valid email"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = InputEmail(
            message_id="<test@example.com>",
            headers_raw="From: sender@example.com\n\n",
            body_text="Test email body",
        )
        
        result = preprocess_email_safe(input_email)
        
        assert isinstance(result, EmailDocument)
        assert result.message_id == "<test@example.com>"


def test_preprocess_email_safe_never_raises(valid_env):
    """Test that safe preprocessing NEVER raises (always returns document)"""
    with patch.dict(os.environ, valid_env, clear=True):
        # Even with problematic input
        input_email = InputEmail(
            message_id="<problem@example.com>",
            headers_raw="Invalid\x00Header",
            body_text="Body",
        )
        
        # Should not raise
        result = preprocess_email_safe(input_email)
        
        assert isinstance(result, EmailDocument)


def test_preprocess_email_regex_only(valid_env):
    """Test regex-only preprocessing"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = InputEmail(
            message_id="<regex@example.com>",
            headers_raw="From: test@example.com\n\n",
            body_text="Email: contact@example.com",
        )
        
        result = preprocess_email_regex_only(input_email)
        
        assert isinstance(result, EmailDocument)
        # Should have redacted PII
        assert "contact@example.com" not in result.body_text or "[PII_EMAIL]" in result.body_text
        # Pipeline version should indicate regex-only
        assert "regex-only" in result.pipeline_version.version


def test_preprocess_email_no_canon(valid_env):
    """Test preprocessing without canonicalization"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = InputEmail(
            message_id="<no-canon@example.com>",
            headers_raw="From: sender@example.com\n\n",
            body_text="""
Body text here.

> Quoted text should remain
            """,
        )
        
        result = preprocess_email_no_canon(input_email)
        
        assert isinstance(result, EmailDocument)
        # Quoted text NOT removed (no canonicalization)
        assert "Quoted text" in result.body_text
        # Pipeline version should indicate no-canon
        assert "no-canon" in result.pipeline_version.version


def test_create_minimal_document(valid_env):
    """Test minimal document creation"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = InputEmail(
            message_id="<minimal@example.com>",
            headers_raw="From: sender@example.com\n\n",
            body_text="Raw body text",
        )
        
        result = create_minimal_document(input_email)
        
        assert isinstance(result, EmailDocument)
        assert result.message_id == "<minimal@example.com>"
        assert result.body_text == "Raw body text"
        assert "minimal" in result.pipeline_version.version
        # No PII redactions
        assert len(result.pii_redactions) == 0


def test_create_minimal_document_with_bad_headers(valid_env):
    """Test minimal document handles bad headers gracefully"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = InputEmail(
            message_id="<bad-headers@example.com>",
            headers_raw="Totally\x00Invalid\nHeaders",
            body_text="Body",
        )
        
        # Should not raise
        result = create_minimal_document(input_email)
        
        assert isinstance(result, EmailDocument)
        assert "from" in result.headers  # Fallback headers


def test_create_minimal_document_empty_body(valid_env):
    """Test minimal document with empty body"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = InputEmail(
            message_id="<empty@example.com>",
            headers_raw="From: sender@example.com\n\n",
            body_text="",
        )
        
        result = create_minimal_document(input_email)
        
        assert isinstance(result, EmailDocument)
        assert "[BODY UNAVAILABLE]" in result.body_text


# ==============================================================================
# TEST ERROR CLASSIFICATION
# ==============================================================================


def test_classify_error_critical():
    """Test classification of critical errors"""
    errors = [
        MemoryError("Out of memory"),
        Exception("memory allocation failed"),
    ]
    
    for error in errors:
        severity = classify_error(error)
        assert severity == ErrorSeverity.CRITICAL


def test_classify_error_high():
    """Test classification of high-severity errors"""
    errors = [
        Exception("PII detection failed"),
        Exception("Parse error in headers"),
    ]
    
    for error in errors:
        severity = classify_error(error)
        assert severity == ErrorSeverity.HIGH


def test_classify_error_medium():
    """Test classification of medium-severity errors"""
    errors = [
        TimeoutError("Regex timeout"),
        Exception("Canonicalization failed"),
    ]
    
    for error in errors:
        severity = classify_error(error)
        assert severity == ErrorSeverity.MEDIUM


def test_classify_error_low():
    """Test classification of low-severity errors"""
    error = Exception("Some minor issue")
    severity = classify_error(error)
    assert severity == ErrorSeverity.LOW


# ==============================================================================
# TEST RETRY LOGIC
# ==============================================================================


def test_should_retry_under_max_attempts():
    """Test retry allowed under max attempts"""
    error = Exception("Transient error")
    
    assert should_retry(error, attempt=1, max_attempts=3) is True
    assert should_retry(error, attempt=2, max_attempts=3) is True


def test_should_retry_at_max_attempts():
    """Test no retry at max attempts"""
    error = Exception("Transient error")
    
    assert should_retry(error, attempt=3, max_attempts=3) is False


def test_should_retry_critical_error():
    """Test no retry for critical errors"""
    error = MemoryError("Out of memory")
    
    assert should_retry(error, attempt=1, max_attempts=3) is False


def test_should_retry_validation_error():
    """Test no retry for validation errors (deterministic)"""
    error = Exception("Validation failed: invalid input")
    
    assert should_retry(error, attempt=1, max_attempts=3) is False


# ==============================================================================
# TEST SAFETY UTILITIES
# ==============================================================================


def test_truncate_for_safety_small_text():
    """Test that small text is not truncated"""
    text = "Small text"
    
    result = truncate_for_safety(text, max_kb=500)
    
    assert result == text


def test_truncate_for_safety_large_text():
    """Test that large text is truncated"""
    text = "A" * 600_000  # 600KB
    
    result = truncate_for_safety(text, max_kb=500)
    
    # Should be truncated
    assert len(result) < len(text)
    assert "[TEXT TRUNCATED FOR MEMORY SAFETY]" in result


def test_truncate_for_safety_exact_limit():
    """Test text at exact limit"""
    text = "A" * (500 * 1024)  # Exactly 500KB
    
    result = truncate_for_safety(text, max_kb=500)
    
    # Should not be truncated (exactly at limit)
    assert result == text


def test_truncate_for_safety_unicode():
    """Test truncation with Unicode text"""
    text = "è" * 300_000  # Unicode chars, ~600KB
    
    result = truncate_for_safety(text, max_kb=500)
    
    # Should be truncated gracefully (no encoding errors)
    assert len(result) < len(text)


# ==============================================================================
# TEST EMAIL VALIDATION
# ==============================================================================


def test_is_email_processable_valid():
    """Test validation of valid email"""
    email = InputEmail(
        message_id="<test@example.com>",
        headers_raw="From: sender@example.com\n\n",
        body_text="Body text",
    )
    
    is_valid, error = is_email_processable(email)
    
    assert is_valid is True
    assert error is None


def test_is_email_processable_missing_message_id():
    """Test validation fails for missing message_id"""
    email = InputEmail(
        message_id="",
        headers_raw="From: sender@example.com\n\n",
        body_text="Body",
    )
    
    is_valid, error = is_email_processable(email)
    
    assert is_valid is False
    assert "message_id" in error


def test_is_email_processable_empty_body():
    """Test validation fails for empty body"""
    email = InputEmail(
        message_id="<test@example.com>",
        headers_raw="From: sender@example.com\n\n",
        body_text="",
        raw_bytes=None,
    )
    
    is_valid, error = is_email_processable(email)
    
    assert is_valid is False
    assert "empty" in error.lower()


def test_is_email_processable_invalid_headers_type():
    """Test validation fails for invalid headers type"""
    # Note: This requires bypassing dataclass validation
    # In practice, this would be caught earlier
    email = InputEmail(
        message_id="<test@example.com>",
        headers_raw="Valid headers\n\n",
        body_text="Body",
    )
    
    # Simulate invalid headers type
    email.headers_raw = 12345  # type: ignore
    
    is_valid, error = is_email_processable(email)
    
    assert is_valid is False


def test_is_email_processable_with_raw_bytes():
    """Test validation succeeds with raw_bytes (no body_text)"""
    email = InputEmail(
        message_id="<test@example.com>",
        headers_raw="From: sender@example.com\n\n",
        body_text="",
        raw_bytes=b"Raw email content",
    )
    
    is_valid, error = is_email_processable(email)
    
    assert is_valid is True


# ==============================================================================
# TEST EDGE CASES
# ==============================================================================


def test_fallback_chain_order(valid_env):
    """Test that fallback chain progresses correctly"""
    with patch.dict(os.environ, valid_env, clear=True):
        # Create email
        input_email = InputEmail(
            message_id="<fallback@example.com>",
            headers_raw="From: sender@example.com\n\n",
            body_text="Test",
        )
        
        # All fallback methods should work
        result_safe = preprocess_email_safe(input_email)
        result_regex = preprocess_email_regex_only(input_email)
        result_no_canon = preprocess_email_no_canon(input_email)
        result_minimal = create_minimal_document(input_email)
        
        # All should produce valid documents
        assert isinstance(result_safe, EmailDocument)
        assert isinstance(result_regex, EmailDocument)
        assert isinstance(result_no_canon, EmailDocument)
        assert isinstance(result_minimal, EmailDocument)


def test_error_severity_levels():
    """Test all error severity levels are defined"""
    assert ErrorSeverity.CRITICAL == "critical"
    assert ErrorSeverity.HIGH == "high"
    assert ErrorSeverity.MEDIUM == "medium"
    assert ErrorSeverity.LOW == "low"
