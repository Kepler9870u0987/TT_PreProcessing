"""
Setup script for Email Preprocessing Layer
"""

from setuptools import setup, find_packages
import os

# Read version from __init__.py
version = {}
with open(os.path.join("src", "__init__.py")) as f:
    exec(f.read(), version)

# Read README for long description
try:
    with open("README.md", "r", encoding="utf-8") as f:
        long_description = f.read()
except FileNotFoundError:
    long_description = "Email Preprocessing & Canonicalization Layer for Thread Classificator Mail"

setup(
    name="email-preprocessing-layer",
    version=version.get("__version__", "2.0.0"),
    author="System Architecture Team",
    description="RFC5322/MIME parsing, canonicalization, and PII redaction for email processing pipeline",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/your-org/TT_PreProcessing",
    packages=find_packages(exclude=["tests", "tests.*", "examples"]),
    python_requires=">=3.11",
    install_requires=[
        "beautifulsoup4==4.12.3",
        "lxml==5.1.0",
        "html2text==2020.1.16",
        "spacy==3.7.4",
        "pydantic==2.6.1",
        "pydantic-settings==2.1.0",
        "python-dotenv==1.0.1",
        "structlog==24.1.0",
        "fastapi>=0.109.0",
        "uvicorn[standard]>=0.27.0",
        "python-dateutil>=2.8.2",
    ],
    extras_require={
        "dev": [
            "pytest==8.0.0",
            "pytest-cov==4.1.0",
            "pytest-benchmark==4.0.0",
            "pytest-asyncio==0.23.5",
            "hypothesis==6.98.0",
            "httpx==0.26.0",
            "black==24.1.1",
            "mypy==1.8.0",
            "flake8==7.0.0",
            "isort==5.13.2",
            "bandit==1.7.7",
            "pip-audit==2.7.0",
        ]
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Communications :: Email",
        "Topic :: Text Processing",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    keywords="email preprocessing canonicalization pii-redaction gdpr mime rfc5322",
    project_urls={
        "Documentation": "https://github.com/your-org/TT_PreProcessing/doc",
        "Source": "https://github.com/your-org/TT_PreProcessing",
        "Tracker": "https://github.com/your-org/TT_PreProcessing/issues",
    },
)
