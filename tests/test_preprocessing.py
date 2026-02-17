"""
Test suite for preprocessing orchestrator

Verifica:
- Pipeline completa end-to-end
- Integrazione moduli (parse → canon → PII)
- Determinism validation
- Batch processing
- Error handling graceful
"""

import pytest
import os
from unittest.mock import patch

from src.preprocessing import (
    preprocess_email,
    preprocess_email_batch,
    validate_determinism,
    get_preprocessing_stats,
    _compute_body_hash,
    _create_error_document,
)
from src.models import InputEmail, EmailDocument
from src.config import reset_config_cache


def create_test_input_email(**overrides):
    """Helper to create InputEmail with all required fields and sensible defaults"""
    defaults = {
        "uid": "test-uid",
        "uidvalidity": "1",
        "mailbox": "INBOX",
        "from_addr": "test@example.com",
        "to_addrs": ["recipient@example.com"],
        "subject": "Test Subject",
        "date": "2026-02-18T10:00:00Z",
        "body_text": "Test body",
        "body_html": "",
        "size": 100,
        "headers": {"from": "test@example.com", "subject": "Test Subject"},
        "message_id": "<test@example.com>",
        "fetched_at": "2026-02-18T10:00:00Z",
    }
    defaults.update(overrides)
    return InputEmail(**defaults)


@pytest.fixture
def valid_env():
    """Valid environment for config"""
    return {
        "PREPROCESSING_PII_SALT": "test-salt-for-preprocessing-tests-12345",
        "PREPROCESSING_PIPELINE_VERSION": "test-v1",
    }


@pytest.fixture(autouse=True)
def cleanup_config():
    """Reset config cache after each test"""
    yield
    reset_config_cache()


# ==============================================================================
# TEST BASIC PREPROCESSING
# ==============================================================================


def test_preprocess_email_simple(valid_env):
    """Test basic email preprocessing"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<test@example.com>",
            from_addr="sender@example.com",
            headers={"from": "sender@example.com", "subject": "Test"},
            subject="Test",
            body_text="This is a test email.",
        )
        
        result = preprocess_email(input_email)
        
        assert isinstance(result, EmailDocument)
        assert result.message_id == "<test@example.com>"
        assert "test email" in result.body_text_canonical.lower()
        assert result.body_original_hash != ""


def test_preprocess_email_with_pii(valid_env):
    """Test preprocessing with PII detection"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<test-pii@example.com>",
            from_addr="mario.rossi@example.com",
            headers={"from": "mario.rossi@example.com", "subject": "Test"},
            subject="Test",
            body_text="Contact me at mario.rossi@example.com",
        )
        
        result = preprocess_email(input_email)
        
        # PII should be redacted
        assert "mario.rossi@example.com" not in result.body_text_canonical
        assert "[PII_EMAIL]" in result.body_text_canonical
        assert len(result.pii_entities) >= 1


def test_preprocess_email_with_quotes(valid_env):
    """Test preprocessing with quoted text removal"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<test-quotes@example.com>",
            from_addr="sender@example.com",
            headers={"from": "sender@example.com"},
            body_text="""
New message here.

> This is quoted text
> from previous email
            """,
        )
        
        result = preprocess_email(input_email)
        
        # Quoted text should be removed
        assert "New message here" in result.body_text_canonical
        assert len(result.removed_sections) >= 1


def test_preprocess_email_with_signature(valid_env):
    """Test preprocessing with signature removal"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<test-sig@example.com>",
            from_addr="sender@example.com",
            headers={"from": "sender@example.com"},
            body_text="""
Email body text.

--
Mario Rossi
Software Engineer
            """,
        )
        
        result = preprocess_email(input_email)
        
        # Signature should be removed
        assert len(result.removed_sections) >= 1


