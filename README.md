# Email Preprocessing Layer

> GDPR-compliant email preprocessing pipeline for Thread Classificator Mail

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Overview

Email Preprocessing Layer è un microservizio di preprocessing per email utilizzato dal pipeline **Thread Classificator Mail**. Fornisce:

- **Parsing RFC5322/MIME**: Estrazione header e body da email raw
- **Canonicalization**: Rimozione quote, signature, disclaimer, boilerplate
- **PII Detection & Redaction**: Rilevamento e oscuramento PII (GDPR-compliant) tramite regex e NER
- **Determinism Guarantee**: Stesso input + stessa versione → stesso output
- **API REST**: FastAPI service con health checks e batch processing

### Key Features

✅ **GDPR Compliant**: PII hashing con salt, audit trail, no PII in logs  
✅ **Production Ready**: Error handling, graceful degradation, observability  
✅ **Deterministic**: Critical per reproducibility, backtesting, audit  
✅ **Italian-optimized**: Supporto Codice Fiscale, P.IVA, IBAN, telefoni IT  
✅ **Memory Safe**: Bug mitigations per ReDoS, memory leak, truncation  

---

## Quick Start

### Prerequisites

- **Python 3.11+**
- **pip** o **poetry**
- **spaCy model**: `it_core_news_lg` (per NER)

### Installation

```bash
# Clone repository
git clone https://github.com/your-org/email-preprocessing.git
cd email-preprocessing

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Download spaCy Italian model
python -m spacy download it_core_news_lg

# Configure environment
cp .env.example .env
# Edit .env and set PII_SALT (CRITICAL!)
```

### Configuration

Create `.env` file:

```bash
# CRITICAL: Generate secure salt for PII hashing
# Example: python -c "import secrets; print(secrets.token_hex(32))"
PREPROCESSING_PII_SALT=your-secret-salt-here-64-chars-minimum

# Pipeline version (for determinism tracking)
PREPROCESSING_PIPELINE_VERSION=1.0.0

# Optional: spaCy model path
PREPROCESSING_SPACY_MODEL=it_core_news_lg
```

**⚠️ SECURITY WARNING**: Never commit `.env` with real `PII_SALT` to git!

---

## Usage

### 1. Python Library

```python
from src.models import InputEmail
from src.preprocessing import preprocess_email

# Create input
input_email = InputEmail(
    message_id="<test@example.com>",
    headers_raw="From: mario.rossi@example.com\nSubject: Test\n\n",
    body_text="Contact me at mario.rossi@example.com",
)

# Process
result = preprocess_email(input_email)

# Output
print(result.body_text)  # "[PII_EMAIL] Contact me at [PII_EMAIL]"
print(f"Redacted {len(result.pii_redactions)} PII entries")
```

### 2. REST API

#### Start Server

```bash
# Development
uvicorn src.main:app --reload --port 8000

# Production
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
```

#### API Endpoints

**POST /preprocess** - Full preprocessing pipeline

```bash
curl -X POST http://localhost:8000/preprocess \
  -H "Content-Type: application/json" \
  -d '{
    "message_id": "<test@example.com>",
    "headers_raw": "From: sender@example.com\\nSubject: Test\\n\\n",
    "body_text": "Email body with test@example.com"
  }'
```

Response:
```json
{
  "message_id": "<test@example.com>",
  "headers": {"from": "sender@example.com", "subject": "Test"},
  "body_text": "Email body with [PII_EMAIL]",
  "body_hash": "abc123...",
  "pii_redactions_count": 1,
  "removed_sections_count": 0,
  "pipeline_version": "1.0.0",
  "processing_time_ms": 45.2
}
```

**POST /preprocess/safe** - Safe mode (never fails, fallback chain)

```bash
curl -X POST http://localhost:8000/preprocess/safe \
  -H "Content-Type: application/json" \
  -d '{...}'
```

**POST /preprocess/batch** - Batch processing (max 100 emails)

```bash
curl -X POST http://localhost:8000/preprocess/batch \
  -H "Content-Type: application/json" \
  -d '{
    "emails": [
      {"message_id": "<1@example.com>", "headers_raw": "...", "body_text": "..."},
      {"message_id": "<2@example.com>", "headers_raw": "...", "body_text": "..."}
    ]
  }'
```

**GET /health** - Health check

```bash
curl http://localhost:8000/health
# {"status": "healthy", "version": "1.0.0", "config_loaded": true}
```

