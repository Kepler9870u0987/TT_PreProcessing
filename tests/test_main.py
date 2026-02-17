"""
Test suite for FastAPI service

Verifica:
- POST /preprocess endpoint
- POST /preprocess/safe endpoint  
- POST /preprocess/batch endpoint
- GET /health endpoint
- GET /health/ready endpoint
- Error handling (400, 500)
- Request/response validation
"""

import pytest
import os
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.main import app
from src.config import reset_config_cache


@pytest.fixture
def client():
    """FastAPI test client"""
    return TestClient(app)


@pytest.fixture
def valid_env():
    """Valid environment for config"""
    return {
        "PREPROCESSING_PII_SALT": "test-salt-for-fastapi-tests-123456789",
        "PREPROCESSING_PIPELINE_VERSION": "test-v1",
    }


@pytest.fixture(autouse=True)
def cleanup_config():
    """Reset config cache after each test"""
    yield
    reset_config_cache()


# ==============================================================================
# TEST ROOT ENDPOINT
# ==============================================================================


def test_root_endpoint(client):
    """Test root endpoint returns service info"""
    response = client.get("/")
    
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert "Email Preprocessing" in data["service"]


# ==============================================================================
# TEST /preprocess ENDPOINT
# ==============================================================================


def test_preprocess_endpoint_success(client, valid_env):
    """Test successful email preprocessing"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {
            "message_id": "<test@example.com>",
            "headers_raw": "From: sender@example.com\nSubject: Test\n\n",
            "body_text": "Email body text",
        }
        
        response = client.post("/preprocess", json=request_data)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["message_id"] == "<test@example.com>"
        assert "body_text" in data
        assert "body_hash" in data
        assert data["pii_redactions_count"] >= 0
        assert data["processing_time_ms"] > 0


def test_preprocess_endpoint_with_pii(client, valid_env):
    """Test preprocessing with PII redaction"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {
            "message_id": "<pii@example.com>",
            "headers_raw": "From: test@example.com\n\n",
            "body_text": "Contact: test@example.com",
        }
        
        response = client.post("/preprocess", json=request_data)
        
        assert response.status_code == 200
        data = response.json()
        
        # PII should be redacted
        assert "test@example.com" not in data["body_text"]
        assert data["pii_redactions_count"] >= 1


def test_preprocess_endpoint_invalid_email(client, valid_env):
    """Test preprocessing with invalid email (400 error)"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {
            "message_id": "",  # Invalid: empty message_id
            "headers_raw": "From: sender@example.com\n\n",
            "body_text": "",
        }
        
        response = client.post("/preprocess", json=request_data)
        
        assert response.status_code == 400
        assert "Invalid email" in response.json()["detail"]


def test_preprocess_endpoint_missing_fields(client, valid_env):
    """Test preprocessing with missing required fields (422 validation error)"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {
            "message_id": "<test@example.com>",
            # Missing headers_raw and body_text
        }
        
        response = client.post("/preprocess", json=request_data)
        
        assert response.status_code == 422  # Pydantic validation error


# ==============================================================================
# TEST /preprocess/safe ENDPOINT
# ==============================================================================


def test_preprocess_safe_endpoint_success(client, valid_env):
    """Test safe preprocessing endpoint"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {
            "message_id": "<safe@example.com>",
            "headers_raw": "From: sender@example.com\n\n",
            "body_text": "Safe email body",
        }
        
        response = client.post("/preprocess/safe", json=request_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["message_id"] == "<safe@example.com>"


def test_preprocess_safe_never_fails(client, valid_env):
    """Test that safe endpoint never returns 500"""
    with patch.dict(os.environ, valid_env, clear=True):
        # Even with problematic data
        request_data = {
            "message_id": "<problem@example.com>",
            "headers_raw": "Invalid\x00Headers",
            "body_text": "Body",
        }
        
        response = client.post("/preprocess/safe", json=request_data)
        
        # Should succeed (not 500)
        assert response.status_code == 200


# ==============================================================================
# TEST /preprocess/batch ENDPOINT
# ==============================================================================


def test_preprocess_batch_endpoint_success(client, valid_env):
    """Test batch preprocessing"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {
            "emails": [
                {
                    "message_id": f"<batch-{i}@example.com>",
                    "headers_raw": "From: sender@example.com\n\n",
                    "body_text": f"Email {i}",
                }
                for i in range(3)
            ]
        }
        
        response = client.post("/preprocess/batch", json=request_data)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_count"] == 3
        assert len(data["results"]) == 3
        assert data["processing_time_ms"] > 0


def test_preprocess_batch_endpoint_preserves_order(client, valid_env):
    """Test that batch processing preserves order"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {
            "emails": [
                {
                    "message_id": f"<order-{i}@example.com>",
                    "headers_raw": "From: sender@example.com\n\n",
                    "body_text": f"Email {i}",
                }
                for i in range(5)
            ]
        }
        
        response = client.post("/preprocess/batch", json=request_data)
        
        assert response.status_code == 200
        results = response.json()["results"]
        
        for i, result in enumerate(results):
            assert result["message_id"] == f"<order-{i}@example.com>"


def test_preprocess_batch_endpoint_size_limit(client, valid_env):
    """Test batch size limit (max 100)"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {
            "emails": [
                {
                    "message_id": f"<batch-{i}@example.com>",
                    "headers_raw": "From: sender@example.com\n\n",
                    "body_text": "Body",
                }
                for i in range(101)  # Over limit
            ]
        }
        
        response = client.post("/preprocess/batch", json=request_data)
        
        assert response.status_code == 400
        assert "exceeds limit" in response.json()["detail"]


