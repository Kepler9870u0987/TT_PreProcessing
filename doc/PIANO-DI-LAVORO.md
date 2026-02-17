# PIANO DI LAVORO - Layer Preprocessing & Canonicalization
## Thread Classificator Mail

**Creato**: 17 Febbraio 2026  
**Ultimo aggiornamento**: 17 Febbraio 2026  
**Stato globale**: 🔴 NON INIZIATO

---

## LEGENDA STATUS

- 🔴 Non iniziato
- 🟡 In corso
- 🟢 Completato
- ⏸️ Bloccato
- ⏭️ Skippato (motivazione indicata)

---

## FASE 0: SETUP PROGETTO E AMBIENTE

**Status**: 🔴

### 0.1 Struttura directory
- [ ] Creare struttura cartelle: `src/`, `tests/`, `examples/sample_emails/`, `examples/notebooks/`
- [ ] Creare `src/__init__.py`, `tests/__init__.py`

### 0.2 Dipendenze e ambiente
- [ ] Creare `requirements.txt` con dipendenze pinnate:
  - `beautifulsoup4==4.12.3`, `lxml==5.1.0`, `html2text==2020.1.16`
  - `spacy==3.7.4`, `pydantic==2.6.1`, `structlog==24.1.0`
  - `fastapi>=0.109.0`, `uvicorn>=0.27.0` (per health checks e servizio)
- [ ] Creare `requirements-dev.txt`:
  - `pytest==8.0.0`, `pytest-cov==4.1.0`, `hypothesis==6.98.0`
  - `black==24.1.1`, `mypy==1.8.0`, `flake8==7.0.0`
  - `numpy` (per benchmark), `pytest-benchmark`
  - `httpx` (per test FastAPI)
- [ ] Creare `.env.example` con variabili d'ambiente documentate:
  - `PREPROCESSING_PII_SALT` (obbligatoria, generare con `python -c 'import secrets; print(secrets.token_hex(32))'`)
  - `PREPROCESSING_LOG_LEVEL` (default INFO)
  - `PREPROCESSING_PII_NER_CONFIDENCE_THRESHOLD` (default 0.75)
  - `PREPROCESSING_REMOVE_QUOTES` (default true)
  - `PREPROCESSING_REMOVE_SIGNATURES` (default true)
  - `PREPROCESSING_MAX_BODY_SIZE_KB` (default 500)
- [ ] Creare `setup.py` per installazione pacchetto
- [ ] Creare `Makefile` con target: `install`, `test`, `lint`, `format`, `coverage`, `typecheck`, `run`

### 0.3 Configurazione CI/Linting
- [ ] Creare/aggiornare `pyproject.toml` per black, mypy, pytest
- [ ] Aggiornare `.gitignore` per venv, `__pycache__`, `.mypy_cache`, `htmlcov`, `.pytest_cache`, `*.egg-info`

---

## FASE 1: MODELLI DATI (`src/models.py`)

**Status**: 🔴

### 1.1 Dataclass PipelineVersion
- [ ] Implementare `PipelineVersion` (`frozen=True`) con campi:
  - `parser_version: str = "email-parser-1.3.0"`
  - `canonicalization_version: str = "1.3.0"`
  - `ner_model_version: str = "it_core_news_lg-3.8.2"`
  - `pii_redaction_version: str = "1.0.0"`

### 1.2 Dataclass RemovedSection
- [ ] Implementare `RemovedSection` con campi:
  - `type: str` — valori ammessi: `"quote"`, `"signature"`, `"disclaimer"`, `"reply_header"`, `"quote_standard"`, `"closing_formal"`, `"forward_marker"`
  - `span_start: int`, `span_end: int`
  - `content_preview: str` — troncato a max 100 caratteri
  - `confidence: float` — range 0.0–1.0

### 1.3 Dataclass PIIRedaction
- [ ] Implementare `PIIRedaction` con campi:
  - `type: str` — `"EMAIL"`, `"PHONE_IT"`, `"NAME"`, `"ORG"`, `"IBAN"`, `"PIVA"`, `"CF"`
  - `original_hash: str` — SHA256(originale + salt), primi 16 hex
  - `redacted: str` — es. `"[PII_EMAIL]"`, `"[PII_NAME]"`
  - `span_start: int`, `span_end: int`
  - `confidence: float` — 0.0–1.0
  - `detection_method: str` — `"regex"`, `"ner"`, `"hybrid"`

### 1.4 Dataclass InputEmail
- [ ] Implementare `InputEmail` con tutti i campi da specifica:
  - `uid`, `uidvalidity`, `mailbox`, `from_addr`, `to_addrs: List[str]`, `subject`, `date`
  - `body_text`, `body_html`, `size: int`, `headers: Dict[str, str]`
  - `message_id`, `fetched_at`
- [ ] Aggiungere campo opzionale `raw_bytes: Optional[bytes] = None` (**mitigazione BUG-001**)
- [ ] Aggiungere campo opzionale `body_truncated: bool = False`

