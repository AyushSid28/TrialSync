#!/bin/bash
#
# Analyze the CSV file to understand patient ID distribution
#

CSV_FILE="${1:-/Users/admin/Projects/SmartPatientMobileApp/data/kaggle/patients_data.csv}"

echo "==================================="
echo "CSV File Analysis"
echo "==================================="
echo "File: $CSV_FILE"
echo ""

if [ ! -f "$CSV_FILE" ]; then
    echo "ERROR: File not found"
    exit 1
fi

# Total rows
TOTAL=$(($(wc -l < "$CSV_FILE") - 1))
echo "Total rows: $TOTAL"
echo ""

# Extract PatientID column (assuming it's the first column or has header)
echo "Patient ID Distribution:"
echo "------------------------"

# Get min/max patient IDs
echo "Extracting patient IDs..."
awk -F',' 'NR>1 {print $1}' "$CSV_FILE" | \
    sed 's/[^0-9]//g' | \
    sort -n | \
    {
        read first
        last=$first
        count=1
        while read num; do
            last=$num
            count=$((count + 1))
        done
        echo "First Patient ID: $first"
        echo "Last Patient ID: $last"
        echo "Total unique IDs: $count"
        echo ""
        
        # Show sample IDs
        echo "Sample IDs (first 20):"
        awk -F',' 'NR>1 && NR<=21 {print "  " $1}' "$CSV_FILE"
        echo ""
        
        echo "Sample IDs (last 20):"
        awk -F',' 'NR>1 {print $1}' "$CSV_FILE" | tail -20 | sed 's/^/  /'
    }

echo ""
echo "==================================="
echo "Analysis Complete"
echo "==================================="
