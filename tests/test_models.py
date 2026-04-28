"""Smoke tests for core ORM models."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.db.models import ClinicalTrial, Patient, User


@pytest.mark.asyncio
async def test_create_staff_user(db_session) -> None:
    user = User(
        user_type="user",
        email="staff@example.com",
        password_hash="hashed",
        name="Staff User",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    result = await db_session.execute(select(User).where(User.email == "staff@example.com"))
    loaded = result.scalar_one()
    assert loaded.name == "Staff User"
    assert loaded.user_type == "user"


@pytest.mark.asyncio
async def test_patient_joined_inheritance_same_id(db_session) -> None:
    patient = Patient(
        email="patient@example.com",
        password_hash="hashed",
        name="Pat Ient",
        display_patient_id="CC-90001",
        geography={"country": "United States", "state": "CA"},
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    assert patient.user_type == "patient"
    uid = patient.id

    u_row = await db_session.get(User, uid)
    assert u_row is not None
    assert u_row.email == "patient@example.com"

    p_row = await db_session.get(Patient, uid)
    assert p_row is not None
    assert p_row.display_patient_id == "CC-90001"


@pytest.mark.asyncio
async def test_clinical_trial_nct(db_session) -> None:
    trial = ClinicalTrial(
        registry="US",
        nct_id="NCT00000001",
        title="Example trial",
        sponsor="Sponsor Inc",
        status="Recruiting",
        payload={"eligibility": {"sex": "ALL"}},
    )
    db_session.add(trial)
    await db_session.commit()
    await db_session.refresh(trial)

    result = await db_session.execute(select(ClinicalTrial).where(ClinicalTrial.nct_id == "NCT00000001"))
    loaded = result.scalar_one()
    assert loaded.registry == "US"
    assert loaded.payload["eligibility"]["sex"] == "ALL"