### 1.5 Dataclass EmailDocument
- [ ] Implementare `EmailDocument` (`frozen=True`) con tutti i campi output:
  - Identificatori: `uid`, `uidvalidity`, `mailbox`, `message_id`, `fetched_at`, `size`
  - Header processati: `from_addr_redacted`, `to_addrs_redacted: List[str]`, `subject_canonical`, `date_parsed`, `headers_canonical: Dict[str, str]`
  - Body: `body_text_canonical`, `body_html_canonical`, `body_original_hash`
  - Metadati: `removed_sections: List[RemovedSection]`, `pii_entities: List[PIIRedaction]`
  - Versioning: `pipeline_version: PipelineVersion`, `processing_timestamp: str`, `processing_duration_ms: int`
- [ ] Usare `field(default_factory=...)` per campi mutabili (list, dict)
- [ ] Verificare compatibilità `frozen=True` con default factory

### 1.6 Eccezioni custom
- [ ] `PreprocessingError(Exception)` — base exception per il layer
- [ ] `PIIDetectionError(PreprocessingError)` — errori PII detection
- [ ] `CanonicalizationError(PreprocessingError)` — errori canonicalization
- [ ] `ParsingError(PreprocessingError)` — errori parsing RFC5322/MIME

### 1.7 Test modelli (`tests/test_models.py`)
- [ ] Test creazione `PipelineVersion` con valori default
- [ ] Test creazione `EmailDocument` completa con tutti i campi
- [ ] Test immutabilità (frozen) di `EmailDocument` e `PipelineVersion` — assegnazione a campo deve raise `FrozenInstanceError`
- [ ] Test `InputEmail` con e senza `raw_bytes`
- [ ] Test `RemovedSection.content_preview` troncamento a 100 char

---

## FASE 2: CONFIGURAZIONE (`src/config.py`)

**Status**: 🔴

### 2.1 PreprocessingConfig con Pydantic BaseSettings
- [ ] Implementare `PreprocessingConfig(BaseSettings)`:
  - **Versioning**: `parser_version`, `canonicalization_version`, `ner_model_version`, `pii_redaction_version` (con default da specifica)
  - **PII**: `pii_salt: str = Field(..., env="PREPROCESSING_PII_SALT")` — **OBBLIGATORIO**, nessun default (**mitigazione BUG-003**)
  - **PII**: `pii_ner_confidence_threshold: float = 0.75`
  - **Canonicalization**: `remove_quotes: bool = True`, `remove_signatures: bool = True`, `max_body_size_kb: int = 500`
  - **Performance**: `spacy_batch_size: int = 50`, `regex_timeout_sec: int = 1`
  - **Logging**: `log_level: str = "INFO"`, `log_pii_preview: bool = False`
- [ ] `Config.env_prefix = "PREPROCESSING_"`, `case_sensitive = False`
- [ ] Messaggio errore chiaro se `pii_salt` mancante con istruzioni di generazione

### 2.2 Singleton thread-safe (**mitigazione BUG-005**)
- [ ] Implementare `get_config()` con `@lru_cache(maxsize=1)` — thread-safe by design, zero overhead
- [ ] Alternativa: double-check locking con `threading.Lock` (solo se necessario reset)

### 2.3 Test configurazione (`tests/test_config.py`)
- [ ] Test caricamento config da env vars (mock `os.environ`)
- [ ] Test `ValidationError` se `PII_SALT` mancante
- [ ] Test singleton restituisce stessa istanza (identity check `is`)
- [ ] Test override singoli parametri via env
- [ ] Test valori default corretti

---

## FASE 3: LOGGING (`src/logging_setup.py`)

**Status**: 🔴

### 3.1 Setup structlog
- [ ] Implementare `setup_logging(log_level: str = "INFO")`:
  - `logging.basicConfig()` per configurazione base
  - `structlog.configure()` con processors:
    - `add_log_level`, `add_logger_name`
    - `TimeStamper(fmt="iso")`
    - `StackInfoRenderer()`, `format_exc_info`
    - `JSONRenderer()`
  - `cache_logger_on_first_use=True`
- [ ] Creare `logger = structlog.get_logger()` esportato dal modulo
- [ ] **SICUREZZA**: garantire che PII non appaiano nei log nemmeno in debug mode

### 3.2 Test logging (`tests/test_logging.py`)
- [ ] Test output è JSON valido
- [ ] Test campi standard presenti (level, timestamp, event)
- [ ] Test livelli log rispettati (DEBUG non appare se level=INFO)

---

## FASE 4: RFC5322/MIME PARSING (`src/parsing.py`)

**Status**: 🔴

### 4.1 Header Processing
- [ ] Implementare `parse_headers_rfc5322(headers_dict: Dict[str, str]) -> Dict[str, str]`:
  - Unfolding: rimuovere `\r\n\t`, `\r\n ` (whitespace continuation)
  - Decode charset: gestire `=?UTF-8?B?...?=` con `make_header(decode_header(...))`
  - Lowercase di tutte le keys
  - Header duplicati: concatenare con `; ` separatore
  - Error handling: `try/except` con fallback al valore raw e log warning