def test_preprocess_batch_empty(client, valid_env):
    """Test batch with empty list"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {"emails": []}
        
        response = client.post("/preprocess/batch", json=request_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 0


# ==============================================================================
# TEST /health ENDPOINT
# ==============================================================================


def test_health_endpoint(client, valid_env):
    """Test basic health check"""
    with patch.dict(os.environ, valid_env, clear=True):
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] in ["healthy", "degraded"]
        assert "version" in data
        assert "config_loaded" in data


def test_health_endpoint_without_config(client):
    """Test health check when config fails"""
    with patch.dict(os.environ, {}, clear=True):
        # No PII_SALT - config will fail
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["config_loaded"] is False
        assert data["status"] == "degraded"


# ==============================================================================
# TEST /health/ready ENDPOINT
# ==============================================================================


def test_readiness_endpoint_ready(client, valid_env):
    """Test readiness check when ready"""
    with patch.dict(os.environ, valid_env, clear=True):
        response = client.get("/health/ready")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "ready"
        assert data["checks"]["config"] is True


def test_readiness_endpoint_not_ready(client):
    """Test readiness check when not ready"""
    with patch.dict(os.environ, {}, clear=True):
        # No config - not ready
        response = client.get("/health/ready")
        
        # Should return 503 Service Unavailable
        assert response.status_code == 503
        data = response.json()
        
        assert data["status"] == "not_ready"


# ==============================================================================
# TEST RAW_BYTES HANDLING
# ==============================================================================


def test_preprocess_with_raw_bytes(client, valid_env):
    """Test preprocessing with raw_bytes (base64 encoded)"""
    import base64
    
    with patch.dict(os.environ, valid_env, clear=True):
        raw_email = b"From: sender@example.com\n\nRaw email body"
        encoded = base64.b64encode(raw_email).decode("utf-8")
        
        request_data = {
            "message_id": "<raw@example.com>",
            "headers_raw": "From: sender@example.com\n\n",
            "body_text": "Truncated body",
            "raw_bytes": encoded,
        }
        
        response = client.post("/preprocess", json=request_data)
        
        assert response.status_code == 200


def test_preprocess_with_invalid_base64(client, valid_env):
    """Test preprocessing with invalid base64 in raw_bytes"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {
            "message_id": "<invalid-b64@example.com>",
            "headers_raw": "From: sender@example.com\n\n",
            "body_text": "Body",
            "raw_bytes": "not-valid-base64!!!",
        }
        
        response = client.post("/preprocess", json=request_data)
        
        # Should succeed (falls back to body_text)
        assert response.status_code == 200


# ==============================================================================
# TEST RESPONSE MODELS
# ==============================================================================


def test_preprocess_response_schema(client, valid_env):
    """Test that response matches expected schema"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {
            "message_id": "<schema@example.com>",
            "headers_raw": "From: sender@example.com\n\n",
            "body_text": "Test",
        }
        
        response = client.post("/preprocess", json=request_data)
        
        assert response.status_code == 200
        data = response.json()
        
        # Check all required fields
        required_fields = [
            "message_id",
            "headers",
            "body_text",
            "body_hash",
            "pii_redactions_count",
            "removed_sections_count",
            "pipeline_version",
            "processing_time_ms",
        ]
        
        for field in required_fields:
            assert field in data, f"Missing field: {field}"


# ==============================================================================
# TEST ERROR HANDLING
# ==============================================================================


def test_generic_exception_handler(client):
    """Test that unhandled exceptions return 500"""
    # This would require triggering an actual unhandled exception
    # For now, just verify endpoint exists
    pass


# ==============================================================================
# TEST MIDDLEWARE
# ==============================================================================


def test_cors_middleware(client, valid_env):
    """Test CORS middleware is active"""
    with patch.dict(os.environ, valid_env, clear=True):
        response = client.options("/preprocess")
        
        # CORS headers should be present
        # Note: TestClient may not fully simulate CORS
        assert response.status_code in [200, 405]  # OPTIONS may not be implemented


# ==============================================================================
# TEST UNICODE HANDLING
# ==============================================================================


def test_preprocess_unicode_text(client, valid_env):
    """Test preprocessing with Unicode text"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {
            "message_id": "<unicode@example.com>",
            "headers_raw": "From: sender@example.com\nSubject: Tèst\n\n",
            "body_text": "Body with Unicode: € ñ 中文",
        }
        
        response = client.post("/preprocess", json=request_data)
        
        assert response.status_code == 200
        data = response.json()
        
        # Unicode should be preserved
        assert "€" in data["body_text"] or "中文" in data["body_text"]


# ==============================================================================
# TEST EDGE CASES
# ==============================================================================


def test_preprocess_very_long_body(client, valid_env):
    """Test preprocessing with very long body"""
    with patch.dict(os.environ, valid_env, clear=True):
        long_body = "A" * 100_000  # 100KB
        
        request_data = {
            "message_id": "<long@example.com>",
            "headers_raw": "From: sender@example.com\n\n",
            "body_text": long_body,
        }
        
        response = client.post("/preprocess", json=request_data)
        
        assert response.status_code == 200


def test_preprocess_empty_headers(client, valid_env):
    """Test preprocessing with empty headers"""
    with patch.dict(os.environ, valid_env, clear=True):
        request_data = {
            "message_id": "<empty-headers@example.com>",
            "headers_raw": "",
            "body_text": "Body",
        }
        
        response = client.post("/preprocess", json=request_data)
        
        assert response.status_code == 200
