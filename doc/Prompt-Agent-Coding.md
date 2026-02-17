# PROMPT PER AI CODING AGENT - LAYER PREPROCESSING & CANONICALIZATION
## Thread Classificator Mail - Production Ready Implementation

---

## 🎯 RUOLO E OBIETTIVO

Sei un **Senior Software Engineer** specializzato in:
- Python 3.11+ (typing avanzato, dataclasses, async/await)
- Email processing (RFC5322, MIME, encodings)
- NLP e Privacy Engineering (spaCy, GDPR compliance, PII detection)
- Architetture production-ready (error handling, logging, testing, observability)

**Obiettivo**: Implementare il layer **Preprocessing & Canonicalization** per una pipeline di triage email customer service italiana, seguendo rigorosamente:
1. La specifica completa nel file `Preprocessing-Layer-Spec.md` (fornito come contesto)
2. I requisiti dai brainstorming v2/v3 sulla pipeline deterministica
3. L'input data structure dal layer di ingestion già implementato
4. Best practices production (error handling, logging strutturato, testing, security)

---

## 📋 CONTESTO ARCHITETTURALE

### Pipeline Position

```
Ingestion Layer (✓ fatto) 
  → InputEmail JSON
    → [QUESTO LAYER] Preprocessing & Canonicalization
      → EmailDocument
        → Candidate Generation
          → LLM Classification
            → ...
```

### Invariante Chiave: DETERMINISMO STATISTICO

**A parità di versione**, stesso input → stesso output:
- `parser_version = "email-parser-1.3.0"`
- `canonicalization_version = "1.3.0"`
- `ner_model_version = "it_core_news_lg-3.8.2"`
- `pii_redaction_version = "1.0.0"`

**Perché**: Ripetibilità esperimenti, assenza drift, audit, backtesting.

---

## 📥 INPUT DATA STRUCTURE

```python
from typing import Dict, List
from dataclasses import dataclass

@dataclass
class InputEmail:
    """Dal layer di ingestion IMAP (già implementato)"""
    uid: str                      # IMAP UID
    uidvalidity: str             # IMAP UIDValidity
    mailbox: str                 # Cartella (INBOX, Sent, etc.)
    from_addr: str               # Mittente raw
    to_addrs: List[str]          # Destinatari
    subject: str                 # Oggetto
    date: str                    # Data ISO8601
    body_text: str               # Plain text (⚠️ TRONCATO a 2000 char)
    body_html: str               # HTML (⚠️ TRONCATO a 500 char)
    size: int                    # Size in byte
    headers: Dict[str, str]      # Tutti gli header
    message_id: str              # Message-ID RFC5322
    fetched_at: str              # Timestamp estrazione
```

**⚠️ ATTENZIONE**: `body_text` e `body_html` sono **troncati**. Il layer deve gestire:
- Accettare questi campi come "preview"
- Idealmente: supportare campo opzionale `raw_bytes: Optional[bytes]` per re-parse completo MIME
- Fallback: lavorare con body troncato se `raw_bytes` assente

---

## 📤 OUTPUT DATA STRUCTURE

