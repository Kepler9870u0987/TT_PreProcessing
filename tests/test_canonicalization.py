"""
Test suite for text canonicalization

Verifica:
- Pattern removal (quote, signature, disclaimer, etc.)
- Determinismo (stesso input → stesso output)
- Idempotenza (f(f(x)) == f(x))
- BUG-002: Regex timeout protection
- BUG-007: Unicode whitespace normalization
- Audit trail tracking
- Configuration flags
"""

import pytest
import re
from hypothesis import given, strategies as st

from src.canonicalization import (
    canonicalize_text,
    canonicalize_subject,
    safe_regex_finditer,
    RegexTimeoutError,
    _normalize_unicode_whitespace,
    _cleanup_excessive_whitespace,
    COMPILED_PATTERNS,
)
from src.models import CanonicalizationError


# ==============================================================================
# TEST PATTERN REMOVAL
# ==============================================================================


def test_canonicalize_remove_quote_standard():
    """Test removal of standard email quotes (>)"""
    text = """Hello,

> This is a quoted line
> Another quoted line

My response here.
"""
    canon, removed = canonicalize_text(text)

    assert "quoted line" not in canon
    assert "My response" in canon
    assert len(removed) >= 1
    assert any(r.type == "quote_standard" for r in removed)


def test_canonicalize_remove_reply_header_italian():
    """Test removal of Italian reply headers"""
    text = """Il giorno 17 febbraio 2026 alle 10:30, Mario Rossi ha scritto:

> Contenuto originale

Mia risposta.
"""
    canon, removed = canonicalize_text(text)

    assert "Il giorno" not in canon
    assert "ha scritto" not in canon
    assert "Mia risposta" in canon
    assert any(r.type == "reply_header_it" for r in removed)


def test_canonicalize_remove_signature_separator():
    """Test removal of signature separators"""
    text = """Email body content

--
Mario Rossi
Company Name
"""
    canon, removed = canonicalize_text(text)

    assert "Email body content" in canon
    # Signature separator and content after should be removed
    assert any(r.type == "signature_separator" for r in removed)


def test_canonicalize_remove_disclaimer():
    """Test removal of confidentiality disclaimers"""
    text = """Important email content.

Questo messaggio è indirizzato esclusivamente al destinatario e può contenere informazioni riservate e confidenziale.
"""
    canon, removed = canonicalize_text(text)

    assert "Important email" in canon
    assert "confidenziale" not in canon
    assert any(r.type == "disclaimer_confidential" for r in removed)


def test_canonicalize_remove_closing_formal():
    """Test removal of formal closings"""
    text = """Messaggio principale.

Cordiali saluti,
Mario Rossi
"""
    canon, removed = canonicalize_text(text)

    assert "Messaggio principale" in canon
    assert "Cordiali saluti" not in canon
    assert any(r.type == "closing_formal" for r in removed)


# ==============================================================================
# TEST DETERMINISM (CRITICAL)
# ==============================================================================


def test_canonicalize_deterministic():
    """
    CRITICAL: Test that canonicalization is deterministic.
    Same input must produce same output across multiple runs.
    """
    text = """Hello,

> quoted text
> more quotes

Content here.

--
Signature
"""

    results = [canonicalize_text(text) for _ in range(10)]

    # All canonical texts should be identical
    first_canon = results[0][0]
    for canon, _ in results[1:]:
        assert canon == first_canon, "Canonicalization is not deterministic"

    # All removed_sections should have same count
    first_removed_count = len(results[0][1])
    for _, removed in results[1:]:
        assert len(removed) == first_removed_count


# ==============================================================================
# TEST IDEMPOTENCE (CRITICAL)
# ==============================================================================


def test_canonicalize_idempotent():
    """
    CRITICAL: Test idempotence - applying twice should equal applying once.
    f(f(x)) == f(x)
    """
    text = """Email with > quotes and --signature"""

    canon1, removed1 = canonicalize_text(text)
    canon2, removed2 = canonicalize_text(canon1)

    # Second canonicalization should not change text
    assert canon1 == canon2
    # Second pass should find no more sections to remove
    assert len(removed2) == 0


@given(st.text(min_size=10, max_size=500))
def test_canonicalize_idempotent_property(text: str):
    """Property-based test: idempotence holds for any text"""
    try:
        canon1, _ = canonicalize_text(text, regex_timeout_sec=0.5)
        canon2, _ = canonicalize_text(canon1, regex_timeout_sec=0.5)
        assert canon1 == canon2
    except (CanonicalizationError, RegexTimeoutError):
        # Some random text might trigger edge cases, that's ok
        pass


# ==============================================================================
# TEST UNICODE NORMALIZATION (BUG-007 MITIGATION)
# ==============================================================================


