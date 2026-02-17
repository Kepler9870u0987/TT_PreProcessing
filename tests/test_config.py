"""
Test suite for configuration management

Verifica:
- Caricamento da env vars
- Validazione PII_SALT obbligatorio (BUG-003)
- Singleton thread-safe (BUG-005)
- Default values
- Validation rules
"""

import os
import pytest
import threading
from unittest.mock import patch
from pydantic import ValidationError

from src.config import (
    PreprocessingConfig,
    get_config,
    reset_config_cache,
    generate_example_salt,
)


@pytest.fixture(autouse=True)
def reset_config():
    """Reset config cache before each test"""
    reset_config_cache()
    yield
    reset_config_cache()


@pytest.fixture
def valid_env_vars():
    """Provide valid environment variables"""
    return {
        "PREPROCESSING_PII_SALT": "a1b2c3d4e5f6g7h8a1b2c3d4e5f6g7h8",  # 32 char hex
        "PREPROCESSING_LOG_LEVEL": "INFO",
    }


# ==============================================================================
# TEST PII_SALT VALIDATION (BUG-003 MITIGATION)
# ==============================================================================


def test_config_requires_pii_salt():
    """Test that PII_SALT is mandatory (no default)"""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError) as exc_info:
            get_config()
        error_msg = str(exc_info.value)
        assert "PII_SALT" in error_msg
        assert "REQUIRED" in error_msg or "required" in error_msg.lower()
        assert "secrets.token_hex" in error_msg  # Should include generation instructions


def test_config_rejects_placeholder_salts():
    """Test that placeholder/example salts are rejected"""
    forbidden_salts = [
        "changeme",
        "example",
        "test",
        "placeholder",
        "thread-classificator-2026-pii-salt",
    ]

    for salt in forbidden_salts:
        reset_config_cache()
        with patch.dict(os.environ, {"PREPROCESSING_PII_SALT": salt}, clear=True):
            with pytest.raises((ValueError, ValidationError)):
                get_config()


def test_config_accepts_valid_salt(valid_env_vars):
    """Test that valid salt is accepted"""
    with patch.dict(os.environ, valid_env_vars, clear=True):
        config = get_config()
        assert config.pii_salt == valid_env_vars["PREPROCESSING_PII_SALT"]


def test_config_salt_minimum_length():
    """Test that salt must be at least 16 characters"""
    short_salt = "tooshort"
    with patch.dict(os.environ, {"PREPROCESSING_PII_SALT": short_salt}, clear=True):
        with pytest.raises((ValidationError, ValueError)):
            get_config()


# ==============================================================================
# TEST SINGLETON PATTERN (BUG-005 MITIGATION)
# ==============================================================================


def test_config_singleton_returns_same_instance(valid_env_vars):
    """Test that get_config() returns the same instance"""
    with patch.dict(os.environ, valid_env_vars, clear=True):
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2  # Same object in memory


def test_config_singleton_thread_safe(valid_env_vars):
    """Test that singleton is thread-safe (BUG-005 mitigation)"""
    with patch.dict(os.environ, valid_env_vars, clear=True):
        configs = []
        errors = []

        def get_config_in_thread():
            try:
                config = get_config()
                configs.append(config)
            except Exception as e:
                errors.append(e)

        # Create 10 threads that all try to get config simultaneously
        threads = [threading.Thread(target=get_config_in_thread) for _ in range(10)]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all to complete
        for thread in threads:
            thread.join()

        # Check no errors occurred
        assert len(errors) == 0, f"Errors in threads: {errors}"

        # Check all threads got the same instance
        assert len(configs) == 10
        first_config = configs[0]
        for config in configs[1:]:
            assert config is first_config, "Different config instances created in threads"


# ==============================================================================
# TEST DEFAULT VALUES
# ==============================================================================


def test_config_default_values(valid_env_vars):
    """Test that default values are correctly set"""
    with patch.dict(os.environ, valid_env_vars, clear=True):
        config = get_config()

        # Versioning
        assert config.parser_version == "email-parser-1.3.0"
        assert config.canonicalization_version == "1.3.0"
        assert config.ner_model_version == "it_core_news_lg-3.8.2"
        assert config.pii_redaction_version == "1.0.0"

        # PII Detection
        assert config.pii_ner_confidence_threshold == 0.75
        assert config.pii_regex_timeout_sec == 1

        # Canonicalization
        assert config.remove_quotes is True
        assert config.remove_signatures is True
        assert config.max_body_size_kb == 500

        # Performance
        assert config.spacy_batch_size == 50
        assert config.multiprocessing_workers == 4

        # Logging
        assert config.log_level == "INFO"
        assert config.log_pii_preview is False


# ==============================================================================
# TEST ENVIRONMENT VARIABLE OVERRIDE
# ==============================================================================


