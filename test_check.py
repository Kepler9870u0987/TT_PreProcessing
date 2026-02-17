#!/usr/bin/env python
"""Simple test validation"""
import sys
print("Python version:", sys.version)
print("Working directory:", sys.path[0])

try:
    import pytest
    print(f"pytest version: {pytest.__version__}")
except ImportError as e:
    print(f"ERROR importing pytest: {e}")
    sys.exit(1)

print("\nRunning single test...")
result = pytest.main(["-v", "tests/test_models.py::test_pipeline_version_creation"])
print(f"Exit code: {result}")
