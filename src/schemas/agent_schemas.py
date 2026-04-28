from pydantic import BaseModel, Field


class TextToSQLRequest(BaseModel):
    query: str = Field(..., min_length=3, description="Natural language question to convert to SQL")


class TextToSQLResponse(BaseModel):
    query: str
    generated_sql: str
    columns: list[str]
    results: list[dict]
    count: int


class RootWordSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, description="Search text to filter patients by")
    mode: str = Field(
        default="websearch",
        description="Query mode: websearch (Google-style), plain (AND all words), phrase (exact order)",
    )
    limit: int = Field(default=100, ge=1, le=1000)


class RootWordInfo(BaseModel):
    type: str
    original: str
    root_words: list[str]


class FilteredPatient(BaseModel):
    id: str
    display_patient_id: str | None
    age: int | None
    gender: str | None
    ethnicity: str | None
    state: str | None
    country: str | None
    conditions: list | None
    bmi: float | None
    smoker_status: str | None
    general_health: str | None
    relevance_score: float


class RootWordSearchResponse(BaseModel):
    query: str
    mode: str
    root_words: list[RootWordInfo]
    total_patients: int
    filtered_count: int
    filtered_patient_ids: list[str]
    patients: list[FilteredPatient]


class RootWordExtractRequest(BaseModel):
    query: str = Field(..., min_length=2, description="Text to extract root words from")


class RootWordExtractResponse(BaseModel):
    query: str
    root_words: list[RootWordInfo]


class TrialMatchRequest(BaseModel):
    trial_id: str = Field(..., min_length=3, description="NCT ID or UUID of the trial to match patients for")
    limit: int = Field(default=200, ge=1, le=1000)
    source: str = Field(default="kaggle", pattern="^(kaggle|fhir)$", description="Data source: kaggle (flat patients table) or fhir (normalised FHIR tables)")


class CriteriaMatchRequest(BaseModel):
    search_query: str = Field(..., min_length=2, description="Conditions/keywords to search patients by")
    sex: str = Field(default="ALL", description="Filter by sex: ALL, MALE, or FEMALE")
    min_age: int | None = Field(default=None, ge=0, le=120, description="Minimum patient age")
    max_age: int | None = Field(default=None, ge=0, le=120, description="Maximum patient age")
    min_bmi: float | None = Field(default=None, ge=0, le=100, description="Minimum BMI")
    max_bmi: float | None = Field(default=None, ge=0, le=100, description="Maximum BMI")
    smoker_status: str | None = Field(default=None, description="Filter by smoker status: Never, Former, Current etc.")
    limit: int = Field(default=200, ge=1, le=1000)
    source: str = Field(default="kaggle", pattern="^(kaggle|fhir)$", description="Data source: kaggle or fhir")


class AgeRange(BaseModel):
    min: int | None
    max: int | None


class CriteriaUsed(BaseModel):
    conditions: list[str]
    keywords: list[str]
    search_query: str
    sex_filter: str
    age_range: AgeRange
    eligibility_text: str


class MatchedPatient(BaseModel):
    id: str
    display_patient_id: str | None
    age: int | None
    gender: str | None
    ethnicity: str | None
    state: str | None
    country: str | None
    conditions: list | None
    bmi: float | None
    smoker_status: str | None
    general_health: str | None
    relevance_score: float


class TrialMatchPipeline(BaseModel):
    text_to_sql_prefiltered: int
    text_to_sql_query: str | None
    root_word_verified: int
    used_prefilter: bool
    cache_hit: bool = False
    stage1_ms: int | None = None
    stage2_ms: int | None = None
    total_ms: int | None = None


class TrialMatchResponse(BaseModel):
    trial_id: str | None
    trial_nct_id: str | None
    trial_title: str | None
    trial_status: str | None
    criteria_used: CriteriaUsed
    llm_extraction: dict | None = None
    pipeline: TrialMatchPipeline | None = None
    total_patients: int
    matched_count: int
    matched_patient_ids: list[str]
    patients: list[MatchedPatient]
    saved_to: str


class ScorePatientRequest(BaseModel):
    trial_id: str = Field(..., min_length=3, description="NCT ID or UUID of the trial to score patients for")
    limit: int = Field(default=200, ge=1, le=1000, description="Max patients to score from orchestrator")
    source: str = Field(default="kaggle", pattern="^(kaggle|fhir)$", description="Data source: kaggle or fhir")


class ScoreCriteriaRequest(BaseModel):
    search_query: str = Field(..., min_length=2, description="Free-text description of patient criteria")
    sex: str = Field(default="ALL", description="Filter by sex: ALL, MALE, or FEMALE")
    min_age: int | None = Field(default=None, ge=0, le=120)
    max_age: int | None = Field(default=None, ge=0, le=120)
    min_bmi: float | None = Field(default=None, ge=0, le=100)
    max_bmi: float | None = Field(default=None, ge=0, le=100)
    smoker_status: str | None = Field(default=None)
    limit: int = Field(default=200, ge=1, le=1000)
    source: str = Field(default="kaggle", pattern="^(kaggle|fhir)$", description="Data source: kaggle or fhir")


class ScoreBreakdownItem(BaseModel):
    score: float
    max: float
    details: str


class PatientSummary(BaseModel):
    age: int | None
    gender: str | None
    conditions: list | None
    state: str | None
    country: str | None
    bmi: float | None
    smoker_status: str | None
    general_health: str | None


class ScoredPatient(BaseModel):
    patient_id: str
    display_patient_id: str | None
    composite_score: float
    excluded: bool
    exclusion_reasons: list[str]
    patient_summary: PatientSummary
    breakdown: dict[str, ScoreBreakdownItem]


class ParsedEligibility(BaseModel):
    inclusion_rules: list[str]
    exclusion_rules: list[str]
    excluded_conditions: list[str]


class ScoreSummary(BaseModel):
    total_scored: int
    eligible_count: int
    excluded_count: int
    avg_score: float
    max_score: float
    min_score: float


class ScoreCriteriaUsed(BaseModel):
    conditions: list[str]
    keywords: list[str]
    search_query: str
    sex_filter: str
    age_range: AgeRange
    eligibility_text: str
    location_countries: list[str]
    location_cities: list[str]


class PipelineInfo(BaseModel):
    text_to_sql_prefiltered: int
    text_to_sql_query: str | None
    root_word_verified: int
    used_prefilter: bool
    cache_hit: bool = False
    stage1_ms: int | None = None
    stage2_ms: int | None = None
    stage3_ms: int | None = None
    total_ms: int | None = None


class ScorePatientResponse(BaseModel):
    trial_id: str
    trial_nct_id: str | None
    trial_title: str | None
    trial_status: str | None
    criteria_used: ScoreCriteriaUsed
    llm_extraction: dict | None = None
    pipeline: PipelineInfo
    parsed_eligibility: ParsedEligibility
    icd10_codes_mapped: int
    scoring_weights: dict[str, int]
    summary: ScoreSummary
    scored_patients: list[ScoredPatient]
    audit_log_id: str
