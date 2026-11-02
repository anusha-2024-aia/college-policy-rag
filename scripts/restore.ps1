# ==============================================================================
# KVIT Document RAG - PostgreSQL Restore Script (PowerShell)
# Restores a compressed pg_dump archive into a target database.
# ==============================================================================
param(
    [Parameter(Mandatory=$true)]
    [string]$BackupFile,
    [string]$TargetDb = ""
)

if (-not (Test-Path $BackupFile)) {
    Write-Error "ERROR: Backup archive not found: $BackupFile"
    exit 1
}

if (-not $TargetDb) {
    $TargetDb = if ($env:DATABASE_URL) { $env:DATABASE_URL } else { "postgresql://postgres:postgres@127.0.0.1:5432/document_rag" }
}

Write-Host ">>> [RESTORE] Restoring database from archive: $BackupFile" -ForegroundColor Cyan
Write-Host ">>> Target Database: $TargetDb"

$pgRestore = Get-Command pg_restore -ErrorAction SilentlyContinue
if ($pgRestore) {
    & pg_restore --clean --if-exists --no-owner --no-privileges -d $TargetDb -v $BackupFile
    Write-Host ">>> [SUCCESS] Restore completed successfully." -ForegroundColor Green
} else {
    Write-Host ">>> [INFO] pg_restore not found in local PATH. Restoring via Docker container..." -ForegroundColor Yellow
    Get-Content $BackupFile -Raw | docker compose exec -T pgvector pg_restore -U postgres --clean --if-exists --no-owner -d document_rag
    Write-Host ">>> [SUCCESS] Restore completed via Docker." -ForegroundColor Green
}

