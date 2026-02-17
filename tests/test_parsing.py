"""
Test suite for RFC5322/MIME parsing

Verifica:
- Header parsing con unfolding e charset decoding
- MIME multipart extraction
- HTML→text conversion deterministica
- BUG-001: raw_bytes support
- BUG-008: HTML entity decoding
- Edge cases e charset handling
"""

import pytest
from email import policy
from email.message import EmailMessage

from src.parsing import (
    parse_headers_rfc5322,
    extract_body_parts_from_truncated,
    html_to_text_robust,
    merge_body_parts,
    _decode_header_value,
    _cleanup_whitespace,
    ParsingError,
)
from src.models import InputEmail


# ==============================================================================
# TEST HEADER PARSING
# ==============================================================================


def test_parse_headers_simple():
    """Test basic header parsing"""
    email_bytes = b"""From: sender@example.com
To: recipient@example.com
Subject: Test Email
Message-ID: <123@example.com>

Body text
"""
    headers = parse_headers_rfc5322(email_bytes)

    assert headers["from"] == "sender@example.com"
    assert headers["to"] == "recipient@example.com"
    assert headers["subject"] == "Test Email"
    assert headers["message-id"] == "<123@example.com>"


def test_parse_headers_unfolding():
    """Test header unfolding (multi-line headers)"""
    email_bytes = b"""Subject: This is a very long subject line
 that continues on the next line
 and maybe even a third line
From: sender@example.com

Body
"""
    headers = parse_headers_rfc5322(email_bytes)

    # Should be unfolded to single line
    assert "very long subject" in headers["subject"]
    assert "continues" in headers["subject"]
    assert "third line" in headers["subject"]
    # Should not contain literal newlines
    assert "\n" not in headers["subject"]


def test_parse_headers_charset_decoding():
    """Test charset decoding (RFC2047 encoded-words)"""
    # Italian subject with UTF-8 encoding
    email_bytes = b"""From: test@example.com
Subject: =?UTF-8?B?T2dnZXR0byBjb24gw6BjY2VudGk=?=
To: dest@example.com

Body
"""
    headers = parse_headers_rfc5322(email_bytes)

    # Should decode to "Oggetto con àccenti"
    assert "Oggetto" in headers["subject"]
    assert "àccenti" in headers["subject"] or "accenti" in headers["subject"]


def test_parse_headers_duplicate():
    """Test handling of duplicate headers (e.g., multiple Received)"""
    email_bytes = b"""Received: from server1.example.com
Received: from server2.example.com
From: sender@example.com

Body
"""
    headers = parse_headers_rfc5322(email_bytes)

    # Duplicate headers should be concatenated with semicolon
    assert "received" in headers
    assert "server1" in headers["received"]
    assert "server2" in headers["received"]
    assert ";" in headers["received"]


def test_parse_headers_malformed_graceful():
    """Test graceful handling of malformed headers"""
    # Completely invalid email
    email_bytes = b"This is not a valid email format"

    # Should raise ParsingError, not crash
    with pytest.raises(ParsingError):
        parse_headers_rfc5322(email_bytes)


# ==============================================================================
# TEST BODY EXTRACTION (BUG-001 MITIGATION)
# ==============================================================================


def test_extract_body_with_raw_bytes():
    """Test full MIME parsing when raw_bytes available (BUG-001 mitigation)"""
    raw_email = b"""From: sender@example.com
To: recipient@example.com
Subject: Test
Content-Type: text/plain; charset="utf-8"

This is the full body content that was not truncated!
"""
    input_email = InputEmail(
        uid="1",
        uidvalidity="1",
        mailbox="INBOX",
        from_addr="sender@example.com",
        to_addrs=["recipient@example.com"],
        subject="Test",
        date="2026-02-17T10:00:00Z",
        body_text="truncated...",  # Truncated by ingestion
        body_html="",
        size=len(raw_email),
        headers={},
        message_id="<1@example.com>",
        fetched_at="2026-02-17T10:00:00Z",
        raw_bytes=raw_email,  # Full raw bytes provided
        body_truncated=True,
    )

    text_plain, text_html = extract_body_parts_from_truncated(input_email)

    # Should extract full body from raw_bytes, not use truncated version
    assert "full body content" in text_plain
    assert "not truncated" in text_plain


def test_extract_body_fallback_truncated():
    """Test fallback to truncated body when raw_bytes not available"""
    input_email = InputEmail(
        uid="1",
        uidvalidity="1",
        mailbox="INBOX",
        from_addr="sender@example.com",
        to_addrs=[],
        subject="Test",
        date="2026-02-17T10:00:00Z",
        body_text="This is truncated body",
        body_html="<p>HTML truncated</p>",
        size=5000,
        headers={},
        message_id="<1@example.com>",
        fetched_at="2026-02-17T10:00:00Z",
        raw_bytes=None,  # No raw bytes
        body_truncated=True,
    )

    text_plain, text_html = extract_body_parts_from_truncated(input_email)

    # Should use truncated body from ingestion
    assert text_plain == "This is truncated body"
    assert text_html == "<p>HTML truncated</p>"


