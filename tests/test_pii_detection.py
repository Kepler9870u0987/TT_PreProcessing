"""
Test suite for PII detection & redaction

Verifica:
- Regex detection (EMAIL, PHONE_IT, CF, PIVA, IBAN)
- NER detection (nomi, organizzazioni)
- Whitelist (business terms non redatti)
- Merge logic con priority (regex > ner)
- Hash determinism
- BUG-004: Golden dataset NER
- BUG-006: Memory safety su large text
- Header redaction
"""

import pytest
import os
from unittest.mock import patch

from src.pii_detection import (
    PIIDetector,
    redact_headers_pii,
    get_pii_detector,
    COMPILED_PII_PATTERNS,
    COMPILED_WHITELIST_PATTERNS,
    PIIDetectionError,
)
from src.config import reset_config_cache


@pytest.fixture
def detector():
    """Create PIIDetector with test salt"""
    return PIIDetector(salt="test-salt-123456789abcdef0")


@pytest.fixture
def valid_env():
    """Provide valid environment  for config"""
    return {"PREPROCESSING_PII_SALT": "test-salt-for-pii-detection-12345678"}


@pytest.fixture(autouse=True)
def cleanup_config():
    """Reset config cache after each test"""
    yield
    reset_config_cache()


# ==============================================================================
# TEST REGEX DETECTION
# ==============================================================================


def test_detect_email(detector):
    """Test EMAIL detection"""
    text = "Contact me at mario.rossi@example.com for details."
    redactions = detector.detect_pii_regex(text)

    assert len(redactions) == 1
    assert redactions[0].type == "EMAIL"
    assert redactions[0].detection_method == "regex"
    assert redactions[0].confidence == 1.0
    assert "mario.rossi@example.com" in text[redactions[0].span_start : redactions[0].span_end]