```python
from typing import List, Dict
from dataclasses import dataclass, field

@dataclass(frozen=True)
class PipelineVersion:
    """Versioning obbligatorio per determinismo"""
    parser_version: str = "email-parser-1.3.0"
    canonicalization_version: str = "1.3.0"
    ner_model_version: str = "it_core_news_lg-3.8.2"
    pii_redaction_version: str = "1.0.0"

@dataclass
class RemovedSection:
    """Audit trail per sezioni rimosse"""
    type: str           # "quote" | "signature" | "disclaimer" | "reply_header"
    span_start: int
    span_end: int
    content_preview: str  # Max 100 char
    confidence: float     # 0.0-1.0

@dataclass
class PIIRedaction:
    """Audit trail per PII redatti"""
    type: str              # "EMAIL" | "PHONE" | "NAME" | "IBAN" | "PIVA" | "CF"
    original_hash: str     # SHA256(original + salt)
    redacted: str          # "[PII_EMAIL]" o hash
    span_start: int
    span_end: int
    confidence: float      # 0.0-1.0
    detection_method: str  # "regex" | "ner" | "hybrid"

@dataclass(frozen=True)
class EmailDocument:
    """Output del layer preprocessing"""
    # Identificatori originali
    uid: str
    uidvalidity: str
    mailbox: str
    message_id: str
    fetched_at: str
    size: int
    
    # Header processati e redatti
    from_addr_redacted: str
    to_addrs_redacted: List[str]
    subject_canonical: str           # Lower, unfold, PII redatto
    date_parsed: str                 # ISO8601
    headers_canonical: Dict[str, str]  # Keys lower, values unfold + PII redatti
    
    # Body processato
    body_text_canonical: str         # Plain + HTML→text merged, pulito, PII redatto
    body_html_canonical: str         # HTML sanitizzato, PII redatto
    body_original_hash: str          # SHA256(body) per audit (non il body stesso!)
    
    # Metadati processing
    removed_sections: List[RemovedSection] = field(default_factory=list)
    pii_entities: List[PIIRedaction] = field(default_factory=list)
    
    # Versioning (obbligatorio)
    pipeline_version: PipelineVersion = field(default_factory=PipelineVersion)
    processing_timestamp: str = ""
    processing_duration_ms: int = 0
```

---

## 🔧 REQUISITI IMPLEMENTAZIONE

### 1. RFC5322/MIME PARSING

**File**: `src/parsing.py`

#### 1.1 Header Processing

```python
from email import policy
from email.parser import BytesParser
from email.header import decode_header, make_header

def parse_headers_rfc5322(headers_dict: Dict[str, str]) -> Dict[str, str]:
    """
    Parse e normalizza headers:
    - Unfold (rimuovi line breaks interni)
    - Decode charset (UTF-8, ISO-8859-1, etc.)
    - Lowercase keys
    
    Args:
        headers_dict: Dict raw da InputEmail
        
    Returns:
        Dict normalizzato {key_lower: decoded_value}
    """
    # IMPLEMENTA QUI
    pass
```

**Requirements**:
- Usa `email.header.unfold()` per unfolding RFC5322
- Gestisci encoded headers `=?UTF-8?B?...?=` con `make_header(decode_header(...))`
- Header duplicati (es. `Received`): concatena con `;` o lista
- Error handling: fallback graceful su decode failure

#### 1.2 MIME Body Extraction

```python
def extract_body_parts_from_truncated(
    body_text_preview: str,
    body_html_preview: str,
    raw_bytes: Optional[bytes] = None
) -> Tuple[str, str]:
    """
    Estrai text/plain e text/html.
    
    Strategy:
    - Se raw_bytes disponibile: full MIME parse
    - Altrimenti: usa preview troncati (fallback)
    
    Returns:
        (text_plain, text_html)
    """
    # IMPLEMENTA QUI
    pass
```

**Requirements**:
- Se `raw_bytes` presente: parse completo MIME con `BytesParser`
- Walk multipart, skip attachment (`Content-Disposition: attachment`)
- Merge multiple parti stesso tipo
- Fallback a preview troncati se `raw_bytes` assente

#### 1.3 HTML→Text Conversion

```python
from bs4 import BeautifulSoup
import html2text

def html_to_text_robust(html: str) -> str:
    """
    Conversione HTML→text deterministica.
    
    Pipeline:
    1. BeautifulSoup parse (lxml)
    2. Remove script/style/meta
    3. html2text conversion
    4. Cleanup whitespace
    """
    # IMPLEMENTA QUI
    pass
```

**Dependencies**: `beautifulsoup4==4.12.3`, `lxml==5.1.0`, `html2text==2020.1.16`

---

### 2. CANONICALIZZAZIONE DETERMINISTICA

**File**: `src/canonicalization.py`

#### 2.1 Quote/Signature Removal

