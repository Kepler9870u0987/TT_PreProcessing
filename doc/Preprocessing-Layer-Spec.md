# Layer Preprocessing & Canonicalization - Specifica Completa
## Thread Classificator Mail - Production Ready Documentation

**Versione**: 2.0  
**Data**: Febbraio 2026  
**Autore**: System Architecture Team

---

## 1. CONTESTO ARCHITETTURALE

### 1.1 Posizione nella Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                    PIPELINE COMPLETA                            │
├─────────────────────────────────────────────────────────────────┤
│ 1. Ingestion Layer (✓ IMPLEMENTATO)                            │
│    └─> Output: InputEmail JSON                                 │
│                                                                 │
│ 2. Preprocessing & Canonicalization (👉 DA IMPLEMENTARE)       │
│    ├─> RFC5322/MIME parsing completo                          │
│    ├─> Canonicalizzazione deterministica                       │
│    ├─> PII Redaction (GDPR compliance)                        │
│    └─> Output: EmailDocument                                   │
│                                                                 │
│ 3. Candidate Generation (deterministico)                       │
│ 4. LLM Classification Layer (tool calling)                     │
│ 5. Post-processing & Enrichment                                │
│ 6. Entity Extraction (RegEx + NER)                            │
│ 7. Observation Storage & Dictionary Update                     │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Invariante Chiave: Determinismo Statistico

**Garanzia**: A parità di versione dei componenti, stesso input → stesso output

```python
@dataclass(frozen=True)
class PipelineVersion:
    parser_version: str = "email-parser-1.3.0"
    canonicalization_version: str = "1.3.0"
    ner_model_version: str = "it_core_news_lg-3.8.2"
    pii_redaction_version: str = "1.0.0"
```

**Motivazione**: Ripetibilità esperimenti, assenza drift silenzioso, audit trail completo, backtesting affidabile.

---

## 2. STRUTTURE DATI

### 2.1 Input: InputEmail (da Ingestion Layer)

```python
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class InputEmail:
    """Struttura dati in ingresso dal layer di ingestion IMAP"""
    uid: str                      # IMAP UID univoco
    uidvalidity: str             # IMAP UIDValidity per sync
    mailbox: str                 # Cartella IMAP (INBOX, Sent, etc.)
    from_addr: str               # Mittente raw
    to_addrs: List[str]          # Lista destinatari
    subject: str                 # Oggetto email
    date: str                    # Data ricezione/invio (string)
    body_text: str               # Corpo plain text (troncato 2000 char)
    body_html: str               # Anteprima HTML (troncata 500 char)
    size: int                    # Dimensione messaggio in byte
    headers: Dict[str, str]      # Tutti gli header come dizionario
    message_id: str              # Message-ID RFC5322
    fetched_at: str              # Timestamp estrazione ISO8601
```

**Nota importante**: `body_text` e `body_html` sono **troncati** dal layer ingestion. Il layer preprocessing deve ricostruire il body completo parsando gli header per MIME multipart.

### 2.2 Output: EmailDocument

```python
@dataclass(frozen=True)
class EmailDocument:
    """Documento email processato e canonicalizzato"""
    # Identificatori originali
    uid: str
    uidvalidity: str
    mailbox: str
    message_id: str
    fetched_at: str
    size: int
    
    # Header processati e redatti
    from_addr_redacted: str              # Hash o [EMAIL]
    to_addrs_redacted: List[str]         # Lista redatta
    subject_canonical: str               # Lower, unfold, PII redatto
    date_parsed: str                     # ISO8601 format
    headers_canonical: Dict[str, str]    # Keys lower, values unfold + redatti
    
    # Body processato
    body_text_canonical: str             # Plain + HTML→text merged, pulito, PII redatto
    body_html_canonical: str             # HTML sanitizzato, PII redatto
    body_original_hash: str              # SHA256(body originale) per audit
    
    # Metadati processing
    removed_sections: List[RemovedSection]  # Quote/sig/disclaimer rimossi
    pii_entities: List[PIIRedaction]        # Traccia PII redatti
    
    # Versioning (obbligatorio)
    pipeline_version: PipelineVersion
    processing_timestamp: str            # ISO8601
    processing_duration_ms: int          # Latenza processing

@dataclass
class RemovedSection:
    """Traccia sezioni rimosse per audit"""
    type: str           # "quote" | "signature" | "disclaimer" | "reply_header"
    span_start: int
    span_end: int
    content_preview: str  # Primi 100 char per audit
    confidence: float   # 0.0-1.0, pattern matching confidence

@dataclass
class PIIRedaction:
    """Traccia PII redatti per audit e compliance"""
    type: str           # "EMAIL" | "PHONE" | "NAME" | "IBAN" | "PIVA" | "CF"
    original_hash: str  # SHA256(original + salt) per reversibilità audit
    redacted: str       # "[PII_EMAIL]" o hash anonimizzato
    span_start: int
    span_end: int
    confidence: float   # 0.0-1.0, detection confidence
    detection_method: str  # "regex" | "ner" | "hybrid"
```

---

## 3. REQUISITI FUNZIONALI DETTAGLIATI

### 3.1 RFC5322/MIME Parsing

**Obiettivo**: Estrazione completa e corretta del contenuto email secondo standard RFC.

#### 3.1.1 Header Processing

