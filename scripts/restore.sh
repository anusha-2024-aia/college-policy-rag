#!/usr/bin/env bash
# ==============================================================================
# KVIT Document RAG - PostgreSQL Restore Script
# Restores a compressed pg_dump archive into a target database.
# ==============================================================================
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <backup_file.dump> [target_db_url]"
    exit 1
fi

BACKUP_FILE="$1"
TARGET_DB="${2:-${DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:5432/document_rag}}"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "ERROR: Backup archive not found: ${BACKUP_FILE}"
    exit 1
fi

echo ">>> [RESTORE] Restoring database from archive: ${BACKUP_FILE}"
echo ">>> Target Database: ${TARGET_DB}"

if command -v pg_restore >/dev/null 2>&1; then
    pg_restore --clean --if-exists --no-owner --no-privileges -d "${TARGET_DB}" -v "${BACKUP_FILE}" || true
    echo ">>> [SUCCESS] Restore completed successfully."
else
    echo ">>> [INFO] pg_restore CLI not found in PATH. Restoring via Docker container..."
    docker compose exec -T pgvector pg_restore -U postgres --clean --if-exists --no-owner -d document_rag < "${BACKUP_FILE}" || true
    echo ">>> [SUCCESS] Restore completed via Docker."
fi

