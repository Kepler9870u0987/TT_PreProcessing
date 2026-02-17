"""
Test suite for data models

Verifica:
- Creazione oggetti
- Immutabilità (frozen dataclasses)
- Validazione campi
- Serializzazione JSON
- Edge cases e error handling
"""

import json
import pytest
from datetime import datetime
from dataclasses import asdict

from src.models import (
    PipelineVersion,
    RemovedSection,
    PIIRedaction,
    InputEmail,
    EmailDocument,
    PreprocessingError,
    PIIDetectionError,
    CanonicalizationError,
    ParsingError,
)


# ==============================================================================
# TEST CUSTOM EXCEPTIONS
# ==============================================================================


def test_custom_exceptions_inheritance():
    """Verify exception hierarchy"""
    assert issubclass(PIIDetectionError, PreprocessingError)
    assert issubclass(CanonicalizationError, PreprocessingError)
    assert issubclass(ParsingError, PreprocessingError)
    assert issubclass(PreprocessingError, Exception)


def test_custom_exceptions_messages():
    """Test exception messages"""
    with pytest.raises(PreprocessingError) as exc_info:
        raise PreprocessingError("Test error")
    assert str(exc_info.value) == "Test error"

    with pytest.raises(PIIDetectionError) as exc_info:
        raise PIIDetectionError("PII detection failed")
    assert "PII detection failed" in str(exc_info.value)


# ==============================================================================
# TEST PIPELINE VERSION
# ==============================================================================


def test_pipeline_version_creation():
    """Test creating PipelineVersion with defaults"""
    version = PipelineVersion()
    assert version.parser_version == "email-parser-1.3.0"
    assert version.canonicalization_version == "1.3.0"
    assert version.ner_model_version == "it_core_news_lg-3.8.2"
    assert version.pii_redaction_version == "1.0.0"


def test_pipeline_version_immutable():
    """Test that PipelineVersion is frozen (immutable)"""
    version = PipelineVersion()
    with pytest.raises(Exception):  # dataclass frozen raises FrozenInstanceError
        version.parser_version = "modified"  # type: ignore


def test_pipeline_version_string_representation():
    """Test __str__ method"""
    version = PipelineVersion()
    expected = "email-parser-1.3.0|1.3.0|it_core_news_lg-3.8.2|1.0.0"
    assert str(version) == expected


def test_pipeline_version_custom():
    """Test creating PipelineVersion with custom values"""
    version = PipelineVersion(
        parser_version="custom-1.0.0",
        canonicalization_version="2.0.0",
        ner_model_version="custom-model",
        pii_redaction_version="2.0.0",
    )
    assert version.parser_version == "custom-1.0.0"
    assert "custom-1.0.0|2.0.0|custom-model|2.0.0" == str(version)


# ==============================================================================
# TEST REMOVED SECTION
# ==============================================================================


def test_removed_section_creation():
    """Test creating RemovedSection"""
    section = RemovedSection(
        type="quote", span_start=10, span_end=50, content_preview="Preview text", confidence=0.95
    )
    assert section.type == "quote"
    assert section.span_start == 10
    assert section.span_end == 50
    assert section.content_preview == "Preview text"
    assert section.confidence == 0.95


def test_removed_section_confidence_validation():
    """Test confidence must be in [0.0, 1.0]"""
    with pytest.raises(ValueError, match="Confidence must be in"):
        RemovedSection(type="quote", span_start=0, span_end=10, content_preview="test", confidence=1.5)

    with pytest.raises(ValueError, match="Confidence must be in"):
        RemovedSection(type="quote", span_start=0, span_end=10, content_preview="test", confidence=-0.1)


def test_removed_section_span_validation():
    """Test span validation (start < end, both positive)"""
    with pytest.raises(ValueError, match="Invalid span"):
        RemovedSection(type="quote", span_start=-1, span_end=10, content_preview="test", confidence=0.9)

    with pytest.raises(ValueError, match="Invalid span"):
        RemovedSection(type="quote", span_start=50, span_end=10, content_preview="test", confidence=0.9)


def test_removed_section_preview_truncation():
    """Test content_preview is truncated to 100 chars"""
    long_text = "A" * 200
    section = RemovedSection(type="signature", span_start=0, span_end=200, content_preview=long_text, confidence=1.0)
    assert len(section.content_preview) == 100
    assert section.content_preview == "A" * 100


# ==============================================================================
# TEST PII REDACTION
# ==============================================================================


def test_pii_redaction_creation():
    """Test creating PIIRedaction"""
    redaction = PIIRedaction(
        type="EMAIL",
        original_hash="a1b2c3d4e5f6g7h8",
        redacted="[PII_EMAIL]",
        span_start=20,
        span_end=40,
        confidence=0.99,
        detection_method="regex",
    )
    assert redaction.type == "EMAIL"
    assert redaction.original_hash == "a1b2c3d4e5f6g7h8"
    assert redaction.redacted == "[PII_EMAIL]"
    assert redaction.confidence == 0.99
    assert redaction.detection_method == "regex"