```python
from email import policy
from email.parser import BytesParser
from email.header import decode_header, make_header

def parse_headers_rfc5322(raw_bytes: bytes) -> Dict[str, str]:
    """
    Parse headers RFC5322 con:
    - Unfolding (rimozione line breaks interni)
    - Decode charset (UTF-8, ISO-8859-1, etc.)
    - Normalizzazione case-insensitive keys
    """
    msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    headers = {}
    
    for key, value in msg.items():
        # Unfold header (rimuovi \r\n\t o \r\n spazi)
        unfolded = value.replace('\r\n\t', ' ').replace('\r\n ', ' ')
        
        # Decode charset se encoded (=?UTF-8?B?...?=)
        try:
            decoded = str(make_header(decode_header(unfolded)))
        except:
            decoded = unfolded
            
        headers[key.lower()] = decoded
    
    return headers
```

**Edge cases da gestire**:
- Header duplicati (es. multiple `Received`): concatena con `;` o crea lista
- Header malformati: fallback graceful, log warning
- Charset misti: priorità UTF-8, poi ISO-8859-1, poi best-effort

#### 3.1.2 MIME Multipart Handling

```python
def extract_body_parts(msg) -> Tuple[str, str]:
    """
    Estrai text/plain e text/html da struttura MIME multipart.
    
    Regole:
    - Preferenza text/plain se disponibile
    - Fallback a HTML→text conversion
    - Gestione attachment (ignora per body)
    - Merge multiple parti dello stesso tipo
    """
    text_parts = []
    html_parts = []
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            # Skip attachment
            if "attachment" in content_disposition:
                continue
                
            if content_type == "text/plain":
                try:
                    content = part.get_content()
                    if isinstance(content, str):
                        text_parts.append(content)
                except:
                    continue
                    
            elif content_type == "text/html":
                try:
                    content = part.get_content()
                    if isinstance(content, str):
                        html_parts.append(content)
                except:
                    continue
    else:
        # Non-multipart, singola parte
        content_type = msg.get_content_type()
        content = msg.get_content()
        
        if content_type == "text/plain":
            text_parts.append(content)
        elif content_type == "text/html":
            html_parts.append(content)
    
    # Merge
    text_plain = "\n\n".join(text_parts) if text_parts else ""
    text_html = "\n\n".join(html_parts) if html_parts else ""
    
    return text_plain, text_html
```

#### 3.1.3 HTML→Text Conversion

```python
from bs4 import BeautifulSoup
import html2text

def html_to_text_robust(html: str) -> str:
    """
    Conversione HTML→text robusta e deterministica.
    
    Pipeline:
    1. Parse con BeautifulSoup (lxml parser)
    2. Rimuovi script, style, meta tags
    3. Converti con html2text (markdown-like)
    4. Cleanup whitespace
    """
    if not html.strip():
        return ""
    
    # Parse HTML
    soup = BeautifulSoup(html, "lxml")
    
    # Remove script e style
    for tag in soup(["script", "style", "meta", "link"]):
        tag.decompose()
    
    # Convert to text preservando struttura
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.ignore_emphasis = False
    h.body_width = 0  # No wrapping
    
    text = h.handle(str(soup))
    
    # Cleanup whitespace
    lines = [line.rstrip() for line in text.split('\n')]
    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 newline consecutive
    
    return text.strip()
```

**Note**:
- BeautifulSoup con parser `lxml` è più robusto di `html.parser` per HTML malformato
- html2text preserva link e struttura (utile per downstream analysis)
- Determinismo garantito da versioni pinnate: `beautifulsoup4==4.12.3`, `html2text==2020.1.16`

### 3.2 Canonicalizzazione Deterministica

**Obiettivo**: Normalizzare testo in forma canonica riproducibile, rimuovendo elementi non informativi.

#### 3.2.1 Quote Pattern Removal

```python
QUOTE_PATTERNS = [
    # Email quote standard (>)
    (r'(?m)^[\s]*>+.*$', 'quote_standard'),
    
    # Reply headers italiani
    (r'(?is)Il giorno.*ha scritto:', 'reply_header_it'),
    (r'(?is)On.*wrote:', 'reply_header_en'),
    (r'(?is)Da:.*Inviato:.*A:.*Oggetto:', 'reply_header_outlook'),
    
    # Signature separators
    (r'(?m)^[\s]*--[\s]*$', 'signature_separator'),
    (r'(?m)^[\s]*_{5,}[\s]*$', 'signature_underline'),
    
    # Disclaimer/footer aziendali
    (r'(?is)Questo messaggio.*confidenziale.*', 'disclaimer_confidential'),
    (r'(?is)Informativa privacy.*GDPR.*', 'disclaimer_privacy'),
    (r'(?is)P\.?[\s]?Rispetta l\'ambiente.*', 'disclaimer_environment'),
    
    # Formule di chiusura standard
    (r'(?is)Cordiali saluti[,\s]*', 'closing_formal'),
    (r'(?is)Distinti saluti[,\s]*', 'closing_formal'),
    
    # Forward markers
    (r'(?m)^[\s]*-+[\s]*Forwarded message[\s]*-+', 'forward_marker'),
    (r'(?m)^[\s]*-+[\s]*Messaggio inoltrato[\s]*-+', 'forward_marker_it'),
]

CANONICALIZATION_VERSION = "1.3.0"

def canonicalize_text(
    text: str, 
    keep_audit: bool = True,
    remove_quotes: bool = True,
    remove_signatures: bool = True
) -> Tuple[str, List[RemovedSection]]:
    """
    Canonicalizzazione deterministica del testo.
    
    Args:
        text: Testo da canonicalizzare
        keep_audit: Se True, traccia sezioni rimosse
        remove_quotes: Se True, rimuovi quoted text
        remove_signatures: Se True, rimuovi firme
    
    Returns:
        (testo_canonico, sezioni_rimosse)
    """
    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    removed = []
    
    for pattern, section_type in QUOTE_PATTERNS:
        # Filtra per opzioni
        if not remove_quotes and 'quote' in section_type:
            continue
        if not remove_signatures and 'signature' in section_type:
            continue
            
        for match in re.finditer(pattern, text):
            if keep_audit:
                removed.append(RemovedSection(
                    type=section_type,
                    span_start=match.start(),
                    span_end=match.end(),
                    content_preview=match.group(0)[:100],
                    confidence=0.95  # Pattern-based = alta confidence
                ))
        
        # Replace pattern
        text = re.sub(pattern, '\n', text)
    
    # Cleanup excessive whitespace
    text = re.sub(r' {2,}', ' ', text)          # Multiple spaces → single
    text = re.sub(r'\n{3,}', '\n\n', text)      # Max 2 consecutive newlines
    text = text.strip()
    
    return text, removed
```