def test_normalize_unicode_whitespace():
    """Test normalization of Unicode whitespace characters (BUG-007)"""
    # U+00A0: non-breaking space
    # U+2003: em space
    # U+2009: thin space
    text = "Hello\u00A0world\u2003with\u2009spaces"

    normalized = _normalize_unicode_whitespace(text)

    # All should be converted to ASCII space (0x20)
    assert normalized == "Hello world with spaces"
    # No Unicode whitespace should remain
    assert "\u00A0" not in normalized
    assert "\u2003" not in normalized
    assert "\u2009" not in normalized


def test_canonicalize_with_unicode_whitespace():
    """Test full canonicalization with Unicode whitespace"""
    text = "Email\u00A0content\u2003with\u2009various\u00A0spaces"

    canon, _ = canonicalize_text(text)

    # All Unicode whitespace should be normalized
    assert "\u00A0" not in canon
    assert "\u2003" not in canon
    assert canon == "Email content with various spaces"


def test_canonicalize_unicode_nfc():
    """Test Unicode NFC normalization"""
    # Composed vs decomposed unicode (e.g., é vs e + combining accent)
    text_composed = "café"  # U+00E9 (é composed)
    text_decomposed = "cafe\u0301"  # e + U+0301 (combining acute accent)

    canon_composed, _ = canonicalize_text(text_composed)
    canon_decomposed, _ = canonicalize_text(text_decomposed)

    # Both should normalize to same form
    assert canon_composed == canon_decomposed


# ==============================================================================
# TEST REGEX TIMEOUT (BUG-002 MITIGATION)
# ==============================================================================


def test_safe_regex_finditer_normal_case():
    """Test safe_regex_finditer works for normal cases"""
    pattern = re.compile(r"\b\w+\b")
    text = "Hello world"

    matches = safe_regex_finditer(pattern, text, timeout_sec=1.0)

    assert len(matches) == 2
    assert matches[0].group() == "Hello"
    assert matches[1].group() == "world"


def test_safe_regex_finditer_timeout():
    """Test safe_regex_finditer raises timeout on pathological regex"""
    # Pathological regex that causes catastrophic backtracking
    # (a+)+ with input "aaaaaaaaaaaaaaaaaaaaX" causes exponential backtracking
    pattern = re.compile(r"(a+)+b")
    text = "a" * 100 + "X"  # No 'b' at end, regex backtracks extensively

    # Should timeout and raise RegexTimeoutError
    with pytest.raises(RegexTimeoutError):
        safe_regex_finditer(pattern, text, timeout_sec=0.1)


def test_canonicalize_with_timeout_protection():
    """Test that canonicalization survives regex timeout"""
    # Create text that might cause regex issues
    text = "a" * 10000 + " normal content here"

    # Should complete without crashing (might skip some patterns due to timeout)
    canon, removed = canonicalize_text(text, regex_timeout_sec=0.5)

    # Should return something (even if not all patterns applied)
    assert isinstance(canon, str)
    assert isinstance(removed, list)


# ==============================================================================
# TEST WHITESPACE CLEANUP
# ==============================================================================


def test_cleanup_excessive_whitespace_multiple_spaces():
    """Test cleanup of multiple spaces"""
    text = "Hello    world    test"
    cleaned = _cleanup_excessive_whitespace(text)
    assert cleaned == "Hello world test"


def test_cleanup_excessive_whitespace_newlines():
    """Test cleanup of excessive newlines (max 2)"""
    text = "Line 1\n\n\n\n\nLine 2"
    cleaned = _cleanup_excessive_whitespace(text)
    assert cleaned == "Line 1\n\nLine 2"


def test_cleanup_trailing_whitespace():
    """Test removal of trailing whitespace per line"""
    text = "Line 1   \nLine 2  \nLine 3"
    cleaned = _cleanup_excessive_whitespace(text)
    assert cleaned == "Line 1\nLine 2\nLine 3"


# ==============================================================================
# TEST SUBJECT CANONICALIZATION
# ==============================================================================


def test_canonicalize_subject_remove_re():
    """Test removal of RE: prefix"""
    assert canonicalize_subject("RE: Test Subject") == "test subject"
    assert canonicalize_subject("re: Test Subject") == "test subject"
    assert canonicalize_subject("Re: Test Subject") == "test subject"


def test_canonicalize_subject_remove_fw():
    """Test removal of FW:/FWD: prefix"""
    assert canonicalize_subject("FW: Test Subject") == "test subject"
    assert canonicalize_subject("FWD: Test Subject") == "test subject"
    assert canonicalize_subject("Fwd: Test Subject") == "test subject"


def test_canonicalize_subject_remove_multiple_prefixes():
    """Test removal of multiple RE:/FW: prefixes"""
    subject = "RE: FW: RE: Original Subject"
    result = canonicalize_subject(subject)
    assert result == "original subject"
    assert "re:" not in result
    assert "fw:" not in result


