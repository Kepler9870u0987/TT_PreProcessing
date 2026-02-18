"""
PII Detection & Redaction Module

GDPR Compliance Layer:
- Detect PII con regex (EMAIL, PHONE_IT, CF, PIVA, IBAN)  
- Detect PII con NER spaCy (nomi, organizzazioni)
- Hash deterministico con salt
- Merge redactions con priority logic
- BUG-004 MITIGATION: Golden dataset per stabilità NER
- BUG-006 MITIGATION: Truncate a 500KB per NER

CRITICAL SECURITY: Ogni redaction tracked per audit trail.
"""

import re
import hashlib
from typing import List, Dict, Tuple, Optional, Set
from functools import lru_cache

import spacy
from spacy.language import Language

from src.models import PIIRedaction, PIIDetectionError
from src.config import get_config
from src.logging_setup import get_logger

logger = get_logger(__name__)

# Version tracking
PII_REDACTION_VERSION = "1.0.0"


# ==============================================================================
# REGEX PATTERNS FOR PII
# ==============================================================================

PII_REGEX_PATTERNS: Dict[str, str] = {
    "EMAIL": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    "PHONE_IT": r'''(?:
        \+39[\s]?[0-9]{2,3}[\s]?[0-9]{6,7} |  # +39 format
        0[0-9]{2,3}[\s]?[0-9]{6,7}             # 0xx format
    )''',
    "PIVA": r'\b(?:IT\s?)?[0-9]{11}\b',  # P.IVA italiana
    "CF": r'\b[A-Z]{6}[0-9]{2}[A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z]\b',  # Codice Fiscale
    "IBAN": r'\bIT\d{2}[A-Z]\d{10}[0-9A-Z]{12}\b',  # IBAN italiano
}

# Business whitelist patterns (prevent over-redaction)
BUSINESS_WHITELIST_PATTERNS: Dict[str, str] = {
    "INVOICE_NUMBER": r'\b(?:fattura|invoice|ordine|order|pratica)\s*(?:n\.?|num\.?|nr\.?)?\s*\d+\b',
    "REFERENCE_NUMBER": r'\b(?:rif\.?|ref\.?|protocollo|prot\.?)\s*\d+\b',
}

# Compile patterns at module load
COMPILED_PII_PATTERNS: Dict[str, re.Pattern[str]] = {
    name: re.compile(pattern, re.VERBOSE | re.IGNORECASE) for name, pattern in PII_REGEX_PATTERNS.items()
}

COMPILED_WHITELIST_PATTERNS: Dict[str, re.Pattern[str]] = {
    name: re.compile(pattern, re.IGNORECASE) for name, pattern in BUSINESS_WHITELIST_PATTERNS.items()
}

# NER model version
NER_MODEL_VERSION = "it_core_news_lg-3.8.2"


# ==============================================================================
# PII DETECTOR CLASS
# ==============================================================================