**Design rationale**:
- Pattern italiani specifici (customer service italiano)
- Confidence tracking per audit
- Configurabilità (flags per abilitare/disabilitare rimozioni)
- Preview 100 char per debug senza violare privacy

#### 3.2.2 Subject Canonicalization

```python
def canonicalize_subject(subject: str) -> str:
    """
    Canonicalizza subject line:
    - Rimuovi prefissi RE:/FW:/FWD:
    - Lowercase
    - Strip whitespace
    - Rimuovi emoji/unicode non necessari
    """
    if not subject:
        return ""
    
    # Remove RE:/FW: prefixes (case insensitive, multiple)
    subject = re.sub(r'^(re|fw|fwd|r|i):\s*', '', subject, flags=re.IGNORECASE)
    
    # Lowercase
    subject = subject.lower()
    
    # Strip
    subject = subject.strip()
    
    return subject
```

### 3.3 PII Redaction (GDPR Compliance)

**Obiettivo**: Identificare e redattare dati personali sensibili prima del processing LLM esterno.

#### 3.3.1 Privacy by Design

**Principi**:
1. **Redaction prima di LLM**: PII non devono mai raggiungere modelli esterni
2. **Tracciabilità**: ogni redaction loggata con hash reversibile per audit
3. **Determinismo**: stesso testo → stesse redaction
4. **Minimizzazione**: redigi solo il necessario, evita over-redaction

**Checklist GDPR**:
- ✅ Email redatte o hashate
- ✅ Nomi propri redatti con NER
- ✅ Telefoni, IBAN, CF, P.IVA redatti con regex
- ✅ Hash con salt per reversibilità controllata
- ✅ Log solo preview (max 500 char)
- ✅ Retention policy configurabile

#### 3.3.2 Regex Pattern (Deterministici)

```python
PII_REGEX_PATTERNS = {
    "EMAIL": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    
    "PHONE_IT": r'''
        (?:
            (?:\+39\s?)?                    # Prefisso Italia opzionale
            (?:
                3\d{2}[\s\-]?\d{6,7}        # Mobile: 3XX XXXXXXX
                |
                0\d{1,3}[\s\-]?\d{6,8}      # Fisso: 0X(X) XXXXXX(XX)
            )
        )
    ''',
    
    "PIVA": r'\b(?:IT\s?)?[0-9]{11}\b',  # P.IVA italiana
    
    "CF": r'\b[A-Z]{6}[0-9]{2}[A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z]\b',  # Codice Fiscale
    
    "IBAN": r'\bIT\d{2}[A-Z]\d{10}[0-9A-Z]{12}\b',  # IBAN italiano
    
    # Pattern aggiuntivi per over-redaction prevention
    "COMMON_BUSINESS_TERMS": r'\b(?:fattura|contratto|ordine|pratica)\s*(?:n\.?|num\.?)?\s*\d+\b',
}

PII_REDACTION_VERSION = "1.0.0"
PII_SALT = "thread-classificator-2026-pii-salt"  # Configurabile via env
```

**Nota**: Pattern `PHONE_IT` usa verbose regex per leggibilità. In produzione, compila una volta con `re.VERBOSE`.

#### 3.3.3 NER-based PII Detection