```python
QUOTE_PATTERNS = [
    # Quote standard
    (r'(?m)^[\s]*>+.*$', 'quote_standard'),
    
    # Reply headers italiani
    (r'(?is)Il giorno.*ha scritto:', 'reply_header_it'),
    (r'(?is)On.*wrote:', 'reply_header_en'),
    (r'(?is)Da:.*Inviato:.*A:.*Oggetto:', 'reply_header_outlook'),
    
    # Signature separators
    (r'(?m)^[\s]*--[\s]*$', 'signature_separator'),
    (r'(?m)^[\s]*_{5,}[\s]*$', 'signature_underline'),
    
    # Disclaimer
    (r'(?is)Questo messaggio.*confidenziale.*', 'disclaimer_confidential'),
    (r'(?is)Informativa privacy.*GDPR.*', 'disclaimer_privacy'),
    
    # Chiusure formali
    (r'(?is)Cordiali saluti[,\s]*', 'closing_formal'),
    (r'(?is)Distinti saluti[,\s]*', 'closing_formal'),
]

CANONICALIZATION_VERSION = "1.3.0"

def canonicalize_text(
    text: str,
    keep_audit: bool = True
) -> Tuple[str, List[RemovedSection]]:
    """
    Canonicalizza testo rimuovendo quote/firme/disclaimer.
    
    DETERMINISMO:
    - Stessi pattern, stesso ordine
    - Regex compile once, reuse
    - Whitespace cleanup deterministico
    
    Returns:
        (testo_canonico, sezioni_rimosse)
    """
    # IMPLEMENTA QUI
    pass
```

**Requirements**:
- Applica pattern **in ordine** (determinismo)
- Traccia RemovedSection per audit
- `content_preview` max 100 char
- Cleanup whitespace: `re.sub(r'\s+', ' ')` e `re.sub(r'\n{3,}', '\n\n')`
- **Test unit obbligatorio**: `test_canonicalization_idempotent()`

#### 2.2 Subject Canonicalization

```python
def canonicalize_subject(subject: str) -> str:
    """
    Canonicalizza subject:
    - Remove RE:/FW:/FWD: prefixes
    - Lowercase
    - Strip whitespace
    """
    # IMPLEMENTA QUI
    pass
```

---

### 3. PII REDACTION (GDPR COMPLIANCE)

**File**: `src/pii_detection.py`

#### 3.1 Regex Patterns

```python
import hashlib
import re

PII_REGEX_PATTERNS = {
    "EMAIL": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    
    "PHONE_IT": r'''(?x)  # Verbose mode
        (?:
            (?:\+39\s?)?                    # Prefisso Italia
            (?:
                3\d{2}[\s\-]?\d{6,7}        # Mobile
                |
                0\d{1,3}[\s\-]?\d{6,8}      # Fisso
            )
        )
    ''',
    
    "PIVA": r'\b(?:IT\s?)?[0-9]{11}\b',
    "CF": r'\b[A-Z]{6}[0-9]{2}[A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z]\b',
    "IBAN": r'\bIT\d{2}[A-Z]\d{10}[0-9A-Z]{12}\b',
}

PII_SALT = "thread-classificator-2026-pii-salt"  # ⚠️ Deve essere da env in prod!

# Whitelist (no redaction)
BUSINESS_WHITELIST = [
    r'\b(?:fattura|contratto|ordine|pratica)\s*(?:n\.?|num\.?)?\s*\d+\b',
]
```

#### 3.2 PIIDetector Class

```python
import spacy
from typing import List, Tuple

NER_MODEL_VERSION = "it_core_news_lg-3.8.2"

class PIIDetector:
    """
    Rilevatore PII con Regex + NER.
    
    Strategy:
    1. Regex per PII strutturati (alta precisione)
    2. NER per nomi propri (alta recall)
    3. Merge deterministico (regex > ner)
    """
    
    def __init__(self, pii_salt: str):
        self.pii_salt = pii_salt
        
        # Load NER model
        self.nlp = spacy.load("it_core_news_lg")
        self.nlp.max_length = 2_000_000
        
        # Compile regex
        self.regex_compiled = {
            pii_type: re.compile(pattern, re.IGNORECASE | re.VERBOSE)
            for pii_type, pattern in PII_REGEX_PATTERNS.items()
        }
        
        self.whitelist_regex = re.compile(
            '|'.join(BUSINESS_WHITELIST),
            re.IGNORECASE
        )
    
    def detect_pii_regex(self, text: str) -> List[PIIRedaction]:
        """Detect PII con regex deterministici"""
        # IMPLEMENTA QUI
        pass
    
    def detect_pii_ner(
        self, 
        text: str,
        confidence_threshold: float = 0.75
    ) -> List[PIIRedaction]:
        """Detect nomi/org con spaCy NER"""
        # IMPLEMENTA QUI
        pass
    
    def merge_redactions(
        self,
        redactions: List[PIIRedaction]
    ) -> List[PIIRedaction]:
        """
        Merge overlap con priorità:
        1. detection_method: regex > ner
        2. longest span wins
        3. higher confidence wins
        """
        # IMPLEMENTA QUI
        pass
    
    def apply_redactions(
        self,
        text: str,
        redactions: List[PIIRedaction]
    ) -> str:
        """Applica redactions al testo (reverse order preserva indici)"""
        # IMPLEMENTA QUI
        pass
    
    def detect_and_redact(self, text: str) -> Tuple[str, List[PIIRedaction]]:
        """Pipeline completa: detect → merge → redact"""
        regex_redactions = self.detect_pii_regex(text)
        ner_redactions = self.detect_pii_ner(text)
        
        all_redactions = regex_redactions + ner_redactions
        merged = self.merge_redactions(all_redactions)
        
        redacted_text = self.apply_redactions(text, merged)
        
        return redacted_text, merged
```

