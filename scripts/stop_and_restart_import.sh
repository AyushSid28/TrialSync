#!/bin/bash
#
# Stop current import and restart with optimal settings
#

set -e

echo "==================================="
echo "Stopping Current Import Process"
echo "==================================="
echo ""

# Find and kill the import process
IMPORT_PID=$(ps aux | grep "import_kaggle_patients" | grep -v grep | awk '{print $2}' | head -1)

if [ -n "$IMPORT_PID" ]; then
    echo "Found import process: PID $IMPORT_PID"
    echo "Stopping..."
    kill -SIGINT "$IMPORT_PID" 2>/dev/null || kill -9 "$IMPORT_PID" 2>/dev/null
    sleep 2
    echo "✓ Process stopped"
else
    echo "No import process found"
fi

echo ""
echo "==================================="
echo "Checking Last Imported Patient"
echo "==================================="
echo ""

# Check where we left off
LAST_ID=$(psql "$DATABASE_URL" -t -c "SELECT display_patient_id FROM patients ORDER BY display_patient_id DESC LIMIT 1;" | xargs)

if [ -n "$LAST_ID" ]; then
    echo "Last imported patient ID: $LAST_ID"
    
    # Extract numeric value
    NUMERIC_ID=$(echo "$LAST_ID" | grep -o '[0-9]*$')
    NEXT_ID=$((NUMERIC_ID + 1))
    
    echo "Will resume from: $NEXT_ID"
else
    echo "No patients found - starting from beginning"
    NEXT_ID=0
fi

echo ""
echo "==================================="
echo "Restarting with Optimal Settings"
echo "==================================="
echo ""

CSV_FILE="${1:-/Users/admin/Projects/SmartPatientMobileApp/data/kaggle/patients_data.csv}"

echo "CSV File: $CSV_FILE"
echo "Start From: $NEXT_ID"
echo "Workers: 4 (optimal)"
echo "Batch Size: 200"
echo "Mode: Concurrent in-memory (fast, no streaming)"
echo ""

uv run python -m src.scrappers.import_kaggle_patients \
    --file "$CSV_FILE" \
    --start-from "$NEXT_ID" \
    --workers 4 \
    --batch-size 200

echo ""
echo "==================================="
echo "Import Complete!"
echo "==================================="
