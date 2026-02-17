"""
FastAPI service for Email Preprocessing Layer

Endpoints:
- POST /preprocess - Full preprocessing pipeline
- POST /preprocess/safe - Safe preprocessing with fallbacks
- POST /preprocess/batch - Batch processing
- GET /health - Basic health check
- GET /health/ready - Readiness check (checks dependencies)
- GET /metrics - Prometheus metrics (optional)
"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import time
import structlog

from src.models import InputEmail, EmailDocument
from src.preprocessing import preprocess_email, preprocess_email_batch
from src.error_handling import preprocess_email_safe, is_email_processable
from src.config import get_config


logger = structlog.get_logger(__name__)

# FastAPI app
app = FastAPI(
    title="Email Preprocessing Service",
    description="GDPR-compliant email preprocessing for Thread Classificator Mail",
    version="1.0.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# REQUEST/RESPONSE MODELS
# ==============================================================================


class PreprocessRequest(BaseModel):
    """Single email preprocessing request"""

    message_id: str = Field(..., description="Unique message ID")
    headers_raw: str = Field(..., description="Raw headers (RFC5322 format)")
    body_text: str = Field(..., description="Email body text (may be truncated)")
    raw_bytes: Optional[str] = Field(
        None, description="Base64-encoded raw email (for full MIME parse)"
    )

    def to_input_email(self) -> InputEmail:
        """Convert to InputEmail model"""
        import base64

        raw_bytes_decoded = None
        if self.raw_bytes:
            try:
                raw_bytes_decoded = base64.b64decode(self.raw_bytes)
            except Exception as e:
                logger.warning("raw_bytes_decode_failed", error=str(e))

        return InputEmail(
            message_id=self.message_id,
            headers_raw=self.headers_raw,
            body_text=self.body_text,
            raw_bytes=raw_bytes_decoded,
        )


class PreprocessResponse(BaseModel):
    """Preprocessing response"""

    message_id: str
    headers: Dict[str, str]
    body_text: str
    body_hash: str
    pii_redactions_count: int
    removed_sections_count: int
    pipeline_version: str
    processing_time_ms: float


class BatchPreprocessRequest(BaseModel):
    """Batch processing request"""

    emails: List[PreprocessRequest] = Field(..., max_items=100)  # Limit batch size


class BatchPreprocessResponse(BaseModel):
    """Batch processing response"""

    results: List[PreprocessResponse]
    total_count: int
    success_count: int
    processing_time_ms: float


class HealthResponse(BaseModel):
    """Health check response"""

    status: str
    version: str
    config_loaded: bool


class ReadinessResponse(BaseModel):
    """Readiness check response"""

    status: str
    checks: Dict[str, bool]
    message: Optional[str] = None


# ==============================================================================
# MIDDLEWARE
# ==============================================================================


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests with timing"""
    start_time = time.time()

    # Process request
    response = await call_next(request)

    # Log
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration_ms, 2),
    )

    return response


# ==============================================================================
# ENDPOINTS
# ==============================================================================


