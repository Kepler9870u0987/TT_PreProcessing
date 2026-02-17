"""
Error handling & graceful degradation

Implementa fallback chain per resilienza:
1. preprocess_email() - Full pipeline
2. preprocess_email_safe() - Catch all errors, retry with fallbacks
3. preprocess_email_regex_only() - Disable NER (memory-safe)
4. preprocess_email_no_canon() - Skip canonicalization
5. create_minimal_document() - Last resort: minimal processing

Garantisce che nessuna email venga persa, anche con errori.
"""

import structlog
from typing import Optional

from src.__version__ import __version__
from src.models import (
    InputEmail,
    EmailDocument,
    PipelineVersion,
    PreprocessingError,
)
from src.preprocessing import preprocess_email, _compute_body_hash, _create_error_document
from src.parsing import parse_headers_rfc5322
from src.pii_detection import PIIDetector, get_pii_detector, redact_headers_pii
from src.config import get_config


logger = structlog.get_logger(__name__)


def preprocess_email_safe(input_email: InputEmail) -> EmailDocument:
    """
    Safe preprocessing with fallback chain.
    
    Fallback order:
    1. Full pipeline (preprocess_email)
    2. Regex-only PII (no NER)
    3. No canonicalization
    4. Minimal document (headers + raw body)
    
    Args:
        input_email: Input email
        
    Returns:
        EmailDocument (always succeeds, never raises)
    """
    # Try full pipeline
    try:
        return preprocess_email(input_email)
    except Exception as e:
        logger.warning("full_pipeline_failed", error=str(e), fallback="regex_only")
    
    # Try regex-only (no NER, safer for memory)
    try:
        return preprocess_email_regex_only(input_email)
    except Exception as e:
        logger.warning("regex_only_failed", error=str(e), fallback="no_canon")
    
    # Try without canonicalization (skip quote/signature removal)
    try:
        return preprocess_email_no_canon(input_email)
    except Exception as e:
        logger.warning("no_canon_failed", error=str(e), fallback="minimal")
    
    # Last resort: minimal document
    try:
        return create_minimal_document(input_email)
    except Exception as e:
        logger.error("minimal_document_failed", error=str(e))
        # Absolute last resort: error document
        return _create_error_document(input_email, f"All fallbacks failed: {e}")


def preprocess_email_regex_only(input_email: InputEmail) -> EmailDocument:
    """
    Preprocessing with regex-only PII detection (no NER).
    
    Safer for memory (BUG-006), faster, deterministic.
    Used as fallback when NER fails or is unavailable.
    
    Args:
        input_email: Input email
        
    Returns:
        EmailDocument with regex PII detection only
    """
    config = get_config()
    pii_detector = get_pii_detector()
    
    logger.info("preprocessing_regex_only", message_id=input_email.message_id)
    
    # Headers già parsati
    headers = input_email.headers
    
    # Use body_text as-is (no full MIME parse, no canonicalization)
    body = input_email.body_text or ""
    
    # Regex-only PII detection
    try:
        redactions = pii_detector.detect_pii_regex(body)
        redacted_body = pii_detector.apply_redactions(body, redactions)
        logger.info("pii_redacted_regex_only", redaction_count=len(redactions))
    except Exception as e:
        logger.error("regex_pii_failed", error=str(e))
        redacted_body = body
        redactions = []
    
    # Redact headers
    try:
        redacted_headers = redact_headers_pii(headers, pii_detector)
    except Exception as e:
        logger.warning("header_redaction_failed_regex_only", error=str(e))
        redacted_headers = headers
    
    # Compute hash
    body_hash = _compute_body_hash(redacted_body)
    import datetime
    
    # Create document
    return EmailDocument(
        # Original identifiers
        uid=input_email.uid,
        uidvalidity=input_email.uidvalidity,
        mailbox=input_email.mailbox,
        message_id=input_email.message_id,
        fetched_at=input_email.fetched_at,
        size=input_email.size,
        
        # Processed headers
        from_addr_redacted=redacted_headers.get('from', '[PII_EMAIL]'),
        to_addrs_redacted=[addr.strip() for addr in redacted_headers.get('to', '').split(',') if addr.strip()],
        subject_canonical=redacted_headers.get('subject', ''),
        date_parsed=redacted_headers.get('date', ''),
        headers_canonical=redacted_headers,
        
        # Body
        body_text_canonical=redacted_body,
        body_html_canonical='',
        body_original_hash=body_hash,
        
        # Metadata
        removed_sections=[],  # No canonicalization
        pii_entities=redactions,
        
        # Versioning
        pipeline_version=PipelineVersion(),
        processing_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        processing_duration_ms=0,
    )