**GET /health/ready** - Readiness check (dependencies)

```bash
curl http://localhost:8000/health/ready
# {"status": "ready", "checks": {"config": true, "pii_detector": true}}
```

---

## Architecture

### Pipeline Flow

```
┌─────────────┐
│ Raw Email   │
│ (RFC5322)   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Parsing   │  ← BUG-001: raw_bytes support
│  (headers,  │
│   body)     │
└──────┬──────┘
       │
       ▼
┌──────────────┐
│ Canonical-   │  ← BUG-002: ReDoS protection
│ ization      │  ← BUG-007: Unicode normalize
│ (quote/sig   │
│  removal)    │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ PII          │  ← BUG-003: PII_SALT mandatory
│ Detection    │  ← BUG-004: Golden dataset
│ (regex+NER)  │  ← BUG-006: Memory safety
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Email        │
│ Document     │  (immutable, frozen)
└──────────────┘
```

### Modules

- **models.py**: Data structures (InputEmail, EmailDocument, PIIRedaction)
- **config.py**: Configuration management (Pydantic BaseSettings)
- **logging_setup.py**: Structured logging with PII filtering
- **parsing.py**: RFC5322/MIME parsing, HTML→text conversion
- **canonicalization.py**: Text normalization, quote/signature removal
- **pii_detection.py**: PII detection (regex + spaCy NER)
- **preprocessing.py**: Main orchestration (integrates all modules)
- **error_handling.py**: Graceful degradation, fallback chain
- **main.py**: FastAPI service (REST endpoints)

---

## PII Detection

### Supported PII Types

| Type       | Description                 | Method | Example                      |
|------------|-----------------------------|--------|------------------------------|
| EMAIL      | Email address               | Regex  | `mario.rossi@example.com`    |
| PHONE_IT   | Italian phone number        | Regex  | `+39 02 12345678`            |
| CF         | Codice Fiscale              | Regex  | `RSSMRA85M01H501Z`           |
| PIVA       | Partita IVA                 | Regex  | `IT12345678901`              |
| IBAN       | IBAN                        | Regex  | `IT60X0542811101000000123456`|
| NAME       | Person name                 | NER    | `Mario Rossi`                |
| ORG        | Organization name           | NER    | `Microsoft Italia`           |

### Redaction Format

```
Original: "Contact Mario Rossi at mario.rossi@example.com"
Redacted: "Contact [PII_NAME_a1b2c3d4] at [PII_EMAIL_e5f6g7h8]"
```

Hash format: `SHA256(PII + salt)[:16]` (16 hex chars)

### Audit Trail

Each `PIIRedaction` contains:
- `type`: PII type (EMAIL, NAME, etc.)
- `hash`: SHA256 hash (for potential reverse lookup)
- `replacement`: Redaction marker
- `span_start`, `span_end`: Original position
- `confidence`: Detection confidence (0.0-1.0)
- `detection_method`: "regex" or "ner"

---

## Testing

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_preprocessing.py -v

# Run with markers
pytest -m "not slow"
```

### Test Structure

```
tests/
├── test_models.py           # 42 tests
├── test_config.py           # 29 tests
├── test_logging.py          # 15 tests
├── test_parsing.py          # 28 tests
├── test_canonicalization.py # 30+ tests (Hypothesis)
├── test_pii_detection.py    # 33 tests (Golden dataset)
├── test_preprocessing.py    # 20+ tests (End-to-end)
├── test_error_handling.py   # 25+ tests (Fallback chain)
└── test_main.py             # 30+ tests (FastAPI)
```

**Total: 250+ test functions**

---

## Bug Mitigations

### BUG-001: Body Truncated in DB
- **Solution**: `InputEmail.raw_bytes` field for full MIME parse
- **Test**: `test_parsing.py::test_extract_body_with_raw_bytes`

### BUG-002: ReDoS Vulnerability
- **Solution**: Bounded quantifiers (`.{1,200}`), `safe_regex_finditer()` with timeout
- **Test**: `test_canonicalization.py::test_safe_regex_timeout`

### BUG-003: PII_SALT Hardcoded
- **Solution**: Mandatory `pii_salt` field, validator rejecting placeholders
- **Test**: `test_config.py::test_pii_salt_mandatory`

### BUG-004: NER Non-Deterministic
- **Mitigation**: Golden dataset regression tests (10-20 samples)
- **Test**: `test_pii_detection.py::test_golden_dataset_ner_regression`

### BUG-005: Race Condition in Config
- **Solution**: `@lru_cache(maxsize=1)` singleton pattern
- **Test**: `test_config.py::test_config_singleton_thread_safe`

### BUG-006: Memory Leak with Large Emails
- **Solution**: Truncate to 500KB before NER, `nlp.max_length=2MB`
- **Test**: `test_pii_detection.py::test_ner_truncation_large_text`

### BUG-007: Unicode Whitespace Not Normalized
- **Solution**: `unicodedata.normalize('NFC')`, `_normalize_unicode_whitespace()`
- **Test**: `test_canonicalization.py::test_normalize_unicode_whitespace`

### BUG-008: HTML Entity Not Decoded
- **Solution**: `html.unescape()` before BeautifulSoup
- **Test**: `test_parsing.py::test_html_to_text_entities`

---

## Performance

### Targets

- **Latency**: p50 < 500ms, p99 < 2s
- **Throughput**: > 100 email/s (single instance)
- **Memory**: < 500MB per worker (with 500KB truncation)

### Benchmarking

```bash
# Run performance tests
pytest tests/test_performance.py -v