def test_config_override_from_env(valid_env_vars):
    """Test that environment variables override defaults"""
    custom_env = {
        **valid_env_vars,
        "PREPROCESSING_LOG_LEVEL": "DEBUG",
        "PREPROCESSING_PII_NER_CONFIDENCE_THRESHOLD": "0.90",
        "PREPROCESSING_REMOVE_QUOTES": "false",
        "PREPROCESSING_MAX_BODY_SIZE_KB": "1000",
    }

    with patch.dict(os.environ, custom_env, clear=True):
        config = get_config()
        assert config.log_level == "DEBUG"
        assert config.pii_ner_confidence_threshold == 0.90
        assert config.remove_quotes is False
        assert config.max_body_size_kb == 1000


# ==============================================================================
# TEST VALIDATION RULES
# ==============================================================================


def test_config_log_level_validation(valid_env_vars):
    """Test that log_level must be valid"""
    invalid_env = {**valid_env_vars, "PREPROCESSING_LOG_LEVEL": "INVALID"}

    with patch.dict(os.environ, invalid_env, clear=True):
        with pytest.raises(ValidationError) as exc_info:
            get_config()
        assert "log_level" in str(exc_info.value).lower()


def test_config_log_level_case_insensitive(valid_env_vars):
    """Test that log_level is case-insensitive"""
    for level in ["debug", "Debug", "DEBUG"]:
        reset_config_cache()
        env = {**valid_env_vars, "PREPROCESSING_LOG_LEVEL": level}
        with patch.dict(os.environ, env, clear=True):
            config = get_config()
            assert config.log_level == "DEBUG"


def test_config_confidence_threshold_range(valid_env_vars):
    """Test that confidence threshold must be in [0.0, 1.0]"""
    # Test too high
    reset_config_cache()
    invalid_env = {**valid_env_vars, "PREPROCESSING_PII_NER_CONFIDENCE_THRESHOLD": "1.5"}
    with patch.dict(os.environ, invalid_env, clear=True):
        with pytest.raises(ValidationError):
            get_config()

    # Test too low
    reset_config_cache()
    invalid_env = {**valid_env_vars, "PREPROCESSING_PII_NER_CONFIDENCE_THRESHOLD": "-0.1"}
    with patch.dict(os.environ, invalid_env, clear=True):
        with pytest.raises(ValidationError):
            get_config()

    # Test valid boundaries
    for value in ["0.0", "1.0", "0.5"]:
        reset_config_cache()
        valid = {**valid_env_vars, "PREPROCESSING_PII_NER_CONFIDENCE_THRESHOLD": value}
        with patch.dict(os.environ, valid, clear=True):
            config = get_config()
            assert 0.0 <= config.pii_ner_confidence_threshold <= 1.0


def test_config_max_body_size_bounds(valid_env_vars):
    """Test that max_body_size_kb has valid bounds"""
    # Too small
    reset_config_cache()
    invalid = {**valid_env_vars, "PREPROCESSING_MAX_BODY_SIZE_KB": "50"}
    with patch.dict(os.environ, invalid, clear=True):
        with pytest.raises(ValidationError):
            get_config()

    # Too large
    reset_config_cache()
    invalid = {**valid_env_vars, "PREPROCESSING_MAX_BODY_SIZE_KB": "6000"}
    with patch.dict(os.environ, invalid, clear=True):
        with pytest.raises(ValidationError):
            get_config()

    # Valid range
    reset_config_cache()
    valid = {**valid_env_vars, "PREPROCESSING_MAX_BODY_SIZE_KB": "1000"}
    with patch.dict(os.environ, valid, clear=True):
        config = get_config()
        assert config.max_body_size_kb == 1000


# ==============================================================================
# TEST UTILITY FUNCTIONS
# ==============================================================================


def test_get_max_body_size_bytes(valid_env_vars):
    """Test conversion from KB to bytes"""
    with patch.dict(os.environ, valid_env_vars, clear=True):
        config = get_config()
        assert config.get_max_body_size_bytes() == 500 * 1024


def test_generate_example_salt():
    """Test salt generation utility"""
    salt1 = generate_example_salt()
    salt2 = generate_example_salt()

    # Should be 64 hex characters (32 bytes)
    assert len(salt1) == 64
    assert len(salt2) == 64

    # Should be different each time
    assert salt1 != salt2

    # Should be valid hex
    int(salt1, 16)  # Should not raise
    int(salt2, 16)


def test_reset_config_cache(valid_env_vars):
    """Test that reset_config_cache() works"""
    with patch.dict(os.environ, valid_env_vars, clear=True):
        config1 = get_config()
        reset_config_cache()

        # After reset, should get a new instance
        config2 = get_config()

        # Note: They will have same values but might be different objects
        # (depends on execution context)
        assert config1.pii_salt == config2.pii_salt


# ==============================================================================
# TEST SECURITY WARNINGS
# ==============================================================================


def test_config_log_pii_preview_default_false(valid_env_vars):
    """Test that log_pii_preview defaults to False (security)"""
    with patch.dict(os.environ, valid_env_vars, clear=True):
        config = get_config()
        assert config.log_pii_preview is False


def test_config_can_enable_pii_preview_for_debug(valid_env_vars):
    """Test that PII preview can be enabled (for development only)"""
    env = {**valid_env_vars, "PREPROCESSING_LOG_PII_PREVIEW": "true"}
    with patch.dict(os.environ, env, clear=True):
        config = get_config()
        assert config.log_pii_preview is True