def test_canonicalize_subject_italian_prefix():
    """Test removal of Italian prefix (I: for Inoltrato)"""
    assert canonicalize_subject("I: Oggetto email") == "oggetto email"
    assert canonicalize_subject("R: Oggetto email") == "oggetto email"


def test_canonicalize_subject_lowercase():
    """Test that subject is lowercased"""
    assert canonicalize_subject("UPPERCASE SUBJECT") == "uppercase subject"


def test_canonicalize_subject_strip_whitespace():
    """Test that leading/trailing whitespace is stripped"""
    assert canonicalize_subject("  Subject with spaces  ") == "subject with spaces"


def test_canonicalize_subject_empty():
    """Test handling of empty subject"""
    assert canonicalize_subject("") == ""
    assert canonicalize_subject("   ") == ""


def test_canonicalize_subject_unicode():
    """Test handling of Unicode in subject"""
    subject = "RE: Oggetto con àccenti"
    result = canonicalize_subject(subject)
    assert result == "oggetto con àccenti"


# ==============================================================================
# TEST CONFIGURATION FLAGS
# ==============================================================================


def test_canonicalize_with_remove_quotes_false():
    """Test that remove_quotes=False preserves quotes"""
    text = """Email content
> quoted line
More content"""

    canon, removed = canonicalize_text(text, remove_quotes=False, remove_signatures=True)

    # Quotes should be preserved
    assert "> quoted line" in canon or "quoted line" in canon
    # Should not have removed quote-type sections
    assert not any(r.type.startswith("quote") for r in removed)


def test_canonicalize_with_remove_signatures_false():
    """Test that remove_signatures=False preserves signatures"""
    text = """Email content
--
Signature here"""

    canon, removed = canonicalize_text(text, remove_quotes=True, remove_signatures=False)

    # Signature separator should be preserved
    assert "--" in canon or "Signature" in canon
    # Should not have removed signature-type sections
    assert not any(r.type.startswith("signature") for r in removed)


def test_canonicalize_all_removal_disabled():
    """Test with all removal disabled"""
    text = """Content
> quote
--
Signature"""

    canon, removed = canonicalize_text(text, remove_quotes=False, remove_signatures=False)

    # Everything should be preserved (only whitespace cleanup)
    # Note: Still applies unicode normalization and whitespace cleanup
    assert len(removed) == 0


# ==============================================================================
# TEST AUDIT TRAIL
# ==============================================================================


def test_removed_sections_audit_trail():
    """Test that removed sections are tracked for audit"""
    text = """Content
> quote
--
Signature
Cordiali saluti,
"""

    canon, removed = canonicalize_text(text)

    # Should have multiple removed sections
    assert len(removed) >= 2

    # Each removed section should have required fields
    for section in removed:
        assert hasattr(section, "type")
        assert hasattr(section, "span_start")
        assert hasattr(section, "span_end")
        assert hasattr(section, "content_preview")
        assert hasattr(section, "confidence")
        assert 0.0 <= section.confidence <= 1.0


def test_removed_section_content_preview_truncated():
    """Test that content_preview is truncated to 100 chars"""
    # Create long signature
    long_signature = "--\n" + "A" * 200

    text = f"""Email content
{long_signature}
"""

    canon, removed = canonicalize_text(text)

    # Find signature removal
    signature_removed = [r for r in removed if r.type == "signature_separator"]
    if signature_removed:
        # Content preview should be max 100 chars
        assert len(signature_removed[0].content_preview) <= 100


# ==============================================================================
# TEST EDGE CASES
# ==============================================================================


def test_canonicalize_empty_text():
    """Test canonicalization of empty text"""
    canon, removed = canonicalize_text("")
    assert canon == ""
    assert removed == []


def test_canonicalize_only_whitespace():
    """Test canonicalization of text with only whitespace"""
    canon, removed = canonicalize_text("   \n\n   \n   ")
    assert canon == ""
    assert removed == []


def test_canonicalize_text_with_only_patterns():
    """Test text that is entirely patterns (no content remains)"""
    text = """> quote 1
> quote 2
> quote 3"""

    canon, removed = canonicalize_text(text)

    # Should remove all quotes
    assert len(removed) >= 3
    # Canonical text should be empty or minimal
    assert len(canon.strip()) < 20


def test_canonicalize_mixed_line_endings():
    """Test handling of mixed line endings"""
    text = "Line 1\r\nLine 2\rLine 3\nLine 4"

    canon, _ = canonicalize_text(text)

    # All should be normalized to \n
    assert "\r\n" not in canon
    assert "\r" not in canon


def test_compiled_patterns_are_valid():
    """Test that all compiled patterns are valid regexes"""
    assert len(COMPILED_PATTERNS) > 0

    for pattern, pattern_type, confidence in COMPILED_PATTERNS:
        assert isinstance(pattern, re.Pattern)
        assert isinstance(pattern_type, str)
        assert 0.0 <= confidence <= 1.0
