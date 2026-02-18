"""
Configuration management for Email Preprocessing Layer

CRITICAL SECURITY:
- BUG-003 MITIGATION: PII_SALT is MANDATORY from environment variable
- BUG-005 MITIGATION: Singleton pattern with @lru_cache for thread-safety

Usage:
    from src.config import get_config
    config = get_config()
    salt = config.pii_salt
"""

import secrets
from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class PIIMode(str, Enum):
    """PII processing mode.
    
    - redact: Detect PII and replace with placeholders (GDPR default)
    - detect_only: Detect PII and populate pii_entities, but leave text intact
    - disabled: Skip PII processing entirely (pii_entities = [])
    """
    REDACT = "redact"
    DETECT_ONLY = "detect_only"
    DISABLED = "disabled"


class PreprocessingConfig(BaseSettings):
    """
    Configuration con validazione Pydantic.
    
    Tutte le configurazioni possono essere override da variabili d'ambiente
    con prefisso PREPROCESSING_.
    
    CRITICAL: pii_salt è OBBLIGATORIO e NON ha default (GDPR compliance).
    """

    model_config = SettingsConfigDict(
        env_prefix="PREPROCESSING_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra env vars
    )

    # ==========================================================================
    # CRITICAL: PII Salt (BUG-003 MITIGATION)
    # ==========================================================================
    pii_salt: str = Field(
        ...,  # REQUIRED, no default - forces explicit configuration
        description=(
            "Salt for PII hashing (GDPR compliance). MUST be unique per environment. "
            "Generate with: python -c 'import secrets; print(secrets.token_hex(32))'"
        ),
        min_length=16,  # Minimum 16 characters for security
    )

    # ==========================================================================
    # Versioning (auto-managed)
    # ==========================================================================
    parser_version: str = "email-parser-1.3.0"
    canonicalization_version: str = "1.3.0"
    ner_model_version: str = "it_core_news_lg-3.8.2"
    pii_redaction_version: str = "1.0.0"

    # ==========================================================================
    # PII Detection Settings
    # ==========================================================================
    pii_mode: PIIMode = Field(
        default=PIIMode.REDACT,
        description=(
            "PII processing mode: "
            "'redact' = detect & replace with placeholders (GDPR default), "
            "'detect_only' = detect & populate pii_entities but leave text intact, "
            "'disabled' = skip PII processing entirely"
        ),
    )

    pii_ner_confidence_threshold: float = Field(
        default=0.75,
        description="Confidence threshold for NER-based PII detection (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )

    pii_regex_timeout_sec: int = Field(
        default=1,
        description="Timeout for regex pattern matching (prevents ReDoS attacks)",
        ge=1,
        le=10,
    )

    # ==========================================================================
    # Canonicalization Settings
    # ==========================================================================
    remove_quotes: bool = Field(default=True, description="Enable removal of email quotes and reply markers")

    remove_signatures: bool = Field(default=True, description="Enable removal of signatures and disclaimers")

    max_body_size_kb: int = Field(
        default=500,
        description="Maximum body size for NER processing (KB) - larger emails will be truncated",
        ge=100,
        le=5000,
    )

    # ==========================================================================
    # Performance Settings
    # ==========================================================================
    spacy_batch_size: int = Field(
        default=50,
        description="Batch size for spaCy NER processing",
        ge=1,
        le=1000,
    )

    multiprocessing_workers: int = Field(
        default=4,
        description="Number of worker processes for batch processing",
        ge=1,
        le=32,
    )

    # ==========================================================================
    # API & Security Settings
    # ==========================================================================
    allowed_origins: list[str] = Field(
        default=["http://localhost:8000", "http://localhost:3000"],
        description="CORS allowed origins. Use ['*'] for development only, restrict in production",
    )

    # ==========================================================================
    # Logging Settings
    # ==========================================================================
    log_level: str = Field(
        default="INFO",
        description="Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )

    log_pii_preview: bool = Field(
        default=False,
        description="WARNING: Never enable in production - may expose PII in logs",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is valid"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}, got {v}")
        return v_upper

    @field_validator("pii_salt")
    @classmethod
    def validate_pii_salt_not_example(cls, v: str) -> str:
        """
        Prevent using example/placeholder salts in production.
        
        SECURITY: Reject common placeholder values.
        """
        forbidden_values = [
            "changeme",
            "example",
            "test",
            "placeholder",
            "your-salt-here",
            "thread-classificator-2026-pii-salt",  # From spec example
        ]
        if v.lower() in forbidden_values:
            raise ValueError(
                f"PII_SALT cannot be a placeholder value. "
                f"Generate a secure salt with: python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        return v

    def get_max_body_size_bytes(self) -> int:
        """Convert max_body_size_kb to bytes"""
        return self.max_body_size_kb * 1024


@lru_cache(maxsize=1)
def get_config() -> PreprocessingConfig:
    """
    Get singleton config instance.
    
    BUG-005 MITIGATION: Uses @lru_cache for thread-safe singleton pattern.
    The cache ensures only one instance is created even with concurrent access.
    
    Returns:
        PreprocessingConfig: Singleton configuration instance
        
    Raises:
        ValidationError: If PII_SALT is missing or configuration is invalid
    """
    try:
        config = PreprocessingConfig()  # type: ignore
        return config
    except ValidationError as e:
        # Improve error message for missing PII_SALT
        errors = e.errors()
        for error in errors:
            if "pii_salt" in str(error.get("loc", [])):
                raise ValueError(
                    "\n"
                    "="*80 + "\n"
                    "CRITICAL: PII_SALT environment variable is REQUIRED but not set!\n"
                    "\n"
                    "This is mandatory for GDPR compliance and PII hashing.\n"
                    "\n"
                    "To fix:\n"
                    "  1. Generate a secure salt: python -c \"import secrets; print(secrets.token_hex(32))\"\n"
                    "  2. Set environment variable: export PREPROCESSING_PII_SALT=<generated-salt>\n"
                    "  3. Or create .env file with: PREPROCESSING_PII_SALT=<generated-salt>\n"
                    "\n"
                    "IMPORTANT: Use DIFFERENT salts for dev/staging/prod environments!\n"
                    "="*80
                ) from e
        # Re-raise original validation error for other issues
        raise


def generate_example_salt() -> str:
    """
    Generate a cryptographically secure salt for PII hashing.
    
    Used for development/testing setup.
    Returns 64-character hex string (32 bytes).
    """
    return secrets.token_hex(32)


# Convenience function for testing
def reset_config_cache() -> None:
    """
    Reset configuration cache.
    
    WARNING: Only use in tests! This clears the singleton cache.
    """
    get_config.cache_clear()
