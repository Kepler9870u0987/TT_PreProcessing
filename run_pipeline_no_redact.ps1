#!/usr/bin/env pwsh
# Script per eseguire la pipeline in modalità NON-REDACT
# I PII vengono rilevati ma NON oscurati nel testo

Write-Host "🚀 Esecuzione pipeline in modalità NON-REDACT..." -ForegroundColor Cyan
Write-Host ""

# Genera un salt temporaneo (in produzione usare uno fisso e sicuro)
$salt = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})

# Imposta variabili d'ambiente per la configurazione
$env:PREPROCESSING_PII_MODE = "detect_only"  # Rileva PII ma NON oscura
$env:PREPROCESSING_PII_SALT = $salt

Write-Host "📋 Configurazione:" -ForegroundColor Yellow
Write-Host "  PII_MODE: $env:PREPROCESSING_PII_MODE (i PII vengono rilevati ma non oscurati)" -ForegroundColor Green
Write-Host "  PII_SALT: [generato]" -ForegroundColor Green
Write-Host ""

# Esegui la pipeline
Write-Host "🔄 Esecuzione test_ingestion_pipeline.py..." -ForegroundColor Cyan
python test_ingestion_pipeline.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ Pipeline completata con successo!" -ForegroundColor Green
    Write-Host ""
    Write-Host "📄 Output salvato in: test_ingestion_output.json" -ForegroundColor Cyan
    Write-Host "   Questo file contiene il body NON oscurato, pronto per il prossimo layer." -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "❌ Errore durante l'esecuzione della pipeline" -ForegroundColor Red
    exit $LASTEXITCODE
}
