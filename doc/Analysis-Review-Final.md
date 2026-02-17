# ANALISI COMPLETA LAYER PREPROCESSING & CANONICALIZATION
## Thread Classificator Mail - Review Architetturale & Security Audit

**Data**: 17 Febbraio 2026  
**Reviewer**: System Architect  
**Versione Layer**: 1.3.0  
**Status**: Pre-Implementation Review

---

## EXECUTIVE SUMMARY

Il layer **Preprocessing & Canonicalization** è stato specificato con approccio **production-ready** considerando:

✅ **Determinismo statistico** garantito tramite versioning rigoroso  
✅ **GDPR compliance** con PII redaction by design  
✅ **Error handling** robusto con graceful degradation  
✅ **Observability** completa (metriche, logging strutturato, health checks)  
✅ **Testing strategy** comprensiva (unit, integration, performance, property-based)

**Raccomandazione**: **IMPLEMENTABILE** con le mitigazioni identificate nei bug logici (sezione 3).

---

## 1. VALUTAZIONE CONTESTO E COERENZA

### 1.1 Allineamento con Brainstorming v2/v3

| Requisito Brainstorming | Status Specifica | Note |
|------------------------|------------------|------|
| **Determinismo statistico** | ✅ Completo | PipelineVersion dataclass con tutti i campi richiesti |
| **Privacy by design (PII)** | ✅ Completo | Hash + redaction + audit trail |
| **Versioning componenti** | ✅ Completo | parser, canonicalization, NER, PII versions |
| **Audit trail** | ✅ Completo | RemovedSection + PIIRedaction tracking |
| **RFC5322/MIME parsing** | ✅ Completo | Header unfold, charset decode, multipart |
| **Canonicalization** | ✅ Completo | Quote/sig removal con pattern italiani |
| **Logging dettagliato** | ✅ Completo | Structured logging JSON |
| **Metriche valutazione** | ⚠️ Parziale | Metriche layer definite, ma integrazione con evaluate_multilabel_topics() non esplicita |

**Gap identificati**:
- Brainstorming v3 menziona **drift detection**: non implementato in questo layer (corretto, spetta a layer successivi)
- Brainstorming v2 include **stoplist versionata**: menzionata ma non implementata (corretto, spetta a Candidate Generation layer)

### 1.2 Compatibilità Input/Output

**Input (da Ingestion Layer)**:
- ✅ Struttura `InputEmail` definita correttamente
- ⚠️ **CRITICO**: `body_text` e `body_html` sono **troncati** (2000/500 char)
- ✅ Mitigazione proposta: supporto `raw_bytes` opzionale per full parse

**Output (a Candidate Generation Layer)**:
- ✅ `EmailDocument` include tutti i campi necessari
- ✅ `body_text_canonical` pronto per tokenizzazione downstream
- ✅ `pii_entities` e `removed_sections` per audit
- ✅ `pipeline_version` per determinismo

**Interfaccia layer successivi**:
```python
# Candidate Generation consumerà:
EmailDocument.body_text_canonical  # Testo pulito, PII-free
EmailDocument.subject_canonical     # Subject normalizzato
EmailDocument.pipeline_version      # Per tracking versione
```

---

## 2. ANALISI ARCHITETTURALE

### 2.1 Design Patterns Applicati

| Pattern | Dove | Motivazione |
|---------|------|-------------|
| **Singleton Config** | `get_config()` | Evita reload ripetuti |
| **Strategy Pattern** | `PIIDetector` (regex + NER) | Flessibilità detection method |
| **Template Method** | `preprocess_email()` | Pipeline fissa, step configurabili |
| **Decorator Pattern** | `preprocess_email_safe()` | Graceful degradation wrapping |
| **Builder Pattern** | `EmailDocument` construction | Costruzione incrementale output |

**Valutazione**: ✅ Design patterns appropriati per caso d'uso production.

### 2.2 Separation of Concerns

