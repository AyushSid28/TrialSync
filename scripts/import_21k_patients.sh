#!/bin/bash
#
# Import 21,000 Kaggle patient records with concurrent workers
#
# Usage:
#   ./scripts/import_21k_patients.sh /path/to/cvd_full.csv
#

set -e

CSV_FILE="${1:-data/cvd_cleaned.csv}"
WORKERS="${WORKERS:-4}"
BATCH_SIZE="${BATCH_SIZE:-200}"

echo "==================================="
echo "Patient Import - Concurrent Mode"
echo "==================================="
echo "CSV File: $CSV_FILE"
echo "Workers: $WORKERS"
echo "Batch Size: $BATCH_SIZE"
echo "==================================="
echo ""

# Check if file exists
if [ ! -f "$CSV_FILE" ]; then
    echo "ERROR: CSV file not found: $CSV_FILE"
    exit 1
fi

# Count rows in CSV (minus header)
ROW_COUNT=$(($(wc -l < "$CSV_FILE") - 1))
echo "Found $ROW_COUNT rows in CSV"
echo ""

# Estimate time
EST_TIME=$((ROW_COUNT / 140))
echo "Estimated completion time: ~${EST_TIME} seconds (with $WORKERS workers)"
echo ""

# Run import
echo "Starting import..."
uv run python -m src.scrappers.import_kaggle_patients \
    --file "$CSV_FILE" \
    --workers "$WORKERS" \
    --batch-size "$BATCH_SIZE" \
    --enable-consent

echo ""
echo "==================================="
echo "Import Complete!"
echo "==================================="