def test_pii_redaction_confidence_validation():
    """Test confidence validation"""
    with pytest.raises(ValueError, match="Confidence must be in"):
        PIIRedaction(
            type="EMAIL",
            original_hash="hash",
            redacted="[PII]",
            span_start=0,
            span_end=10,
            confidence=2.0,
            detection_method="regex",
        )


def test_pii_redaction_span_validation():
    """Test span validation"""
    with pytest.raises(ValueError, match="Invalid span"):
        PIIRedaction(
            type="NAME",
            original_hash="hash",
            redacted="[PII_NAME]",
            span_start=100,
            span_end=50,
            confidence=0.8,
            detection_method="ner",
        )


def test_pii_redaction_detection_method_validation():
    """Test detection_method must be regex|ner|hybrid"""
    with pytest.raises(ValueError, match="Invalid detection_method"):
        PIIRedaction(
            type="EMAIL",
            original_hash="hash",
            redacted="[PII]",
            span_start=0,
            span_end=10,
            confidence=1.0,
            detection_method="invalid",
        )

    # Valid methods should work
    for method in ["regex", "ner", "hybrid"]:
        redaction = PIIRedaction(
            type="EMAIL",
            original_hash="hash",
            redacted="[PII]",
            span_start=0,
            span_end=10,
            confidence=1.0,
            detection_method=method,
        )
        assert redaction.detection_method == method


# ==============================================================================
# TEST INPUT EMAIL
# ==============================================================================


def test_input_email_creation():
    """Test creating InputEmail with all fields"""
    email = InputEmail(
        uid="12345",
        uidvalidity="67890",
        mailbox="INBOX",
        from_addr="sender@example.com",
        to_addrs=["recipient@example.com"],
        subject="Test Subject",
        date="2026-02-17T10:00:00Z",
        body_text="Plain text body",
        body_html="<p>HTML body</p>",
        size=1024,
        headers={"from": "sender@example.com", "to": "recipient@example.com"},
        message_id="<msg123@example.com>",
        fetched_at="2026-02-17T10:01:00Z",
    )
    assert email.uid == "12345"
    assert email.from_addr == "sender@example.com"
    assert len(email.to_addrs) == 1
    assert email.raw_bytes is None  # Default
    assert email.body_truncated is False  # Default


def test_input_email_with_raw_bytes():
    """Test InputEmail with optional raw_bytes (BUG-001 mitigation)"""
    raw_content = b"Subject: Test\r\n\r\nBody"
    email = InputEmail(
        uid="1",
        uidvalidity="1",
        mailbox="INBOX",
        from_addr="test@test.com",
        to_addrs=[],
        subject="Test",
        date="2026-02-17T10:00:00Z",
        body_text="truncated",
        body_html="",
        size=100,
        headers={},
        message_id="<1@test.com>",
        fetched_at="2026-02-17T10:00:00Z",
        raw_bytes=raw_content,
        body_truncated=True,
    )
    assert email.raw_bytes == raw_content
    assert email.body_truncated is True


def test_input_email_serialization():
    """Test InputEmail can be serialized to dict (for JSON)"""
    email = InputEmail(
        uid="1",
        uidvalidity="1",
        mailbox="INBOX",
        from_addr="test@test.com",
        to_addrs=["dest@test.com"],
        subject="Test",
        date="2026-02-17T10:00:00Z",
        body_text="text",
        body_html="html",
        size=100,
        headers={"subject": "Test"},
        message_id="<1@test.com>",
        fetched_at="2026-02-17T10:00:00Z",
    )
    email_dict = asdict(email)
    assert email_dict["uid"] == "1"
    assert email_dict["from_addr"] == "test@test.com"
    assert isinstance(email_dict["to_addrs"], list)


# ==============================================================================
# TEST EMAIL DOCUMENT
# ==============================================================================


def test_email_document_creation():
    """Test creating EmailDocument with all required fields"""
    doc = EmailDocument(
        uid="12345",
        uidvalidity="67890",
        mailbox="INBOX",
        message_id="<msg@example.com>",
        fetched_at="2026-02-17T10:00:00Z",
        size=2048,
        from_addr_redacted="[PII_EMAIL]",
        to_addrs_redacted=["[PII_EMAIL]"],
        subject_canonical="test subject",
        date_parsed="2026-02-17T10:00:00Z",
        headers_canonical={"from": "[PII_EMAIL]"},
        body_text_canonical="canonical text",
        body_html_canonical="<p>canonical</p>",
        body_original_hash="sha256:abc123...",
        removed_sections=[],
        pii_entities=[],
        pipeline_version=PipelineVersion(),
        processing_timestamp="2026-02-17T10:05:00Z",
        processing_duration_ms=342,
    )
    assert doc.uid == "12345"
    assert doc.body_text_canonical == "canonical text"
    assert len(doc.removed_sections) == 0
    assert len(doc.pii_entities) == 0