```
┌─────────────────────────────────────────────────────────┐
│ preprocessing.py           (orchestrazione)             │
├─────────────────────────────────────────────────────────┤
│ parsing.py                 (RFC5322/MIME)               │
│ canonicalization.py        (text cleaning)              │
│ pii_detection.py           (privacy)                    │
│ error_handling.py          (resilience)                 │
│ logging_setup.py           (observability)              │
│ config.py                  (configuration)              │
└─────────────────────────────────────────────────────────┘
```

**Valutazione**: ✅ Moduli ben separati, responsabilità singole, low coupling.

### 2.3 Dependency Management

**External Dependencies**:
```
beautifulsoup4==4.12.3   # HTML parsing (stable, mature)
lxml==5.1.0              # Fast XML/HTML parser
html2text==2020.1.16     # HTML→text (deterministic version)
spacy==3.7.4             # NER (pinned version)
pydantic==2.6.1          # Config validation (modern)
structlog==24.1.0        # Structured logging (best-in-class)
```

**Valutazione**: ✅ Dependencies mature, versioni pinnate, no vulnerabilità note.

**Raccomandazione**: Aggiungi `poetry.lock` o `requirements.lock` per reproducibilità totale.

---

## 3. BUG LOGICI E PROBLEMI DI SICUREZZA

### 3.1 CRITICI (P0 - Blockers)

#### 🔴 BUG-001: Body Troncato da Ingestion Layer

**Descrizione**: `InputEmail.body_text` limitato a 2000 char perde contenuto.

**Impatto**:
- Email lunghe (>2KB plain text) processate parzialmente
- PII detection incompleta (PII oltre char 2000 non redatti)
- Classificazione downstream degradata (loss informazioni)

**Root cause**: Design decision del layer ingestion (performance?)

**Mitigazioni proposte**:

**Opzione A (RACCOMANDATO)**: Modificare Ingestion Layer
```python
@dataclass
class InputEmail:
    body_text: str        # FULL body (no truncation)
    body_html: str        # FULL body HTML
    # Rimuovi troncamenti
```

**Opzione B**: Supportare `raw_bytes` opzionali
```python
@dataclass
class InputEmail:
    body_text: str               # Preview troncato (backward compat)
    body_html: str               # Preview troncato
    raw_bytes: Optional[bytes]   # NUOVO: raw email per full parse
```

```python
def preprocess_email(input_email: InputEmail, ...) -> EmailDocument:
    if input_email.raw_bytes:
        # Full MIME parse
        msg = BytesParser(policy=policy.default).parsebytes(input_email.raw_bytes)
        body_text, body_html = extract_full_body(msg)
    else:
        # Fallback a preview (log warning)
        logger.warning("body_truncated_using_preview", uid=input_email.uid)
        body_text = input_email.body_text
        body_html = input_email.body_html
```

**Opzione C**: Re-fetch da IMAP quando truncated
```python
if len(input_email.body_text) >= 1999:  # Probabilmente troncato
    raw_email = imap_client.fetch_full(input_email.uid, input_email.mailbox)
    # Re-process completo
```

**Raccomandazione**: **Opzione A** (modificare ingestion), fallback **Opzione B** se ingestion non modificabile a breve.

**Status**: ⚠️ **DA RISOLVERE** prima del deploy production.

---

#### 🔴 BUG-002: ReDoS Vulnerability nei Regex Pattern

**Descrizione**: Alcuni pattern regex possono causare catastrophic backtracking su input malicious.

**Pattern vulnerabili**:
```python
# ❌ POTENZIALMENTE VULNERABILE
(r'(?is)Il giorno.*ha scritto:', 'reply_header_it')  # .* può backtrack

# ❌ VULNERABILE
(r'(?is)Questo messaggio.*confidenziale.*', 'disclaimer')  # .* nested
```

**Impatto**:
- DoS attack: email crafted con pattern patologici causa hang (CPU 100%)
- Timeout processing, email non processate

**Attack vector**:
```
Subject: Il giorno AAAAAAA...AAAA (50KB di A) ha scritto: test
# Regex .* backtrack esponenziale
```

**Mitigazione**:

