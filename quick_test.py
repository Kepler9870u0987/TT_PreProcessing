#!/usr/bin/env python
"""Quick test runner to verify suite status"""
import subprocess
import sys

test_suites = [
    "tests/test_models.py",
    "tests/test_config.py", 
    "tests/test_logging.py",
    "tests/test_parsing.py",
    "tests/test_canonicalization.py",
    "tests/test_pii_detection.py",
    "tests/test_preprocessing.py",
    "tests/test_error_handling.py",
    "tests/test_main.py",
]

print("=" * 80)
print("RUNNING TEST SUITE")
print("=" * 80)

for suite in test_suites:
    print(f"\n🧪 Testing: {suite}")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", suite, "-v", "--tb=short"],
        capture_output=True,
        text=True,
        timeout=120
    )
    
    # Extract summary line
    lines = result.stdout.split('\n')
    for line in lines:
        if 'passed' in line or 'failed' in line or 'error' in line.lower():
            print(f"   {line.strip()}")
    
    if result.returncode != 0:
        print(f"   ❌ EXIT CODE: {result.returncode}")
        # Print failures
        in_failure = False
        for line in lines:
            if 'FAILED' in line or 'ERROR' in line:
                in_failure = True
            if in_failure:
                print(f"      {line}")
                if line.strip() == "":
                    in_failure = False
    else:
        print(f"   ✅ PASSED")

print("\n" + "=" * 80)
print("TEST SUITE COMPLETE")
print("=" * 80)