def preprocess_email_no_canon(input_email: InputEmail) -> EmailDocument:
    """
    Preprocessing without canonicalization (no quote/signature removal).
    
    Used as fallback when canonicalization fails (e.g., regex timeout).
    
    Args:
        input_email: Input email
        
    Returns:
        EmailDocument without canonicalization
    """
    config = get_config()
    pii_detector = get_pii_detector()
    
    logger.info("preprocessing_no_canon", message_id=input_email.message_id)
    
    # Headers già parsati
    headers = input_email.headers
    
    # Use body_text as-is
    body = input_email.body_text or ""
    
    # Regex-only PII (safer)
    try:
        redactions = pii_detector.detect_pii_regex(body)
        redacted_body = pii_detector.apply_redactions(body, redactions)
    except Exception:
        redacted_body = body
        redactions = []
    
    # Redact headers
    try:
        redacted_headers = redact_headers_pii(headers, pii_detector)
    except Exception:
        redacted_headers = headers
    
    body_hash = _compute_body_hash(redacted_body)
    import datetime
    
    return EmailDocument(
        # Original identifiers
        uid=input_email.uid,
        uidvalidity=input_email.uidvalidity,
        mailbox=input_email.mailbox,
        message_id=input_email.message_id,
        fetched_at=input_email.fetched_at,
        size=input_email.size,
        
        # Processed headers
        from_addr_redacted=redacted_headers.get('from', '[PII_EMAIL]'),
        to_addrs_redacted=[addr.strip() for addr in redacted_headers.get('to', '').split(',') if addr.strip()],
        subject_canonical=redacted_headers.get('subject', ''),
        date_parsed=redacted_headers.get('date', ''),
        headers_canonical=redacted_headers,
        
        # Body
        body_text_canonical=redacted_body,
        body_html_canonical='',
        body_original_hash=body_hash,
        
        # Metadata
        removed_sections=[],
        pii_entities=redactions,
        
        # Versioning
        pipeline_version=PipelineVersion(),
        processing_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        processing_duration_ms=0,
    )


def create_minimal_document(input_email: InputEmail) -> EmailDocument:
    """
    Create minimal EmailDocument with no processing.
    
    Last resort fallback: just parse headers and use raw body.
    No PII redaction, no canonicalization.
    
    Args:
        input_email: Input email
        
    Returns:
        Minimal EmailDocument
    """
    config = get_config()
    
    logger.warning("creating_minimal_document", message_id=input_email.message_id)
    
    # Headers già parsati
    headers = input_email.headers if input_email.headers else {"from": "unknown", "subject": "unknown"}
    
    body = input_email.body_text or "[BODY UNAVAILABLE]"
    body_hash = _compute_body_hash(body)
    import datetime
    
    return EmailDocument(
        # Original identifiers
        uid=input_email.uid,
        uidvalidity=input_email.uidvalidity,
        mailbox=input_email.mailbox,
        message_id=input_email.message_id,
        fetched_at=input_email.fetched_at,
        size=input_email.size,
        
        # Processed headers
        from_addr_redacted=headers.get('from', 'unknown'),
        to_addrs_redacted=[addr.strip() for addr in headers.get('to', '').split(',') if addr.strip()],
        subject_canonical=headers.get('subject', 'unknown'),
        date_parsed=headers.get('date', ''),
        headers_canonical=headers,
        
        # Body
        body_text_canonical=body,
        body_html_canonical='',
        body_original_hash=body_hash,
        
        # Metadata
        removed_sections=[],
        pii_entities=[],
        
        # Versioning
        pipeline_version=PipelineVersion(),
        processing_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        processing_duration_ms=0,
    )


