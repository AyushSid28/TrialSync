#!/bin/bash
#
# Quick check: How many patients are in the database?
#

echo "Checking database..."
echo ""

psql "$DATABASE_URL" -c "
SELECT 
    COUNT(*) as total_patients,
    MIN(display_patient_id) as first_id,
    MAX(display_patient_id) as last_id,
    COUNT(DISTINCT display_patient_id) as unique_ids
FROM patients;
"

echo ""
echo "Recent patients:"
psql "$DATABASE_URL" -c "
SELECT display_patient_id, email, age, gender, conditions
FROM patients
ORDER BY created_at DESC
LIMIT 10;
"
