#!/usr/bin/env bash
set -euo pipefail

CSV_PATH=${1:-backend/sample_data/test_import.csv}
SUPPLIER_ID=${SUPPLIER_ID:-1}
API_BASE=${API_BASE:-http://localhost:8000/api/admin}
TOKEN=${TOKEN:-}

if [[ -z "$TOKEN" ]]; then
  echo "Set TOKEN with admin bearer token"
  exit 1
fi

curl -sS -X POST "$API_BASE/import/run-csv?supplier_id=$SUPPLIER_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@${CSV_PATH}" | jq .
