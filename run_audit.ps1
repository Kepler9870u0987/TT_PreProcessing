# Security and Quality Audit Script
Write-Host "================================" -ForegroundColor Cyan
Write-Host "SECURITY & QUALITY AUDIT" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan

$ErrorActionPreference = "Continue"

# 1. Check for common security issues with bandit
Write-Host "`n[1/6] Running bandit security scan..." -ForegroundColor Yellow
python -m bandit -r src/ -f txt -o audit_bandit.txt
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Bandit completed" -ForegroundColor Green
} else {
    Write-Host "⚠️  Bandit found issues (see audit_bandit.txt)" -ForegroundColor Yellow
}

# 2. Check for vulnerable dependencies
Write-Host "`n[2/6] Scanning dependencies for vulnerabilities..." -ForegroundColor Yellow
python -m pip_audit --format json --output audit_dependencies.json
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ No vulnerable dependencies" -ForegroundColor Green
} else {
    Write-Host "⚠️  Vulnerabilities found (see audit_dependencies.json)" -ForegroundColor Yellow
}

# 3. Run flake8 linting
Write-Host "`n[3/6] Running flake8 linter..." -ForegroundColor Yellow
python -m flake8 src/ tests/ --count --statistics --output-file=audit_flake8.txt
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Flake8 passed" -ForegroundColor Green
} else {
    Write-Host "⚠️  Linting issues found (see audit_flake8.txt)" -ForegroundColor Yellow
}

# 4. Check code formatting with black
Write-Host "`n[4/6] Checking code format with black..." -ForegroundColor Yellow
python -m black --check src/ tests/ > audit_black.txt 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Black formatting OK" -ForegroundColor Green
} else {
    Write-Host "⚠️  Formatting issues (see audit_black.txt)" -ForegroundColor Yellow
}

# 5. Check import sorting with isort
Write-Host "`n[5/6] Checking imports with isort..." -ForegroundColor Yellow
python -m isort --check-only src/ tests/ > audit_isort.txt 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Import sorting OK" -ForegroundColor Green
} else {
    Write-Host "⚠️  Import sorting issues (see audit_isort.txt)" -ForegroundColor Yellow
}

# 6. Type checking with mypy (best-effort)
Write-Host "`n[6/6] Running mypy type checker..." -ForegroundColor Yellow
python -m mypy src/ --ignore-missing-imports --no-error-summary > audit_mypy.txt 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Type checking passed" -ForegroundColor Green
} else {
    Write-Host "⚠️  Type issues found (see audit_mypy.txt)" -ForegroundColor Yellow
}

Write-Host "`n================================" -ForegroundColor Cyan
Write-Host "AUDIT COMPLETE" -ForegroundColor Cyan
Write-Host "Results saved to audit_*.txt files" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