```python
import spacy
from typing import List, Set

NER_MODEL_VERSION = "it_core_news_lg-3.8.2"

class PIIDetector:
    """Rilevatore PII deterministico con Regex + NER"""
    
    def __init__(self):
        self.nlp = spacy.load("it_core_news_lg")
        self.nlp.max_length = 2_000_000  # Aumenta limite per email lunghe
        
        # Compila regex patterns
        self.regex_compiled = {
            pii_type: re.compile(pattern, re.IGNORECASE | re.VERBOSE)
            for pii_type, pattern in PII_REGEX_PATTERNS.items()
            if not pii_type.startswith("COMMON_")
        }
        
        # Whitelist business terms (no redaction)
        self.business_whitelist = re.compile(
            PII_REGEX_PATTERNS["COMMON_BUSINESS_TERMS"],
            re.IGNORECASE
        )
    
    def detect_pii_regex(self, text: str) -> List[PIIRedaction]:
        """Detect PII con regex deterministici"""
        redactions = []
        
        for pii_type, regex in self.regex_compiled.items():
            for match in regex.finditer(text):
                matched_text = match.group(0)
                
                # Check whitelist
                if self.business_whitelist.search(matched_text):
                    continue
                
                # Hash original
                original_hash = hashlib.sha256(
                    (matched_text + PII_SALT).encode('utf-8')
                ).hexdigest()[:16]
                
                redactions.append(PIIRedaction(
                    type=pii_type,
                    original_hash=original_hash,
                    redacted=f"[PII_{pii_type}]",
                    span_start=match.start(),
                    span_end=match.end(),
                    confidence=0.95,
                    detection_method="regex"
                ))
        
        return redactions
    
    def detect_pii_ner(
        self, 
        text: str, 
        confidence_threshold: float = 0.75
    ) -> List[PIIRedaction]:
        """Detect nomi/organizzazioni con spaCy NER"""
        if len(text) > 500_000:
            # Tronca per performance
            text = text[:500_000]
        
        doc = self.nlp(text)
        redactions = []
        
        for ent in doc.ents:
            # Redigi solo PERSON e ORG
            if ent.label_ not in ["PER", "PERSON", "ORG"]:
                continue
            
            # Filtri anti-false-positive
            if len(ent.text) < 3:
                continue
            if ent.text.lower() in ["sig", "dott", "ing", "avv"]:
                continue
            
            # Hash
            original_hash = hashlib.sha256(
                (ent.text + PII_SALT).encode('utf-8')
            ).hexdigest()[:16]
            
            redactions.append(PIIRedaction(
                type="NAME" if ent.label_ in ["PER", "PERSON"] else "ORG",
                original_hash=original_hash,
                redacted=f"[PII_NAME]",
                span_start=ent.start_char,
                span_end=ent.end_char,
                confidence=0.80,
                detection_method="ner"
            ))
        
        return redactions
    
    def merge_redactions(
        self, 
        redactions: List[PIIRedaction]
    ) -> List[PIIRedaction]:
        """
        Merge redactions sovrapposte:
        - Regex > NER (priorità detection method)
        - Longest span wins se stesso method
        """
        if not redactions:
            return []
        
        # Sort by start, then method priority
        method_priority = {"regex": 0, "ner": 1, "hybrid": 2}
        redactions_sorted = sorted(
            redactions,
            key=lambda r: (
                r.span_start,
                -r.span_end,
                method_priority.get(r.detection_method, 99)
            )
        )
        
        merged = []
        for redaction in redactions_sorted:
            # Check overlap
            has_overlap = False
            for i, existing in enumerate(merged):
                if self._overlaps(redaction, existing):
                    has_overlap = True
                    
                    # Priorità: regex > ner, poi longest
                    if method_priority[redaction.detection_method] < method_priority[existing.detection_method]:
                        merged[i] = redaction
                    elif redaction.detection_method == existing.detection_method:
                        if (redaction.span_end - redaction.span_start) > (existing.span_end - existing.span_start):
                            merged[i] = redaction
                    break
            
            if not has_overlap:
                merged.append(redaction)
        
        return sorted(merged, key=lambda r: r.span_start)
    
    def _overlaps(self, r1: PIIRedaction, r2: PIIRedaction) -> bool:
        """Check se due redactions si sovrappongono"""
        return not (r1.span_end <= r2.span_start or r2.span_end <= r1.span_start)
    
    def apply_redactions(
        self, 
        text: str, 
        redactions: List[PIIRedaction]
    ) -> str:
        """Applica redactions al testo"""
        if not redactions:
            return text
        
        # Sort reverse per applicare da fine a inizio (preserva indici)
        redactions_sorted = sorted(redactions, key=lambda r: r.span_start, reverse=True)
        
        for redaction in redactions_sorted:
            text = (
                text[:redaction.span_start] +
                redaction.redacted +
                text[redaction.span_end:]
            )
        
        return text
    
    def detect_and_redact(self, text: str) -> Tuple[str, List[PIIRedaction]]:
        """Pipeline completa: detect + merge + redact"""
        regex_redactions = self.detect_pii_regex(text)
        ner_redactions = self.detect_pii_ner(text)
        
        all_redactions = regex_redactions + ner_redactions
        merged_redactions = self.merge_redactions(all_redactions)
        
        redacted_text = self.apply_redactions(text, merged_redactions)
        
        return redacted_text, merged_redactions
```

**Design rationale**:
- **Regex first**: alta precisione per PII strutturati (email, phone, CF, IBAN)
- **NER second**: recall su nomi propri non catturati da regex
- **Merge deterministico**: regex > ner > longest span (regola fissa)
- **Whitelist**: previene over-redaction su termini business comuni
- **Confidence tracking**: abilita threshold configurabili per prod/audit

#### 3.3.4 Header PII Redaction

```python
def redact_headers(
    headers: Dict[str, str],
    pii_detector: PIIDetector
) -> Dict[str, str]:
    """
    Redatta PII dagli header email.
    
    Target headers:
    - From, To, Cc, Bcc (email)
    - Reply-To, Sender (email)
    - Subject (PII generici)
    """
    redacted = {}
    
    for key, value in headers.items():
        if key in ['from', 'to', 'cc', 'bcc', 'reply-to', 'sender']:
            # Redatta email addresses
            redacted_value, _ = pii_detector.detect_and_redact(value)
            redacted[key] = redacted_value
        elif key == 'subject':
            # Redatta PII generici nel subject
            redacted_value, _ = pii_detector.detect_and_redact(value)
            redacted[key] = redacted_value
        else:
            # Altri header: preserva
            redacted[key] = value
    
    return redacted
```

---

## 4. REQUISITI NON FUNZIONALI

### 4.1 Performance

| Metrica | Target | Motivazione |
|---------|--------|-------------|
| **Latenza p50** | < 500ms | Real-time processing capability |
| **Latenza p99** | < 2s | Gestione email complesse (100KB body) |
| **Throughput** | > 100 email/s | Batch processing notturno |
| **Memory footprint** | < 500MB per worker | Scalabilità orizzontale |

**Ottimizzazioni**:
- Lazy loading modello spaCy (carica una volta, riusa)
- Regex compiled cache
- Multiprocessing per batch (CPU-bound)