def test_email_document_immutable():
    """Test that EmailDocument is frozen (immutable)"""
    doc = EmailDocument.create_default_factory()
    with pytest.raises(Exception):  # FrozenInstanceError
        doc.uid = "modified"  # type: ignore


def test_email_document_with_audit_data():
    """Test EmailDocument with removed_sections and pii_entities"""
    removed = [
        RemovedSection(type="quote", span_start=0, span_end=50, content_preview="quoted text", confidence=0.95)
    ]
    pii = [
        PIIRedaction(
            type="EMAIL",
            original_hash="hash123",
            redacted="[PII_EMAIL]",
            span_start=10,
            span_end=30,
            confidence=1.0,
            detection_method="regex",
        )
    ]

    doc = EmailDocument(
        uid="1",
        uidvalidity="1",
        mailbox="INBOX",
        message_id="<1@test.com>",
        fetched_at="2026-02-17T10:00:00Z",
        size=100,
        from_addr_redacted="[PII_EMAIL]",
        to_addrs_redacted=[],
        subject_canonical="subject",
        date_parsed="2026-02-17T10:00:00Z",
        headers_canonical={},
        body_text_canonical="text",
        body_html_canonical="",
        body_original_hash="hash",
        removed_sections=removed,
        pii_entities=pii,
        pipeline_version=PipelineVersion(),
        processing_timestamp="2026-02-17T10:00:00Z",
        processing_duration_ms=100,
    )

    assert len(doc.removed_sections) == 1
    assert len(doc.pii_entities) == 1
    assert doc.removed_sections[0].type == "quote"
    assert doc.pii_entities[0].type == "EMAIL"


def test_email_document_default_factory():
    """Test EmailDocument.create_default_factory()"""
    doc = EmailDocument.create_default_factory()
    assert doc.uid == ""
    assert doc.body_text_canonical == ""
    assert doc.removed_sections == []
    assert doc.pii_entities == []
    assert doc.processing_duration_ms == 0
    # Verify processing_timestamp is valid ISO8601
    datetime.fromisoformat(doc.processing_timestamp.rstrip("Z"))


def test_email_document_serialization():
    """Test EmailDocument can be converted to dict"""
    doc = EmailDocument.create_default_factory()
    doc_dict = asdict(doc)
    assert isinstance(doc_dict, dict)
    assert "uid" in doc_dict
    assert "pipeline_version" in doc_dict
    assert isinstance(doc_dict["pipeline_version"], dict)


# ==============================================================================
# EDGE CASES AND INTEGRATION
# ==============================================================================


def test_empty_lists_in_email_document():
    """Test EmailDocument handles empty lists correctly"""
    doc = EmailDocument(
        uid="1",
        uidvalidity="1",
        mailbox="INBOX",
        message_id="<1@test.com>",
        fetched_at="2026-02-17T10:00:00Z",
        size=0,
        from_addr_redacted="",
        to_addrs_redacted=[],
        subject_canonical="",
        date_parsed="2026-02-17T10:00:00Z",
        headers_canonical={},
        body_text_canonical="",
        body_html_canonical="",
        body_original_hash="",
        removed_sections=[],
        pii_entities=[],
        pipeline_version=PipelineVersion(),
        processing_timestamp="2026-02-17T10:00:00Z",
        processing_duration_ms=0,
    )
    assert doc.removed_sections == []
    assert doc.pii_entities == []
    assert doc.to_addrs_redacted == []


def test_pipeline_version_equality():
    """Test PipelineVersion equality comparison"""
    v1 = PipelineVersion()
    v2 = PipelineVersion()
    assert v1 == v2

    v3 = PipelineVersion(parser_version="different")
    assert v1 != v3


def test_unicode_in_models():
    """Test models handle unicode correctly"""
    section = RemovedSection(
        type="signature", span_start=0, span_end=10, content_preview="Cordiali saluti 👋", confidence=1.0
    )
    assert "👋" in section.content_preview

    email = InputEmail(
        uid="1",
        uidvalidity="1",
        mailbox="INBOX",
        from_addr="test@test.com",
        to_addrs=["destinatario@test.it"],
        subject="Oggetto con àccenti",
        date="2026-02-17T10:00:00Z",
        body_text="Testo con caratteri speciali: €, ñ, ü",
        body_html="",
        size=100,
        headers={},
        message_id="<1@test.com>",
        fetched_at="2026-02-17T10:00:00Z",
    )
    assert "àccenti" in email.subject
    assert "€" in email.body_text