1. **Timeout protezione**:
```python
import signal

def safe_regex_finditer(pattern, text, timeout_sec=1):
    """Regex con timeout"""
    def timeout_handler(signum, frame):
        raise TimeoutError("Regex timeout")
    
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_sec)
    
    try:
        matches = list(pattern.finditer(text))
        signal.alarm(0)
        return matches
    except TimeoutError:
        signal.alarm(0)
        logger.warning("regex_timeout", pattern=pattern.pattern)
        return []
```

2. **Pattern refactoring** (preferito):
```python
# ✅ SAFE - bounded quantifier
(r'(?is)Il giorno.{1,200}ha scritto:', 'reply_header_it')

# ✅ SAFE - non-greedy + bounded
(r'(?is)Questo messaggio.{1,500}?confidenziale', 'disclaimer')
```

**Raccomandazione**: Applicare **entrambe** le mitigazioni (defense in depth).

**Status**: ⚠️ **DA RISOLVERE** prima del deploy production.

---

#### 🔴 BUG-003: PII_SALT Hardcoded in Defaults

**Descrizione**: Codice specifica default hardcoded per `PII_SALT`.

```python
# ❌ VULNERABILE
PII_SALT = "thread-classificator-2026-pii-salt"
```

**Impatto**:
- Se codice committato con default → tutti gli hash reversibili
- Attacker può rainbow-table attack con salt noto
- Violazione GDPR (pseudonimizzazione inefficace)

**Mitigazione**:

```python
# ✅ CORRETTO
import os

PII_SALT = os.environ.get("PREPROCESSING_PII_SALT")
if not PII_SALT:
    raise ValueError(
        "PREPROCESSING_PII_SALT environment variable MUST be set. "
        "Generate with: python -c 'import secrets; print(secrets.token_hex(32))'"
    )
```

**Deployment checklist**:
```bash
# Kubernetes Secret
kubectl create secret generic preprocessing-secrets \
  --from-literal=pii-salt="$(openssl rand -hex 32)"

# Docker Compose
echo "PREPROCESSING_PII_SALT=$(openssl rand -hex 32)" >> .env
```

**Raccomandazione**: Rimuovi **tutti** i default hardcoded per salt/secrets.

**Status**: ⚠️ **DA RISOLVERE** prima del deploy production.

---

### 3.2 ALTA PRIORITÀ (P1 - Must Fix)

#### 🟠 BUG-004: NER Model Non-Determinism Across Environments

**Descrizione**: spaCy NER può variare tra env/hardware diversi.

**Impatto**:
- Test locali passano, CI/prod falliscono
- Determinismo non garantito (violazione invariante chiave)

**Cause**:
- CPU vs GPU processing (diversi path computazionali)
- Floating point precision differences
- spaCy versione micro differente

**Mitigazione**:

1. **Pin esatto modello + versione spaCy**:
```txt
# requirements.txt
spacy==3.7.4
https://github.com/explosion/spacy-models/releases/download/it_core_news_lg-3.7.0/it_core_news_lg-3.7.0-py3-none-any.whl
```

2. **Seed deterministico** (se disponibile):
```python
import random
import numpy as np

random.seed(42)
np.random.seed(42)
# spaCy non espone seed globale, ma pin dipendenze
```

3. **Regression test con golden dataset**:
```python
def test_ner_stability_golden():
    """NER deve produrre output noti su dataset golden"""
    text = "Mario Rossi ha chiamato da Milano."
    
    doc = nlp(text)
    entities = [(e.text, e.label_) for e in doc.ents]
    
    # Golden output noto
    expected = [("Mario Rossi", "PER"), ("Milano", "LOC")]
    
    assert entities == expected, f"NER drift detected: {entities} != {expected}"
```

**Raccomandazione**: Include golden dataset in test suite, alert se drift.

**Status**: ⚠️ **DA IMPLEMENTARE** in test suite.

---

#### 🟠 BUG-005: Race Condition in Singleton Config

**Descrizione**: `get_config()` singleton non thread-safe.

```python
# ❌ NOT THREAD-SAFE
_config = None

def get_config():
    global _config
    if _config is None:
        _config = PreprocessingConfig()  # Race condition qui
    return _config
```