**Requirements**:
- **Determinismo**: regex always same results, NER model pinned version
- **Hash con salt**: `hashlib.sha256((original + salt).encode()).hexdigest()[:16]`
- **Whitelist check**: skip redaction se match business terms
- **Confidence tracking**: regex=0.95, ner=0.80
- **Anti-false-positive**: skip nomi <3 char, skip "sig", "dott", etc.

#### 3.3 Header PII Redaction

```python
def redact_headers_pii(
    headers: Dict[str, str],
    pii_detector: PIIDetector
) -> Dict[str, str]:
    """
    Redatta PII da headers critici:
    - From, To, Cc, Bcc, Reply-To, Sender
    - Subject
    """
    # IMPLEMENTA QUI
    pass
```

---

### 4. MAIN PREPROCESSING FUNCTION

**File**: `src/preprocessing.py`

```python
from datetime import datetime
import time
from typing import Optional

def preprocess_email(
    input_email: InputEmail,
    config: Optional['PreprocessingConfig'] = None,
    raw_bytes: Optional[bytes] = None
) -> EmailDocument:
    """
    Main preprocessing function.
    
    Pipeline:
    1. Parse headers RFC5322 (unfold, decode)
    2. Extract body (MIME if raw_bytes, else fallback)
    3. HTML→text conversion
    4. Canonicalize body (remove quotes/sig)
    5. Canonicalize subject
    6. PII detection & redaction (body + headers)
    7. Build EmailDocument output
    
    Args:
        input_email: Input dal layer ingestion
        config: Config (usa default se None)
        raw_bytes: Optional raw email bytes per full MIME parse
    
    Returns:
        EmailDocument processato
    
    Raises:
        PreprocessingError: Se processing fallisce
    """
    if config is None:
        config = PreprocessingConfig()
    
    start_time = time.perf_counter()
    
    try:
        # 1. Parse headers
        headers_canonical = parse_headers_rfc5322(input_email.headers)
        
        # 2. Extract body
        text_plain, text_html = extract_body_parts_from_truncated(
            input_email.body_text,
            input_email.body_html,
            raw_bytes
        )
        
        # 3. HTML→text
        text_from_html = html_to_text_robust(text_html) if text_html else ""
        
        # 4. Merge bodies
        body_merged = merge_body_parts(text_plain, text_from_html)
        
        # 5. Canonicalize body
        body_canonical, removed_sections = canonicalize_text(
            body_merged,
            keep_audit=True
        )
        
        # 6. Canonicalize subject
        subject_canonical = canonicalize_subject(input_email.subject)
        
        # 7. PII detection & redaction
        pii_detector = PIIDetector(config.pii_salt)
        
        # Body
        body_redacted, body_pii = pii_detector.detect_and_redact(body_canonical)
        
        # Headers
        headers_redacted = redact_headers_pii(headers_canonical, pii_detector)
        
        # Subject
        subject_redacted, subject_pii = pii_detector.detect_and_redact(subject_canonical)
        
        # Merge PII entities
        all_pii = body_pii + subject_pii
        
        # 8. Compute hash body original (NEVER store plaintext!)
        body_original_hash = hashlib.sha256(
            body_merged.encode('utf-8')
        ).hexdigest()
        
        # 9. Build output
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        
        output = EmailDocument(
            uid=input_email.uid,
            uidvalidity=input_email.uidvalidity,
            mailbox=input_email.mailbox,
            message_id=input_email.message_id,
            fetched_at=input_email.fetched_at,
            size=input_email.size,
            
            from_addr_redacted=headers_redacted.get('from', '[ERROR]'),
            to_addrs_redacted=[headers_redacted.get('to', '[ERROR]')],
            subject_canonical=subject_redacted,
            date_parsed=input_email.date,
            headers_canonical=headers_redacted,
            
            body_text_canonical=body_redacted,
            body_html_canonical="",  # HTML redatto (opzionale)
            body_original_hash=body_original_hash,
            
            removed_sections=removed_sections,
            pii_entities=all_pii,
            
            pipeline_version=PipelineVersion(
                parser_version=config.parser_version,
                canonicalization_version=config.canonicalization_version,
                ner_model_version=config.ner_model_version,
                pii_redaction_version=config.pii_redaction_version
            ),
            
            processing_timestamp=datetime.utcnow().isoformat() + 'Z',
            processing_duration_ms=duration_ms
        )
        
        return output
        
    except Exception as e:
        # Log error
        logger.error(
            "preprocessing_failed",
            uid=input_email.uid,
            error=str(e),
            exc_info=True
        )
        raise PreprocessingError(f"Failed to preprocess email {input_email.uid}") from e


class PreprocessingError(Exception):
    """Custom exception per preprocessing errors"""
    pass
```