# Locust load testing (TODO)
locust -f tests/locustfile.py --host http://localhost:8000
```

---

## Deployment

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download it_core_news_lg

# Copy source
COPY src/ src/

# Environment
ENV PREPROCESSING_PII_SALT=""
ENV PREPROCESSING_PIPELINE_VERSION="1.0.0"

# Run
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
# Build
docker build -t email-preprocessing:latest .

# Run
docker run -p 8000:8000 \
  -e PREPROCESSING_PII_SALT="your-secret-salt" \
  email-preprocessing:latest
```

### Kubernetes

```yaml
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
        image: email-preprocessing:latest
        ports:
        - containerPort: 8000
        env:
        - name: PREPROCESSING_PII_SALT
          valueFrom:
            secretKeyRef:
              name: preprocessing-secrets
              key: pii-salt
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
```

---

## Development

### Setup Dev Environment

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Enable pre-commit hooks
pre-commit install

# Code formatting
black src/ tests/
isort src/ tests/

# Linting
flake8 src/ tests/
mypy src/ --strict

# Security audit
bandit -r src/
pip-audit
```

### Makefile Commands

```bash
make install      # Install dependencies
make test         # Run tests
make coverage     # Run tests with coverage
make format       # Format code (black + isort)
make lint         # Lint code (flake8 + mypy)
make security     # Security audit (bandit + pip-audit)
make run          # Start dev server
make clean        # Clean cache files
```

---

## Contributing

1. Fork repository
2. Create feature branch: `git checkout -b feature/my-feature`
3. Make changes and add tests
4. Run tests: `pytest`
5. Run linting: `make lint`
6. Commit: `git commit -m "Add my feature"`
7. Push: `git push origin feature/my-feature`
8. Open Pull Request

### Code Style

- **Python**: PEP 8, Black formatting
- **Docstrings**: Google style
- **Type hints**: Required for all functions
- **Test coverage**: > 90% for new code

---

## License

MIT License - see [LICENSE](LICENSE) file

---

## Support

- **Issues**: [GitHub Issues](https://github.com/your-org/email-preprocessing/issues)
- **Documentation**: [Wiki](https://github.com/your-org/email-preprocessing/wiki)
- **Email**: support@your-org.com

---

## Roadmap

### Phase 1 (Current) ✅
- [x] Core preprocessing pipeline
- [x] PII detection (regex + NER)
- [x] FastAPI service
- [x] Bug mitigations (BUG-001 to BUG-008)

### Phase 2 (Next)
- [ ] Performance optimization (async processing)
- [ ] Prometheus metrics
- [ ] OpenTelemetry tracing
- [ ] Advanced NER (custom fine-tuned model)

### Phase 3 (Future)
- [ ] Multi-language support (EN, FR, ES)
- [ ] ML-based canonicalization
- [ ] Advanced threat detection
- [ ] GraphQL API

---

## Acknowledgments

- **beautifulsoup4**: HTML parsing
- **spaCy**: NER (Italian model)
- **FastAPI**: REST API framework
- **Pydantic**: Data validation
- **structlog**: Structured logging

---

**Made with ❤️ for Thread Classificator Mail**