**Impatto**:
- Con multiprocessing/threading: doppia inizializzazione
- Config inconsistente tra thread

**Mitigazione**:

```python
# ✅ THREAD-SAFE con lock
import threading

_config = None
_config_lock = threading.Lock()

def get_config():
    global _config
    if _config is None:
        with _config_lock:
            if _config is None:  # Double-check locking
                _config = PreprocessingConfig()
    return _config
```

**Alternativa**: Usa `@lru_cache` (built-in thread-safe):
```python
from functools import lru_cache

@lru_cache(maxsize=1)
def get_config():
    return PreprocessingConfig()
```

**Raccomandazione**: Implementare **lru_cache** (più semplice, zero overhead).

**Status**: ⚠️ **DA RISOLVERE** per production.

---

#### 🟠 BUG-006: Memory Leak su Email Molto Lunghe

**Descrizione**: spaCy NER con `nlp.max_length = 2_000_000` può causare OOM.

**Impatto**:
- Email >1MB causa memory spike
- Container kill (OOMKilled in Kubernetes)

**Mitigazione**:

1. **Truncate intelligente**:
```python
def detect_pii_ner_safe(self, text: str, max_length: int = 500_000) -> List[PIIRedaction]:
    """NER con truncation safe"""
    if len(text) > max_length:
        logger.warning(
            "text_truncated_for_ner",
            original_length=len(text),
            truncated_to=max_length
        )
        text = text[:max_length]
    
    # NER processing
    doc = self.nlp(text)
    # ...
```

2. **Streaming processing** (advanced):
```python
# spaCy pipe per batch processing
docs = list(nlp.pipe([text], batch_size=1000, n_process=1))
```

3. **Memory limit monitoring**:
```python
import resource

def check_memory_usage():
    """Check memory usage"""
    max_mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024  # MB
    if max_mem > 400:  # 400MB threshold
        logger.warning("high_memory_usage", memory_mb=max_mem)
```

**Raccomandazione**: Implementare **truncation safe** + monitoring.

**Status**: ⚠️ **DA IMPLEMENTARE** per production.

---

### 3.3 MEDIA PRIORITÀ (P2 - Should Fix)

#### 🟡 BUG-007: Whitespace Non-Determinism in Edge Cases

**Descrizione**: Unicode whitespace non gestiti esplicitamente.

**Esempio**:
```python
# Unicode whitespace vari
text = "Hello\u00A0world\u2003test"  # \u00A0 = non-breaking space, \u2003 = em space

# re.sub(r'\s+', ' ', text) li gestisce, ma behavior potrebbe variare
```

**Mitigazione**:

```python
import unicodedata

def normalize_whitespace_unicode(text: str) -> str:
    """Normalizza tutti i whitespace Unicode"""
    # Step 1: Unicode normalization (NFC)
    text = unicodedata.normalize('NFC', text)
    
    # Step 2: Sostituisci tutti Unicode whitespace con space
    # Category 'Z' = separator (Zs=space, Zl=line, Zp=paragraph)
    text = ''.join(
        ' ' if unicodedata.category(char).startswith('Z') else char
        for char in text
    )
    
    # Step 3: Cleanup
    text = re.sub(r' +', ' ', text)
    
    return text
```

**Raccomandazione**: Applicare in `canonicalize_text()`.

**Status**: ⚠️ Nice-to-have per robustezza.

---

#### 🟡 BUG-008: HTML Entity Decoding Mancante

**Descrizione**: HTML entities (`&lt;`, `&amp;`, etc.) non decodificati prima di PII detection.

**Esempio**:
```python
html = "Contact: mario&#46;rossi&#64;example&#46;com"
# Senza decode: "mario&#46;rossi&#64;example&#46;com" non match email regex
```

**Mitigazione**:

```python
import html

def html_to_text_robust(html_text: str) -> str:
    """HTML→text con entity decoding"""
    # Step 1: Decode HTML entities
    html_text = html.unescape(html_text)
    
    # Step 2: BeautifulSoup parsing
    soup = BeautifulSoup(html_text, "lxml")
    # ...
```

