#!/bin/bash
#
# Clean up orphaned patient records in users table
#
# This happens when:
# 1. You truncate/delete from patients table
# 2. But users table still has patient records
# 3. Foreign key is CASCADE, but manual DELETE might not trigger it
#

set -e

echo "==================================="
echo "Cleanup Orphaned Patient Users"
echo "==================================="
echo ""

echo "Checking for orphaned records..."
echo ""

# Count orphaned
ORPHANED=$(psql "$DATABASE_URL" -t -c "
    SELECT COUNT(*) 
    FROM users u
    LEFT JOIN patients p ON u.id = p.id
    WHERE u.user_type = 'patient' AND p.id IS NULL
" | xargs)

echo "Found $ORPHANED orphaned patient records in users table"

if [ "$ORPHANED" -eq "0" ]; then
    echo "✓ Database is clean - no cleanup needed"
    exit 0
fi

echo ""
echo "These records exist in 'users' but not in 'patients'."
echo "This causes the import to skip all patients (duplicate email detection)."
echo ""
read -p "Delete $ORPHANED orphaned records? (y/N) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Deleting orphaned records..."
    
    psql "$DATABASE_URL" -c "
        DELETE FROM users 
        WHERE user_type = 'patient' 
        AND id NOT IN (SELECT id FROM patients)
    "
    
    echo ""
    echo "✓ Cleanup complete!"
    echo ""
    
    # Verify
    REMAINING=$(psql "$DATABASE_URL" -t -c "
        SELECT COUNT(*) 
        FROM users u
        LEFT JOIN patients p ON u.id = p.id
        WHERE u.user_type = 'patient' AND p.id IS NULL
    " | xargs)
    
    echo "Verification:"
    echo "  Orphaned records remaining: $REMAINING"
    
    if [ "$REMAINING" -eq "0" ]; then
        echo "  ✓ All orphaned records cleaned"
        echo ""
        echo "You can now run the import successfully:"
        echo "  uv run python -m src.scrappers.import_kaggle_patients --file <your_file> --workers 4"
    else
        echo "  ⚠️  Warning: Some records remain"
    fi
else
    echo ""
    echo "Cleanup cancelled"
fi

echo ""
echo "==================================="