### 4.2 MIME Body Extraction
- [ ] Implementare `extract_body_parts_from_truncated(body_text_preview: str, body_html_preview: str, raw_bytes: Optional[bytes] = None) -> Tuple[str, str]`:
  - **Se `raw_bytes` presente**: `BytesParser(policy=policy.default).parsebytes(raw_bytes)` → full MIME parse
  - Walk multipart: `msg.walk()`, skip `Content-Disposition: attachment`
  - Raccogliere `text/plain` e `text/html` separatamente
  - Merge multiple parti stesso tipo con `\n\n`
  - **Se `raw_bytes` assente**: fallback a preview troncati + log warning `"body_truncated_using_preview"`
  - Gestione charset non-UTF8: `msg.get_content()` con policy.default gestisce automaticamente, fallback graceful

### 4.3 HTML→Text Conversion
- [ ] Implementare `html_to_text_robust(html_text: str) -> str`:
  - **Step 1**: `html.unescape(html_text)` — decode entities (**mitigazione BUG-008**)
  - **Step 2**: `BeautifulSoup(html_text, "lxml")` — parse robusto
  - **Step 3**: Rimuovere tag `script`, `style`, `meta`, `link` con `.decompose()`
  - **Step 4**: `html2text.HTML2Text()` con parametri deterministici:
    - `ignore_links = False`, `ignore_images = True`, `ignore_emphasis = False`, `body_width = 0`
  - **Step 5**: Cleanup whitespace: rstrip ogni riga, `re.sub(r'\n{3,}', '\n\n', text)`, strip finale
  - Return `""` se input vuoto

### 4.4 Body Merge
- [ ] Implementare `merge_body_parts(text_plain: str, text_from_html: str) -> str`:
  - Se entrambi presenti: preferenza `text_plain`; se `text_from_html` significativamente più lungo (>2x), arricchire
  - Se solo HTML→text: usarlo
  - Se solo plain: usarlo
  - Se nessuno: return `""`

### 4.5 Test parsing (`tests/test_parsing.py`)
- [ ] Test unfolding header RFC5322 (con `\r\n\t` e `\r\n `)
- [ ] Test decode header charset UTF-8 encoded (`=?UTF-8?B?...?=`)
- [ ] Test decode header charset ISO-8859-1
- [ ] Test header duplicati (es. multiple `Received`) → concatenati con `;`
- [ ] Test header malformati → fallback graceful, no exception
- [ ] Test MIME multipart extraction (multipart/mixed con text/plain + text/html)
- [ ] Test MIME multipart/alternative (preferenza plain)
- [ ] Test skip attachment (Content-Disposition: attachment)
- [ ] Test email solo HTML (no text/plain) → HTML→text conversion
- [ ] Test email solo plain (no HTML) → plain usato direttamente
- [ ] Test charset non-UTF8 (ISO-8859-1 email body)
- [ ] Test HTML→text determinismo: `f(x) == f(x)` su multipli run
- [ ] Test HTML entity decoding (`&amp;` → `&`, `&#64;` → `@`, `&lt;` → `<`)
- [ ] Test HTML malformato (tag non chiusi) → parse graceful senza crash
- [ ] Test merge body parts: entrambi presenti, solo plain, solo HTML, nessuno
- [ ] Test fallback a preview quando `raw_bytes` assente

---

## FASE 5: CANONICALIZZAZIONE (`src/canonicalization.py`)

**Status**: 🔴

### 5.1 Quote/Signature Patterns (**mitigazione BUG-002: ReDoS**)
- [ ] Definire `QUOTE_PATTERNS` come lista di tuple `(pattern_str, section_type)`:
  - `(r'(?m)^[\s]*>+.*$', 'quote_standard')` — quote email standard
  - `(r'(?is)Il giorno.{1,200}ha scritto:', 'reply_header_it')` — **bounded, NO `.*`**
  - `(r'(?is)On.{1,200}wrote:', 'reply_header_en')` — **bounded**
  - `(r'(?is)Da:.{1,200}Inviato:.{1,200}A:.{1,200}Oggetto:', 'reply_header_outlook')` — **bounded**
  - `(r'(?m)^[\s]*--[\s]*$', 'signature_separator')`
  - `(r'(?m)^[\s]*_{5,}[\s]*$', 'signature_underline')`
  - `(r'(?is)Questo messaggio.{1,500}?confidenziale', 'disclaimer_confidential')` — **bounded + non-greedy**
  - `(r'(?is)Informativa privacy.{1,500}?GDPR', 'disclaimer_privacy')` — **bounded**
  - `(r'(?is)P\.?[\s]?Rispetta l\'ambiente.*', 'disclaimer_environment')`
  - `(r'(?is)Cordiali saluti[,\s]*', 'closing_formal')`
  - `(r'(?is)Distinti saluti[,\s]*', 'closing_formal')`
  - `(r'(?m)^[\s]*-+[\s]*Forwarded message[\s]*-+', 'forward_marker')`
  - `(r'(?m)^[\s]*-+[\s]*Messaggio inoltrato[\s]*-+', 'forward_marker_it')`
