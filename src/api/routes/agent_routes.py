import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from src.api.dependencies import DBSession
from src.agents.text_to_sql_agent import TextToSQLAgent
from src.agents.root_word_search_agent import RootWordSearchAgent
from src.agents.trial_match_orchestrator import TrialMatchOrchestrator
from src.agents.scoring_agent import ScoringAgent
from src.schemas.agent_schemas import (
    TextToSQLRequest,
    TextToSQLResponse,
    RootWordSearchRequest,
    RootWordSearchResponse,
    RootWordExtractRequest,
    RootWordExtractResponse,
    TrialMatchRequest,
    CriteriaMatchRequest,
    TrialMatchResponse,
    ScorePatientRequest,
    ScoreCriteriaRequest,
    ScorePatientResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/search-trials")
async def search_trials(
    session: DBSession,
    q: str = Query("", description="Search by title, NCT ID, or condition"),
    status: str = Query("", description="Filter by status: RECRUITING, COMPLETED, etc."),
    limit: int = Query(20, ge=1, le=100),
):
    """Search/browse clinical trials by condition, title, or NCT ID.

    Prioritizes matches in conditions and title over deep payload text
    so a search for 'diabetes' returns diabetes trials, not trials that
    merely mention diabetes in their exclusion criteria.
    """
    try:
        where_clauses = ["nct_id IS NOT NULL"]
        params: dict = {"limit": limit}

        if q.strip():
            where_clauses.append(
                "((payload->'conditions')::text ILIKE :q"
                " OR title ILIKE :q"
                " OR nct_id ILIKE :q"
                " OR (payload->'keywords')::text ILIKE :q)"
            )
            params["q"] = f"%{q.strip()}%"

        if status.strip():
            where_clauses.append("status ILIKE :status")
            params["status"] = f"%{status.strip()}%"

        where_str = " AND ".join(where_clauses)

        order_clause = "scraped_at DESC"
        if q.strip():
            order_clause = (
                "CASE WHEN (payload->'conditions')::text ILIKE :q THEN 0"
                "     WHEN (payload->'keywords')::text ILIKE :q THEN 1"
                "     ELSE 2 END, scraped_at DESC"
            )

        sql = f"""
            SELECT nct_id, title, status,
                   payload->'conditions' AS conditions
            FROM clinical_trials
            WHERE {where_str}
            ORDER BY {order_clause}
            LIMIT :limit
        """
        result = await session.execute(text(sql), params)
        rows = result.fetchall()
        columns = list(result.keys())

        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        logger.error("Trial search failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


@router.post("/text-to-sql", response_model=TextToSQLResponse)
async def text_to_sql(request: TextToSQLRequest, session: DBSession):
    """Convert natural language → SQL → execute → return results."""
    try:
        agent = TextToSQLAgent(session)
        result = await agent.run(request.query)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Text-to-SQL agent failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@router.post("/root-word-search", response_model=RootWordSearchResponse)
async def root_word_search(request: RootWordSearchRequest, session: DBSession):
    """Pre-filter patients using root-word stemming on conditions/codes.

    Takes a search query, extracts root words via PostgreSQL stemming,
    searches patient JSONB data (conditions, icd10_codes, geography),
    and returns ONLY matching patient IDs + demographics.
    The full dataset gets shortened to just the relevant subset.
    """
    try:
        agent = RootWordSearchAgent(session)
        result = await agent.run(
            query=request.query,
            mode=request.mode,
            limit=request.limit,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Root word search agent failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@router.post("/extract-root-words", response_model=RootWordExtractResponse)
async def extract_root_words(request: RootWordExtractRequest, session: DBSession):
    """Utility: Preview how PostgreSQL's English stemmer breaks down a query."""
    try:
        agent = RootWordSearchAgent(session)
        root_words = await agent.extract_root_words(request.query)
        return {"query": request.query, "root_words": root_words}
    except Exception as e:
        logger.error("Root word extraction failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Extraction error: {str(e)}")


@router.post("/match-patients", response_model=TrialMatchResponse)
async def match_patients_to_trial(request: TrialMatchRequest, session: DBSession):
    """Match patients to a specific clinical trial using its NCT ID or UUID."""
    try:
        orchestrator = TrialMatchOrchestrator(session)
        result = await orchestrator.run_by_trial(
            trial_id=request.trial_id,
            limit=request.limit,
            source=request.source,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Trial match failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Match error: {str(e)}")


@router.post("/match-patients-criteria", response_model=TrialMatchResponse)
async def match_patients_by_criteria(request: CriteriaMatchRequest, session: DBSession):
    """Match patients using manually provided criteria (no trial lookup)."""
    try:
        orchestrator = TrialMatchOrchestrator(session)
        result = await orchestrator.run_by_criteria(
            search_query=request.search_query,
            sex=request.sex,
            min_age=request.min_age,
            max_age=request.max_age,
            min_bmi=request.min_bmi,
            max_bmi=request.max_bmi,
            smoker_status=request.smoker_status,
            limit=request.limit,
            source=request.source,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Criteria match failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Match error: {str(e)}")



@router.post("/score-patients",response_model=ScorePatientResponse)
async def score_patients(request:ScorePatientRequest,session:DBSession):
    """Score and rank maatched patients by relevance to a critical trial.
    
    Runs the orchestrator to get matched patients,then applies multifactor weighted
    scoring (condition overlap,age,sex,geography,health metrics)
    and exclusion criteria.Returns patients ranked 0-100 with per-factor breakdown.

    
    
    """
    try:
        agent=ScoringAgent(session)
        result=await agent.run(
            trial_id=request.trial_id,
            limit=request.limit,
            source=request.source,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400,detail=str(e))

    except Exception as e:
        logger.error("Scoring agent failed",exc_info=True)
        raise HTTPException(status_code=500,detail=f"Scoring error:{str(e)}")


@router.post("/score-patients-criteria", response_model=ScorePatientResponse)
async def score_patients_by_criteria(request: ScoreCriteriaRequest, session: DBSession):
    """Score and rank patients matched via free-text criteria (no trial lookup)."""
    try:
        agent = ScoringAgent(session)
        result = await agent.run_by_criteria(
            search_query=request.search_query,
            sex=request.sex,
            min_age=request.min_age,
            max_age=request.max_age,
            min_bmi=request.min_bmi,
            max_bmi=request.max_bmi,
            smoker_status=request.smoker_status,
            limit=request.limit,
            source=request.source,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Scoring by criteria failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Scoring error: {str(e)}")