### 4.2 Affidabilità

- **Error handling**: Graceful degradation, no crash su email malformata
- **Logging**: Structured logging (JSON) per tracciabilità
- **Retry logic**: Max 3 tentativi con backoff esponenziale
- **Dead letter queue**: Email non processabili → DLQ per review manuale

### 4.3 Security

- **PII in memory**: Minimizza tempo di ritenzione, cleanup esplicito
- **Salt management**: Carica da env var, mai hardcoded
- **Audit log**: Ogni processing loggato con hash input/output
- **Access control**: Solo layer autorizzati possono accedere body_original

### 4.4 Observability

**Metriche da esporre** (Prometheus):
```python
# Processing
preprocessing_duration_seconds (histogram)
preprocessing_errors_total (counter, by error_type)
preprocessing_emails_total (counter, by status: success|failure)

# PII Redaction
pii_detections_total (counter, by pii_type, detection_method)
pii_redaction_confidence (histogram)

# Canonicalization
removed_sections_total (counter, by section_type)
body_size_before_bytes (histogram)
body_size_after_bytes (histogram)
```

---

## 5. CASI D'USO E EDGE CASES

### 5.1 Email Multipart Complessa

```
Email con struttura:
├─ multipart/mixed
   ├─ multipart/alternative
   │  ├─ text/plain (parte 1)
   │  └─ text/html (parte 1)
   ├─ text/plain (parte 2, quoted reply)
   └─ application/pdf (attachment)

Comportamento atteso:
- Estrai text/plain parte 1
- Estrai HTML parte 1 → converti a text
- Merge parte 1 plain + parte 1 html→text
- Ignora parte 2 (quoted, rimossa da canonicalization)
- Ignora attachment
```

### 5.2 Email Solo HTML (No Plain)

```
Comportamento:
- Rileva assenza text/plain
- Estrai HTML
- Converti HTML→text con BeautifulSoup + html2text
- Usa come body_text_canonical
```

### 5.3 Email con Charset Non-UTF8

```
Es: ISO-8859-1 (Latin-1) per email legacy

Comportamento:
- email.parser con policy.default gestisce decode automatico
- Fallback a UTF-8 best-effort
- Log warning se decode parziale
```

### 5.4 PII Over-Redaction

```
Problema: "Invio fattura n. 12345" → redatto come "[PII_PHONE]" (12345 match phone pattern)

Soluzione:
- Whitelist pattern "fattura n. \d+"
- Context-aware regex (lookbehind/lookahead)
- NER confidence threshold più alto per ridurre false positive
```

### 5.5 Email Molto Lunghe (>1MB)

```
Comportamento:
- Tronca body a 500KB per NER (performance)
- Log warning
- Mantieni full body per regex PII (performante)
- Considera sampling per email >5MB
```

---

## 6. TEST STRATEGY

### 6.1 Unit Test (Copertura >90%)

```python
def test_canonicalization_determinism():
    """Stesso input → stesso output"""
    sample = "Hello\n\n> quoted line\n--\nSignature"
    clean1, removed1 = canonicalize_text(sample)
    clean2, removed2 = canonicalize_text(sample)
    
    assert clean1 == clean2
    assert len(removed1) == len(removed2)
    assert removed1[0].type == removed2[0].type

def test_pii_redaction_email():
    """Email redaction funziona"""
    text = "Contattami a mario.rossi@example.com"
    detector = PIIDetector()
    redacted, pii_list = detector.detect_and_redact(text)
    
    assert "[PII_EMAIL]" in redacted
    assert "mario.rossi@example.com" not in redacted
    assert len(pii_list) == 1
    assert pii_list[0].type == "EMAIL"

def test_html_to_text_stability():
    """HTML conversion deterministica"""
    html = "<p>Hello <b>world</b></p>"
    text1 = html_to_text_robust(html)
    text2 = html_to_text_robust(html)
    
    assert text1 == text2
    assert "Hello world" in text1
```

### 6.2 Integration Test

```python
def test_full_preprocessing_pipeline():
    """Test end-to-end con sample email"""
    input_email = InputEmail(
        uid="12345",
        uidvalidity="67890",
        mailbox="INBOX",
        from_addr="mario.rossi@example.com",
        to_addrs=["support@company.it"],
        subject="RE: Fattura n. 12345",
        date="2026-02-17T10:30:00Z",
        body_text="Buongiorno...",
        body_html="<p>Buongiorno...</p>",
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
```

### 6.3 Property-Based Testing

```python
from hypothesis import given, strategies as st

@given(st.text(min_size=10, max_size=1000))
def test_canonicalization_idempotent(text):
    """Canonicalization è idempotente"""
    clean1, _ = canonicalize_text(text)
    clean2, _ = canonicalize_text(clean1)
    
    assert clean1 == clean2  # Applying twice = stessa dell'applicare una volta
```

### 6.4 Performance Benchmark

```python
def benchmark_preprocessing_latency():
    """Misura latenza su dataset sample"""
    emails = load_sample_emails(n=1000)  # Mix di size
    
    latencies = []
    for email in emails:
        start = time.perf_counter()
        preprocess_email(email)
        latencies.append((time.perf_counter() - start) * 1000)
    
    p50 = np.percentile(latencies, 50)
    p99 = np.percentile(latencies, 99)
    
    assert p50 < 500, f"p50={p50}ms exceeds 500ms target"
    assert p99 < 2000, f"p99={p99}ms exceeds 2s target"
```

---

## 7. SICUREZZA E COMPLIANCE

### 7.1 GDPR Checklist