- [ ] Compilare regex a livello di modulo (una volta sola, **ENHANCEMENT-001**): usare `_COMPILED_PATTERNS` lista
- [ ] Implementare `safe_regex_finditer(pattern, text, timeout_sec=1)`:
  - **Windows**: usare `threading.Timer` (non `signal.SIGALRM` che non esiste su Windows)
  - Timeout → return lista vuota + log warning `"regex_timeout"`
  - Alternativa: usare libreria `regex` con `timeout` parameter se disponibile

### 5.2 Canonicalize Text
- [ ] Implementare `canonicalize_text(text: str, keep_audit: bool = True, remove_quotes: bool = True, remove_signatures: bool = True) -> Tuple[str, List[RemovedSection]]`:
  - **Step 1**: Normalize line endings `\r\n` → `\n`, `\r` → `\n`
  - **Step 2**: Unicode normalization NFC (`unicodedata.normalize('NFC', text)`) — **mitigazione BUG-007**
  - **Step 3**: Normalizzare Unicode whitespace (category 'Z' → space ASCII)
  - **Step 4**: Per ogni pattern compilato (in ordine deterministico):
    - Filtrare per flags `remove_quotes`/`remove_signatures`
    - `finditer()` → creare `RemovedSection` con `content_preview[:100]`, `confidence=0.95`
    - `re.sub(pattern, '\n', text)` per rimuovere
  - **Step 5**: Cleanup finale: `re.sub(r' {2,}', ' ', text)`, `re.sub(r'\n{3,}', '\n\n', text)`, `.strip()`
  - Return `(testo_canonico, lista_removed_sections)`

### 5.3 Canonicalize Subject
- [ ] Implementare `canonicalize_subject(subject: str) -> str`:
  - Return `""` se subject vuoto/None
  - Loop ricorsivo per rimuovere prefissi `RE:`, `FW:`, `FWD:`, `R:`, `I:` (case insensitive) fino a stabilizzazione
  - Lowercase
  - Strip whitespace

### 5.4 Test canonicalization (`tests/test_canonicalization.py`)
- [ ] **Determinismo**: stesso input → stesso output su 10 run consecutivi
- [ ] **Idempotenza** (hypothesis): `canonicalize_text(canonicalize_text(x)[0])[0] == canonicalize_text(x)[0]`
- [ ] Test rimozione quote standard (`> testo`) — verificare `RemovedSection.type == "quote_standard"`
- [ ] Test rimozione reply header italiano (`Il giorno ... ha scritto:`)
- [ ] Test rimozione reply header inglese (`On ... wrote:`)
- [ ] Test rimozione reply header Outlook (`Da:...Inviato:...A:...Oggetto:`)
- [ ] Test rimozione firma (`--`)
- [ ] Test rimozione disclaimer confidenziale
- [ ] Test rimozione chiusure formali (`Cordiali saluti`, `Distinti saluti`)
- [ ] Test rimozione forward marker (EN e IT)
- [ ] Test audit trail: `RemovedSection` contiene `span_start`, `span_end`, `content_preview` ≤ 100 char
- [ ] Test subject canonicalization: `"RE: FW: Fattura"` → `"fattura"`
- [ ] Test subject canonicalization multipli prefissi: `"RE: RE: RE: test"` → `"test"`
- [ ] Test subject vuoto → `""`
- [ ] Test Unicode whitespace normalization (non-breaking space `\u00A0`, em space `\u2003` → space)
- [ ] Test regex timeout: input con `.{100000}` non causa hang (termina entro 2s)
- [ ] Test flags: `remove_quotes=False` → quote preservate, `remove_signatures=False` → firme preservate

---

## FASE 6: PII DETECTION & REDACTION (`src/pii_detection.py`)

**Status**: 🔴

### 6.1 Regex Patterns
- [ ] Definire `PII_REGEX_PATTERNS: Dict[str, str]`:
  - `"EMAIL"`: `r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'`
  - `"PHONE_IT"`: pattern verbose per mobile (`3XX...`) e fisso (`0X...`) con prefisso `+39` opzionale
  - `"PIVA"`: `r'\b(?:IT\s?)?[0-9]{11}\b'`
  - `"CF"`: `r'\b[A-Z]{6}[0-9]{2}[A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z]\b'`
  - `"IBAN"`: `r'\bIT\d{2}[A-Z]\d{10}[0-9A-Z]{12}\b'`
- [ ] Definire `BUSINESS_WHITELIST: List[str]`:
  - `r'\b(?:fattura|contratto|ordine|pratica)\s*(?:n\.?|num\.?)?\s*\d+\b'`
- [ ] Compilare pattern a livello di modulo: `_COMPILED_PII` dict e `_COMPILED_WHITELIST` regex

