export interface AgeRange {
  min: number | null;
  max: number | null;
}

export interface CriteriaUsed {
  conditions: string[];
  keywords: string[];
  search_query: string;
  sex_filter: string;
  age_range: AgeRange;
  eligibility_text: string;
  location_countries?: string[];
  location_cities?: string[];
}

export interface LlmExtraction {
  search_query: string;
  sex: string;
  min_age: number | null;
  max_age: number | null;
  min_bmi: number | null;
  max_bmi: number | null;
  smoker_status: string | null;
}

export interface ScoreBreakdownItem {
  score: number;
  max: number;
  details: string;
}

export interface PatientSummary {
  age: number | null;
  gender: string | null;
  conditions: string[] | null;
  state: string | null;
  country: string | null;
  bmi: number | null;
  smoker_status: string | null;
  general_health: string | null;
}

export interface ScoredPatient {
  patient_id: string;
  display_patient_id: string | null;
  composite_score: number;
  excluded: boolean;
  exclusion_reasons: string[];
  patient_summary: PatientSummary;
  breakdown: Record<string, ScoreBreakdownItem>;
}

export interface ParsedEligibility {
  inclusion_rules: string[];
  exclusion_rules: string[];
  excluded_conditions: string[];
}

export interface ScoreSummary {
  total_scored: number;
  eligible_count: number;
  excluded_count: number;
  avg_score: number;
  max_score: number;
  min_score: number;
}

export interface PipelineInfo {
  text_to_sql_prefiltered: number;
  text_to_sql_query: string | null;
  root_word_verified: number;
  used_prefilter: boolean;
  cache_hit: boolean;
  stage1_ms: number | null;
  stage2_ms: number | null;
  stage3_ms: number | null;
  total_ms: number | null;
}

export interface ScoreResponse {
  trial_id: string;
  trial_nct_id: string | null;
  trial_title: string | null;
  trial_status: string | null;
  criteria_used: CriteriaUsed;
  llm_extraction: LlmExtraction | null;
  pipeline: PipelineInfo;
  parsed_eligibility: ParsedEligibility;
  icd10_codes_mapped: number;
  scoring_weights: Record<string, number>;
  summary: ScoreSummary;
  scored_patients: ScoredPatient[];
  audit_log_id: string;
}

export interface TrialOption {
  nct_id: string;
  conditions: string[];
}