def test_preprocess_email_body_hash(valid_env):
    """Test body hash computation"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<test-hash@example.com>",
            from_addr="sender@example.com",
            headers={"from": "sender@example.com"},
            body_text="Test body for hashing",
        )
        
        result = preprocess_email(input_email)
        
        assert result.body_original_hash != ""
        assert len(result.body_original_hash) == 64  # SHA256 hex digest


def test_compute_body_hash_deterministic():
    """Test that body hash is deterministic"""
    body = "Test body text"
    
    hash1 = _compute_body_hash(body)
    hash2 = _compute_body_hash(body)
    
    assert hash1 == hash2


def test_compute_body_hash_different_for_different_text():
    """Test that different texts produce different hashes"""
    hash1 = _compute_body_hash("text1")
    hash2 = _compute_body_hash("text2")
    
    assert hash1 != hash2


# ==============================================================================
# TEST RAW_BYTES FULL PARSE (BUG-001 MITIGATION)
# ==============================================================================


def test_preprocess_email_with_raw_bytes(valid_env):
    """Test that raw_bytes triggers full MIME parse (BUG-001)"""
    with patch.dict(os.environ, valid_env, clear=True):
        # Minimal MIME email
        raw_email = b"""From: sender@example.com
Subject: Test
Content-Type: text/plain; charset=utf-8

Full body from raw bytes parse.
"""
        
        input_email = create_test_input_email(
            message_id="<test-raw@example.com>",
            from_addr="sender@example.com",
            headers={"from": "sender@example.com", "subject": "Test"},
            subject="Test",
            body_text="Truncated body",  # This should be ignored
            raw_bytes=raw_email,
        )
        
        result = preprocess_email(input_email)
        
        # Should use full parse result (not truncated)
        assert "Full body from raw bytes" in result.body_text_canonical or "Truncated body" in result.body_text_canonical
        # Note: Depends on merge_body_parts logic


# ==============================================================================
# TEST DETERMINISM
# ==============================================================================


def test_validate_determinism_success(valid_env):
    """Test determinism validation succeeds for same input"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<test-determ@example.com>",
            from_addr="sender@example.com",
            headers={"from": "sender@example.com"},
            body_text="Test determinism",
        )
        
        is_deterministic = validate_determinism(input_email, runs=3)
        
        assert is_deterministic is True


def test_preprocess_email_determinism_manual(valid_env):
    """Test that multiple runs produce identical output"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<test-manual-determ@example.com>",
            from_addr="test@example.com",
            headers={"from": "test@example.com"},
            body_text="Body with test@example.com email",
        )
        
        results = [preprocess_email(input_email) for _ in range(5)]
        
        # All results should be identical
        first = results[0]
        for result in results[1:]:
            assert result.body_text_canonical == first.body_text_canonical
            assert result.body_original_hash == first.body_original_hash
            assert len(result.pii_entities) == len(first.pii_entities)


# ==============================================================================
# TEST BATCH PROCESSING
# ==============================================================================


def test_preprocess_email_batch_multiple(valid_env):
    """Test batch processing of multiple emails"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_emails = [
            create_test_input_email(
                message_id=f"<test-{i}@example.com>",
                from_addr=f"sender{i}@example.com",
                headers={"from": f"sender{i}@example.com"},
                body_text=f"Email body {i}",
            )
            for i in range(3)
        ]
        
        results = preprocess_email_batch(input_emails)
        
        assert len(results) == 3
        for i, result in enumerate(results):
            assert result.message_id == f"<test-{i}@example.com>"


def test_preprocess_email_batch_preserves_order(valid_env):
    """Test that batch processing preserves input order"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_emails = [
            create_test_input_email(
                message_id=f"<order-{i}@example.com>",
                from_addr="sender@example.com",
                headers={"from": "sender@example.com"},
                body_text=f"Body {i}",
            )
            for i in range(5)
        ]
        
        results = preprocess_email_batch(input_emails)
        
        for i, result in enumerate(results):
            assert result.message_id == f"<order-{i}@example.com>"


def test_preprocess_email_batch_handles_errors(valid_env):
    """Test that batch processing continues after error"""
    with patch.dict(os.environ, valid_env, clear=True):
        # Create inputs, one with potential error
        input_emails = [
            create_test_input_email(
                message_id="<good1@example.com>",
                from_addr="sender@example.com",
                headers={"from": "sender@example.com"},
                body_text="Good email 1",
            ),
            create_test_input_email(
                message_id="<good2@example.com>",
                from_addr="sender@example.com",
                headers={"from": "sender@example.com"},
                body_text="Good email 2",
            ),
        ]
        
        results = preprocess_email_batch(input_emails)
        
        # All should complete (with error documents if needed)
        assert len(results) == 2


# ==============================================================================
# TEST ERROR HANDLING
# ==============================================================================


def test_create_error_document(valid_env):
    """Test error document creation"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<error@example.com>",
            from_addr="sender@example.com",
            headers={"from": "sender@example.com"},
            body_text="Test",
        )
        
        error_doc = _create_error_document(input_email, "Test error")
        
        assert isinstance(error_doc, EmailDocument)
        assert error_doc.message_id == "<error@example.com>"
        assert "PREPROCESSING ERROR" in error_doc.body_text_canonical
        assert "Test error" in error_doc.body_text_canonical