### 6.2 Classe PIIDetector
- [ ] **`__init__(self, pii_salt: str)`**:
  - Salvare `self.pii_salt`
  - Caricare modello spaCy: `spacy.load("it_core_news_lg")`
  - Impostare `nlp.max_length = 2_000_000`
  - Assegnare regex compilati e whitelist compilata
  - Log info: modello caricato, versione

- [ ] **`detect_pii_regex(self, text: str) -> List[PIIRedaction]`**:
  - Per ogni `(pii_type, regex)` in compiled patterns:
    - Per ogni match `regex.finditer(text)`:
      - Check whitelist: se `whitelist_regex.search(match.group())` → skip
      - Hash: `sha256((matched_text + self.pii_salt).encode('utf-8')).hexdigest()[:16]`
      - Creare `PIIRedaction(type=pii_type, original_hash=hash, redacted=f"[PII_{pii_type}]", span_start, span_end, confidence=0.95, detection_method="regex")`
  - Return lista redactions

- [ ] **`detect_pii_ner(self, text: str, confidence_threshold: float = 0.75) -> List[PIIRedaction]`**:
  - **Truncation safe** (**BUG-006**): se `len(text) > 500_000` → troncare + log warning `"text_truncated_for_ner"`
  - `doc = self.nlp(text)`
  - Per ogni `ent in doc.ents`:
    - Solo `ent.label_` in `["PER", "PERSON", "ORG"]`
    - **Anti-false-positive**: skip se `len(ent.text) < 3`, skip titoli (`"sig"`, `"dott"`, `"ing"`, `"avv"`, `"dr"`, `"prof"`)
    - Hash con salt
    - Tipo: `"NAME"` se PER/PERSON, `"ORG"` se ORG
    - `PIIRedaction(..., confidence=0.80, detection_method="ner")`

- [ ] **`merge_redactions(self, redactions: List[PIIRedaction]) -> List[PIIRedaction]`**:
  - Sort per `(span_start, -span_end, method_priority)`
  - Priority: `regex=0 > ner=1 > hybrid=2`
  - Per ogni redaction: check overlap con merged list
  - Overlap: regex vince su NER; a parità, longest span vince; a parità, higher confidence vince
  - Return sorted per `span_start`

- [ ] **`_overlaps(self, r1, r2) -> bool`**: check se due span si sovrappongono

- [ ] **`apply_redactions(self, text: str, redactions: List[PIIRedaction]) -> str`**:
  - Sort redactions in reverse order per `span_start` (preserva indici)
  - Per ogni redaction: `text = text[:start] + redaction.redacted + text[end:]`

- [ ] **`detect_and_redact(self, text: str) -> Tuple[str, List[PIIRedaction]]`**:
  - `regex_redactions = self.detect_pii_regex(text)`
  - `ner_redactions = self.detect_pii_ner(text)`
  - `merged = self.merge_redactions(regex_redactions + ner_redactions)`
  - `redacted_text = self.apply_redactions(text, merged)`
  - Return `(redacted_text, merged)`

### 6.3 Header PII Redaction
- [ ] Implementare `redact_headers_pii(headers: Dict[str, str], pii_detector: PIIDetector) -> Dict[str, str]`:
  - Headers target per redaction completa: `from`, `to`, `cc`, `bcc`, `reply-to`, `sender`
  - `subject`: redatta PII generici
  - Altri header: preservare invariati

### 6.4 Test PII detection (`tests/test_pii_detection.py`)
- [ ] **Fixture**: `pii_detector = PIIDetector(pii_salt="test-salt-deterministic-123")`
- [ ] Test redaction email: `"mario.rossi@example.com"` → `"[PII_EMAIL]"`
- [ ] Test redaction telefono mobile: `"+39 333 1234567"` → `"[PII_PHONE_IT]"`
- [ ] Test redaction telefono fisso: `"02 12345678"` → `"[PII_PHONE_IT]"`
- [ ] Test redaction Codice Fiscale: `"RSSMRA80A01H501X"` → `"[PII_CF]"`
- [ ] Test redaction P.IVA: `"IT12345678901"` → `"[PII_PIVA]"`
- [ ] Test redaction IBAN: `"IT60X0542811101000000123456"` → `"[PII_IBAN]"`
- [ ] Test NER: nomi propri italiani riconosciuti (`"Mario Rossi"`)
- [ ] Test NER: organizzazioni riconosciute
- [ ] Test **whitelist**: `"fattura n. 12345"` → `"12345"` NON redatto
- [ ] Test **merge overlap**: regex ha priorità su NER per stessa porzione testo
- [ ] Test **merge**: longest span vince a parità detection method
- [ ] Test **apply_redactions**: indici preservati (sostituzione da fine a inizio)
- [ ] Test **hash deterministico**: stesso `(testo + salt)` → stesso hash su più run
- [ ] Test **anti-false-positive**: `"sig"`, `"dott"` non redatti come nomi
- [ ] Test **anti-false-positive**: nomi < 3 char non redatti
- [ ] Test **header redaction**: `from` contiene `[PII_EMAIL]`, `subject` contiene PII redatti
- [ ] Test **truncation safe NER**: testo >500KB troncato senza crash
- [ ] Test **golden dataset NER** (**BUG-004**/regression): 10 frasi → entità attese stabili