---

### 5. CONFIGURATION

**File**: `src/config.py`

```python
from pydantic import BaseSettings, Field
import os

class PreprocessingConfig(BaseSettings):
    """Configuration con validazione Pydantic"""
    
    # Versioning
    parser_version: str = "email-parser-1.3.0"
    canonicalization_version: str = "1.3.0"
    ner_model_version: str = "it_core_news_lg-3.8.2"
    pii_redaction_version: str = "1.0.0"
    
    # PII Redaction
    pii_salt: str = Field(
        ...,
        env="PREPROCESSING_PII_SALT",
        description="Salt for PII hashing (MUST be set via env)"
    )
    pii_ner_confidence_threshold: float = 0.75
    
    # Canonicalization
    remove_quotes: bool = True
    remove_signatures: bool = True
    max_body_size_kb: int = 500
    
    # Logging
    log_level: str = "INFO"
    log_pii_preview: bool = False  # Security: NEVER in production
    
    class Config:
        env_prefix = "PREPROCESSING_"
        case_sensitive = False


# Singleton
_config = None

def get_config() -> PreprocessingConfig:
    """Get or create config singleton"""
    global _config
    if _config is None:
        _config = PreprocessingConfig()
    return _config
```

---

### 6. LOGGING

**File**: `src/logging_setup.py`

```python
import structlog
import logging
import sys

def setup_logging(log_level: str = "INFO"):
    """Setup structured logging con structlog"""
    
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper())
    )
    
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

logger = structlog.get_logger()
```

**Usage**:
```python
logger.info(
    "preprocessing_completed",
    uid=email.uid,
    duration_ms=342,
    pii_redactions=5,
    removed_sections=2
)
```

---

### 7. ERROR HANDLING & RESILIENCE

**File**: `src/error_handling.py`

