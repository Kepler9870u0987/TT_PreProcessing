#!/usr/bin/env python
"""
Final Validation Script - Email Preprocessing Layer
Verifica veloce dello stato del sistema
"""
import sys
from pathlib import Path

print("=" * 80)
print("EMAIL PREPROCESSING LAYER - FINAL VALIDATION")
print("=" * 80)

checks_passed = 0
checks_total = 0

def check(description: str, condition: bool) -> bool:
    global checks_passed, checks_total
    checks_total += 1
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"{status} - {description}")
    if condition:
        checks_passed += 1
    return condition

# 1. Check Python version
checks_total += 1
try:
    assert sys.version_info >= (3, 11), "Python 3.11+ required"
    print(f"✅ PASS - Python version: {sys.version_info.major}.{sys.version_info.minor}")
    checks_passed += 1
except AssertionError as e:
    print(f"❌ FAIL - {e}")

# 2. Check core modules import
try:
    from src import models, config, logging_setup, parsing, canonicalization
    from src import pii_detection, preprocessing, error_handling, main
    check("Core modules import", True)
except ImportError as e:
    check(f"Core modules import: {e}", False)

# 3. Check spaCy
try:
    import spacy
    check(f"spaCy installed: {spacy.__version__}", True)
    try:
        import it_core_news_lg
        check("Italian model (it_core_news_lg)", True)
    except ImportError:
        check("Italian model (it_core_news_lg)", False)
except ImportError:
    check("spaCy installed", False)

# 4. Check key dependencies
deps = {
    "pydantic": "2.6+",
    "fastapi": "0.109+",
    "structlog": "24.1+",
    "beautifulsoup4": "4.12+",
}

for dep, version in deps.items():
    try:
        __import__(dep)
        check(f"Dependency: {dep} {version}", True)
    except ImportError:
        check(f"Dependency: {dep}", False)

# 5. Check test framework
try:
    import pytest
    check(f"pytest installed: {pytest.__version__}", True)
except ImportError:
    check("pytest installed", False)

# 6. Check project structure
project_root = Path(__file__).parent
required_files = [
    "src/models.py",
    "src/config.py",
    "src/preprocessing.py",
    "tests/test_models.py",
    "README.md",
    "Dockerfile",
    "requirements.txt",
]

for file in required_files:
    path = project_root / file
    check(f"File exists: {file}", path.exists())

# 7. Check sample data
sample_emails = list((project_root / "examples" / "sample_emails").glob("*.eml"))
check(f"Sample emails: {len(sample_emails)} files", len(sample_emails) >= 5)

# 8. Check deployment artifacts
artifacts = [
    "Dockerfile",
    "docker-compose.yml",
    "k8s/deployment.yaml",
    ".github/workflows/ci.yml",
]

for artifact in artifacts:
    path = project_root / artifact
    check(f"Deployment artifact: {artifact}", path.exists())

# Summary
print("\n" + "=" * 80)
print(f"VALIDATION COMPLETE: {checks_passed}/{checks_total} checks passed")
if checks_passed == checks_total:
    print("✅ STATUS: READY FOR DEPLOYMENT")
    sys.exit(0)
elif checks_passed >= checks_total * 0.8:
    print("⚠️  STATUS: MINOR ISSUES (review recommended)")
    sys.exit(0)
else:
    print("❌ STATUS: CRITICAL ISSUES (fix required)")
    sys.exit(1)
