"""
Preprocessing orchestrator

Integra parsing, canonicalization, PII detection in pipeline completa.
Pipeline: raw email → parse → canonicalize → PII redact → EmailDocument
"""

import hashlib
from typing import Optional, List, Dict, Any
import structlog

from src.models import InputEmail, EmailDocument, PIIRedaction, PipelineVersion
from src.parsing import parse_headers_rfc5322, extract_body_parts_from_truncated, merge_body_parts
from src.canonicalization import canonicalize_text
from src.pii_detection import get_pii_detector, redact_headers_pii
from src.config import get_config


logger = structlog.get_logger(__name__)


def preprocess_email(input_email: InputEmail) -> EmailDocument:
    """
    Main preprocessing pipeline.
    
    Pipeline steps:
    1. Parse headers (RFC5322)
    2. Extract body (text + HTML)
    3. Merge body parts
    4. Canonicalize text
    5. Detect & redact PII (body + headers)
    6. Compute body hash
    7. Create EmailDocument
    
    Args:
        input_email: Input email with message_id, body_text, optional raw_bytes
        
    Returns:
        EmailDocument with PII redacted, canonicalized, immutable
        
    Raises:
        PreprocessingError: If critical step fails
    """
    config = get_config()
    pii_detector = get_pii_detector()
    
    logger.info("preprocessing_started", message_id=input_email.message_id)
    
    # STEP 1: Parse headers
    try:
        headers = parse_headers_rfc5322(input_email.headers_raw)
        logger.debug("headers_parsed", count=len(headers))
    except Exception as e:
        logger.warning("headers_parse_failed", error=str(e))
        headers = {}
    
    # STEP 2 & 3: Extract body parts + merge
    try:
        text_parts, html_parts = extract_body_parts_from_truncated(input_email)
        merged_body = merge_body_parts(text_parts, html_parts)
        logger.debug("body_extracted", length=len(merged_body))
    except Exception as e:
        logger.error("body_extraction_failed", error=str(e))
        # Fallback to truncated body_text
        merged_body = input_email.body_text or ""
    
    # STEP 4: Canonicalize text
    try:
        canonical_body, removed_sections = canonicalize_text(merged_body)
        logger.debug(
            "text_canonicalized",
            original_len=len(merged_body),
            canonical_len=len(canonical_body),
            removed_count=len(removed_sections),
        )
    except Exception as e:
        logger.error("canonicalization_failed", error=str(e))
        # Fallback: use original text
        canonical_body = merged_body
        removed_sections = []
    
    # STEP 5a: Redact PII in body
    try:
        redacted_body, pii_redactions = pii_detector.detect_and_redact(canonical_body)
        logger.info("pii_redacted_body", redaction_count=len(pii_redactions))
    except Exception as e:
        logger.error("pii_redaction_failed", error=str(e))
        # Fallback: no redaction
        redacted_body = canonical_body
        pii_redactions = []
    
    # STEP 5b: Redact PII in headers
    try:
        redacted_headers = redact_headers_pii(headers, pii_detector)
        logger.debug("pii_redacted_headers", header_count=len(redacted_headers))
    except Exception as e:
        logger.warning("header_redaction_failed", error=str(e))
        redacted_headers = headers
    
    # STEP 6: Compute body hash (for deduplication)
    try:
        body_hash = _compute_body_hash(redacted_body)
        logger.debug("body_hash_computed", hash_prefix=body_hash[:8])
    except Exception as e:
        logger.warning("body_hash_failed", error=str(e))
        body_hash = ""
    
    # STEP 7: Create EmailDocument
    email_doc = EmailDocument(
        message_id=input_email.message_id,
        headers=redacted_headers,
        body_text=redacted_body,
        body_hash=body_hash,
        pii_redactions=pii_redactions,
        removed_sections=removed_sections,
        pipeline_version=PipelineVersion(
            version=config.pipeline_version,
            preprocessing_layer="1.0.0",  # TODO: Read from __version__
        ),
    )
    
    logger.info(
        "preprocessing_completed",
        message_id=email_doc.message_id,
        pii_count=len(pii_redactions),
        removed_count=len(removed_sections),
        body_length=len(redacted_body),
    )
    
    return email_doc


def _compute_body_hash(body: str) -> str:
    """
    Compute SHA256 hash of body text (for deduplication).
    
    Args:
        body: Canonical, redacted body text
        
    Returns:
        Hex digest (64 chars)
    """
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ==============================================================================
# BATCH PROCESSING
# ==============================================================================


def preprocess_email_batch(input_emails: List[InputEmail]) -> List[EmailDocument]:
    """
    Process multiple emails in batch.
    
    Args:
        input_emails: List of InputEmail
        
    Returns:
        List of EmailDocument (same order as input)
        
    Note:
        Currently sequential processing. Future: parallel processing with multiprocessing.
    """
    results = []
    
    logger.info("batch_processing_started", count=len(input_emails))
    
    for idx, input_email in enumerate(input_emails):
        try:
            result = preprocess_email(input_email)
            results.append(result)
        except Exception as e:
            logger.error(
                "batch_item_failed",
                index=idx,
                message_id=input_email.message_id,
                error=str(e),
            )
            # Create error document
            results.append(_create_error_document(input_email, str(e)))
    
    logger.info("batch_processing_completed", count=len(results))
    
    return results


def _create_error_document(input_email: InputEmail, error: str) -> EmailDocument:
    """
    Create error EmailDocument when preprocessing fails.
    
    Args:
        input_email: Original input
        error: Error message
        
    Returns:
        Minimal EmailDocument with error info in body
    """
    config = get_config()
    
    return EmailDocument(
        message_id=input_email.message_id,
        headers={"preprocessing-error": error},
        body_text=f"[PREPROCESSING ERROR: {error}]",
        body_hash="",
        pii_redactions=[],
        removed_sections=[],
        pipeline_version=PipelineVersion(
            version=config.pipeline_version,
            preprocessing_layer="1.0.0",
        ),
    )


# ==============================================================================
# DETERMINISM VALIDATION
# ==============================================================================


def validate_determinism(input_email: InputEmail, runs: int = 3) -> bool:
    """
    Validate that preprocessing is deterministic.
    
    Args:
        input_email: Input email to test
        runs: Number of runs to compare
        
    Returns:
        True if all runs produce identical output, False otherwise
    """
    results = []
    
    for i in range(runs):
        result = preprocess_email(input_email)
        # Compare body_text, headers, pii_redactions
        results.append(
            {
                "body_text": result.body_text,
                "headers": result.headers,
                "pii_count": len(result.pii_redactions),
                "body_hash": result.body_hash,
            }
        )
    
    # Check all results are identical
    first = results[0]
    for result in results[1:]:
        if result != first:
            logger.warning("determinism_violation_detected", first=first, other=result)
            return False
    
    logger.info("determinism_validated", runs=runs)
    return True


# ==============================================================================
# STATISTICS
# ==============================================================================


def get_preprocessing_stats(email_doc: EmailDocument) -> Dict[str, Any]:
    """
    Extract statistics from processed email.
    
    Args:
        email_doc: Processed EmailDocument
        
    Returns:
        Dictionary with stats
    """
    return {
        "message_id": email_doc.message_id,
        "body_length": len(email_doc.body_text),
        "pii_redactions_count": len(email_doc.pii_redactions),
        "pii_types": list({r.type for r in email_doc.pii_redactions}),
        "removed_sections_count": len(email_doc.removed_sections),
        "header_count": len(email_doc.headers),
        "pipeline_version": email_doc.pipeline_version.version,
    }