# ==============================================================================
# ERROR CLASSIFICATION
# ==============================================================================


class ErrorSeverity:
    """Error severity levels"""

    CRITICAL = "critical"  # Total failure, cannot process
    HIGH = "high"  # Major component failed, fallback needed
    MEDIUM = "medium"  # Partial failure, degraded output
    LOW = "low"  # Minor issue, output is still valid


def classify_error(exception: Exception) -> str:
    """
    Classify exception by severity.
    
    Args:
        exception: Exception to classify
        
    Returns:
        Severity level (CRITICAL, HIGH, MEDIUM, LOW)
    """
    error_type = type(exception).__name__
    error_msg = str(exception).lower()
    
    # Critical: Memory, system errors
    if any(
        keyword in error_msg
        for keyword in ["memory", "out of memory", "killed", "segfault"]
    ):
        return ErrorSeverity.CRITICAL
    
    # High: PII detection, parsing errors
    if "pii" in error_msg or "parse" in error_msg:
        return ErrorSeverity.HIGH
    
    # Medium: Canonicalization, timeout
    if "timeout" in error_msg or "canon" in error_msg:
        return ErrorSeverity.MEDIUM
    
    # Default: Low
    return ErrorSeverity.LOW


def should_retry(exception: Exception, attempt: int, max_attempts: int = 3) -> bool:
    """
    Determine if operation should be retried.
    
    Args:
        exception: Exception that occurred
        attempt: Current attempt number (1-indexed)
        max_attempts: Maximum attempts allowed
        
    Returns:
        True if should retry, False otherwise
    """
    if attempt >= max_attempts:
        return False
    
    # Don't retry critical errors
    severity = classify_error(exception)
    if severity == ErrorSeverity.CRITICAL:
        return False
    
    # Don't retry validation errors (deterministic failures)
    if "validation" in str(exception).lower():
        return False
    
    # Retry transient errors (timeout, temporary resource issues)
    return True


# ==============================================================================
# RESILIENCE UTILITIES
# ==============================================================================


def truncate_for_safety(text: str, max_kb: int = 500) -> str:
    """
    Truncate text for memory safety.
    
    Args:
        text: Input text
        max_kb: Maximum size in KB
        
    Returns:
        Truncated text (with warning marker if truncated)
    """
    max_bytes = max_kb * 1024
    text_bytes = text.encode("utf-8")
    
    if len(text_bytes) <= max_bytes:
        return text
    
    # Truncate
    truncated_bytes = text_bytes[:max_bytes]
    truncated_text = truncated_bytes.decode("utf-8", errors="ignore")
    
    logger.warning(
        "text_truncated_for_safety",
        original_size_kb=len(text_bytes) // 1024,
        truncated_size_kb=max_kb,
    )
    
    return truncated_text + "\n\n[TEXT TRUNCATED FOR MEMORY SAFETY]"


def is_email_processable(input_email: InputEmail) -> tuple[bool, Optional[str]]:
    """
    Check if email is processable (basic validation).
    
    Args:
        input_email: Input email to check
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check message_id
    if not input_email.message_id:
        return False, "Missing message_id"
    
    # Check we have some content
    if not input_email.body_text and not input_email.raw_bytes:
        return False, "Empty email body"
    
    # Check headers exist
    if not input_email.headers:
        return False, "Missing headers"
    
    return True, None
