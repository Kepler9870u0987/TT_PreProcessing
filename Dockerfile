# Dockerfile per Email Preprocessing Layer
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for layer caching)
COPY requirements.txt requirements-dev.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy Italian model
RUN python -m spacy download it_core_news_lg

# Copy application code
COPY src/ ./src/
COPY tests/ ./tests/
COPY pyproject.toml setup.py Makefile ./

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Environment variables (override in docker-compose or k8s)
ENV PREPROCESSING_PII_SALT=""
ENV PREPROCESSING_PIPELINE_VERSION="1.0.0"
ENV PREPROCESSING_LOG_LEVEL="INFO"

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=3)" || exit 1

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