- [x] **Minimizzazione dati**: Solo PII necessari processati
- [x] **Pseudonimizzazione**: Hash con salt per reversibilità audit
- [x] **Diritto all'oblio**: Hash permettono deletion tracking
- [x] **Privacy by design**: PII redaction integrata nel layer
- [x] **Audit log**: Ogni redaction tracciata con timestamp
- [x] **Retention policy**: body_original_hash con TTL configurabile
- [x] **Access control**: body_original solo per audit autorizzato

### 7.2 Security Best Practices

```python
# ❌ MAI fare questo
PII_SALT = "hardcoded-salt-123"  # VULNERABILE

# ✅ Corretto
PII_SALT = os.environ.get("PII_SALT", None)
if not PII_SALT:
    raise ValueError("PII_SALT env var must be set")

# ✅ Cleanup esplicito memoria sensibile
def cleanup_sensitive_data(email_doc: EmailDocument):
    """Zero-out memoria dopo processing"""
    import gc
    del email_doc
    gc.collect()
```

### 7.3 Audit Trail Format

```json
{
  "event_type": "email_preprocessing",
  "timestamp": "2026-02-17T19:53:42.123Z",
  "input_hash": "sha256:abc123...",
  "output_hash": "sha256:def456...",
  "pipeline_version": "email-parser-1.3.0|canonicalization-1.3.0|pii-redaction-1.0.0",
  "pii_redactions": [
    {
      "type": "EMAIL",
      "count": 2,
      "detection_method": "regex",
      "avg_confidence": 0.95
    }
  ],
  "removed_sections": [
    {
      "type": "quote_standard",
      "count": 3
    }
  ],
  "processing_duration_ms": 342,
  "status": "success"
}
```

---

## 8. BUG LOGICI IDENTIFICATI E MITIGAZIONI

### 8.1 Body Troncato da Ingestion

**Bug**: InputEmail ha `body_text` troncato a 2000 char, perdendo contenuto per email lunghe.

**Impatto**: 
- Perdita informazioni per classificazione
- Inconsistenza: header completi ma body parziale

**Mitigazione**:
```python
# Opzione 1: Ri-fetch raw email da IMAP quando body troncato
if len(input_email.body_text) >= 1999:
    # Body probabilmente troncato
    raw_email = fetch_full_email(input_email.uid, input_email.mailbox)
    # Re-parse completo
    
# Opzione 2: Ingestion layer deve fornire full body o flag "truncated"
@dataclass
class InputEmail:
    body_text: str
    body_html: str
    body_truncated: bool = False  # NUOVO campo
```

**Raccomandazione**: Modificare Ingestion Layer per esporre body completo o fornire `raw_bytes` opzionali.

### 8.2 Whitespace Non-Determinismo

**Bug**: Stripping/normalizzazione whitespace può variare tra run se implementato male.

**Esempio**:
```python
# ❌ NON deterministico
text = " ".join(text.split())  # split() dipende da locale

# ✅ Deterministico
text = re.sub(r'\s+', ' ', text)  # Regex esplicita
```

**Mitigazione**: Usa sempre regex esplicite, pinna versione Python, documenta comportamento edge case.

### 8.3 NER Model Non-Determinism

**Bug**: spaCy NER può avere variabilità tra versioni o env diversi.

**Mitigazione**:
```python
# Pin esatto versione modello
# requirements.txt:
spacy==3.7.4
https://github.com/explosion/spacy-models/releases/download/it_core_news_lg-3.7.0/it_core_news_lg-3.7.0-py3-none-any.whl

# Test regression NER
def test_ner_stability():
    """NER deve produrre stessi risultati su sample noto"""
    text = "Mario Rossi ha chiamato ieri."
    doc1 = nlp(text)
    doc2 = nlp(text)
    
    entities1 = [(e.text, e.label_) for e in doc1.ents]
    entities2 = [(e.text, e.label_) for e in doc2.ents]
    
    assert entities1 == entities2
    assert entities1 == [("Mario Rossi", "PER")]  # Expected output
```

### 8.4 HTML Parsing Ambiguità

**Bug**: HTML malformato può essere parsato diversamente da BeautifulSoup tra versioni.

**Mitigazione**:
- Pin `beautifulsoup4==4.12.3` e `lxml==5.1.0`
- Regression test su sample HTML patologici
- Fallback graceful su parse error

### 8.5 Regex ReDoS Vulnerability

**Bug**: Regex mal scritte possono causare exponential backtracking (ReDoS attack).

**Esempio vulnerabile**:
```python
# ❌ VULNERABILE a ReDoS
PATTERN = r'(a+)+'  # Catastrophic backtracking

# ✅ SAFE
PATTERN = r'a+'  # Linear
```

**Mitigazione**:
```python
import re
import signal

class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError()

def safe_regex_search(pattern, text, timeout_sec=1):
    """Regex con timeout per prevenire ReDoS"""
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_sec)
    
    try:
        matches = pattern.findall(text)
        signal.alarm(0)  # Reset
        return matches
    except TimeoutError:
        signal.alarm(0)
        logger.warning(f"Regex timeout on pattern: {pattern.pattern}")
        return []
```

---

## 9. FEATURES PRODUCTION-READY

### 9.1 Configuration Management