```python
from typing import Optional

def preprocess_email_safe(
    input_email: InputEmail,
    config: Optional[PreprocessingConfig] = None
) -> EmailDocument:
    """
    Preprocessing con graceful degradation:
    - Se NER fallisce → solo regex PII
    - Se canonicalization fallisce → body raw
    - Se tutto fallisce → documento minimale
    """
    try:
        return preprocess_email(input_email, config)
        
    except PIIDetectionError as e:
        logger.warning(
            "pii_detection_failed_fallback_regex_only",
            uid=input_email.uid,
            error=str(e)
        )
        return preprocess_email_regex_only(input_email, config)
        
    except CanonicalizationError as e:
        logger.warning(
            "canonicalization_failed_using_raw_body",
            uid=input_email.uid,
            error=str(e)
        )
        return preprocess_email_no_canon(input_email, config)
        
    except Exception as e:
        logger.error(
            "preprocessing_total_failure_minimal_doc",
            uid=input_email.uid,
            error=str(e),
            exc_info=True
        )
        return create_minimal_document(input_email)


def create_minimal_document(input_email: InputEmail) -> EmailDocument:
    """Documento minimale per total failure fallback"""
    return EmailDocument(
        uid=input_email.uid,
        uidvalidity=input_email.uidvalidity,
        mailbox=input_email.mailbox,
        from_addr_redacted="[ERROR]",
        to_addrs_redacted=["[ERROR]"],
        subject_canonical=input_email.subject[:100],
        date_parsed=input_email.date,
        body_text_canonical=input_email.body_text[:500],
        body_html_canonical="",
        body_original_hash="error",
        headers_canonical={},
        removed_sections=[],
        pii_entities=[],
        pipeline_version=PipelineVersion(),
        processing_timestamp=datetime.utcnow().isoformat() + 'Z',
        processing_duration_ms=0,
        message_id=input_email.message_id,
        fetched_at=input_email.fetched_at,
        size=input_email.size
    )


class PIIDetectionError(PreprocessingError):
    """PII detection failed"""
    pass

class CanonicalizationError(PreprocessingError):
    """Canonicalization failed"""
    pass
```

---

### 8. TESTING

**File**: `tests/test_canonicalization.py`

```python
import pytest
from src.canonicalization import canonicalize_text

def test_canonicalization_determinism():
    """Stesso input → stesso output"""
    sample = "Hello\\n\\n> quoted line\\n--\\nSignature"
    
    clean1, removed1 = canonicalize_text(sample)
    clean2, removed2 = canonicalize_text(sample)
    
    assert clean1 == clean2
    assert len(removed1) == len(removed2)
    assert removed1[0].type == removed2[0].type


def test_canonicalization_idempotent():
    """Applicare due volte = applicare una volta"""
    sample = "Hello\\n\\n> quoted\\n> more quoted\\n\\nBody text"
    
    clean1, _ = canonicalize_text(sample)
    clean2, _ = canonicalize_text(clean1)
    
    assert clean1 == clean2


def test_quote_removal():
    """Quote pattern rimosse"""
    sample = "Real content\\n> Quoted line\\n> Another quote\\nMore content"
    clean, removed = canonicalize_text(sample)
    
    assert "> Quoted" not in clean
    assert "Real content" in clean
    assert "More content" in clean
    assert len(removed) >= 1
    assert removed[0].type == "quote_standard"
```

**File**: `tests/test_pii_detection.py`

```python
import pytest
from src.pii_detection import PIIDetector

@pytest.fixture
def pii_detector():
    return PIIDetector(pii_salt="test-salt-123")


def test_email_redaction(pii_detector):
    """Email addresses redatti"""
    text = "Contattami a mario.rossi@example.com per info"
    
    redacted, pii_list = pii_detector.detect_and_redact(text)
    
    assert "[PII_EMAIL]" in redacted
    assert "mario.rossi@example.com" not in redacted
    assert len(pii_list) == 1
    assert pii_list[0].type == "EMAIL"
    assert pii_list[0].detection_method == "regex"


def test_phone_redaction(pii_detector):
    """Numeri telefono italiani redatti"""
    text = "Chiamami al +39 333 1234567 o 02 12345678"
    
    redacted, pii_list = pii_detector.detect_and_redact(text)
    
    assert "[PII_PHONE_IT]" in redacted
    assert "333 1234567" not in redacted
    assert len(pii_list) >= 2  # Due numeri


def test_codice_fiscale_redaction(pii_detector):
    """Codice Fiscale redatto"""
    text = "Il mio CF è RSSMRA80A01H501X"
    
    redacted, pii_list = pii_detector.detect_and_redact(text)
    
    assert "[PII_CF]" in redacted
    assert "RSSMRA80A01H501X" not in redacted


def test_whitelist_no_redaction(pii_detector):
    """Business terms non redatti"""
    text = "Riferimento fattura n. 12345"
    
    redacted, pii_list = pii_detector.detect_and_redact(text)
    
    # "12345" non deve essere redatto (è parte di "fattura n. 12345")
    assert "12345" in redacted
```

