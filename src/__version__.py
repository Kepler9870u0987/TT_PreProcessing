"""
Version information for Email Preprocessing Layer.

This file is automatically read by:
- pyproject.toml (single source of truth)
- src/preprocessing.py (pipeline version tracking)
- src/main.py (FastAPI app version)
"""

__version__ = "2.0.0"
__version_info__ = tuple(int(x) for x in __version__.split("."))

# Component versions (must match requirements.txt)
PARSER_VERSION = "email-parser-1.3.0"
CANONICALIZATION_VERSION = "1.3.0"
NER_MODEL_VERSION = "it_core_news_lg-3.8.2"
PII_REDACTION_VERSION = "1.0.0"
