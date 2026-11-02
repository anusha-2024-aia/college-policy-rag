#!/usr/bin/env bash
# ==============================================================================
# KVIT Document RAG - PostgreSQL Backup Script
# Creates a compressed, timestamped pg_dump archive.
# ==============================================================================
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-data/backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTPUT_FILE="${1:-${BACKUP_DIR}/document_rag_${TIMESTAMP}.dump}"

mkdir -p "${BACKUP_DIR}"

DB_URL="${DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:5432/document_rag}"

echo ">>> [BACKUP] Starting PostgreSQL database backup..."
echo ">>> Target Archive: ${OUTPUT_FILE}"

if command -v pg_dump >/dev/null 2>&1; then
    pg_dump -d "${DB_URL}" -F c -b -v -f "${OUTPUT_FILE}"
    echo ">>> [SUCCESS] Backup completed successfully: ${OUTPUT_FILE} ($(du -h "${OUTPUT_FILE}" | cut -f1))"
else
    echo ">>> [WARNING] pg_dump CLI not found in PATH."
    echo ">>> If running inside Docker, execute:"
    echo ">>> docker compose exec -T pgvector pg_dump -U postgres document_rag -F c > \"${OUTPUT_FILE}\""
fi