```python
from pydantic import BaseSettings, Field

class PreprocessingConfig(BaseSettings):
    """Configuration con validazione Pydantic"""
    
    # Versioning
    parser_version: str = "email-parser-1.3.0"
    canonicalization_version: str = "1.3.0"
    ner_model_version: str = "it_core_news_lg-3.8.2"
    pii_redaction_version: str = "1.0.0"
    
    # PII Redaction
    pii_salt: str = Field(..., env="PII_SALT")
    pii_ner_confidence_threshold: float = 0.75
    pii_regex_timeout_sec: int = 1
    
    # Canonicalization
    remove_quotes: bool = True
    remove_signatures: bool = True
    max_body_size_kb: int = 500
    
    # Performance
    spacy_batch_size: int = 50
    multiprocessing_workers: int = 4
    
    # Logging
    log_level: str = "INFO"
    log_pii_preview: bool = False  # Security: mai loggare PII in prod
    
    class Config:
        env_prefix = "PREPROCESSING_"
        case_sensitive = False

config = PreprocessingConfig()
```

### 9.2 Structured Logging

```python
import structlog

logger = structlog.get_logger()

def preprocess_email_with_logging(input_email: InputEmail) -> EmailDocument:
    """Main function con logging strutturato"""
    
    log = logger.bind(
        uid=input_email.uid,
        mailbox=input_email.mailbox,
        message_id=input_email.message_id
    )
    
    log.info("preprocessing_started", size=input_email.size)
    
    start = time.perf_counter()
    
    try:
        # Processing
        output = _preprocess_internal(input_email)
        
        duration_ms = (time.perf_counter() - start) * 1000
        
        log.info(
            "preprocessing_completed",
            duration_ms=duration_ms,
            pii_redactions=len(output.pii_entities),
            removed_sections=len(output.removed_sections),
            body_size_before=len(input_email.body_text),
            body_size_after=len(output.body_text_canonical)
        )
        
        return output
        
    except Exception as e:
        duration_ms = (time.perf_counter() - start) * 1000
        
        log.error(
            "preprocessing_failed",
            duration_ms=duration_ms,
            error_type=type(e).__name__,
            error_msg=str(e),
            exc_info=True
        )
        
        raise
```

### 9.3 Health Checks

```python
from fastapi import FastAPI, HTTPException
from typing import Dict

app = FastAPI()

@app.get("/health")
def health_check() -> Dict[str, str]:
    """Health check basico"""
    return {"status": "healthy"}

@app.get("/health/ready")
def readiness_check() -> Dict[str, any]:
    """Readiness check dettagliato"""
    checks = {}
    
    # Check NER model loaded
    try:
        _ = nlp("test")
        checks["ner_model"] = "ok"
    except Exception as e:
        checks["ner_model"] = f"error: {e}"
    
    # Check config loaded
    try:
        _ = config.pii_salt
        checks["config"] = "ok"
    except Exception as e:
        checks["config"] = f"error: {e}"
    
    # Overall status
    all_ok = all(v == "ok" for v in checks.values())
    
    return {
        "status": "ready" if all_ok else "not_ready",
        "checks": checks
    }
```

### 9.4 Graceful Degradation

```python
def preprocess_email_safe(input_email: InputEmail) -> EmailDocument:
    """
    Preprocessing con graceful degradation:
    - Se NER fallisce → usa solo regex PII
    - Se canonicalization fallisce → usa body raw
    - Se tutto fallisce → ritorna documento minimale
    """
    
    try:
        return preprocess_email(input_email)
    except PIIDetectionError as e:
        logger.warning("pii_detection_failed_fallback_to_regex", error=str(e))
        return preprocess_email_regex_only(input_email)
    except CanonicalizationError as e:
        logger.warning("canonicalization_failed_using_raw_body", error=str(e))
        return preprocess_email_no_canon(input_email)
    except Exception as e:
        logger.error("preprocessing_total_failure_minimal_doc", error=str(e))
        return create_minimal_document(input_email)

def create_minimal_document(input_email: InputEmail) -> EmailDocument:
    """Documento minimale per fallback"""
    return EmailDocument(
        uid=input_email.uid,
        uidvalidity=input_email.uidvalidity,
        mailbox=input_email.mailbox,
        from_addr_redacted="[ERROR]",
        to_addrs_redacted=["[ERROR]"],
        subject_canonical=input_email.subject,
        date_parsed=input_email.date,
        body_text_canonical=input_email.body_text[:1000],
        body_html_canonical="",
        body_original_hash="error",
        headers_canonical={},
        removed_sections=[],
        pii_entities=[],
        pipeline_version=PipelineVersion(),
        processing_timestamp=datetime.utcnow().isoformat(),
        processing_duration_ms=0
    )
```

### 9.5 Rate Limiting & Backpressure

```python
from asyncio import Semaphore

class PreprocessingService:
    """Service con rate limiting e backpressure"""
    
    def __init__(self, max_concurrent: int = 10):
        self.semaphore = Semaphore(max_concurrent)
        self.pii_detector = PIIDetector()
    
    async def preprocess_async(self, input_email: InputEmail) -> EmailDocument:
        """Preprocessing asincrono con semaforo"""
        async with self.semaphore:
            # Offload CPU-bound task to thread pool
            loop = asyncio.get_event_loop()
            output = await loop.run_in_executor(
                None,  # Default executor
                self._preprocess_sync,
                input_email
            )
            return output
    
    def _preprocess_sync(self, input_email: InputEmail) -> EmailDocument:
        """Sync preprocessing function"""
        return preprocess_email(input_email)
```

---

## 10. DEPLOYMENT CONSIDERATIONS

### 10.1 Docker Container

```dockerfile
# Dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy model
RUN python -m spacy download it_core_news_lg

# Copy application code
COPY src/ ./src/

# Environment variables
ENV PREPROCESSING_PII_SALT="changeme"
ENV PREPROCESSING_LOG_LEVEL="INFO"

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# Run application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 10.2 Kubernetes Deployment

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: email-preprocessing
spec:
  replicas: 3
  selector:
    matchLabels:
      app: email-preprocessing
  template:
    metadata:
      labels:
        app: email-preprocessing
    spec:
      containers:
      - name: preprocessing
        image: email-preprocessing:1.3.0
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        env:
        - name: PREPROCESSING_PII_SALT
          valueFrom:
            secretKeyRef:
              name: preprocessing-secrets
              key: pii-salt
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
```