**Raccomandazione**: Aggiungere `html.unescape()` in `html_to_text_robust()`.

**Status**: ⚠️ Fix semplice, alta ROI.

---

### 3.4 BASSA PRIORITÀ (P3 - Nice to Have)

#### 🟢 ENHANCEMENT-001: Caching Compiled Regex

**Descrizione**: Regex pattern compilati ad ogni call.

**Ottimizzazione**:

```python
import functools

@functools.lru_cache(maxsize=128)
def get_compiled_pattern(pattern: str, flags: int) -> re.Pattern:
    """Cache compiled regex patterns"""
    return re.compile(pattern, flags)

# Usage
pattern = get_compiled_pattern(r'(?m)^>.*$', re.IGNORECASE)
```

**Beneficio**: -10-15% latency su pattern-heavy operations.

---

#### 🟢 ENHANCEMENT-002: Async Processing Support

**Descrizione**: Supportare `async def preprocess_email_async()`.

**Beneficio**: Throughput +2-3x con async I/O (se ingestion layer async).

**Implementazione**:

```python
async def preprocess_email_async(
    input_email: InputEmail,
    config: Optional[PreprocessingConfig] = None
) -> EmailDocument:
    """Async preprocessing con offload CPU-bound a thread pool"""
    loop = asyncio.get_event_loop()
    
    # Offload CPU-bound sync function
    output = await loop.run_in_executor(
        None,  # Default ThreadPoolExecutor
        preprocess_email,
        input_email,
        config
    )
    
    return output
```

---

## 4. FEATURE PRODUCTION-READY

### 4.1 Implementate ✅

| Feature | Status | Note |
|---------|--------|------|
| **Configuration Management** | ✅ | Pydantic config con env vars |
| **Structured Logging** | ✅ | structlog JSON format |
| **Error Handling** | ✅ | Graceful degradation, custom exceptions |
| **Health Checks** | ✅ | `/health` e `/health/ready` endpoints |
| **Metrics Exposition** | ✅ | Prometheus format definito |
| **Type Hints** | ✅ | Completo con mypy --strict |
| **Docstrings** | ✅ | Google style |
| **Test Suite** | ✅ | Unit, integration, performance |

### 4.2 Da Implementare (Raccomandazioni)

#### 🔵 FEATURE-001: Circuit Breaker per NER

**Problema**: Se spaCy NER ha failure rate alto → rallenta tutto.

**Soluzione**:

```python
from pybreaker import CircuitBreaker

ner_breaker = CircuitBreaker(
    fail_max=5,           # Apri dopo 5 failure
    timeout_duration=60   # Riprova dopo 60s
)

class PIIDetector:
    @ner_breaker
    def detect_pii_ner(self, text: str) -> List[PIIRedaction]:
        """NER con circuit breaker"""
        # Se circuit open → raise CircuitBreakerError
        # Fallback a regex-only in error_handling.py
        ...
```

**Beneficio**: Sistema degrada gracefully invece di crashare.

---

#### 🔵 FEATURE-002: Distributed Tracing

**Problema**: Debug latency issues in pipeline complessa.

**Soluzione**: OpenTelemetry tracing.

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def preprocess_email(input_email: InputEmail) -> EmailDocument:
    with tracer.start_as_current_span("preprocessing") as span:
        span.set_attribute("email.uid", input_email.uid)
        span.set_attribute("email.size", input_email.size)
        
        with tracer.start_as_current_span("pii_detection"):
            # PII detection
            ...
        
        with tracer.start_as_current_span("canonicalization"):
            # Canonicalization
            ...