@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint"""
    return {
        "service": "Email Preprocessing Layer",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.post("/preprocess", response_model=PreprocessResponse, status_code=status.HTTP_200_OK)
async def preprocess_endpoint(request: PreprocessRequest):
    """
    Preprocess single email (full pipeline).

    Raises HTTP 400 if email is invalid, HTTP 500 if processing fails.
    """
    start_time = time.time()

    # Validate
    input_email = request.to_input_email()
    is_valid, error = is_email_processable(input_email)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid email: {error}")

    # Process
    try:
        result = preprocess_email(input_email)
    except Exception as e:
        logger.error("preprocessing_failed", error=str(e), message_id=request.message_id)
        raise HTTPException(status_code=500, detail=f"Preprocessing failed: {str(e)}")

    # Build response
    processing_time_ms = (time.time() - start_time) * 1000

    return PreprocessResponse(
        message_id=result.message_id,
        headers=result.headers,
        body_text=result.body_text,
        body_hash=result.body_hash,
        pii_redactions_count=len(result.pii_redactions),
        removed_sections_count=len(result.removed_sections),
        pipeline_version=result.pipeline_version.version,
        processing_time_ms=round(processing_time_ms, 2),
    )


@app.post("/preprocess/safe", response_model=PreprocessResponse, status_code=status.HTTP_200_OK)
async def preprocess_safe_endpoint(request: PreprocessRequest):
    """
    Preprocess single email (safe mode with fallbacks).

    Never fails - always returns a document (possibly degraded).
    """
    start_time = time.time()

    # Convert
    input_email = request.to_input_email()

    # Process (safe - never raises)
    result = preprocess_email_safe(input_email)

    # Build response
    processing_time_ms = (time.time() - start_time) * 1000

    return PreprocessResponse(
        message_id=result.message_id,
        headers=result.headers,
        body_text=result.body_text,
        body_hash=result.body_hash,
        pii_redactions_count=len(result.pii_redactions),
        removed_sections_count=len(result.removed_sections),
        pipeline_version=result.pipeline_version.version,
        processing_time_ms=round(processing_time_ms, 2),
    )


@app.post("/preprocess/batch", response_model=BatchPreprocessResponse, status_code=status.HTTP_200_OK)
async def preprocess_batch_endpoint(request: BatchPreprocessRequest):
    """
    Preprocess multiple emails in batch.

    Returns results for all emails (failed items get error documents).
    """
    start_time = time.time()

    # Validate batch size
    if len(request.emails) > 100:
        raise HTTPException(status_code=400, detail="Batch size exceeds limit of 100")

    # Convert to InputEmails
    input_emails = [req.to_input_email() for req in request.emails]

    # Process batch
    results = preprocess_email_batch(input_emails)

    # Build responses
    responses = []
    for result in results:
        responses.append(
            PreprocessResponse(
                message_id=result.message_id,
                headers=result.headers,
                body_text=result.body_text,
                body_hash=result.body_hash,
                pii_redactions_count=len(result.pii_redactions),
                removed_sections_count=len(result.removed_sections),
                pipeline_version=result.pipeline_version.version,
                processing_time_ms=0,  # Individual timing not tracked in batch
            )
        )

    processing_time_ms = (time.time() - start_time) * 1000

    return BatchPreprocessResponse(
        results=responses,
        total_count=len(results),
        success_count=len([r for r in results if "error" not in r.pipeline_version.version.lower()]),
        processing_time_ms=round(processing_time_ms, 2),
    )


@app.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check():
    """
    Basic health check.

    Returns 200 if service is alive.
    """
    try:
        config = get_config()
        config_loaded = True
    except Exception:
        config_loaded = False

    return HealthResponse(
        status="healthy" if config_loaded else "degraded",
        version="1.0.0",
        config_loaded=config_loaded,
    )


@app.get("/health/ready", response_model=ReadinessResponse, status_code=status.HTTP_200_OK)
async def readiness_check():
    """
    Readiness check - verifies dependencies.

    Checks:
    - Config loaded
    - PII detector available
    
    Returns 200 if ready, 503 if not ready.
    """
    checks = {}
    
    # Check config
    try:
        get_config()
        checks["config"] = True
    except Exception as e:
        logger.error("readiness_check_config_failed", error=str(e))
        checks["config"] = False
    
    # Check PII detector
    try:
        from src.pii_detection import get_pii_detector
        get_pii_detector()
        checks["pii_detector"] = True
    except Exception as e:
        logger.error("readiness_check_pii_detector_failed", error=str(e))
        checks["pii_detector"] = False
    
    # Determine status
    all_checks_passed = all(checks.values())
    status_code = status.HTTP_200_OK if all_checks_passed else status.HTTP_503_SERVICE_UNAVAILABLE
    
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_checks_passed else "not_ready",
            "checks": checks,
            "message": None if all_checks_passed else "Some dependencies unavailable",
        },
    )


# ==============================================================================
# ERROR HANDLERS
# ==============================================================================


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions"""
    logger.error("unhandled_exception", error=str(exc), path=request.url.path)
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "path": request.url.path,
        },
    )


# ==============================================================================
# STARTUP/SHUTDOWN
# ==============================================================================


@app.on_event("startup")
async def startup_event():
    """Service startup"""
    logger.info("service_starting", version="1.0.0")
    
    # Pre-load config
    try:
        config = get_config()
        logger.info("config_loaded", pipeline_version=config.pipeline_version)
    except Exception as e:
        logger.error("config_load_failed", error=str(e))
    
    # Pre-load PII detector (optional, for faster first request)
    # try:
    #     from src.pii_detection import get_pii_detector
    #     get_pii_detector()
    #     logger.info("pii_detector_preloaded")
    # except Exception as e:
    #     logger.warning("pii_detector_preload_failed", error=str(e))
    
    logger.info("service_started")


@app.on_event("shutdown")
async def shutdown_event():
    """Service shutdown"""
    logger.info("service_shutting_down")


# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,  # Disable in production
    )
