# ==============================================================================
# KVIT Document RAG - PostgreSQL Backup Script (PowerShell)
# Creates a compressed, timestamped pg_dump archive.
# ==============================================================================
param(
    [string]$OutputFile = ""
)

$BackupDir = "data\backups"
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $OutputFile) {
    $OutputFile = Join-Path $BackupDir "document_rag_$Timestamp.dump"
}

$DbUrl = if ($env:DATABASE_URL) { $env:DATABASE_URL } else { "postgresql://postgres:postgres@127.0.0.1:5432/document_rag" }

Write-Host ">>> [BACKUP] Starting PostgreSQL database backup..." -ForegroundColor Cyan
Write-Host ">>> Target Archive: $OutputFile"

$pgDump = Get-Command pg_dump -ErrorAction SilentlyContinue
if ($pgDump) {
    & pg_dump -d $DbUrl -F c -b -v -f $OutputFile
    Write-Host ">>> [SUCCESS] Backup completed successfully: $OutputFile" -ForegroundColor Green
} else {
    Write-Host ">>> [INFO] pg_dump not found in local PATH. Running backup via Docker container..." -ForegroundColor Yellow
    docker compose exec -T pgvector pg_dump -U postgres document_rag -F c > $OutputFile
    Write-Host ">>> [SUCCESS] Backup completed via Docker: $OutputFile" -ForegroundColor Green
}