### 10.3 Monitoring Dashboard

```yaml
# Prometheus alerts
groups:
- name: preprocessing_alerts
  rules:
  - alert: HighErrorRate
    expr: rate(preprocessing_errors_total[5m]) > 0.05
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High error rate in email preprocessing"
      
  - alert: HighLatency
    expr: histogram_quantile(0.99, preprocessing_duration_seconds) > 2
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "p99 latency exceeds 2s"
      
  - alert: PIIDetectionAnomalies
    expr: rate(pii_detections_total[1h]) > 2 * rate(pii_detections_total[1h] offset 24h)
    for: 10m
    labels:
      severity: info
    annotations:
      summary: "Unusual spike in PII detections"
```

---

## 11. PROSSIMI STEP E ROADMAP

### Phase 1: MVP (Current)
- [x] Definizione architettura
- [x] Specifica completa layer
- [ ] Implementazione core functions
- [ ] Unit test coverage >90%
- [ ] Integration test

### Phase 2: Production Hardening
- [ ] Performance benchmarking
- [ ] Load testing (10K email/hour)
- [ ] Security audit
- [ ] GDPR compliance review
- [ ] Documentation completa

### Phase 3: Advanced Features
- [ ] Multi-language support (EN, FR, DE)
- [ ] Advanced NER (custom model fine-tuned)
- [ ] PII detection confidence calibration
- [ ] A/B testing framework
- [ ] Real-time monitoring dashboard

---

## 12. REFERENCES

### RFCs
- RFC 5322: Internet Message Format
- RFC 2045-2049: MIME (Multipurpose Internet Mail Extensions)

### Libraries
- `email` (Python stdlib): RFC5322/MIME parsing
- `beautifulsoup4==4.12.3`: HTML parsing
- `html2text==2020.1.16`: HTML→text conversion
- `spacy==3.7.4`: NER italiano
- `it_core_news_lg-3.7.0`: spaCy Italian model

### Best Practices
- OWASP Email Security
- GDPR Article 25 (Privacy by Design)
- NIST SP 800-122 (PII De-identification)

---

## APPENDIX A: ESEMPIO COMPLETO INPUT/OUTPUT

### Input (InputEmail JSON)
```json
{
  "uid": "12345",
  "uidvalidity": "67890",
  "mailbox": "INBOX",
  "from_addr": "mario.rossi@clienteabc.it",
  "to_addrs": ["support@company.it"],
  "subject": "RE: Fattura n. 2024/001 - Sollecito pagamento",
  "date": "2026-02-17T10:30:00+01:00",
  "body_text": "Buongiorno,\n\nfaccio seguito alla mia precedente del 10/02...",
  "body_html": "<p>Buongiorno,</p><p>faccio seguito...</p>",
  "size": 2048,
  "headers": {
    "message-id": "<abc123@clienteabc.it>",
    "in-reply-to": "<xyz789@company.it>",
    "from": "Mario Rossi <mario.rossi@clienteabc.it>",
    "to": "support@company.it"
  },
  "message_id": "<abc123@clienteabc.it>",
  "fetched_at": "2026-02-17T10:31:00Z"
}
```

### Output (EmailDocument)
```json
{
  "uid": "12345",
  "uidvalidity": "67890",
  "mailbox": "INBOX",
  "message_id": "<abc123@clienteabc.it>",
  "fetched_at": "2026-02-17T10:31:00Z",
  "size": 2048,
  
  "from_addr_redacted": "[PII_EMAIL]",
  "to_addrs_redacted": ["support@company.it"],
  "subject_canonical": "fattura n. 2024/001 - sollecito pagamento",
  "date_parsed": "2026-02-17T10:30:00+01:00",
  "headers_canonical": {
    "message-id": "<abc123@clienteabc.it>",
    "from": "[PII_NAME] <[PII_EMAIL]>",
    "to": "support@company.it"
  },
  
  "body_text_canonical": "buongiorno,\n\nfaccio seguito alla mia precedente del 10/02...",
  "body_html_canonical": "<p>buongiorno,</p>...",
  "body_original_hash": "sha256:a1b2c3d4...",
  
  "removed_sections": [
    {
      "type": "signature_separator",
      "span_start": 245,
      "span_end": 250,
      "content_preview": "--\nMario Rossi...",
      "confidence": 0.95
    }
  ],
  
  "pii_entities": [
    {
      "type": "EMAIL",
      "original_hash": "e8f7a9b2...",
      "redacted": "[PII_EMAIL]",
      "span_start": 15,
      "span_end": 42,
      "confidence": 0.95,
      "detection_method": "regex"
    },
    {
      "type": "NAME",
      "original_hash": "c3d4e5f6...",
      "redacted": "[PII_NAME]",
      "span_start": 245,
      "span_end": 256,
      "confidence": 0.80,
      "detection_method": "ner"
    }
  ],
  
  "pipeline_version": {
    "parser_version": "email-parser-1.3.0",
    "canonicalization_version": "1.3.0",
    "ner_model_version": "it_core_news_lg-3.8.2",
    "pii_redaction_version": "1.0.0"
  },
  
  "processing_timestamp": "2026-02-17T10:31:05.342Z",
  "processing_duration_ms": 342
}
```

---

**END OF SPECIFICATION**
