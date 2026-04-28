"""FHIR-specific SQL fragments for the patient matching and scoring pipeline.

Mirrors the Kaggle-specific constants in root_word_search_agent.py
(DEMOGRAPHIC_FIELDS, _TSVECTOR_EXPR) but targets the normalised fhir_*
tables instead of the flat patients table.

Key differences from Kaggle path:
- Age is computed from fhir_patients.birth_date (no stored age column)
- Conditions live in a separate fhir_conditions table (JOIN required)
- BMI, smoking status come from fhir_observations via LOINC codes
- State/country are direct columns (not JSONB)
- Search uses ILIKE on fhir_conditions.display_name (no tsvector on JSONB)
"""

FHIR_DEMOGRAPHIC_FIELDS = """
    fp.id,
    fp.full_name AS display_patient_id,
    EXTRACT(YEAR FROM AGE(CURRENT_DATE, fp.birth_date::date))::int AS age,
    fp.gender,
    fp.ethnicity,
    fp.state,
    fp.country
"""

FHIR_CONDITIONS_AGG = """
    LEFT JOIN LATERAL (
        SELECT array_agg(DISTINCT fc.display_name) AS conditions
        FROM fhir_conditions fc
        WHERE fc.patient_id = fp.id
    ) cond_agg ON true
"""

FHIR_BMI_LATEST = """
    LEFT JOIN LATERAL (
        SELECT o.value_numeric AS bmi
        FROM fhir_observations o
        WHERE o.patient_id = fp.id
          AND o.loinc_code = '39156-5'
          AND o.value_numeric IS NOT NULL
        ORDER BY o.effective_date DESC NULLS LAST
        LIMIT 1
    ) bmi_obs ON true
"""

FHIR_SMOKING_LATEST = """
    LEFT JOIN LATERAL (
        SELECT o.value_text AS smoker_status
        FROM fhir_observations o
        WHERE o.patient_id = fp.id
          AND o.loinc_code = '72166-2'
          AND o.value_text IS NOT NULL
        ORDER BY o.effective_date DESC NULLS LAST
        LIMIT 1
    ) smoke_obs ON true
"""

FHIR_BP_LATEST = """
    LEFT JOIN LATERAL (
        SELECT o.bp_systolic, o.bp_diastolic
        FROM fhir_observations o
        WHERE o.patient_id = fp.id
          AND o.loinc_code = '85354-9'
          AND (o.bp_systolic IS NOT NULL OR o.bp_diastolic IS NOT NULL)
        ORDER BY o.effective_date DESC NULLS LAST
        LIMIT 1
    ) bp_obs ON true
"""

LOINC_BMI = "39156-5"
LOINC_SMOKING = "72166-2"
LOINC_BP_PANEL = "85354-9"
LOINC_BODY_WEIGHT = "29463-7"
LOINC_BODY_HEIGHT = "8302-2"


def build_fhir_match_sql(
    search_terms: list[str],
    sex: str = "ALL",
    min_age: int | None = None,
    max_age: int | None = None,
    min_bmi: float | None = None,
    max_bmi: float | None = None,
    smoker_status: str | None = None,
    limit: int = 200,
    prefilter_patient_ids: list[str] | None = None,
) -> tuple[str, dict]:
    """Build a SELECT query that searches fhir_patients by conditions.

    Returns (sql_string, params_dict) ready for sqlalchemy text() execution.
    The output columns match the Kaggle pipeline's patient dict shape so
    downstream scoring works identically.
    """
    where_clauses: list[str] = []
    params: dict = {"limit": limit}

    if search_terms:
        ilike_parts = []
        for i, term in enumerate(search_terms):
            key = f"term_{i}"
            ilike_parts.append(f"fc_search.display_name ILIKE :{key}")
            params[key] = f"%{term.strip()}%"
        condition_where = " OR ".join(ilike_parts)
        where_clauses.append(
            f"EXISTS (SELECT 1 FROM fhir_conditions fc_search "
            f"WHERE fc_search.patient_id = fp.id AND ({condition_where}))"
        )

    if prefilter_patient_ids:
        placeholders = ", ".join(f":pid_{i}" for i in range(len(prefilter_patient_ids)))
        where_clauses.append(f"fp.id::text IN ({placeholders})")
        for i, pid in enumerate(prefilter_patient_ids):
            params[f"pid_{i}"] = pid

    if sex and sex.upper() != "ALL":
        where_clauses.append("fp.gender ILIKE :sex")
        params["sex"] = sex

    if min_age is not None:
        where_clauses.append(
            "EXTRACT(YEAR FROM AGE(CURRENT_DATE, fp.birth_date::date))::int >= :min_age"
        )
        params["min_age"] = min_age

    if max_age is not None:
        where_clauses.append(
            "EXTRACT(YEAR FROM AGE(CURRENT_DATE, fp.birth_date::date))::int <= :max_age"
        )
        params["max_age"] = max_age

    if min_bmi is not None:
        where_clauses.append(
            "EXISTS (SELECT 1 FROM fhir_observations o "
            "WHERE o.patient_id = fp.id AND o.loinc_code = '39156-5' "
            "AND o.value_numeric >= :min_bmi)"
        )
        params["min_bmi"] = min_bmi

    if max_bmi is not None:
        where_clauses.append(
            "EXISTS (SELECT 1 FROM fhir_observations o "
            "WHERE o.patient_id = fp.id AND o.loinc_code = '39156-5' "
            "AND o.value_numeric <= :max_bmi)"
        )
        params["max_bmi"] = max_bmi

    if smoker_status:
        smoke_map = {
            "current": "%smokes%",
            "former": "%ex-smoker%",
            "never": "%never%",
        }
        smoke_pattern = smoke_map.get(smoker_status.lower(), f"%{smoker_status}%")
        where_clauses.append(
            "EXISTS (SELECT 1 FROM fhir_observations o "
            "WHERE o.patient_id = fp.id AND o.loinc_code = '72166-2' "
            "AND o.value_text ILIKE :smoker_status)"
        )
        params["smoker_status"] = smoke_pattern

    if not where_clauses:
        where_clauses.append("fp.deceased IS NOT TRUE")

    where_str = " AND ".join(where_clauses)

    sql = f"""
        SELECT
            {FHIR_DEMOGRAPHIC_FIELDS},
            cond_agg.conditions,
            bmi_obs.bmi,
            smoke_obs.smoker_status,
            NULL AS general_health
        FROM fhir_patients fp
        {FHIR_CONDITIONS_AGG}
        {FHIR_BMI_LATEST}
        {FHIR_SMOKING_LATEST}
        WHERE {where_str}
          AND fp.deceased IS NOT TRUE
        ORDER BY fp.id
        LIMIT :limit
    """

    return sql, params


def parse_search_query_to_terms(search_query: str) -> list[str]:
    """Split an OR-joined search query into individual search terms.

    "diabetes OR cardiac OR stroke" -> ["diabetes", "cardiac", "stroke"]
    """
    parts = [t.strip() for t in search_query.split(" OR ") if t.strip()]
    if not parts and search_query.strip():
        parts = [search_query.strip()]
    return parts