---

## FASE 7: ORCHESTRAZIONE PREPROCESSING (`src/preprocessing.py`)

**Status**: 🔴

### 7.1 Funzione principale
- [ ] Implementare `preprocess_email(input_email: InputEmail, config: Optional[PreprocessingConfig] = None, raw_bytes: Optional[bytes] = None) -> EmailDocument`:
  - **Step 1**: `config = config or get_config()`
  - **Step 2**: `start_time = time.perf_counter()`
  - **Step 3**: Log info `"preprocessing_started"` con `uid`, `mailbox`, `size`
  - **Pipeline**:
    1. Parse headers: `parse_headers_rfc5322(input_email.headers)` → `headers_canonical`
    2. Extract body: `extract_body_parts_from_truncated(input_email.body_text, input_email.body_html, raw_bytes or input_email.raw_bytes)` → `(text_plain, text_html)`
    3. HTML→text: `html_to_text_robust(text_html)` se text_html non vuoto → `text_from_html`
    4. Merge body: `merge_body_parts(text_plain, text_from_html)` → `body_merged`
    5. Canonicalize body: `canonicalize_text(body_merged, keep_audit=True)` → `(body_canonical, removed_sections)`
    6. Canonicalize subject: `canonicalize_subject(input_email.subject)` → `subject_canonical`
    7. PII detection: creare `PIIDetector(config.pii_salt)` (o riusare singleton)
       - Body: `pii_detector.detect_and_redact(body_canonical)` → `(body_redacted, body_pii)`
       - Headers: `redact_headers_pii(headers_canonical, pii_detector)` → `headers_redacted`
       - Subject: `pii_detector.detect_and_redact(subject_canonical)` → `(subject_redacted, subject_pii)`
    8. Hash body originale: `sha256(body_merged.encode()).hexdigest()` — **MAI** store il plaintext
    9. Build `EmailDocument` con tutti i campi + `processing_duration_ms` + `processing_timestamp` ISO8601
  - **Error handling**: catch `Exception` → log error con `exc_info=True`, raise `PreprocessingError`

### 7.2 Ottimizzazione: PIIDetector singleton
- [ ] Considerare lazy loading di `PIIDetector` (carica modello spaCy una volta, riusa):
  - Variable modulo-level `_pii_detector = None` con getter thread-safe
  - Oppure passare `PIIDetector` come parametro opzionale

### 7.3 Test preprocessing end-to-end (`tests/test_preprocessing.py`)
- [ ] Test pipeline completa con email sample (tutti i campi)
- [ ] Test `uid` e metadata originali preservati nell'output
- [ ] Test PII redatti: `from_addr_redacted` contiene `[PII_EMAIL]`
- [ ] Test quote rimosse: `body_text_canonical` non contiene testo quotato
- [ ] Test `pipeline_version` correttamente popolata con versioni da config
- [ ] Test `processing_duration_ms > 0`
- [ ] Test `processing_timestamp` è ISO8601 valido
- [ ] Test `body_original_hash` è sha256 hex di 64 char
- [ ] Test con email minimalista (campi opzionali vuoti/default)
- [ ] Test con `raw_bytes` (full MIME parse path)
- [ ] Test con email senza HTML (solo plain)
- [ ] Test con email senza plain (solo HTML)
- [ ] Test con body troncato (warning loggato)

---

## FASE 8: ERROR HANDLING & RESILIENZA (`src/error_handling.py`)

**Status**: 🔴

### 8.1 Graceful Degradation
- [ ] Implementare `preprocess_email_safe(input_email: InputEmail, config: Optional[PreprocessingConfig] = None) -> EmailDocument`:
  - `try`: `preprocess_email(input_email, config)` — pipeline completa
  - `except PIIDetectionError`: log warning → `preprocess_email_regex_only(input_email, config)` — solo regex PII, no NER
  - `except CanonicalizationError`: log warning → `preprocess_email_no_canon(input_email, config)` — body raw, PII applicati
  - `except Exception`: log error → `create_minimal_document(input_email)` — documento minimale di emergenza

- [ ] Implementare `preprocess_email_regex_only(input_email, config)`:
  - Come `preprocess_email` ma NER disabilitato
  - Solo regex PII detection
  - Flag/log che indica degradation

- [ ] Implementare `preprocess_email_no_canon(input_email, config)`:
  - Come `preprocess_email` ma no canonicalization
  - Body raw (con PII redatto)
  - Flag/log che indica degradation

- [ ] Implementare `create_minimal_document(input_email) -> EmailDocument`:
  - Campi identificativi dall'input
  - `from_addr_redacted = "[ERROR]"`, `to_addrs_redacted = ["[ERROR]"]`
  - `body_text_canonical = input_email.body_text[:500]` (troncato per sicurezza)
  - `body_original_hash = "error"`, `pipeline_version = PipelineVersion()` (default)
  - Tutti i metadati processing a zero/vuoti

