"""
Text Canonicalization Module

Gestisce la normalizzazione deterministica del testo email:
- Rimozione quote, signature, disclaimer
- Normalizzazione Unicode (BUG-007 mitigation)
- Protezione ReDoS con timeout (BUG-002 mitigation)

DETERMINISMO: Stesso input → stesso output (riproducibile).
"""

import re
import unicodedata
import threading
from typing import List, Tuple, Pattern, Optional

from src.models import RemovedSection, CanonicalizationError
from src.logging_setup import get_logger

logger = get_logger(__name__)

# Version tracking
CANONICALIZATION_VERSION = "1.3.0"


# ==============================================================================
# QUOTE/SIGNATURE PATTERNS (BUG-002 MITIGATION: Bounded quantifiers)
# ==============================================================================

# Pattern definitions with BOUNDED quantifiers to prevent ReDoS
QUOTE_PATTERNS: List[Tuple[str, str, float]] = [
    # Email quote standard (>)
    (r"(?m)^[\s]*>+.*$", "quote_standard", 1.0),
    # Reply headers Italian (BOUNDED: max 200 chars to "ha scritto:")
    (r"(?is)Il giorno.{1,200}ha scritto:", "reply_header_it", 0.95),
    # Reply headers English (BOUNDED)
    (r"(?is)On.{1,200}wrote:", "reply_header_en", 0.95),
    # Outlook reply header (BOUNDED)
    (r"(?is)Da:.{1,300}Oggetto:", "reply_header_outlook", 0.95),
    # Signature separators
    (r"(?m)^[\s]*--[\s]*$", "signature_separator", 1.0),
    (r"(?m)^[\s]*_{5,50}[\s]*$", "signature_underline", 0.9),
    # Disclaimer/footer aziendali (BOUNDED)
    (r"(?is)Questo messaggio.{1,500}confidenziale", "disclaimer_confidential", 0.85),
    (r"(?is)Informativa privacy.{1,500}GDPR", "disclaimer_privacy", 0.85),
    (r"(?is)P\.?[\s]?Rispetta l['\']ambiente.{1,200}", "disclaimer_environment", 0.8),
    # Formule di chiusura standard
    (r"(?is)Cordiali saluti[,\s]{0,10}", "closing_formal", 0.9),
    (r"(?is)Distinti saluti[,\s]{0,10}", "closing_formal", 0.9),
    # Forward markers
    (r"(?m)^[\s]*-{3,50}[\s]*Forwarded message[\s]*-{3,50}", "forward_marker", 1.0),
    (r"(?m)^[\s]*-{3,50}[\s]*Messaggio inoltrato[\s]*-{3,50}", "forward_marker_it", 1.0),
]

# Compile patterns at module load (performance optimization)
COMPILED_PATTERNS: List[Tuple[Pattern[str], str, float]] = [
    (re.compile(pattern), pattern_type, confidence) for pattern, pattern_type, confidence in QUOTE_PATTERNS
]


# ==============================================================================
# SAFE REGEX WITH TIMEOUT (BUG-002 MITIGATION)
# ==============================================================================


class RegexTimeoutError(Exception):
    """Raised when regex matching exceeds timeout"""

    pass


def safe_regex_finditer(pattern: Pattern[str], text: str, timeout_sec: float = 1.0) -> List[re.Match[str]]:
    """
    Esegue regex finditer con timeout protection (Windows compatible).
    
    BUG-002 MITIGATION: Previene ReDoS attacks usando threading.Timer.
    
    Args:
        pattern: Compiled regex pattern
        text: Text to search
        timeout_sec: Timeout in seconds
        
    Returns:
        List of match objects
        
    Raises:
        RegexTimeoutError: If regex execution exceeds timeout
    """
    result: List[re.Match[str]] = []
    timed_out = threading.Event()

    def timeout_handler() -> None:
        timed_out.set()

    timer = threading.Timer(timeout_sec, timeout_handler)

    try:
        timer.start()

        for match in pattern.finditer(text):
            if timed_out.is_set():
                raise RegexTimeoutError(f"Regex matching exceeded {timeout_sec}s timeout")
            result.append(match)

        return result

    except RegexTimeoutError:
        logger.warning("regex_timeout", pattern=pattern.pattern[:100], text_len=len(text))
        raise

    finally:
        timer.cancel()


# ==============================================================================
# TEXT CANONICALIZATION
# ==============================================================================