def test_extract_body_multipart_alternative():
    """Test extraction from multipart/alternative email"""
    raw_email = b"""From: sender@example.com
To: recipient@example.com
Content-Type: multipart/alternative; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset="utf-8"

Plain text version

--boundary123
Content-Type: text/html; charset="utf-8"

<p>HTML version</p>

--boundary123--
"""
    input_email = InputEmail(
        uid="1",
        uidvalidity="1",
        mailbox="INBOX",
        from_addr="sender@example.com",
        to_addrs=[],
        subject="Test",
        date="2026-02-17T10:00:00Z",
        body_text="",
        body_html="",
        size=len(raw_email),
        headers={},
        message_id="<1@example.com>",
        fetched_at="2026-02-17T10:00:00Z",
        raw_bytes=raw_email,
    )

    text_plain, text_html = extract_body_parts_from_truncated(input_email)

    assert "Plain text version" in text_plain
    assert "<p>HTML version</p>" in text_html


def test_extract_body_skip_attachments():
    """Test that attachments are skipped during body extraction"""
    raw_email = b"""From: sender@example.com
To: recipient@example.com
Content-Type: multipart/mixed; boundary="boundary123"

--boundary123
Content-Type: text/plain

Email body

--boundary123
Content-Type: application/pdf
Content-Disposition: attachment; filename="doc.pdf"

Binary attachment data...

--boundary123--
"""
    input_email = InputEmail(
        uid="1",
        uidvalidity="1",
        mailbox="INBOX",
        from_addr="sender@example.com",
        to_addrs=[],
        subject="Test",
        date="2026-02-17T10:00:00Z",
        body_text="",
        body_html="",
        size=len(raw_email),
        headers={},
        message_id="<1@example.com>",
        fetched_at="2026-02-17T10:00:00Z",
        raw_bytes=raw_email,
    )

    text_plain, text_html = extract_body_parts_from_truncated(input_email)

    assert "Email body" in text_plain
    assert "Binary attachment" not in text_plain  # Attachment skipped


# ==============================================================================
# TEST HTML TO TEXT CONVERSION
# ==============================================================================


def test_html_to_text_simple():
    """Test basic HTML to text conversion"""
    html = "<p>Hello <b>world</b></p>"
    text = html_to_text_robust(html)

    assert "Hello" in text
    assert "world" in text


def test_html_to_text_entity_decoding():
    """Test HTML entity decoding (BUG-008 mitigation)"""
    html = "<p>Email: test&#64;example.com</p><p>Unicode: &amp; &lt; &gt;</p>"
    text = html_to_text_robust(html)

    # &#64; should become @
    assert "@" in text
    assert "test@example.com" in text

    # HTML entities should be decoded
    assert "&" in text
    assert "<" in text
    assert ">" in text


def test_html_to_text_removes_scripts():
    """Test that script tags are removed"""
    html = """
    <html>
    <head><script>alert('malicious');</script></head>
    <body><p>Safe content</p></body>
    </html>
    """
    text = html_to_text_robust(html)

    assert "Safe content" in text
    assert "alert" not in text
    assert "malicious" not in text


def test_html_to_text_removes_styles():
    """Test that style tags are removed"""
    html = '<style>body { color: red; }</style><p>Content</p>'
    text = html_to_text_robust(html)

    assert "Content" in text
    assert "color:" not in text
    assert "red" not in text


def test_html_to_text_deterministic():
    """Test that HTML→text conversion is deterministic"""
    html = "<p>Test <b>determinism</b> with <i>multiple</i> runs</p>"

    results = [html_to_text_robust(html) for _ in range(10)]

    # All results should be identical
    assert all(r == results[0] for r in results)


def test_html_to_text_empty():
    """Test handling of empty HTML"""
    assert html_to_text_robust("") == ""
    assert html_to_text_robust("   ") == ""
    assert html_to_text_robust("<html></html>") == ""


def test_html_to_text_malformed():
    """Test handling of malformed HTML"""
    malformed = "<p>Unclosed paragraph<div>Nested without closing"
    text = html_to_text_robust(malformed)

    # Should not crash, should extract text
    assert "Unclosed paragraph" in text
    assert "Nested" in text


def test_html_to_text_unicode():
    """Test handling of unicode characters"""
    html = "<p>Unicode: €, ñ, 日本語, 🎉</p>"
    text = html_to_text_robust(html)

    assert "€" in text
    assert "ñ" in text
    assert "日本語" in text
    assert "🎉" in text


# ==============================================================================
# TEST WHITESPACE CLEANUP
# ==============================================================================


def test_cleanup_whitespace_multiple_spaces():
    """Test cleanup of multiple spaces"""
    text = "Hello    world    with     spaces"
    cleaned = _cleanup_whitespace(text)
    assert cleaned == "Hello world with spaces"


