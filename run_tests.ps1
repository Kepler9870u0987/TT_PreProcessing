# Quick test runner
Write-Host "Running test suite..." -ForegroundColor Cyan
python -m pytest tests/ -v --tb=short --maxfail=3
Write-Host "Test run complete." -ForegroundColor Green