### 8.2 Test error handling (`tests/test_error_handling.py`)
- [ ] Test fallback regex-only quando NER fallisce (mock NER exception)
- [ ] Test fallback raw body quando canonicalization fallisce (mock exception)
- [ ] Test documento minimale su failure totale
- [ ] Test che `preprocess_email_safe` **MAI** raise exception (qualsiasi input)
- [ ] Test property-based (hypothesis): input random → `preprocess_email_safe` non crasha
- [ ] Test logging: errori loggati con struttura corretta (event, uid, error, exc_info)

---

## FASE 9: SERVIZIO FASTAPI & HEALTH CHECKS (`src/main.py`)

**Status**: 🔴

### 9.1 FastAPI Application
- [ ] Creare `src/main.py` con app FastAPI
- [ ] Endpoint `POST /preprocess`: accetta `InputEmail` JSON, ritorna `EmailDocument` JSON
- [ ] Endpoint `POST /preprocess/safe`: versione con graceful degradation
- [ ] Startup event: caricare modello spaCy, setup logging, validare config

### 9.2 Health Checks
- [ ] `GET /health` — liveness probe:
  - Return `{"status": "healthy"}`, status 200
- [ ] `GET /health/ready` — readiness probe:
  - Check NER model caricato (`nlp("test")` senza errori)
  - Check config caricata (`config.pii_salt` presente)
  - Return `{"status": "ready"|"not_ready", "checks": {...}}`
  - Se non ready → status 503

### 9.3 Observability
- [ ] Middleware per logging request/response (senza PII)
- [ ] Metriche esposte per scraping Prometheus (opzionale, può essere aggiunto dopo):
  - `preprocessing_duration_seconds` (histogram)
  - `preprocessing_errors_total` (counter by error_type)
  - `preprocessing_emails_total` (counter by status)
  - `pii_detections_total` (counter by pii_type, method)
  - `removed_sections_total` (counter by section_type)

### 9.4 Test servizio (`tests/test_main.py`)
- [ ] Test `GET /health` → 200, `{"status": "healthy"}`
- [ ] Test `GET /health/ready` → 200 quando tutto ok
- [ ] Test `POST /preprocess` con payload valido → EmailDocument JSON
- [ ] Test `POST /preprocess` con payload invalido → 422
- [ ] Test `POST /preprocess/safe` non crasha su input malformato

---

## FASE 10: SAMPLE DATA & DOCUMENTAZIONE

**Status**: 🔴

### 10.1 Email di esempio (`examples/sample_emails/`)
- [ ] `simple_plain.eml` — Email semplice plain text senza HTML
- [ ] `multipart_html.eml` — Email multipart con text/plain e text/html
- [ ] `with_pii.eml` — Email con PII fittizi: email, telefono, CF, IBAN, nomi
- [ ] `reply_chain.eml` — Email con quote/reply chain (italiano, header Outlook)
- [ ] `disclaimer_signature.eml` — Email con disclaimer confidenziale e firma aziendale

### 10.2 Notebook demo (`examples/notebooks/`)
- [ ] Creare `preprocessing_demo.ipynb`:
  - Import del modulo
  - Setup environment (salt da env)
  - Processing di una singola email da file .eml
  - Visualizzazione `EmailDocument` output
  - Highlight PII redatti e sezioni rimosse
  - Benchmark di latenza su batch di email

### 10.3 README.md (root del progetto)
- [ ] Sezione **Overview**: descrizione layer, posizione pipeline, architettura modulare
- [ ] Sezione **Setup**:
  - Prerequisiti (Python 3.11+)
  - Creazione venv e installazione dipendenze
  - Download modello spaCy
  - Configurazione env vars (con link a `.env.example`)
- [ ] Sezione **Usage**:
  - Esempio import e chiamata `preprocess_email()`
  - Esempio avvio server FastAPI
  - Esempio curl endpoint
- [ ] Sezione **API Reference**: link alla documentazione auto-generata o descrizione endpoint
- [ ] Sezione **Testing**: comandi per eseguire test, coverage, linting
- [ ] Sezione **Architecture**: diagramma moduli e data flow
- [ ] Sezione **Troubleshooting**: errori comuni (PII_SALT mancante, modello spaCy non trovato)

### 10.4 File `.env.example`
- [ ] Documentare ogni variabile con commento descrittivo e valore di esempio

---

## FASE 11: QUALITY ASSURANCE FINALE

**Status**: 🔴

### 11.1 Coverage e Type Checking
- [ ] `pytest tests/ --cov=src --cov-report=html` → copertura > 90%
- [ ] `mypy src/ --strict` → zero errori
- [ ] `flake8 src/` → zero violazioni
- [ ] `black src/ tests/ --check` → tutto formattato

### 11.2 Performance Benchmark (`tests/test_performance.py`)
- [ ] Creare fixture con 100 email sample di dimensioni variabili (small, medium, large)
- [ ] Test latenza p50 < 500ms
- [ ] Test latenza p99 < 2s
- [ ] Verificare memory footprint ragionevole (no OOM su email grandi)

