import type { ScoreResponse } from "./types";

const BASE = "/api/v1/agents";
const API_KEY = "I1yRx5ycm2uwuYR6RcNgm9HeGxiNctSe";

async function post<T>(endpoint: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}/${endpoint}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `API error ${res.status}`);
  }
  return res.json();
}

export async function scoreByTrial(trialId: string, limit: number) {
  return post<ScoreResponse>("score-patients", { trial_id: trialId, limit });
}

export async function scoreByCriteria(searchQuery: string, limit: number) {
  return post<ScoreResponse>("score-patients-criteria", {
    search_query: searchQuery,
    limit,
  });
}

export interface TrialOption {
  nct_id: string;
  conditions: string[];
}

export async function fetchTrialOptions(): Promise<TrialOption[]> {
  try {
    const res = await fetch("/data/valid_trial_ids.json");
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}
