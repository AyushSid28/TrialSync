"""
Diagnose patient import issues - check if commits are happening.

Run from project root:
    uv run python -m src.scrappers.diagnose_import
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select, text

from src.db.models.patient import Patient
from src.db.models.user import User
from src.db.session import AsyncSessionLocal, engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def diagnose() -> None:
    """Check database state and import readiness."""

    async with AsyncSessionLocal() as session:
        logger.info("=== Database Diagnostic ===\n")

        # Check total patients
        result = await session.execute(text("SELECT COUNT(*) FROM patients"))
        patient_count = result.scalar()
        logger.info(f"Total patients in database: {patient_count}")

        # Check total users
        result = await session.execute(text("SELECT COUNT(*) FROM users"))
        user_count = result.scalar()
        logger.info(f"Total users in database: {user_count}")

        # Check user_types
        result = await session.execute(
            text("SELECT user_type, COUNT(*) FROM users GROUP BY user_type")
        )
        rows = result.fetchall()
        logger.info("\nUser types breakdown:")
        for user_type, count in rows:
            logger.info(f"  {user_type}: {count}")

        # Check if there are pending transactions
        result = await session.execute(text("SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'idle in transaction'"))
        idle_txns = result.scalar()
        if idle_txns > 0:
            logger.warning(f"\n⚠️  Warning: {idle_txns} idle transactions detected")

        # Sample recent patients
        if patient_count > 0:
            result = await session.execute(
                text(
                    """
                    SELECT 
                        p.display_patient_id, 
                        u.email, 
                        p.age, 
                        p.gender,
                        u.user_type,
                        u.created_at
                    FROM patients p
                    JOIN users u ON p.id = u.id
                    ORDER BY u.created_at DESC
                    LIMIT 5
                    """
                )
            )
            rows = result.fetchall()
            logger.info("\nRecent patients:")
            for row in rows:
                logger.info(
                    f"  ID: {row[0]}, Email: {row[1]}, Age: {row[2]}, "
                    f"Gender: {row[3]}, Type: {row[4]}, Created: {row[5]}"
                )

        # Check for orphaned users (in users but not in patients)
        result = await session.execute(
            text(
                """
                SELECT COUNT(*) 
                FROM users u
                LEFT JOIN patients p ON u.id = p.id
                WHERE u.user_type = 'patient' AND p.id IS NULL
                """
            )
        )
        orphaned = result.scalar()
        if orphaned > 0:
            logger.warning(f"\n⚠️  Warning: {orphaned} orphaned user records (in users but not patients)")

        # Test insert capability
        logger.info("\n=== Testing Insert Capability ===")
        test_email = f"test.diagnostic.{asyncio.get_event_loop().time()}@ulalo.com"
        
        try:
            test_user = User(
                email=test_email,
                password_hash="test_hash",
                name="Test User",
                user_type="user",
                is_active=True,
            )
            session.add(test_user)
            await session.flush()
            logger.info("✓ Test insert successful (rolled back)")
            await session.rollback()
        except Exception as e:
            logger.error(f"✗ Test insert failed: {e}")
            await session.rollback()

        logger.info("\n=== Diagnostic Complete ===")


async def main() -> None:
    try:
        await diagnose()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