**File**: `tests/test_preprocessing.py`

```python
import pytest
from src.preprocessing import preprocess_email
from src.models import InputEmail

def test_full_preprocessing_pipeline():
    """Test end-to-end preprocessing"""
    input_email = InputEmail(
        uid="12345",
        uidvalidity="67890",
        mailbox="INBOX",
        from_addr="mario.rossi@example.com",
        to_addrs=["support@company.it"],
        subject="RE: Fattura n. 2024/001",
        date="2026-02-17T10:30:00Z",
        body_text="Buongiorno,\\n\\nfaccio seguito...\\n\\n> Quoted reply",
        body_html="<p>Buongiorno</p>",
        size=1024,
        headers={"message-id": "<abc@example.com>"},
        message_id="<abc@example.com>",
        fetched_at="2026-02-17T10:31:00Z"
    )
    
    output = preprocess_email(input_email)
    
    # Assertions
    assert output.uid == input_email.uid
    assert "[PII_EMAIL]" in output.from_addr_redacted
    assert len(output.pii_entities) > 0
    assert output.pipeline_version.parser_version == "email-parser-1.3.0"
    assert "> Quoted" not in output.body_text_canonical
    assert output.processing_duration_ms > 0
```

**File**: `tests/test_performance.py`

```python
import pytest
import time
import numpy as np
from src.preprocessing import preprocess_email

def test_latency_p50_under_500ms(sample_emails_fixture):
    """p50 latency < 500ms"""
    latencies = []
    
    for email in sample_emails_fixture[:100]:
        start = time.perf_counter()
        preprocess_email(email)
        latencies.append((time.perf_counter() - start) * 1000)
    
    p50 = np.percentile(latencies, 50)
    
    assert p50 < 500, f"p50={p50:.1f}ms exceeds 500ms target"


def test_latency_p99_under_2s(sample_emails_fixture):
    """p99 latency < 2s"""
    latencies = []
    
    for email in sample_emails_fixture[:100]:
        start = time.perf_counter()
        preprocess_email(email)
        latencies.append((time.perf_counter() - start) * 1000)
    
    p99 = np.percentile(latencies, 99)
    
    assert p99 < 2000, f"p99={p99:.1f}ms exceeds 2s target"
```

---

### 9. REQUIREMENTS.TXT

```txt
# Core
python>=3.11

# Email parsing
beautifulsoup4==4.12.3
lxml==5.1.0
html2text==2020.1.16

# NLP
spacy==3.7.4
# Install it_core_news_lg:
# python -m spacy download it_core_news_lg

# Config & Validation
pydantic==2.6.1

# Logging
structlog==24.1.0

# Testing
pytest==8.0.0
pytest-cov==4.1.0
hypothesis==6.98.0

# Development
black==24.1.1
mypy==1.8.0
flake8==7.0.0
```

**Post-install**:
```bash
python -m spacy download it_core_news_lg
```

---

### 10. PROJECT STRUCTURE

```
preprocessing_layer/
├── src/
│   ├── __init__.py
│   ├── models.py              # InputEmail, EmailDocument, dataclasses
│   ├── config.py              # PreprocessingConfig
│   ├── parsing.py             # RFC5322/MIME parsing
│   ├── canonicalization.py    # Text canonicalization
│   ├── pii_detection.py       # PIIDetector class
│   ├── preprocessing.py       # Main preprocess_email()
│   ├── error_handling.py      # Graceful degradation
│   └── logging_setup.py       # Structured logging
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # Fixtures
│   ├── test_parsing.py
│   ├── test_canonicalization.py
│   ├── test_pii_detection.py
│   ├── test_preprocessing.py
│   └── test_performance.py
│
├── examples/
│   ├── sample_emails/         # .eml sample files
│   └── notebooks/
│       └── preprocessing_demo.ipynb
│
├── docs/
│   └── Preprocessing-Layer-Spec.md  # Specifica completa
│
├── requirements.txt
├── requirements-dev.txt
├── setup.py
├── README.md
├── .env.example
└── Makefile
```

---

## 🎯 DELIVERABLES

Devi fornire:

