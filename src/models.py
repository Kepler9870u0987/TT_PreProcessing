"""
Data models for Email Preprocessing Layer

Definisce tutte le strutture dati utilizzate per input, output, 
e tracking del processing pipeline.

CRITICAL: I modelli sono immutabili (frozen=True) dove applicabile per 
garantire thread-safety e determinismo.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime


# ==============================================================================
# CUSTOM EXCEPTIONS
# ==============================================================================


class PreprocessingError(Exception):
    """Base exception per errori di preprocessing"""

    pass


class PIIDetectionError(PreprocessingError):
    """Errore durante la detection/redaction PII"""

    pass


class CanonicalizationError(PreprocessingError):
    """Errore durante la canonicalizzazione del testo"""

    pass


class ParsingError(PreprocessingError):
    """Errore durante il parsing RFC5322/MIME"""

    pass


# ==============================================================================
# PIPELINE VERSIONING
# ==============================================================================


@dataclass(frozen=True)
class PipelineVersion:
    """
    Versioning deterministico del pipeline processing.
    
    INVARIANTE: A parità di versione, stesso input → stesso output
    Tracking per audit trail, backtesting, ripetibilità esperimenti.
    """

    parser_version: str = "email-parser-1.3.0"
    canonicalization_version: str = "1.3.0"
    ner_model_version: str = "it_core_news_lg-3.8.2"
    pii_redaction_version: str = "1.0.0"

    def __str__(self) -> str:
        return (
            f"{self.parser_version}|{self.canonicalization_version}|"
            f"{self.ner_model_version}|{self.pii_redaction_version}"
        )


# ==============================================================================
# AUDIT TRAIL STRUCTURES
# ==============================================================================


@dataclass
class RemovedSection:
    """
    Traccia sezioni rimosse durante canonicalizzazione.
    
    Used for audit trail, debugging, e potenziale rollback.
    """

    type: str  # "quote" | "signature" | "disclaimer" | "reply_header" | "closing_formal" | "forward_marker"
    span_start: int  # Indice inizio (0-based)
    span_end: int  # Indice fine (0-based, exclusive)
    content_preview: str  # Primi 100 caratteri per audit (no PII)
    confidence: float  # 0.0-1.0, confidence del pattern matching

    def __post_init__(self) -> None:
        """Validazione campi"""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0.0, 1.0], got {self.confidence}")
        if self.span_start < 0 or self.span_end < self.span_start:
            raise ValueError(f"Invalid span: start={self.span_start}, end={self.span_end}")
        # Truncate content_preview to 100 chars
        if len(self.content_preview) > 100:
            object.__setattr__(self, "content_preview", self.content_preview[:100])


@dataclass
class PIIRedaction:
    """
    Traccia PII redatti per GDPR compliance e audit trail.
    
    CRITICAL: original_hash permette reversibilità controllata per audit autorizzato.
    """

    type: str  # "EMAIL" | "PHONE_IT" | "NAME" | "ORG" | "IBAN" | "PIVA" | "CF"
    original_hash: str  # SHA256(original + salt), truncated to 16 hex chars
    redacted: str  # "[PII_EMAIL]" | "[PII_NAME]" | etc.
    span_start: int  # Indice inizio nel testo originale (0-based)
    span_end: int  # Indice fine (0-based, exclusive)
    confidence: float  # 0.0-1.0, detection confidence
    detection_method: str  # "regex" | "ner" | "hybrid"

    def __post_init__(self) -> None:
        """Validazione campi"""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0.0, 1.0], got {self.confidence}")
        if self.span_start < 0 or self.span_end < self.span_start:
            raise ValueError(f"Invalid span: start={self.span_start}, end={self.span_end}")
        if self.detection_method not in ("regex", "ner", "hybrid"):
            raise ValueError(f"Invalid detection_method: {self.detection_method}")


# ==============================================================================
# INPUT/OUTPUT DOCUMENTS
# ==============================================================================


@dataclass
class InputEmail:
    """
    Struttura dati in ingresso dal layer di ingestion IMAP.
    
    NOTE CRITICAL:
    - body_text e body_html sono TRONCATI dal layer ingestion (2000/500 char)
    - raw_bytes opzionale permette full MIME parsing (mitigazione BUG-001)
    - body_truncated flag indica se body è completo o troncato
    """

    uid: str  # IMAP UID univoco
    uidvalidity: str  # IMAP UIDValidity per sync
    mailbox: str  # Cartella IMAP (INBOX, Sent, etc.)
    from_addr: str  # Mittente raw
    to_addrs: List[str]  # Lista destinatari
    subject: str  # Oggetto email
    date: str  # Data ricezione/invio (string)
    body_text: str  # Corpo plain text (potenzialmente troncato a 2000 char)
    body_html: str  # Anteprima HTML (potenzialmente troncata a 500 char)
    size: int  # Dimensione messaggio in byte
    headers: Dict[str, str]  # Tutti gli header come dizionario
    message_id: str  # Message-ID RFC5322
    fetched_at: str  # Timestamp estrazione ISO8601

    # BUG-001 MITIGATION: Support optional raw bytes for full MIME parsing
    raw_bytes: Optional[bytes] = None
    body_truncated: bool = False  # Flag indica se body è troncato


@dataclass(frozen=True)
class EmailDocument:
    """
    Documento email processato e canonicalizzato - OUTPUT del layer.
    
    INVARIANTE: Immutabile (frozen=True) per thread-safety e cache safety.
    GARANZIA: Deterministico - stesso input + stessa versione → stesso output.
    """

    # Identificatori originali (immutabili)
    uid: str
    uidvalidity: str
    mailbox: str
    message_id: str
    fetched_at: str
    size: int

    # Header processati e redatti
    from_addr_redacted: str  # Hash o [PII_EMAIL]
    to_addrs_redacted: List[str]  # Lista redatta
    subject_canonical: str  # Lower, unfold, PII redatto
    date_parsed: str  # ISO8601 format
    headers_canonical: Dict[str, str]  # Keys lower, values unfold + redatti

    # Body processato
    body_text_canonical: str  # Plain + HTML→text merged, pulito, PII redatto
    body_html_canonical: str  # HTML sanitizzato, PII redatto
    body_original_hash: str  # SHA256(body originale) per audit

    # Metadati processing
    removed_sections: List[RemovedSection]  # Quote/sig/disclaimer rimossi
    pii_entities: List[PIIRedaction]  # Traccia PII redatti

    # Versioning e timing (obbligatorio per audit)
    pipeline_version: PipelineVersion
    processing_timestamp: str  # ISO8601
    processing_duration_ms: int  # Latenza processing

    def __post_init__(self) -> None:
        """
        Validazione invarianti dopo inizializzazione.
        
        NOTE: Con frozen=True, usiamo object.__setattr__ per conversioni.
        """
        # Ensure lists are not None (use empty lists as default)
        if self.removed_sections is None:
            object.__setattr__(self, "removed_sections", [])
        if self.pii_entities is None:
            object.__setattr__(self, "pii_entities", [])

    @staticmethod
    def create_default_factory() -> "EmailDocument":
        """Factory per creare documento vuoto (used in error handling)"""
        return EmailDocument(
            uid="",
            uidvalidity="",
            mailbox="",
            message_id="",
            fetched_at="",
            size=0,
            from_addr_redacted="",
            to_addrs_redacted=[],
            subject_canonical="",
            date_parsed="",
            headers_canonical={},
            body_text_canonical="",
            body_html_canonical="",
            body_original_hash="",
            removed_sections=[],
            pii_entities=[],
            pipeline_version=PipelineVersion(),
            processing_timestamp=datetime.utcnow().isoformat() + "Z",
            processing_duration_ms=0,
        )