```

**Beneficio**: Visualizzazione latency breakdown in Jaeger/Zipkin.

---

#### 🔵 FEATURE-003: A/B Testing Framework

**Problema**: Testare nuove versioni canonicalization/PII senza impatto prod.

**Soluzione**:

```python
def preprocess_email_with_ab_test(
    input_email: InputEmail,
    experiment_id: Optional[str] = None
) -> EmailDocument:
    """Preprocessing con A/B test support"""
    
    # Determina variant (10% traffic a variant B)
    if experiment_id and random.random() < 0.1:
        # Variant B: nuova versione
        config = PreprocessingConfig(
            canonicalization_version="1.4.0-beta",
            pii_ner_confidence_threshold=0.80  # Più strict
        )
        output = preprocess_email(input_email, config)
        output.metadata["experiment"] = "canonicalization_v1.4_beta"
    else:
        # Control: versione corrente
        output = preprocess_email(input_email)
        output.metadata["experiment"] = "control"
    
    return output
```

**Beneficio**: Deploy sicuro di nuove versioni.

---

## 5. ANALISI SECURITY

### 5.1 Threat Model

| Threat | Likelihood | Impact | Mitigation |
|--------|-----------|--------|------------|
| **PII Leak** | Alta | Critico | Hash + redaction + audit log |
| **ReDoS Attack** | Media | Alto | Regex timeout + pattern refactoring |
| **Memory DoS** | Media | Alto | Truncation + memory monitoring |
| **Salt Exposure** | Bassa | Critico | Env var only, never hardcode |
| **Injection Attack** | Bassa | Medio | Input validation, no eval/exec |

### 5.2 GDPR Compliance Checklist

- [x] **Art. 5(1)(c) - Minimizzazione**: Solo PII necessari processati
- [x] **Art. 25 - Privacy by Design**: PII redaction integrata
- [x] **Art. 32 - Pseudonimizzazione**: Hash con salt
- [x] **Art. 30 - Audit Trail**: Logging ogni processing
- [x] **Art. 17 - Diritto all'oblio**: Hash permettono deletion tracking
- [ ] ⚠️ **Art. 33 - Data Breach Notification**: Processo da definire (fuori scope layer)
- [ ] ⚠️ **Art. 13 - Informativa**: Privacy policy da fornire a clienti (fuori scope layer)

**Status**: ✅ Layer compliant, processi organizzativi da completare.

### 5.3 Security Best Practices Applied

✅ **Principle of Least Privilege**: Solo dati necessari in memoria  
✅ **Defense in Depth**: Multiple layer PII protection (regex + NER + hash)  
✅ **Secure by Default**: No PII in log, hash-only storage  
✅ **Input Validation**: Pydantic config validation  
✅ **Error Handling**: No stack trace con dati sensibili in prod  
✅ **Dependency Security**: Pinned versions, no known CVE  

---

## 6. RACCOMANDAZIONI FINALI

### 6.1 PRE-DEPLOYMENT CHECKLIST

**BLOCKERS (P0) - MUST FIX**:
- [ ] **BUG-001**: Risolvi body troncato (Opzione A o B)
- [ ] **BUG-002**: Applica ReDoS mitigations (timeout + pattern refactor)
- [ ] **BUG-003**: Rimuovi PII_SALT hardcoded

**CRITICAL (P1) - STRONGLY RECOMMENDED**:
- [ ] **BUG-004**: Golden dataset NER stability test
- [ ] **BUG-005**: Thread-safe singleton config
- [ ] **BUG-006**: Memory-safe NER con truncation

**IMPORTANT (P2)**:
- [ ] **BUG-007**: Unicode whitespace normalization
- [ ] **BUG-008**: HTML entity decoding

**ENHANCEMENTS**:
- [ ] **FEATURE-001**: Circuit breaker NER
- [ ] **FEATURE-002**: OpenTelemetry tracing
- [ ] **FEATURE-003**: A/B testing framework

### 6.2 ROADMAP POST-DEPLOYMENT

**Month 1 (MVP)**:
- Deploy con P0 fixed
- Monitoring dashboards setup
- Alert thresholds tuning

**Month 2 (Hardening)**:
- P1 bugs fixed
- Performance optimization (regex caching, etc.)
- Load testing (10K email/hour)

**Month 3 (Advanced)**:
- Circuit breaker implementation
- Distributed tracing integration
- A/B testing framework

### 6.3 SUCCESS METRICS

**Pre-Deployment**:
- ✅ All P0 bugs fixed
- ✅ Test coverage >90%
- ✅ Latency p50 <500ms, p99 <2s
- ✅ Zero PII leak in test suite
- ✅ Security audit passed

**Post-Deployment (Week 1)**:
- Error rate <0.1%
- Latency p50 <300ms (target con optimization)
- Zero GDPR incidents
- PII detection recall >95%

**Post-Deployment (Month 1)**:
- Throughput 100+ email/s sustained
- Uptime >99.9%
- Memory usage stable <500MB/worker
- Zero security incidents

---

## 7. VALUTAZIONE FINALE

### 7.1 SCORES

| Categoria | Score | Rationale |
|-----------|-------|-----------|
| **Architettura** | 9/10 | Design pulito, patterns appropriati. -1 per body troncato issue |
| **Security** | 8/10 | GDPR compliant, PII protection solida. -2 per ReDoS risk e salt default |
| **Reliability** | 9/10 | Error handling robusto, graceful degradation. -1 per memory leak risk |
| **Performance** | 8/10 | Latency targets realistici. -2 per possibili optimization (regex cache, async) |
| **Testability** | 10/10 | Test strategy comprensiva, coverage target >90% |
| **Observability** | 9/10 | Logging strutturato, metriche definite. -1 per mancanza tracing |
| **Maintainability** | 9/10 | Codice pulito, documentazione completa. -1 per complessità NER debugging |

**Overall Score**: **8.9/10** ⭐⭐⭐⭐

### 7.2 DECISIONE FINALE

**✅ GO FOR IMPLEMENTATION** con condizioni:

1. **MUST FIX P0 bugs** (BUG-001, BUG-002, BUG-003) prima di merge
2. **STRONGLY RECOMMENDED P1 bugs** (BUG-004, BUG-005, BUG-006) prima di production deploy
3. **Coordina con Ingestion Layer** per risoluzione body troncato
4. **Security review** da team security prima di production

**Confidence Level**: **Alta** 🟢

Il layer è ben progettato e production-ready con le mitigazioni identificate. Design deterministico, GDPR compliant, e testabile. Bug identificati sono mitigabili con effort ragionevole.

---

## APPENDICE A: TEST MATRIX

| Test Type | Coverage Target | Tools | Execution |
|-----------|----------------|-------|-----------|
| **Unit Test** | >90% | pytest, pytest-cov | CI ogni commit |
| **Integration Test** | Key paths | pytest | CI ogni commit |
| **Property-Based Test** | Idempotence, determinism | hypothesis | CI nightly |
| **Performance Test** | Latency <500ms p50 | pytest-benchmark | CI weekly |
| **Security Test** | OWASP Top 10 | bandit, safety | CI weekly |
| **Load Test** | 100 email/s sustained | locust | Staging pre-deploy |
| **Regression Test** | Golden dataset NER | Custom | CI ogni commit |

---

## APPENDICE B: MONITORING ALERTS

```yaml
# alerts.yaml
groups:
- name: preprocessing_critical
  rules:
  - alert: HighErrorRate
    expr: rate(preprocessing_errors_total[5m]) > 0.01
    for: 5m
    severity: critical
    
  - alert: PIILeakDetected
    expr: increase(pii_detection_failures_total[1h]) > 10
    for: 1m
    severity: critical
    
  - alert: HighLatency
    expr: histogram_quantile(0.99, preprocessing_duration_seconds) > 2
    for: 10m
    severity: warning
    
  - alert: MemoryUsageHigh
    expr: process_resident_memory_bytes > 500_000_000
    for: 5m
    severity: warning
    
  - alert: NERModelUnavailable
    expr: up{job="ner-health-check"} == 0
    for: 1m
    severity: critical
```

---

**END OF ANALYSIS**

**Next Actions**:
1. Share con coding agent per implementation
2. Review con team security
3. Sync con Ingestion Layer team per body troncato
4. Setup CI/CD pipeline con test matrix
5. Prepare production deployment plan

**Approved By**: System Architect  
**Date**: 2026-02-17  
**Version**: 1.0