class PIIDetector:
    """
    Rilevatore PII deterministico con Regex + NER.
    
    Features:
    - Regex-based detection (alta precisione)
    - NER-based detection spaCy (recall su nomi)
    - Hashing deterministico con salt
    - Merge logic con priority (regex > ner)
    - Memory-safe (truncation per large text)
    """

    def __init__(self, salt: Optional[str] = None):
        """
        Initialize PII detector.
        
        Args:
            salt: Salt per PII hashing. Se None, usa config.
        """
        self.config = get_config()
        self.salt = salt or self.config.pii_salt

        # Load spaCy model (lazy loading via singleton)
        self.nlp = self._get_nlp_model()

        logger.info("pii_detector_initialized", ner_model=NER_MODEL_VERSION, salt_len=len(self.salt))

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_nlp_model() -> Language:
        """
        Get spaCy NER model (singleton, thread-safe).
        
        BUG-006 MITIGATION: Set max_length to 2MB.
        """
        try:
            nlp = spacy.load("it_core_news_lg")
            nlp.max_length = 2_000_000  # 2MB max for memory safety
            logger.info("spacy_model_loaded", model="it_core_news_lg")
            return nlp
        except OSError as e:
            logger.error("spacy_model_load_failed", error=str(e))
            raise PIIDetectionError(
                f"Failed to load spaCy model. Install with: python -m spacy download it_core_news_lg"
            ) from e

    def detect_pii_regex(self, text: str) -> List[PIIRedaction]:
        """
        Detect PII usando regex patterns.
        
        Alta precisione per PII strutturati (email, phone, CF, PIVA, IBAN).
        Applica whitelist per prevenire over-redaction.
        
        Args:
            text: Testo da analizzare
            
        Returns:
            Lista di PIIRedaction
        """
        redactions: List[PIIRedaction] = []

        # Check whitelist first (business terms that should NOT be redacted)
        whitelist_spans: Set[Tuple[int, int]] = set()
        for pattern_name, compiled_pattern in COMPILED_WHITELIST_PATTERNS.items():
            for match in compiled_pattern.finditer(text):
                whitelist_spans.add(match.span())

        # Detect PII with each pattern
        for pii_type, compiled_pattern in COMPILED_PII_PATTERNS.items():
            for match in compiled_pattern.finditer(text):
                span_start, span_end = match.span()

                # Skip if overlaps with whitelist
                if any(self._spans_overlap((span_start, span_end), ws) for ws in whitelist_spans):
                    logger.debug("pii_skipped_whitelist", pii_type=pii_type, match=match.group())
                    continue

                original_text = match.group()
                original_hash = self._hash_pii(original_text)
                redacted_text = f"[PII_{pii_type}]"

                redaction = PIIRedaction(
                    type=pii_type,
                    original_hash=original_hash,
                    redacted=redacted_text,
                    span_start=span_start,
                    span_end=span_end,
                    confidence=1.0,  # Regex has high confidence
                    detection_method="regex",
                )
                redactions.append(redaction)

        logger.debug("pii_regex_detected", count=len(redactions))
        return redactions

    def detect_pii_ner(self, text: str, confidence_threshold: Optional[float] = None) -> List[PIIRedaction]:
        """
        Detect PII usando spaCy NER (nomi, organizzazioni).
        
        BUG-006 MITIGATION: Truncate text a 500KB max per evitare memory leak.
        BUG-004: Stabilità NER testata con golden dataset.
        
        Args:
            text: Testo da analizzare
            confidence_threshold: Threshold per confidence (default da config)
            
        Returns:
            Lista di PIIRedaction
        """
        redactions: List[PIIRedaction] = []
        threshold = confidence_threshold or self.config.pii_ner_confidence_threshold

        # BUG-006 MITIGATION: Truncate per memory safety
        max_len = self.config.get_max_body_size_bytes()
        if len(text) > max_len:
            logger.warning("text_truncated_for_ner", original_len=len(text), truncated_len=max_len)
            text = text[:max_len]

        try:
            doc = self.nlp(text)

            for ent in doc.ents:
                # Filter by entity type (PERSON, ORG)
                if ent.label_ not in ("PERSON", "PER", "ORG"):
                    continue

                # Anti false-positive: skip short entities
                if len(ent.text) < 3:
                    continue

                # Anti false-positive: skip titles
                if ent.text.lower() in ("dr", "sig", "sig.ra", "dott", "prof", "ing"):
                    continue

                # Map entity type
                pii_type = "NAME" if ent.label_ in ("PERSON", "PER") else "ORG"

                # spaCy doesn't provide confidence per entity, use threshold check
                # For now, assign default confidence based on entity length
                confidence = min(0.9, 0.7 + len(ent.text) * 0.01)  # Higher for longer names

                if confidence < threshold:
                    continue

                original_hash = self._hash_pii(ent.text)
                redacted_text = f"[PII_{pii_type}]"

                redaction = PIIRedaction(
                    type=pii_type,
                    original_hash=original_hash,
                    redacted=redacted_text,
                    span_start=ent.start_char,
                    span_end=ent.end_char,
                    confidence=confidence,
                    detection_method="ner",
                )
                redactions.append(redaction)

            logger.debug("pii_ner_detected", count=len(redactions))
            return redactions

        except Exception as e:
            logger.error("pii_ner_failed", error=str(e))
            raise PIIDetectionError(f"NER-based PII detection failed: {e}") from e

    def merge_redactions(self, redactions: List[PIIRedaction]) -> List[PIIRedaction]:
        """
        Merge overlapping redactions con priority logic.
        
        Priority:
        1. Regex > NER (regex ha precisione maggiore)
        2. Longest span vince
        
        Args:
            redactions: Lista redactions da mergare
            
        Returns:
            Lista merged redactions (sorted by span_start)
        """
        if not redactions:
            return []

        # Sort by start position
        sorted_redactions = sorted(redactions, key=lambda r: r.span_start)

        merged: List[PIIRedaction] = []
        current = sorted_redactions[0]

        for next_redaction in sorted_redactions[1:]:
            if self._overlaps(current, next_redaction):
                # Overlapping: apply priority logic
                if current.detection_method == "regex" and next_redaction.detection_method == "ner":
                    # Keep regex (higher priority)
                    pass
                elif current.detection_method == "ner" and next_redaction.detection_method == "regex":
                    # Prefer regex
                    current = next_redaction
                else:
                    # Same method: prefer longest span
                    current_len = current.span_end - current.span_start
                    next_len = next_redaction.span_end - next_redaction.span_start
                    if next_len > current_len:
                        current = next_redaction
            else:
                # No overlap: add current to merged, move to next
                merged.append(current)
                current = next_redaction

        # Add last
        merged.append(current)

        logger.debug("redactions_merged", original=len(redactions), merged=len(merged))
        return merged

    def _overlaps(self, r1: PIIRedaction, r2: PIIRedaction) -> bool:
        """Check if two redactions overlap"""
        return not (r1.span_end <= r2.span_start or r2.span_end <= r1.span_start)

    def _spans_overlap(self, span1: Tuple[int, int], span2: Tuple[int, int]) -> bool:
        """Check if two spans overlap"""
        return not (span1[1] <= span2[0] or span2[1] <= span1[0])

    def apply_redactions(self, text: str, redactions: List[PIIRedaction]) -> str:
        """
        Applica redactions al testo (sostituisci PII con placeholder).
        
        CRITICAL: Applica in reverse order per preservare indici.
        
        Args:
            text: Testo originale
            redactions: Lista redactions (devono essere merged e sorted)
            
        Returns:
            Testo con PII redatti
        """
        if not redactions:
            return text

        # Sort by span_start descending (apply in reverse)
        sorted_redactions = sorted(redactions, key=lambda r: r.span_start, reverse=True)

        # Apply each redaction
        for redaction in sorted_redactions:
            text = text[: redaction.span_start] + redaction.redacted + text[redaction.span_end :]

        return text

    def detect_and_redact(self, text: str) -> Tuple[str, List[PIIRedaction]]:
        """
        Pipeline completa: detect + merge + redact.
        
        Args:
            text: Testo da processare
            
        Returns:
            (testo_redatto, lista_redactions) tuple
        """
        # Detect with regex
        regex_redactions = self.detect_pii_regex(text)

        # Detect with NER
        ner_redactions = self.detect_pii_ner(text)

        # Merge overlapping redactions
        all_redactions = regex_redactions + ner_redactions
        merged_redactions = self.merge_redactions(all_redactions)

        # Apply redactions
        redacted_text = self.apply_redactions(text, merged_redactions)

        logger.info("pii_detection_complete", total_redactions=len(merged_redactions))
        return redacted_text, merged_redactions

    def detect_only(self, text: str) -> List[PIIRedaction]:
        """
        Detect PII senza modificare il testo (detect_only mode).
        
        Utile per:
        - Triage email / routing basato su contenuto
        - Arricchimento CRM con entità estratte
        - Analisi AI che necessita del testo integro
        - Audit / reporting su tipologie PII presenti
        
        Args:
            text: Testo da analizzare
            
        Returns:
            Lista PIIRedaction (con span e tipo, testo non modificato)
        """
        # Detect with regex
        regex_redactions = self.detect_pii_regex(text)

        # Detect with NER
        ner_redactions = self.detect_pii_ner(text)

        # Merge overlapping redactions
        all_redactions = regex_redactions + ner_redactions
        merged_redactions = self.merge_redactions(all_redactions)

        logger.info("pii_detect_only_complete", total_detections=len(merged_redactions))
        return merged_redactions

    def _hash_pii(self, pii_text: str) -> str:
        """
        Hash deterministico di PII per audit trail reversibile.
        
        Uses SHA256 + salt, truncated to 16 hex chars.
        
        Args:
            pii_text: PII originale da hashare
            
        Returns:
            Hash string (16 char hex)
        """
        combined = f"{pii_text}{self.salt}"
        full_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        return full_hash[:16]  # Truncate to 16 chars for brevity