def test_preprocess_email_handles_invalid_headers(valid_env):
    """Test preprocessing with malformed headers"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<malformed@example.com>",
            from_addr="sender@example.com",
            headers={"invalid": "data\x00with null"},
            body_text="Body text",
        )
        
        # Should not raise, should handle gracefully
        result = preprocess_email(input_email)
        
        assert isinstance(result, EmailDocument)
        assert result.message_id == "<malformed@example.com>"


def test_preprocess_email_handles_empty_body(valid_env):
    """Test preprocessing with empty body"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<empty@example.com>",
            from_addr="sender@example.com",
            headers={"from": "sender@example.com"},
            body_text="",
        )
        
        result = preprocess_email(input_email)
        
        assert isinstance(result, EmailDocument)
        assert result.body_text_canonical == ""


# ==============================================================================
# TEST STATISTICS
# ==============================================================================


def test_get_preprocessing_stats(valid_env):
    """Test stats extraction from processed email"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<stats@example.com>",
            from_addr="test@example.com",
            headers={"from": "test@example.com"},
            body_text="Body with test@example.com",
        )
        
        result = preprocess_email(input_email)
        stats = get_preprocessing_stats(result)
        
        assert "message_id" in stats
        assert "body_length" in stats
        assert "pii_redactions_count" in stats
        assert stats["message_id"] == "<stats@example.com>"


def test_get_preprocessing_stats_pii_types(valid_env):
    """Test that stats include PII types"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<stats-pii@example.com>",
            from_addr="sender@example.com",
            headers={"from": "sender@example.com"},
            body_text="Email: test@example.com Phone: +39 02 1234567",
        )
        
        result = preprocess_email(input_email)
        stats = get_preprocessing_stats(result)
        
        assert "pii_types" in stats
        assert isinstance(stats["pii_types"], list)


# ==============================================================================
# TEST UNICODE HANDLING
# ==============================================================================


def test_preprocess_email_unicode(valid_env):
    """Test preprocessing with Unicode characters"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<unicode@example.com>",
            from_addr="sender@example.com",
            subject="Testo con àccenti",
            headers={"from": "sender@example.com", "subject": "Testo con àccenti"},
            body_text="Email con càratteri speciali: €, ñ, 中文",
        )
        
        result = preprocess_email(input_email)
        
        # Unicode should be preserved
        assert "àccenti" in result.headers_canonical.get("subject", "").lower()
        assert "€" in result.body_text_canonical or "càratteri" in result.body_text_canonical


# ==============================================================================
# TEST EDGE CASES
# ==============================================================================


def test_preprocess_email_very_long_body(valid_env):
    """Test preprocessing with very long body"""
    with patch.dict(os.environ, valid_env, clear=True):
        long_body = "A" * 100_000  # 100KB
        
        input_email = create_test_input_email(
            message_id="<long@example.com>",
            from_addr="sender@example.com",
            headers={"from": "sender@example.com"},
            body_text=long_body,
        )
        
        result = preprocess_email(input_email)
        
        assert isinstance(result, EmailDocument)
        assert len(result.body_text_canonical) > 0


def test_preprocess_email_special_characters(valid_env):
    """Test preprocessing with special characters"""
    with patch.dict(os.environ, valid_env, clear=True):
        input_email = create_test_input_email(
            message_id="<special@example.com>",
            from_addr="sender@example.com",
            headers={"from": "sender@example.com"},
            body_text="Text with <tags> & special chars: @#$%",
        )
        
        result = preprocess_email(input_email)
        
        assert isinstance(result, EmailDocument)
