"""
RFC5322/MIME Email Parsing

Gestisce:
- Header parsing completo con unfolding e charset decoding
- MIME multipart body extraction
- HTML→text conversion robusta
- BUG-001 MITIGATION: Support per raw_bytes quando body è troncato
- BUG-008 MITIGATION: HTML entity decoding

DETERMINISMO: Output deve essere riproducibile a parità di input e versioni.
"""

import html
import re
from email import policy
from email.parser import BytesParser
from email.header import decode_header
from email.message import Message
from typing import Dict, Tuple, Optional

from bs4 import BeautifulSoup
import html2text

from src.models import InputEmail, ParsingError
from src.logging_setup import get_logger

logger = get_logger(__name__)


# ==============================================================================
# HEADER PROCESSING
# ==============================================================================


def parse_headers_rfc5322(raw_bytes: bytes) -> Dict[str, str]:
    """
    Parse RFC5322 headers con unfolding e charset decoding.
    
    Features:
    - Unfold header (rimuove line breaks interni)
    - Decode charset (UTF-8, ISO-8859-1, etc.)
    - Lowercase keys per normalizzazione
    - Concatena header duplicati con ';'
    
    Args:
        raw_bytes: Raw email bytes
        
    Returns:
        Dict con header processati (keys lowercase)
        
    Raises:
        ParsingError: Se parsing fallisce
    """
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
        headers: Dict[str, str] = {}

        for key, value in msg.items():
            key_lower = key.lower()

            # Decode header with charset handling
            decoded_value = _decode_header_value(value)

            # Handle duplicate headers (concatenate with semicolon)
            if key_lower in headers:
                headers[key_lower] = f"{headers[key_lower]}; {decoded_value}"
            else:
                headers[key_lower] = decoded_value

        # Validation: an email must have at least some basic headers
        # If we got an empty dict, the input was likely not a valid email
        if not headers:
            raise ValueError("No valid RFC5322 headers found in input")

        return headers

    except Exception as e:
        logger.error("header_parsing_failed", error=str(e))
        raise ParsingError(f"Failed to parse RFC5322 headers: {e}") from e


def _decode_header_value(value: str) -> str:
    """
    Decode header value handling various charsets.
    
    Handles RFC2047 encoded-words: =?charset?encoding?encoded-text?=
    """
    try:
        # decode_header returns list of (decoded_bytes, charset) tuples
        decoded_parts = decode_header(value)
        result_parts = []

        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                # Decode bytes with specified charset (or fallback to utf-8)
                try:
                    decoded = part.decode(charset or "utf-8", errors="replace")
                except (LookupError, UnicodeDecodeError):
                    # Fallback for unknown charset
                    decoded = part.decode("utf-8", errors="replace")
                result_parts.append(decoded)
            else:
                # Already a string
                result_parts.append(str(part))

        return " ".join(result_parts)

    except Exception:
        # Fallback: return as-is if decoding fails
        return str(value)


# ==============================================================================
# MIME BODY EXTRACTION
# ==============================================================================


def extract_body_parts_from_truncated(input_email: InputEmail) -> Tuple[str, str]:
    """
    Extract text/plain and text/html from email.
    
    BUG-001 MITIGATION:
    - Se raw_bytes disponibile → full MIME parse
    - Altrimenti → usa body troncato dal layer ingestion + log warning
    
    Args:
        input_email: Input email (può avere raw_bytes opzionale)
        
    Returns:
        (text_plain, text_html) tuple
    """
    # Check if we have raw bytes for full parsing
    if input_email.raw_bytes:
        logger.debug("using_raw_bytes_for_full_parse", uid=input_email.uid)
        return _extract_body_from_raw(input_email.raw_bytes)

    # Fallback: use truncated body from ingestion layer
    if input_email.body_truncated:
        logger.warning(
            "using_truncated_body_fallback",
            uid=input_email.uid,
            text_len=len(input_email.body_text),
            html_len=len(input_email.body_html),
        )

    return input_email.body_text, input_email.body_html


def _extract_body_from_raw(raw_bytes: bytes) -> Tuple[str, str]:
    """
    Extract body parts from raw email bytes (full MIME parsing).
    
    Handles:
    - Multipart emails (alternative, mixed, nested)
    - Single-part emails
    - Charset decoding
    - Skip attachments
    
    Returns:
        (text_plain, text_html) tuple
    """
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
        return _extract_body_parts_recursive(msg)

    except Exception as e:
        logger.error("mime_parsing_failed", error=str(e))
        raise ParsingError(f"Failed to extract body from raw bytes: {e}") from e