### 11.3 Security Audit
- [ ] Grep codebase: `PII_SALT` non appare MAI come valore hardcoded (solo come riferimento env var)
- [ ] Grep codebase: nessun `print()` con dati sensibili
- [ ] Grep log output: nessun PII in plaintext nei log
- [ ] Verificare `body_original_hash` è hash, mai il body plaintext
- [ ] Eseguire `bandit -r src/` per vulnerabilità Python
- [ ] Eseguire `pip audit` o `safety check` per CVE nelle dipendenze

### 11.4 Property-Based Tests con Hypothesis
- [ ] **Idempotenza canonicalization**: `f(f(x)) == f(x)` per testi random
- [ ] **Determinismo pipeline**: `preprocess(x) == preprocess(x)` per email random
- [ ] **No PII leak**: output di `detect_and_redact(text)` non contiene match dei pattern PII regex

### 11.5 Golden Dataset NER (**mitigazione BUG-004**)
- [ ] Creare `tests/golden_ner_dataset.json` con 10-20 frasi italiane e entità attese:
  - `"Mario Rossi ha chiamato ieri"` → `[("Mario Rossi", "PER")]`
  - `"La società Acme S.r.l. di Milano"` → `[("Acme S.r.l.", "ORG"), ("Milano", "LOC")]`
  - etc.
- [ ] Test regression: entità estratte == entità attese; se drift → fail con messaggio chiaro

---

## FASE 12: DEPLOYMENT PREPARATION (OPZIONALE — POST-MVP)

**Status**: 🔴 (opzionale)

### 12.1 Dockerfile
- [ ] Creare `Dockerfile` multi-stage (build + runtime)
- [ ] Pre-installare modello spaCy nella immagine
- [ ] Health check integrato nel container
- [ ] Non esporre PII_SALT nel Dockerfile (solo env var a runtime)

### 12.2 Kubernetes Manifests
- [ ] `k8s/deployment.yaml` con:
  - 3 repliche, risorse (512Mi-1Gi RAM, 500m-1000m CPU)
  - Secret reference per `PREPROCESSING_PII_SALT`
  - Liveness e readiness probes verso `/health` e `/health/ready`
- [ ] `k8s/service.yaml`
- [ ] `k8s/secret.yaml` (template, non con valore reale)

### 12.3 Monitoring & Alerting
- [ ] Creare `monitoring/alerts.yaml` con regole Prometheus:
  - `HighErrorRate`: `rate(errors[5m]) > 0.01` → critical
  - `PIILeakDetected`: `increase(pii_failures[1h]) > 10` → critical
  - `HighLatency`: `p99 > 2s per 10m` → warning
  - `MemoryUsageHigh`: `resident > 500MB per 5m` → warning
  - `NERModelUnavailable`: health check down → critical

---

## RIEPILOGO BUGS DA RISOLVERE

| ID | Priorità | Descrizione | Fase di risoluzione | Status |
|----|----------|-------------|---------------------|--------|
| BUG-001 | 🔴 P0 | Body troncato da Ingestion → supporto `raw_bytes` opzionale | Fase 1 (modelli) + Fase 4 (parsing) | 🔴 |
| BUG-002 | 🔴 P0 | ReDoS vulnerability regex → bounded quantifiers + timeout | Fase 5 (canonicalization) | 🔴 |
| BUG-003 | 🔴 P0 | PII_SALT hardcoded → obbligatorio da env var | Fase 2 (config) | 🔴 |
| BUG-004 | 🟠 P1 | NER non-determinismo cross-environment → golden dataset | Fase 11 (QA) | 🔴 |
| BUG-005 | 🟠 P1 | Singleton config non thread-safe → `@lru_cache` | Fase 2 (config) | 🔴 |
| BUG-006 | 🟠 P1 | Memory leak NER su testi lunghi → truncation 500KB | Fase 6 (PII detection) | 🔴 |
| BUG-007 | 🟡 P2 | Unicode whitespace non-determinismo → NFC + category Z | Fase 5 (canonicalization) | 🔴 |
| BUG-008 | 🟡 P2 | HTML entity decoding mancante → `html.unescape()` | Fase 4 (parsing) | 🔴 |

---

## FEATURE AVANZATE (POST-MVP)

| ID | Feature | Descrizione | Priorità |
|----|---------|-------------|----------|
| ENH-001 | Regex compiled cache | `@lru_cache` per pattern compilati | Integrato in Fase 5 |
| ENH-002 | Async preprocessing | `preprocess_email_async()` con `run_in_executor` | Bassa |
| FEAT-001 | Circuit breaker NER | `pybreaker` per fallback automatico se NER fail rate alto | Media |
| FEAT-002 | Distributed tracing | OpenTelemetry spans per ogni step pipeline | Bassa |
| FEAT-003 | A/B testing framework | Routing % traffic su nuove versioni canonic/PII | Bassa |

---

## STRUTTURA FILE FINALE ATTESA
