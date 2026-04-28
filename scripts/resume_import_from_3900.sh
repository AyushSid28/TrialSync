#!/bin/bash
#
# Resume import from patient ID 3900 onwards (skips 0-3899)
#
# Optimized for speed:
# 1. No --streaming (faster for 21K records)
# 2. CSV-level filtering (no patient_id DB checks)
# 3. 4 concurrent workers
# 4. Clean output (SQL logs disabled)
#

set -e

CSV_FILE="${1:-data/cvd_cleaned.csv}"
START_FROM="${START_FROM:-3900}"
WORKERS="${WORKERS:-4}"
BATCH_SIZE="${BATCH_SIZE:-200}"

echo "==================================="
echo "Resume Patient Import from ID $START_FROM"
echo "==================================="
echo "CSV File: $CSV_FILE"
echo "Start From: Patient ID >= $START_FROM"
echo "Workers: $WORKERS"
echo "Batch Size: $BATCH_SIZE"
echo "Mode: Concurrent in-memory (fast)"
echo "==================================="
echo ""

# Check if file exists
if [ ! -f "$CSV_FILE" ]; then
    echo "ERROR: CSV file not found: $CSV_FILE"
    exit 1
fi

# Count total rows
TOTAL_ROWS=$(($(wc -l < "$CSV_FILE") - 1))
echo "Total rows in CSV: $TOTAL_ROWS"

# Estimate rows to import (rough estimate)
REMAINING=$((TOTAL_ROWS - START_FROM + 1))
echo "Estimated rows to import: ~$REMAINING (from ID $START_FROM onwards)"
echo ""

# Estimate time
EST_TIME=$((REMAINING / 140))
echo "Estimated completion: ~${EST_TIME} seconds (~$((EST_TIME / 60)) minutes)"
echo ""

# Run import WITHOUT --streaming (faster)
echo "Starting import from patient ID $START_FROM..."
echo "(SQL logs disabled for clean output)"
echo ""

uv run python -m src.scrappers.import_kaggle_patients \
    --file "$CSV_FILE" \
    --start-from "$START_FROM" \
    --workers "$WORKERS" \
    --batch-size "$BATCH_SIZE"

echo ""
echo "==================================="
echo "✓ Resume Import Complete!"
echo "==================================="