1. **Codice sorgente completo** (`src/`)
   - Tutte le funzioni implementate
   - Type hints completi
   - Docstring Google style
   - Error handling robusto

2. **Test suite** (`tests/`)
   - Copertura >90%
   - Unit test per ogni modulo
   - Integration test end-to-end
   - Performance benchmark

3. **Sample data** (`examples/`)
   - 3-5 email .eml di esempio (con PII fittizi)
   - Jupyter notebook demo

4. **Documentation**
   - README.md con:
     - Setup instructions
     - Usage examples
     - API reference
     - Troubleshooting
   - `.env.example` con variabili necessarie

5. **Configuration**
   - `requirements.txt` completo
   - `setup.py` per installazione
   - `Makefile` con comandi comuni (test, lint, install)

---

## ✅ ACCEPTANCE CRITERIA

Il codice sarà accettato solo se:

- [x] **Determinismo**: Test `test_canonicalization_determinism()` passa
- [x] **PII Redaction**: Test `test_email_redaction()` passa, nessun PII in output
- [x] **Coverage**: >90% code coverage (pytest-cov)
- [x] **Performance**: p50 <500ms, p99 <2s su sample 100 email
- [x] **Type checking**: `mypy src/ --strict` passa senza errori
- [x] **Linting**: `flake8 src/` passa
- [x] **Formatting**: `black src/ tests/` applicato
- [x] **Security**: `PII_SALT` da env, mai hardcoded
- [x] **Error handling**: Nessun crash su email malformata (graceful degradation)
- [x] **Logging**: Structured logging JSON per ogni processing
- [x] **Documentation**: README completo, funzioni documentate

---

## 🚨 CRITICAL DON'Ts

❌ **MAI**:
- Hardcode `PII_SALT` nel codice
- Loggare PII in plaintext
- Memorizzare `body_original` nel database (solo hash!)
- Usare `pickle` per serializzazione (security risk)
- Ignorare eccezioni senza logging
- Inventare versioni (usa quelle specificate)
- Skip testing (coverage obbligatoria >90%)

✅ **SEMPRE**:
- Usa type hints
- Valida input con Pydantic
- Log structured (JSON)
- Test deterministico (stessi seed, stessi risultati)
- Error handling graceful
- Documentazione completa

---

## 📚 RIFERIMENTI

### Specifiche
- `Preprocessing-Layer-Spec.md` (contesto completo)
- Brainstorming v2/v3 (pipeline architecture)

### RFCs
- RFC 5322: Internet Message Format
- RFC 2045-2049: MIME

### Libraries Doc
- Python `email` module: https://docs.python.org/3/library/email.html
- BeautifulSoup: https://www.crummy.com/software/BeautifulSoup/bs4/doc/
- spaCy: https://spacy.io/usage
- Pydantic: https://docs.pydantic.dev/

### Security
- OWASP Email Security
- GDPR Article 25 (Privacy by Design)

---

## 🏁 STARTING POINT

1. **Setup environment**:
```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m spacy download it_core_news_lg
export PREPROCESSING_PII_SALT="my-secret-salt-change-in-production"
```

2. **Implement in order**:
   - `models.py` (dataclasses)
   - `config.py` (configuration)
   - `logging_setup.py` (logging)
   - `parsing.py` (RFC5322/MIME)
   - `canonicalization.py` (text cleaning)
   - `pii_detection.py` (PII redaction)
   - `preprocessing.py` (main function)
   - `error_handling.py` (resilience)

3. **Test continuously**:
```bash
pytest tests/ -v --cov=src --cov-report=html
```

4. **Lint & format**:
```bash
black src/ tests/
flake8 src/
mypy src/ --strict
```

---

## 🎓 SUCCESS = PRODUCTION-READY CODE

Ricorda: questo layer andrà in **produzione** per processare migliaia di email/giorno. Ogni bug può:
- Violare GDPR (PII leak)
- Compromettere classificazione downstream
- Causare data loss (email non processate)

**Priorità**:
1. **Security** (PII protection)
2. **Reliability** (error handling)
3. **Determinism** (testing riproducibile)
4. **Performance** (latency targets)
5. **Observability** (logging strutturato)

Scrivi codice di cui andresti fiero in code review. Buon lavoro! 🚀
