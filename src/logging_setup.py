"""
Structured logging setup for Email Preprocessing Layer

CRITICAL SECURITY: NO PII deve apparire nei log (GDPR compliance)

Usa structlog per JSON logging con processori che filtrano dati sensibili.

Usage:
    from src.logging_setup import setup_logging, get_logger
    
    setup_logging("INFO")
    logger = get_logger(__name__)
    logger.info("processing_started", uid="12345", size=2048)
"""

import logging
import sys
from typing import Any, Dict

import structlog
from structlog.types import EventDict, Processor


# ==============================================================================
# SENSITIVE FIELD FILTER (GDPR COMPLIANCE)
# ==============================================================================

# Fields that should NEVER appear in logs
SENSITIVE_FIELDS = {
    "pii_salt",
    "raw_bytes",
    "body_text",
    "body_html",
    "body_text_canonical",
    "body_html_canonical",
    "from_addr",
    "to_addrs",
    "email",
    "phone",
    "password",
    "token",
    "secret",
    "api_key",
}


def filter_sensitive_fields(logger: Any, name: str, event_dict: EventDict) -> EventDict:
    """
    Processor che rimuove campi sensibili dai log.
    
    CRITICAL: Previene leak di PII anche in modalità DEBUG.
    """
    filtered_dict = {}
    for key, value in event_dict.items():
        # Check if field is sensitive
        if key.lower() in SENSITIVE_FIELDS:
            filtered_dict[key] = "[REDACTED]"
        # Check for nested dicts (headers, etc.)
        elif isinstance(value, dict):
            filtered_dict[key] = _filter_dict_recursive(value)
        else:
            filtered_dict[key] = value

    return filtered_dict


def _filter_dict_recursive(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively filter sensitive fields from nested dicts"""
    filtered = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_FIELDS:
            filtered[key] = "[REDACTED]"
        elif isinstance(value, dict):
            filtered[key] = _filter_dict_recursive(value)
        else:
            filtered[key] = value
    return filtered


# ==============================================================================
# SETUP FUNCTIONS
# ==============================================================================


def setup_logging(log_level: str = "INFO", json_format: bool = True) -> None:
    """
    Configure structlog per l'applicazione.
    
    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Se True, output in JSON. Se False, console human-readable.
    
    Features:
        - JSON output per produzione
        - Timestamp ISO8601
        - Logger name
        - Event filtering per GDPR
        - Console colorata per development
    """
    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )

    # Define processors
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        filter_sensitive_fields,  # CRITICAL: Filter PII
    ]

    if json_format:
        # Production: JSON output
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Development: Human-readable console output
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    """
    Get a configured structlog logger.
    
    Args:
        name: Logger name (usually __name__ of the module)
    
    Returns:
        Configured BoundLogger instance
    """
    return structlog.get_logger(name)


# ==============================================================================
# CONVENIENCE LOGGING CONTEXTS
# ==============================================================================


def log_preprocessing_context(uid: str, message_id: str, size: int) -> Dict[str, Any]:
    """
    Create standard context dict for preprocessing logs.
    
    Usage:
        logger.info("processing_started", **log_preprocessing_context(uid, msg_id, size))
    """
    return {
        "uid": uid,
        "message_id": message_id,
        "size": size,
    }


def log_error_context(error: Exception, uid: str = "") -> Dict[str, Any]:
    """
    Create context dict for error logging.
    
    Includes exception type and message (but not full traceback in log).
    """
    return {
        "error_type": type(error).__name__,
        "error_message": str(error),
        "uid": uid,
    }