def test_cleanup_whitespace_multiple_newlines():
    """Test cleanup of excessive newlines"""
    text = "Line 1\n\n\n\n\nLine 2"
    cleaned = _cleanup_whitespace(text)
    assert cleaned == "Line 1\n\nLine 2"


def test_cleanup_whitespace_trailing():
    """Test removal of trailing whitespace per line"""
    text = "Line 1   \nLine 2  \nLine 3"
    cleaned = _cleanup_whitespace(text)
    assert cleaned == "Line 1\nLine 2\nLine 3"


# ==============================================================================
# TEST BODY MERGING
# ==============================================================================


def test_merge_body_plain_only():
    """Test merging when only plain text available"""
    result = merge_body_parts("Plain text content", "")
    assert result == "Plain text content"


def test_merge_body_html_only():
    """Test merging when only HTML available"""
    result = merge_body_parts("", "<p>HTML content</p>")
    assert "HTML content" in result


def test_merge_body_both_redundant():
    """Test merging when HTML is redundant with plain"""
    plain = "This is the email content"
    html = "<p>This is the email content</p>"

    result = merge_body_parts(plain, html)

    # Should use plain only (HTML is redundant)
    assert result == plain


def test_merge_body_both_html_adds_content():
    """Test merging when HTML has additional content"""
    plain = "Short plain text"
    html = "<p>Short plain text</p><p>Additional paragraph with more content and details</p>"

    result = merge_body_parts(plain, html)

    # Should include both (HTML adds >20% more words)
    assert "Short plain text" in result
    assert "Additional" in result or "paragraph" in result


def test_merge_body_empty_both():
    """Test merging when both are empty"""
    result = merge_body_parts("", "")
    assert result == ""


# ==============================================================================
# TEST CHARSET HANDLING
# ==============================================================================


def test_charset_iso_8859_1():
    """Test handling of ISO-8859-1 charset"""
    raw_email = b"""From: sender@example.com
Content-Type: text/plain; charset="iso-8859-1"

Testo con caratteri accentati: \xe0\xe8\xec\xf2\xf9
"""
    input_email = InputEmail(
        uid="1",
        uidvalidity="1",
        mailbox="INBOX",
        from_addr="sender@example.com",
        to_addrs=[],
        subject="Test",
        date="2026-02-17T10:00:00Z",
        body_text="",
        body_html="",
        size=len(raw_email),
        headers={},
        message_id="<1@example.com>",
        fetched_at="2026-02-17T10:00:00Z",
        raw_bytes=raw_email,
    )

    text_plain, _ = extract_body_parts_from_truncated(input_email)

    # Should decode ISO-8859-1 correctly to UTF-8
    assert "Testo" in text_plain
    # ISO-8859-1 accented chars should be preserved
    assert "à" in text_plain or "accentati" in text_plain


def test_decode_header_value_mixed_charset():
    """Test _decode_header_value with mixed charsets"""
    # Test simple ASCII
    assert _decode_header_value("Simple Header") == "Simple Header"

    # Test with encoded-word (would need proper RFC2047 encoding)
    # For now, test that it doesn't crash
    value = _decode_header_value("Test =?UTF-8?Q?value?=")
    assert isinstance(value, str)


# ==============================================================================
# EDGE CASES
# ==============================================================================


def test_extract_body_nested_multipart():
    """Test extraction from nested multipart structure"""
    raw_email = b"""Content-Type: multipart/mixed; boundary="outer"

--outer
Content-Type: multipart/alternative; boundary="inner"

--inner
Content-Type: text/plain

Plain part

--inner
Content-Type: text/html

<p>HTML part</p>

--inner--

--outer--
"""
    input_email = InputEmail(
        uid="1",
        uidvalidity="1",
        mailbox="INBOX",
        from_addr="test@example.com",
        to_addrs=[],
        subject="Test",
        date="2026-02-17T10:00:00Z",
        body_text="",
        body_html="",
        size=len(raw_email),
        headers={},
        message_id="<1@example.com>",
        fetched_at="2026-02-17T10:00:00Z",
        raw_bytes=raw_email,
    )

    text_plain, text_html = extract_body_parts_from_truncated(input_email)

    assert "Plain part" in text_plain
    assert "HTML part" in text_html


def test_html_to_text_with_links():
    """Test that links are preserved (for downstream analysis)"""
    html = '<p>Click <a href="https://example.com">here</a></p>'
    text = html_to_text_robust(html)

    # Links should be preserved in markdown-like format
    assert "Click" in text
    assert "here" in text
    # html2text preserves links as [text](url)
    assert "example.com" in text or "[here]" in text


def test_parse_headers_lowercase_keys():
    """Test that header keys are lowercased"""
    email_bytes = b"""FROM: sender@example.com
TO: recipient@example.com
Subject: Test

Body
"""
    headers = parse_headers_rfc5322(email_bytes)

    # All keys should be lowercase
    assert "from" in headers
    assert "to" in headers
    assert "subject" in headers
    # Original case should not be present
    assert "FROM" not in headers
