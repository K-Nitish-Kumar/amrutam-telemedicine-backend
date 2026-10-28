#!/usr/bin/env bash
# Restore a custom-format backup into an independently provisioned database.
set -euo pipefail
if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "Usage: $0 path/to/backup.dump" >&2
  exit 2
fi
if [[ "${I_UNDERSTAND_RESTORE:-}" != "YES" ]]; then
  echo "Set I_UNDERSTAND_RESTORE=YES only for a disposable restore target." >&2
  exit 2
fi
pg_restore --no-owner --no-acl --dbname="${PGDATABASE:-amrutam_restore}" "$1"
echo "Restore complete; verify schema and application checks before use."
