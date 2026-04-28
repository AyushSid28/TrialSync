#!/bin/bash
#
# Stop current import and restart with optimal settings
# Auto-detects where you left off and resumes efficiently
#

set -e

CSV_FILE="${1:-/Users/admin/Projects/SmartPatientMobileApp/data/kaggle/patients_data.csv}"

echo "==================================="
echo "Import Recovery & Restart"
echo "==================================="
echo ""

# Stop any running import
echo "1. Checking for running imports..."
IMPORT_PID=$(ps aux | grep "[i]mport_kaggle_patients" | awk '{print $2}' | head -1)

if [ -n "$IMPORT_PID" ]; then
    echo "   Found PID $IMPORT_PID - stopping..."
    kill -SIGINT "$IMPORT_PID" 2>/dev/null || kill -9 "$IMPORT_PID" 2>/dev/null
    sleep 2
    echo "   ✓ Stopped"
else
    echo "   No running imports"
fi

echo ""
echo "2. Checking last imported patient..."

# Get last patient ID from database
LAST_ID=$(psql "$DATABASE_URL" -t -c "SELECT display_patient_id FROM patients ORDER BY CAST(REGEXP_REPLACE(display_patient_id, '[^0-9]', '', 'g') AS INTEGER) DESC LIMIT 1;" 2>/dev/null | xargs || echo "")

if [ -n "$LAST_ID" ]; then
    echo "   Last imported: $LAST_ID"
    
    # Extract numeric value
    NUMERIC_ID=$(echo "$LAST_ID" | grep -o '[0-9]*$')
    NEXT_ID=$((NUMERIC_ID + 1))
    
    echo "   Will resume from: $NEXT_ID"
else
    echo "   No patients found - starting from beginning"
    NEXT_ID=1
fi

echo ""
echo "3. Starting optimized import..."
echo "   CSV: $CSV_FILE"
echo "   Start from: ID $NEXT_ID"
echo "   Workers: 4"
echo "   Batch size: 200"
echo "   Mode: Concurrent in-memory (NO streaming)"
echo "   SQL logs: Disabled (clean output)"
echo ""

uv run python -m src.scrappers.import_kaggle_patients \
    --file "$CSV_FILE" \
    --start-from "$NEXT_ID" \
    --workers 4 \
    --batch-size 200

echo ""
echo "==================================="
echo "✓ Import Complete!"
echo "==================================="

# Show final count
TOTAL=$(psql "$DATABASE_URL" -t -c "SELECT COUNT(*) FROM patients;" 2>/dev/null | xargs || echo "unknown")
echo "Total patients in database: $TOTAL"
