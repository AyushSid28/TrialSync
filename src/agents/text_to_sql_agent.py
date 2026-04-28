import asyncio
import json
import logging
import re

from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.agents.prompts import get_prompt
from src.core.config import settings

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:sql)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
_JSONB_QUESTION_RE = re.compile(r"(\w+)\s*\?\s*'([^']+)'")
_JSONB_CONTAINS_RE = re.compile(r"(\w+)\s*@>\s*'\"([^\"]+)\"'")
_FORBIDDEN_RE = re.compile(
    r"\b(?:" + "|".join(["INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
    "TRUNCATE", "CREATE", "GRANT", "REVOKE", "EXECUTE",
    "COPY", "VACUUM", "REINDEX", "CLUSTER"]) + r")\b"
)

FORBIDDEN_KEYWORDS = frozenset([
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
    "TRUNCATE", "CREATE", "GRANT", "REVOKE", "EXECUTE",
    "COPY", "VACUUM", "REINDEX", "CLUSTER",
])

LLM_TIMEOUT_SECONDS = 30
_llm_semaphore = asyncio.Semaphore(3)


class TextToSQLAgent:
    """Converts natural language questions into SQL using LLM + live schema introspection.

    Production features:
    - 30s timeout on LLM calls to prevent hanging
    - 3 retries with exponential backoff (1s, 2s, 4s) on transient failures
    - Semaphore limits concurrent LLM calls to 3 to avoid rate-limit floods
    - Read-only SQL validation blocks any non-SELECT statements
    """

    PROMPT_FILE = "text_to_sql.yaml"

    def __init__(self, session: AsyncSession):
        self.session = session
        self.client = AsyncOpenAI(
            api_key=settings.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            timeout=LLM_TIMEOUT_SECONDS,
        )
        self.model_name = "openai/gpt-4o-mini"

    QUERYABLE_TABLES = frozenset({
        "patients",
        "clinical_trials",
        "fhir_conditions",
        "fhir_medications",
        "fhir_observations",
    })

    FHIR_QUERYABLE_TABLES = frozenset({
        "clinical_trials",
        "fhir_patients",
        "fhir_conditions",
        "fhir_observations",
        "fhir_medications",
        "fhir_procedures",
        "fhir_encounters",
        "fhir_allergies",
        "fhir_immunizations",
        "fhir_diagnostic_reports",
        "fhir_care_plans",
        "fhir_devices",
        "fhir_claims",
    })

    async def introspect_schema(self, source: str = "kaggle") -> str:
        tables = self.FHIR_QUERYABLE_TABLES if source == "fhir" else self.QUERYABLE_TABLES
        query = text(
            """
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = ANY(:tables)
            ORDER BY table_name, ordinal_position
        """
        )
        result = await self.session.execute(query, {"tables": list(tables)})
        rows = result.fetchall()

        if not rows:
            raise ValueError("No tables found in the public schema")

        schema: dict[str, list[str]] = {}
        jsonb_columns: list[tuple[str, str]] = []

        for table, col, dtype, nullable, default in rows:
            if table not in schema:
                schema[table] = []
            parts = f"  {col} {dtype}"
            if nullable == "NO":
                parts += " NOT NULL"
            if default:
                parts += f" DEFAULT {default}"
            schema[table].append(parts)

            if dtype == "jsonb":
                jsonb_columns.append((table, col))

        schema_text = "\n\n".join(
            f"TABLE {table}:\n" + "\n".join(cols) for table, cols in schema.items()
        )

        if jsonb_columns:
            samples = await self._sample_jsonb_values(jsonb_columns)
            if samples:
                schema_text += "\n\nSAMPLE JSONB VALUES (use these exact formats in queries):\n"
                schema_text += samples

        return schema_text

    async def _sample_jsonb_values(self, jsonb_columns: list[tuple[str, str]]) -> str:
        samples = []
        for table, col in jsonb_columns:
            try:
                result = await self.session.execute(
                    text(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL LIMIT 1")
                )
                row = result.fetchone()
                if row and row[0] is not None:
                    val = json.dumps(row[0], default=str)
                    if len(val) > 300:
                        val = val[:300] + "..."
                    samples.append(f"  {table}.{col} = {val}")
            except Exception:
                pass
        return "\n".join(samples)

    def _extract_sql(self, response_text: str) -> str:
        cleaned = response_text.strip()

        match = _FENCE_RE.search(cleaned)
        if match:
            cleaned = match.group(1).strip()

        if not cleaned.upper().startswith("SELECT"):
            lines = cleaned.split("\n")
            for line in lines:
                if line.strip().upper().startswith("SELECT"):
                    cleaned = "\n".join(lines[lines.index(line) :])
                    break

        cleaned = self._fix_jsonb_operators(cleaned)

        return cleaned.rstrip(";") + ";"

    def _fix_jsonb_operators(self, sql: str) -> str:
        sql = _JSONB_QUESTION_RE.sub(r"\1::text ILIKE '%\2%'", sql)
        sql = _JSONB_CONTAINS_RE.sub(r"\1::text ILIKE '%\2%'", sql)
        return sql

    def _validate_sql(self, sql: str) -> None:
        upper = sql.upper()

        match = _FORBIDDEN_RE.search(upper)
        if match:
            raise ValueError(f"Forbidden SQL keyword detected: {match.group()}")

        if not upper.lstrip().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type((TimeoutError, ConnectionError, OSError)),
        reraise=True,
    )
    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call LLM with semaphore, timeout, and retry protection."""
        async with _llm_semaphore:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0,
                    max_tokens=1024,
                ),
                timeout=LLM_TIMEOUT_SECONDS,
            )
            return response.choices[0].message.content

    async def generate_sql(self, natural_language_query: str) -> str:
        schema_context = await self.introspect_schema()

        system_prompt = get_prompt("text_to_sql", role="system", prompts_file=self.PROMPT_FILE)
        user_prompt = get_prompt(
            "text_to_sql",
            role="user",
            prompts_file=self.PROMPT_FILE,
            **{
                "schema_context": schema_context,
                "natural_language_query": natural_language_query,
            },
        )

        logger.info("Generating SQL", extra={"query": natural_language_query})
        raw_content = await self._call_llm(system_prompt, user_prompt)
        raw_sql = self._extract_sql(raw_content)
        self._validate_sql(raw_sql)
        logger.info("SQL generated", extra={"sql": raw_sql})
        return raw_sql

    async def execute_query(self, sql: str) -> tuple[list[str], list[dict]]:
        result = await self.session.execute(text(sql))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        return columns, rows

    async def generate_patient_filter_sql(
        self, criteria: dict, source: str = "kaggle",
    ) -> tuple[str, list[str]]:
        """Generate SQL to pre-filter patients based on trial criteria.

        Uses retry + timeout + semaphore for production resilience.
        When source="fhir", uses the FHIR prompt and schema instead.
        """
        schema_context = await self.introspect_schema(source=source)
        prompt_key = "patient_filter_fhir" if source == "fhir" else "patient_filter"

        conditions = ", ".join(criteria.get("conditions", [])) or "None"
        keywords = ", ".join(criteria.get("keywords", [])) or "None"
        eligibility_text = (criteria.get("eligibility_text", "") or "")[:500]

        system_prompt = get_prompt(
            prompt_key, role="system", prompts_file=self.PROMPT_FILE
        )
        user_prompt = get_prompt(
            prompt_key,
            role="user",
            prompts_file=self.PROMPT_FILE,
            schema_context=schema_context,
            conditions=conditions,
            keywords=keywords,
            eligibility_text=eligibility_text,
        )

        logger.info("Generating patient filter SQL", extra={"conditions": conditions})
        raw_content = await self._call_llm(system_prompt, user_prompt)
        raw_sql = self._extract_sql(raw_content)
        self._validate_sql(raw_sql)
        logger.info("Patient filter SQL generated", extra={"sql": raw_sql})

        result = await self.session.execute(text(raw_sql))
        rows = result.fetchall()
        patient_ids = []
        for row in rows:
            val = str(row[0]) if row[0] is not None else None
            if val:
                patient_ids.append(val)

        logger.info("Text-to-SQL pre-filtered %d patients", len(patient_ids))
        return raw_sql, patient_ids

    async def _regenerate_sql_with_error(
        self, natural_language_query: str, bad_sql: str, error_msg: str
    ) -> str:
        """Re-generate SQL by feeding back the failed query and the DB error."""
        schema_context = await self.introspect_schema()
        system_prompt = get_prompt("text_to_sql", role="system", prompts_file=self.PROMPT_FILE)
        user_prompt = (
            f"DATABASE SCHEMA:\n{schema_context}\n\n"
            f"USER QUESTION:\n{natural_language_query}\n\n"
            f"YOUR PREVIOUS SQL WAS WRONG:\n{bad_sql}\n\n"
            f"DATABASE ERROR:\n{error_msg}\n\n"
            "Fix the SQL. Use ONLY columns and tables that exist in the schema above. "
            "Return ONLY the corrected SQL query."
        )
        raw_content = await self._call_llm(system_prompt, user_prompt)
        raw_sql = self._extract_sql(raw_content)
        self._validate_sql(raw_sql)
        return raw_sql

    async def run(self, natural_language_query: str) -> dict:
        """Public entry point: question in -> structured result out.

        Attempts up to 2 retries if the generated SQL fails execution,
        feeding the error back to the LLM for self-correction.
        """
        sql = await self.generate_sql(natural_language_query)

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                columns, rows = await self.execute_query(sql)
                return {
                    "query": natural_language_query,
                    "generated_sql": sql,
                    "columns": columns,
                    "results": rows,
                    "count": len(rows),
                }
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(
                        "SQL execution failed (attempt %d/%d), retrying with error feedback",
                        attempt + 1, max_retries + 1,
                        extra={"sql": sql, "error": str(e)},
                    )
                    sql = await self._regenerate_sql_with_error(
                        natural_language_query, sql, str(e)
                    )
                else:
                    raise