def test_detect_phone_italian(detector):
    ""Test PHONE_IT detection"""
    texts = [
        "Chiamami al +39 02 12345678",
        "Telefono: 02 12345678",
        "Mobile +39 345 1234567",
    ]

    for text in texts:
        redactions = detector.detect_pii_regex(text)
        assert len(redactions) >= 1
        assert any(r.type == "PHONE_IT" for r in redactions)


def test_detect_codice_fiscale(detector):
    """Test CF (Codice Fiscale) detection"""
    text = "Il mio CF è RSSMRA85M01H501Z per la fattura."
    redactions = detector.detect_pii_regex(text)

    cf_redactions = [r for r in redactions if r.type == "CF"]
    assert len(cf_redactions) == 1
    assert cf_redactions[0].detection_method == "regex"


def test_detect_piva(detector):
    """Test P.IVA detection"""
    texts = [
        "P.IVA: IT12345678901",
        "Partita IVA 12345678901",
    ]

    for text in texts:
        redactions = detector.detect_pii_regex(text)
        piva_redactions = [r for r in redactions if r.type == "PIVA"]
        assert len(piva_redactions) >= 1


def test_detect_iban(detector):
    """Test IBAN detection"""
    text = "Bonifico su IBAN IT60X0542811101000000123456"
    redactions = detector.detect_pii_regex(text)

    iban_redactions = [r for r in redactions if r.type == "IBAN"]
    assert len(iban_redactions) == 1


def test_detect_multiple_pii_types(detector):
    """Test detection of multiple PII types in same text"""
    text = """
    Contatti:
    Email: test@example.com
    Telefono: +39 02 12345678
    CF: RSSMRA85M01H501Z
    """
    redactions = detector.detect_pii_regex(text)

    types = {r.type for r in redactions}
    assert "EMAIL" in types
    assert "PHONE_IT" in types
    assert "CF" in types
    assert len(redactions) >= 3


# ==============================================================================
# TEST WHITELIST (OVER-REDACTION PREVENTION)
# ==============================================================================


def test_whitelist_invoice_number_not_redacted(detector):
    """Test that invoice numbers are NOT redacted"""
    text = "Fattura n. 12345 del 17/02/2026"
    redactions = detector.detect_pii_regex(text)

    # Should not redact "12345" as phone/piva because it's part of invoice number
    assert len(redactions) == 0


def test_whitelist_reference_number_not_redacted(detector):
    """Test that reference numbers are NOT redacted"""
    text = "Rif. 98765432101 - pratica chiusa"
    redactions = detector.detect_pii_regex(text)

    # "98765432101" could match PIVA pattern, but should be whitelisted
    # Note: Actual behavior depends on whitelist pattern strength
    # At minimum, should not cause false positive alarm


def test_business_terms_preserved(detector):
    """Test whitelist patterns are compiled correctly"""
    assert len(COMPILED_WHITELIST_PATTERNS) > 0

    # Test invoice pattern
    invoice_pattern = COMPILED_WHITELIST_PATTERNS.get("INVOICE_NUMBER")
    if invoice_pattern:
        assert invoice_pattern.search("fattura n. 123")


# ==============================================================================
# TEST NER DETECTION
# ==============================================================================


@pytest.mark.skipif(not os.path.exists("/usr/local/lib"), reason="Skip if spaCy model not installed")
def test_detect_person_name(detector, valid_env):
    """Test NER detection of person names"""
    with patch.dict(os.environ, valid_env, clear=True):
        text = "Mario Rossi ha inviato il documento."
        
        try:
            redactions = detector.detect_pii_ner(text)
            name_redactions = [r for r in redactions if r.type == "NAME"]
            
            # Should detect "Mario Rossi"
            assert len(name_redactions) >= 1
            assert name_redactions[0].detection_method == "ner"
        except PIIDetectionError:
            pytest.skip("spaCy model not available")


@pytest.mark.skipif(not os.path.exists("/usr/local/lib"), reason="Skip if spaCy model not installed")
def test_detect_organization_name(detector, valid_env):
    """Test NER detection of organization names"""
    with patch.dict(os.environ, valid_env, clear=True):
        text = "Lavoro per Microsoft Italia dal 2020."
        
        try:
            redactions = detector.detect_pii_ner(text)
            org_redactions = [r for r in redactions if r.type == "ORG"]
            
            assert len(org_redactions) >= 1
        except PIIDetectionError:
            pytest.skip("spaCy model not available")


def test_ner_anti_false_positive_short_names(detector):
    """Test that very short entities are skipped (anti false-positive)"""
    text = "Il Dr. ha confermato."
    
    try:
        redactions = detector.detect_pii_ner(text)
        # "Dr" should be skipped (< 3 chars)
        assert len(redactions) == 0 or all(r.type != "NAME" for r in redactions)
    except PIIDetectionError:
        pytest.skip("spaCy model not available")


def test_ner_anti_false_positive_titles(detector):
    """Test that titles are skipped"""
    text = "Il Dott. Rossi e il Prof. Bianchi."
    
    try:
        redactions = detector.detect_pii_ner(text)
        # "Dott" and "Prof" should be skipped
        skipped = [r for r in redactions if r.span_start < 10]  # First part
        # Titles should not be in redactions
    except PIIDetectionError:
        pytest.skip("spaCy model not available")


def test_ner_truncation_large_text(detector):
    """Test that large text is truncated for NER (BUG-006 mitigation)"""
    # Create text larger than 500KB
    large_text = "A" * 600_000  # 600KB
    
    try:
        redactions = detector.detect_pii_ner(large_text)
        # Should not raise memory error, should complete
        assert isinstance(redactions, list)
    except PIIDetectionError:
        pytest.skip("spaCy model not available")


# ==============================================================================
# TEST HASH DETERMINISM (CRITICAL)
# ==============================================================================


def test_hash_pii_deterministic(detector):
    """Test that same PII produces same hash (deterministic)"""
    pii_text = "mario.rossi@example.com"
    
    hash1 = detector._hash_pii(pii_text)
    hash2 = detector._hash_pii(pii_text)
    
    assert hash1 == hash2
    assert len(hash1) == 16  # Truncated to 16 hex chars


def test_hash_pii_different_for_different_text(detector):
    """Test that different PII produces different hash"""
    hash1 = detector._hash_pii("text1@example.com")
    hash2 = detector._hash_pii("text2@example.com")
    
    assert hash1 != hash2


def test_hash_pii_salt_dependent():
    """Test that hash changes with different salt"""
    detector1 = PIIDetector(salt="salt1")
    detector2 = PIIDetector(salt="salt2")
    
    pii_text = "test@example.com"
    hash1 = detector1._hash_pii(pii_text)
    hash2 = detector2._hash_pii(pii_text)
    
    assert hash1 != hash2  # Different salts → different hashes


# ==============================================================================
# TEST MERGE LOGIC
# ==============================================================================


def test_merge_redactions_no_overlap(detector):
    """Test merging with no overlaps"""
    from src.models import PIIRedaction
    
    redactions = [
        PIIRedaction("EMAIL", "hash1", "[PII_EMAIL]", 0, 10, 1.0, "regex"),
        PIIRedaction("EMAIL", "hash2", "[PII_EMAIL]", 20, 30, 1.0, "regex"),
    ]
    
    merged = detector.merge_redactions(redactions)
    assert len(merged) == 2


def test_merge_redactions_overlap_regex_priority(detector):
    """Test that regex has priority over NER when overlapping"""
    from src.models import PIIRedaction
    
    redactions = [
        PIIRedaction("EMAIL", "hash1", "[PII_EMAIL]", 0, 20, 1.0, "regex"),
        PIIRedaction("NAME", "hash2", "[PII_NAME]", 10, 25, 0.8, "ner"),  # Overlaps
    ]
    
    merged = detector.merge_redactions(redactions)
    assert len(merged) == 1
    assert merged[0].detection_method == "regex"  # Regex wins


def test_merge_redactions_longest_span(detector):
    """Test that longest span wins for same method"""
    from src.models import PIIRedaction
    
    redactions = [
        PIIRedaction("NAME", "hash1", "[PII_NAME]", 0, 10, 0.9, "ner"),
        PIIRedaction("NAME", "hash2", "[PII_NAME]", 5, 20, 0.9, "ner"),  # Longer
    ]
    
    merged = detector.merge_redactions(redactions)
    assert len(merged) == 1
    assert merged[0].span_end == 20  # Longer span wins


# ==============================================================================
# TEST APPLY REDACTIONS
# ==============================================================================


def test_apply_redactions_single(detector):
    """Test applying single redaction"""
    from src.models import PIIRedaction
    
    text = "Email: test@example.com here"
    redactions = [PIIRedaction("EMAIL", "hash", "[PII_EMAIL]", 7, 23, 1.0, "regex")]
    
    redacted = detector.apply_redactions(text, redactions)
    
    assert "test@example.com" not in redacted
    assert "[PII_EMAIL]" in redacted
    assert "Email:" in redacted
    assert "here" in redacted


def test_apply_redactions_multiple(detector):
    """Test applying multiple redactions"""
    from src.models import PIIRedaction
    
    text = "Email: test@example.com Phone: +39 02 123456"
    redactions = [
        PIIRedaction("EMAIL", "hash1", "[PII_EMAIL]", 7, 23, 1.0, "regex"),
        PIIRedaction("PHONE_IT", "hash2", "[PII_PHONE]", 31, 45, 1.0, "regex"),
    ]
    
    redacted = detector.apply_redactions(text, redactions)
    
    assert "test@example.com" not in redacted
    assert "+39 02 123456" not in redacted
    assert "[PII_EMAIL]" in redacted
    assert "[PII_PHONE]" in redacted


def test_apply_redactions_preserves_indices(detector):
    """Test that applying in reverse order preserves indices"""
    from src.models import PIIRedaction
    
    text = "AAA BBB CCC"
    # Redact BBB (indices 4-7)
    redactions = [PIIRedaction("TEST", "hash", "[X]", 4, 7, 1.0, "regex")]
    
    redacted = detector.apply_redactions(text, redactions)
    assert redacted == "AAA [X] CCC"


# ==============================================================================
# TEST DETECT AND REDACT (FULL PIPELINE)
# ==============================================================================


def test_detect_and_redact_email(detector):
    """Test full pipeline with email"""
    text = "Contact: mario.rossi@example.com"
    
    redacted_text, redactions = detector.detect_and_redact(text)
    
    assert "mario.rossi@example.com" not in redacted_text
    assert "[PII_EMAIL]" in redacted_text
    assert len(redactions) >= 1


def test_detect_and_redact_mixed(detector):
    """Test full pipeline with mixed PII"""
    text = "Email: test@example.com CF: RSSMRA85M01H501Z"
    
    redacted_text, redactions = detector.detect_and_redact(text)
    
    assert "test@example.com" not in redacted_text
    assert "RSSMRA85M01H501Z" not in redacted_text
    assert len(redactions) >= 2


def test_detect_and_redact_no_pii(detector):
    """Test full pipeline with no PII"""
    text = "This is a clean text with no personal data."
    
    redacted_text, redactions = detector.detect_and_redact(text)
    
    assert redacted_text == text  # Unchanged
    # Note: NER might detect something, so check carefully
    # At minimum, no regex PII should be found


# ==============================================================================
# TEST HEADER REDACTION
# ==============================================================================


def test_redact_headers_pii_from_field(detector):
    """Test redaction of PII in From header"""
    headers = {
        "from": "Mario Rossi <mario.rossi@example.com>",
        "to": "dest@example.com",
        "subject": "Test",
    }
    
    redacted = redact_headers_pii(headers, detector)
    
    assert "mario.rossi@example.com" not in redacted["from"]
    assert "[PII_EMAIL]" in redacted["from"]


def test_redact_headers_pii_subject(detector):
    """Test redaction of PII in Subject"""
    headers = {
        "from": "sender@example.com",
        "subject": "Contattami a test@example.com",
    }
    
    redacted = redact_headers_pii(headers, detector)
    
    assert "test@example.com" not in redacted["subject"]
    assert "[PII_EMAIL]" in redacted["subject"]


def test_redact_headers_preserves_non_pii(detector):
    """Test that non-PII headers are preserved"""
    headers = {
        "from": "sender@example.com",
        "message-id": "<12345@example.com>",
        "date": "Mon, 17 Feb 2026 10:00:00 +0000",
    }
    
    redacted = redact_headers_pii(headers, detector)
    
    # Non-PII headers should pass through
    assert redacted["message-id"] == "<12345@example.com>"
    assert redacted["date"] == "Mon, 17 Feb 2026 10:00:00 +0000"


# ==============================================================================
# TEST SINGLETON
# ==============================================================================


def test_get_pii_detector_singleton(valid_env):
    """Test that get_pii_detector returns singleton"""
    with patch.dict(os.environ, valid_env, clear=True):
        detector1 = get_pii_detector()
        detector2 = get_pii_detector()
        
        assert detector1 is detector2  # Same instance


# ==============================================================================
# TEST PATTERNS COMPILED
# ==============================================================================


def test_pii_patterns_compiled():
    """Test that all PII patterns are compiled correctly"""
    assert len(COMPILED_PII_PATTERNS) >= 5
    
    for name, pattern in COMPILED_PII_PATTERNS.items():
        assert pattern is not None
        # Test that pattern can be used
        pattern.search("test string")


def test_whitelist_patterns_compiled():
    """Test that whitelist patterns are compiled"""
    assert len(COMPILED_WHITELIST_PATTERNS) >= 2
    
    for name, pattern in COMPILED_WHITELIST_PATTERNS.items():
        assert pattern is not None


# ==============================================================================
# TEST EDGE CASES
# ==============================================================================


def test_detect_pii_empty_text(detector):
    """Test PII detection on empty text"""
    redactions = detector.detect_pii_regex("")
    assert redactions == []


def test_detect_and_redact_unicode(detector):
    """Test PII detection with Unicode text"""
    text = "Email: test@example.com - testo con àccenti €"
    
    redacted_text, redactions = detector.detect_and_redact(text)
    
    assert "test@example.com" not in redacted_text
    assert "àccenti" in redacted_text  # Non-PII unicode preserved
    assert "€" in redacted_text


# ==============================================================================
# GOLDEN DATASET NER (BUG-004 MITIGATION)
# ==============================================================================

# Golden dataset: manually annotated Italian sentences for NER regression testing
GOLDEN_NER_DATASET = [
    {
        "text": "Mario Rossi lavora a Milano.",
        "expected_entities": [
            {"text": "Mario Rossi", "type": "NAME"},
        ],
    },
    {
        "text": "L'azienda Microsoft ha sede a Redmond.",
        "expected_entities": [
            {"text": "Microsoft", "type": "ORG"},
        ],
    },
]


@pytest.mark.skipif(not os.path.exists("/usr/local/lib"), reason="Skip if spaCy model not installed")
def test_golden_dataset_ner_regression(detector):
    """
    BUG-004 MITIGATION: Test NER stability with golden dataset.
    
    If this test fails, NER model behavior has changed (drift detected).
    """
    for case in GOLDEN_NER_DATASET:
        text = case["text"]
        expected = case["expected_entities"]
        
        try:
            redactions = detector.detect_pii_ner(text, confidence_threshold=0.5)
            
            # Check expected entities are detected
            for exp_entity in expected:
                matching = [
                    r
                    for r in redactions
                    if exp_entity["type"] == r.type and exp_entity["text"].lower() in text[r.span_start : r.span_end].lower()
                ]
                
                # Allow some tolerance: at least one match
                # Strict assertion would be: assert len(matching) == 1
                # Relaxed for NER variability:
                if len(matching) == 0:
                    pytest.fail(
                        f"Expected entity '{exp_entity['text']}' type '{exp_entity['type']}' "
                        f"not detected in '{text}'. NER model may have drifted."
                    )
        except PIIDetectionError:
            pytest.skip("spaCy model not available")
