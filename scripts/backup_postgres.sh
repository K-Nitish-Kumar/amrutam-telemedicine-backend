#!/usr/bin/env bash
# Local PostgreSQL backup using the installed pg_dump client.
set -euo pipefail
mkdir -p backups
output="${1:-backups/amrutam_local_$(date -u +%Y%m%dT%H%M%SZ).dump}"
pg_dump --format=custom --no-owner --no-acl --file="$output" "${PGDATABASE:-amrutam_local}"
printf 'Backup written: %s\n' "$output"