# ==============================================================================
# HEADER PII REDACTION
# ==============================================================================


def redact_headers_pii(headers: Dict[str, str], pii_detector: PIIDetector) -> Dict[str, str]:
    """
    Redatta PII dagli header email.
    
    Target headers:
    - from, to, cc, bcc, reply-to, sender (email)
    - subject (PII generici)
    
    Args:
        headers: Header dict (keys lowercase)
        pii_detector: PIIDetector instance
        
    Returns:
        Headers con PII redatti
    """
    redacted_headers = {}

    for key, value in headers.items():
        if key in ("from", "to", "cc", "bcc", "reply-to", "sender"):
            # Redact emails from address headers
            redacted_value, _ = pii_detector.detect_and_redact(value)
            redacted_headers[key] = redacted_value
        elif key == "subject":
            # Redact any PII from subject
            redacted_value, _ = pii_detector.detect_and_redact(value)
            redacted_headers[key] = redacted_value
        else:
            # Other headers pass through unchanged
            redacted_headers[key] = value

    return redacted_headers


# ==============================================================================
# SINGLETON ACCESSOR
# ==============================================================================


@lru_cache(maxsize=1)
def get_pii_detector() -> PIIDetector:
    """
    Get singleton PIIDetector instance (lazy loading).
    
    Returns:
        PIIDetector instance with config-based salt
    """
    config = get_config()
    return PIIDetector(salt=config.pii_salt)