def canonicalize_text(
    text: str, remove_quotes: bool = True, remove_signatures: bool = True, regex_timeout_sec: float = 1.0
) -> Tuple[str, List[RemovedSection]]:
    """
    Canonicalizza testo in forma normalizzata e deterministica.
    
    Pipeline:
    1. Normalize line endings
    2. Unicode NFC normalization (BUG-007)
    3. Normalize Unicode whitespace (BUG-007)
    4. Remove patterns (quotes, signatures, disclaimers)
    5. Cleanup excessive whitespace
    
    Args:
        text: Testo da canonicalizzare
        remove_quotes: Se True, rimuovi quote e reply headers
        remove_signatures: Se True, rimuovi signature e disclaimer
        regex_timeout_sec: Timeout per regex matching (ReDoS protection)
        
    Returns:
        (testo_canonico, sezioni_rimosse) tuple
        
    Raises:
        CanonicalizationError: Se canonicalization fallisce
    """
    try:
        removed_sections: List[RemovedSection] = []

        # 1. Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # 2. Unicode NFC normalization (BUG-007 MITIGATION)
        text = unicodedata.normalize("NFC", text)

        # 3. Normalize Unicode whitespace (BUG-007 MITIGATION)
        text = _normalize_unicode_whitespace(text)

        # 4. Apply removal patterns with audit trail
        for compiled_pattern, pattern_type, confidence in COMPILED_PATTERNS:
            # Check configuration flags
            if not remove_quotes and pattern_type.startswith(("quote", "reply_header", "forward_marker")):
                continue
            if not remove_signatures and pattern_type.startswith(("signature", "disclaimer", "closing")):
                continue

            try:
                # Safe regex matching with timeout
                matches = safe_regex_finditer(compiled_pattern, text, timeout_sec=regex_timeout_sec)

                for match in matches:
                    span_start, span_end = match.span()
                    content_preview = text[span_start:span_end][:100]  # Max 100 chars for audit

                    removed_section = RemovedSection(
                        type=pattern_type,
                        span_start=span_start,
                        span_end=span_end,
                        content_preview=content_preview,
                        confidence=confidence,
                    )
                    removed_sections.append(removed_section)

                # Remove matched text (replace with single newline)
                text = compiled_pattern.sub("\n", text)

            except RegexTimeoutError:
                logger.warning("regex_timeout_skip_pattern", pattern_type=pattern_type)
                # Skip this pattern instead of failing entire canonicalization
                continue

        # 5. Cleanup excessive whitespace
        text = _cleanup_excessive_whitespace(text)

        return text, removed_sections

    except Exception as e:
        logger.error("canonicalization_failed", error=str(e))
        raise CanonicalizationError(f"Failed to canonicalize text: {e}") from e


def _normalize_unicode_whitespace(text: str) -> str:
    """
    Normalizza Unicode whitespace characters a ASCII space.
    
    BUG-007 MITIGATION: Converte tutti i char Unicode categoria 'Z' 
    (Space_Separator) a ASCII space (0x20).
    
    Examples:
        - U+00A0 (non-breaking space) → space
        - U+2003 (em space) → space
        - U+2009 (thin space) → space
    """
    result = []
    for char in text:
        if unicodedata.category(char) == "Zs":  # Space_Separator category
            result.append(" ")  # ASCII space
        else:
            result.append(char)
    return "".join(result)


def _cleanup_excessive_whitespace(text: str) -> str:
    """
    Cleanup whitespace in modo deterministico.
    
    Rules:
    - Multiple spaces → single space
    - Max 2 consecutive newlines
    - Strip leading/trailing whitespace per line
    """
    # Strip trailing whitespace per line
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)

    # Multiple spaces → single space
    text = re.sub(r" {2,}", " ", text)

    # Max 2 consecutive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ==============================================================================
# SUBJECT CANONICALIZATION
# ==============================================================================


def canonicalize_subject(subject: str) -> str:
    """
    Canonicalizza subject line.
    
    Pipeline:
    - Remove RE:/FW:/FWD: prefixes (case insensitive, multiple)
    - Lowercase
    - Strip whitespace
    - Unicode normalization
    
    Args:
        subject: Subject line originale
        
    Returns:
        Subject canonicalizzato
    """
    if not subject:
        return ""

    # Unicode NFC normalization
    subject = unicodedata.normalize("NFC", subject)

    # Remove RE:/FW: prefixes (case insensitive, multiple iterations)
    # Pattern matches: RE:, FW:, FWD:, R:, I: (Italian "Inoltrato")
    while True:
        new_subject = re.sub(r"^(?:re|fw|fwd|r|i):\s*", "", subject, flags=re.IGNORECASE)
        if new_subject == subject:
            break  # No more prefixes to remove
        subject = new_subject

    # Lowercase
    subject = subject.lower()

    # Normalize unicode whitespace
    subject = _normalize_unicode_whitespace(subject)

    # Strip
    subject = subject.strip()

    return subject