def _extract_body_parts_recursive(msg: Message) -> Tuple[str, str]:
    """
    Recursively extract text/plain and text/html parts.
    
    Skip attachments (Content-Disposition: attachment).
    Merge multiple parts of same type.
    """
    text_parts = []
    html_parts = []

    if msg.is_multipart():
        # Walk through all parts
        for part in msg.walk():
            # Skip multipart containers
            if part.is_multipart():
                continue

            content_type = part.get_content_type()
            content_disposition = part.get("Content-Disposition", "")

            # Skip attachments
            if "attachment" in content_disposition.lower():
                continue

            # Extract text/plain
            if content_type == "text/plain":
                text_content = _get_part_content(part)
                if text_content:
                    text_parts.append(text_content)

            # Extract text/html
            elif content_type == "text/html":
                html_content = _get_part_content(part)
                if html_content:
                    html_parts.append(html_content)

    else:
        # Single-part message
        content_type = msg.get_content_type()

        if content_type == "text/plain":
            text_content = _get_part_content(msg)
            if text_content:
                text_parts.append(text_content)

        elif content_type == "text/html":
            html_content = _get_part_content(msg)
            if html_content:
                html_parts.append(html_content)

    # Merge parts with double newline separator
    text_plain = "\n\n".join(text_parts) if text_parts else ""
    text_html = "\n\n".join(html_parts) if html_parts else ""

    return text_plain, text_html


def _get_part_content(part: Message) -> str:
    """
    Extract content from email part with charset handling.
    
    Returns decoded string content.
    """
    try:
        # Get payload (handles base64/quoted-printable automatically with policy.default)
        content = part.get_content()

        # If content is bytes, decode with charset
        if isinstance(content, bytes):
            charset = part.get_content_charset() or "utf-8"
            try:
                return content.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                return content.decode("utf-8", errors="replace")

        # Already string
        return str(content)

    except Exception as e:
        logger.warning("part_content_extraction_failed", error=str(e))
        return ""


# ==============================================================================
# HTML TO TEXT CONVERSION
# ==============================================================================


def html_to_text_robust(html_content: str) -> str:
    """
    Conversione HTML→text robusta e deterministica.
    
    BUG-008 MITIGATION: html.unescape() PRIMA di BeautifulSoup per gestire
    entità HTML encoded (e.g., &#64; → @, &amp; → &).
    
    Pipeline:
    1. HTML entity decoding (html.unescape)
    2. Parse con BeautifulSoup (lxml parser)
    3. Remove script/style/meta tags
    4. Get text with whitespace cleanup
    5. Cleanup whitespace
    
    Args:
        html_content: HTML string to convert
        
    Returns:
        Plain text representation
    """
    if not html_content or not html_content.strip():
        return ""

    try:
        # BUG-008 MITIGATION: Decode HTML entities first
        html_content = html.unescape(html_content)

        # Parse HTML with robust parser (html.parser is built-in, no extra deps)
        soup = BeautifulSoup(html_content, "html.parser")

        # Remove script, style, meta tags (non-content elements)
        for tag in soup(["script", "style", "meta", "link", "noscript"]):
            tag.decompose()

        # Preserve links by adding URL after link text
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            if href and not href.startswith("#"):  # Skip anchor links
                # Add URL in parentheses after link text
                link_text = a_tag.get_text()
                a_tag.string = f"{link_text} ({href})"

        # Get text directly (simpler and more reliable than html2text)
        text = soup.get_text(separator="\n", strip=True)

        # Cleanup whitespace
        text = _cleanup_whitespace(text)

        return text.strip()

    except Exception as e:
        logger.warning("html_to_text_failed", error=str(e), html_preview=html_content[:100])
        # Fallback: return empty string
        return ""


def _cleanup_whitespace(text: str) -> str:
    """
    Cleanup excessive whitespace deterministicamente.
    
    - Multiple spaces → single space
    - Max 2 consecutive newlines
    - Strip trailing whitespace per line
    """
    # Strip trailing whitespace from each line
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)

    # Reduce multiple spaces to single
    text = re.sub(r" {2,}", " ", text)

    # Max 2 consecutive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text


# ==============================================================================
# BODY MERGING
# ==============================================================================


def merge_body_parts(text_plain: str, text_html: str) -> str:
    """
    Merge text/plain e text/html in un unico body canonico.
    
    Logic:
    - Se abbiamo plain text → usa quello
    - Se abbiamo solo HTML → converti HTML→text
    - Se abbiamo entrambi → usa plain + aggiungi HTML→text se diverso
    
    Args:
        text_plain: Plain text part
        text_html: HTML part
        
    Returns:
        Merged canonical body
    """
    # Convert HTML to text if present
    html_as_text = ""
    if text_html.strip():
        html_as_text = html_to_text_robust(text_html)

    # Case 1: Only plain text
    if text_plain.strip() and not html_as_text.strip():
        return text_plain

    # Case 2: Only HTML
    if not text_plain.strip() and html_as_text.strip():
        return html_as_text

    # Case 3: Both available
    if text_plain.strip() and html_as_text.strip():
        # Check if HTML adds significant content beyond plain text
        plain_words = set(text_plain.lower().split())
        html_words = set(html_as_text.lower().split())

        # If HTML has >20% more unique words, append it
        if len(html_words - plain_words) > len(plain_words) * 0.2:
            return f"{text_plain}\n\n{html_as_text}"
        else:
            # HTML is mostly redundant, use plain only
            return text_plain

    # Case 4: Neither available
    return ""
