import { useState, useEffect, useCallback, useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar,
} from "recharts";
import { scoreByTrial, scoreByCriteria, fetchTrialOptions } from "./api";
import type { ScoreResponse, ScoredPatient } from "./types";
import type { TrialOption } from "./api";

const cx = (...p: (string | false | undefined | null)[]) => p.filter(Boolean).join(" ");

function binScores(pts: ScoredPatient[], n = 20) {
  const w = 100 / n;
  const o = Array.from({ length: n }, (_, i) => ({ range: String(Math.round(i * w)), count: 0 }));
  for (const p of pts) o[Math.min(Math.floor(p.composite_score / w), n - 1)].count++;
  return o;
}

/* ── Logo SVG ────────────────────────────────────────────────────── */

function Logo() {
  return (
    <svg viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M8.5 7.5v9c0 3 2.5 5.5 5.5 5.5s5.5-2.5 5.5-5.5v-9"
        stroke="#fff"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <circle cx="14" cy="5" r="1.8" fill="#fff" />
      <path
        d="M9 15.5h10"
        stroke="#fff"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.5"
      />
    </svg>
  );
}

/* ── Collapsible ─────────────────────────────────────────────────── */

function Collapsible({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="collapse">
      <button className="collapse-btn" onClick={() => setOpen(!open)}>
        {label}
        <span className={cx("collapse-arrow", open && "open")}>&#9660;</span>
      </button>
      {open && <div className="collapse-body">{children}</div>}
    </div>
  );
}

/* ── CriteriaBlock ───────────────────────────────────────────────── */

function CriteriaBlock({ data }: { data: ScoreResponse }) {
  const c = data.criteria_used;
  const llm = data.llm_extraction;
  if (llm) {
    const parts: string[] = [];
    if (c.sex_filter !== "ALL") parts.push(`Sex: ${c.sex_filter}`);
    if (c.age_range.min || c.age_range.max) parts.push(`Age: ${c.age_range.min ?? "?"}–${c.age_range.max ?? "?"}`);
    if (llm.min_bmi || llm.max_bmi) parts.push(`BMI: ${llm.min_bmi ?? "?"}–${llm.max_bmi ?? "?"}`);
    if (llm.smoker_status) parts.push(`Smoker: ${llm.smoker_status}`);
    return (
      <div className="criteria">
        <div><strong>Interpreted query</strong> <code>{c.search_query}</code></div>
        {parts.length > 0 && <div><strong>Filters</strong> {parts.join(" · ")}</div>}
        {c.eligibility_text && <div style={{ fontStyle: "italic", marginTop: 2 }}><strong>Your input</strong> {c.eligibility_text}</div>}
      </div>
    );
  }
  return (
    <div className="criteria">
      {c.conditions.length > 0 && <div><strong>Conditions</strong> {c.conditions.join(", ")}</div>}
      {c.keywords.length > 0 && <div><strong>Keywords</strong> {c.keywords.join(", ")}</div>}
      <div><strong>Query</strong> <code>{c.search_query}</code></div>
      <div><strong>Filters</strong> Sex: {c.sex_filter} · Age: {c.age_range.min ?? "?"}–{c.age_range.max ?? "?"}</div>
    </div>
  );
}

/* ── EligibilityRules ────────────────────────────────────────────── */

function EligibilityRules({ data }: { data: ScoreResponse }) {
  const p = data.parsed_eligibility;
  const c = data.criteria_used;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
      <div>
        <strong style={{ color: "var(--text)" }}>Conditions</strong>
        <div style={{ marginTop: 4 }}>{c.conditions.length ? c.conditions.join(", ") : "None"}</div>
        {(c.location_countries?.length ?? 0) > 0 && (
          <div style={{ marginTop: 8 }}><strong style={{ color: "var(--text)" }}>Countries</strong> {c.location_countries!.join(", ")}</div>
        )}
      </div>
      <div>
        {p.inclusion_rules.length > 0 && (
          <><strong style={{ color: "var(--text)" }}>Inclusion</strong>
            <ul style={{ margin: "4px 0 0 1.2rem" }}>{p.inclusion_rules.slice(0, 8).map((r, i) => <li key={i}>{r}</li>)}</ul></>
        )}
        {p.exclusion_rules.length > 0 && (
          <><strong style={{ color: "var(--text)", display: "block", marginTop: 8 }}>Exclusion</strong>
            <ul style={{ margin: "4px 0 0 1.2rem" }}>{p.exclusion_rules.slice(0, 8).map((r, i) => <li key={i}>{r}</li>)}</ul></>
        )}
        {p.excluded_conditions.length > 0 && (
          <div style={{ marginTop: 8 }}>{[...new Set(p.excluded_conditions)].map((c, i) => <span className="tag tag-red" key={i}>{c}</span>)}</div>
        )}
      </div>
    </div>
  );
}

/* ── PatientExpandedRow ──────────────────────────────────────────── */

function PatientExpandedRow({ patient }: { patient: ScoredPatient }) {
  const ps = patient.patient_summary;
  const items: [string, string][] = [
    ["Age", String(ps.age ?? "—")], ["Gender", String(ps.gender ?? "—")],
    ["State", String(ps.state ?? "—")], ["Country", String(ps.country ?? "—")],
    ["BMI", ps.bmi != null ? ps.bmi.toFixed(1) : "—"], ["Smoker", String(ps.smoker_status ?? "—")],
    ["Health", String(ps.general_health ?? "—")], ["Conditions", (ps.conditions ?? []).join(", ") || "—"],
  ];
  return (
    <div className="patient-detail">
      <div className="detail-grid">
        {items.map(([k, v]) => (
          <div className="detail-cell" key={k}>
            <div className="detail-k">{k}</div>
            <div className="detail-v">{v}</div>
          </div>
        ))}
      </div>
      <div className="bar-group">
        {Object.entries(patient.breakdown).map(([factor, d]) => {
          const pct = d.max > 0 ? (d.score / d.max) * 100 : 0;
          const fc = `f-${factor}`;
          return (
            <div key={factor}>
              <div className="bar-head">
                <span className={cx("bar-name", fc)}>{factor}</span>
                <span className="bar-nums">{d.score.toFixed(1)} / {d.max}</span>
              </div>
              <div className="bar-track"><div className={cx("bar-fill", fc)} style={{ width: `${Math.min(pct, 100)}%` }} /></div>
              <div className="bar-note">{d.details}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── PatientRow ──────────────────────────────────────────────────── */

function PatientRow({ rank, patient, isOpen, onToggle }: {
  rank: number; patient: ScoredPatient; isOpen: boolean; onToggle: () => void;
}) {
  const ps = patient.patient_summary;
  const bd = patient.breakdown;
  return (
    <>
      <tr className={isOpen ? "active" : ""} onClick={onToggle}>
        <td className="c-rank">{rank}</td>
        <td>{patient.display_patient_id ?? patient.patient_id.slice(0, 8)}</td>
        <td className="c-mono">
          <span className="score-pill">
            {patient.composite_score}
            <span className="score-track">
              <span className={cx("score-fill",
                patient.composite_score >= 70 && "s-high",
                patient.composite_score >= 40 && patient.composite_score < 70 && "s-mid",
                patient.composite_score < 40 && "s-low",
              )} style={{ width: `${patient.composite_score}%` }} />
            </span>
          </span>
        </td>
        <td className="c-dim">{bd.condition.score}</td>
        <td className="c-dim">{bd.age.score}</td>
        <td className="c-dim">{bd.sex.score}</td>
        <td className="c-dim">{bd.geography.score}</td>
        <td className="c-dim">{bd.health.score}</td>
        <td className="c-dim">{ps.age ?? "?"}</td>
        <td className="c-dim">{ps.gender ?? "?"}</td>
        <td className="c-dim">{ps.state ?? "?"}</td>
        <td className="c-cond">{(ps.conditions ?? []).join(", ")}</td>
      </tr>
      {isOpen && (
        <tr><td colSpan={12} style={{ padding: 0, border: "none" }}><PatientExpandedRow patient={patient} /></td></tr>
      )}
    </>
  );
}

/* ── App ─────────────────────────────────────────────────────────── */

export default function App() {
  const [trials, setTrials] = useState<TrialOption[]>([]);
  const [mode, setMode] = useState<"trial" | "custom">("trial");
  const [trial, setTrial] = useState("");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(200);
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ScoreResponse | null>(null);
  const [tab, setTab] = useState<"eligible" | "excluded" | "raw">("eligible");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    fetchTrialOptions().then(t => {
      setTrials(t);
      const i = t.findIndex(x => x.nct_id === "NCT06230718");
      setTrial(i >= 0 ? t[i].nct_id : t[0]?.nct_id ?? "");
    });
  }, []);

  const run = useCallback(async () => {
    setError(null); setLoading(true); setData(null); setStep(0); setExpandedId(null);
    const timer = setInterval(() => setStep(s => Math.min(s + 1, 3)), 1200);
    try {
      const r = mode === "trial" ? await scoreByTrial(trial, limit) : await scoreByCriteria(query.trim(), limit);
      setData(r); setTab("eligible");
    } catch (e: unknown) { setError(e instanceof Error ? e.message : "Unknown error"); }
    finally { clearInterval(timer); setLoading(false); }
  }, [mode, trial, query, limit]);

  const canRun = mode === "trial" ? !!trial : query.trim().length > 2;
  const eligible = useMemo(() => data?.scored_patients.filter(p => !p.excluded) ?? [], [data]);
  const excluded = useMemo(() => data?.scored_patients.filter(p => p.excluded) ?? [], [data]);

  const trialOpts = useMemo(() => trials.map(t => ({
    value: t.nct_id, label: `${t.nct_id}  —  ${t.conditions.slice(0, 2).join(", ")}`,
  })), [trials]);

  const sentence = useMemo(() => {
    if (!data) return null;
    const s = data.summary;
    return (
      <>Found <span className="hl-accent">{s.eligible_count} eligible</span> of {s.total_scored} scored
        {s.excluded_count > 0 && <>, <span className="hl-red">{s.excluded_count} excluded</span></>}
        . Average score <span className="hl-warm">{s.avg_score}</span>
        {s.max_score > 0 && <>, best match <strong>{s.max_score}</strong></>}.</>
    );
  }, [data]);

  return (
    <div className="app">
      {/* Brand */}
      <div className="brand">
        <div className="brand-mark"><Logo /></div>
        <h1>Ulalo</h1>
      </div>
      <p className="tagline">Patient screening for clinical trials</p>

      {/* Input */}
      <section className="input-section">
        <div className="mode-toggle">
          <button className={mode === "trial" ? "active" : ""} onClick={() => setMode("trial")}>Select Trial</button>
          <button className={mode === "custom" ? "active" : ""} onClick={() => setMode("custom")}>Custom Input</button>
        </div>

        {mode === "trial" ? (
          <div className="input-row">
            <div className="field">
              <label>Clinical Trial</label>
              <select value={trial} onChange={e => setTrial(e.target.value)}>
                {trialOpts.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div className="field-sm">
              <label>Max patients</label>
              <div className="range-wrap">
                <input type="range" min={10} max={500} step={10} value={limit} onChange={e => setLimit(+e.target.value)} />
                <span className="range-val">{limit}</span>
              </div>
            </div>
            <button className="btn btn-accent" disabled={!canRun || loading} onClick={run}>Run Scoring</button>
          </div>
        ) : (
          <>
            <div className="field" style={{ marginBottom: "0.75rem" }}>
              <label>Describe patient criteria</label>
              <textarea value={query} onChange={e => setQuery(e.target.value)}
                placeholder="e.g. elderly women with heart problems, diabetic patients over 50 with high BMI..." rows={3} />
            </div>
            <div className="input-row">
              <div className="field-sm">
                <label>Max patients</label>
                <div className="range-wrap">
                  <input type="range" min={10} max={500} step={10} value={limit} onChange={e => setLimit(+e.target.value)} />
                  <span className="range-val">{limit}</span>
                </div>
              </div>
              <button className="btn btn-accent" disabled={!canRun || loading} onClick={run}>Run Scoring</button>
            </div>
          </>
        )}
      </section>

      <hr className="rule" />

      {/* Loading */}
      {loading && (
        <div className="loading">
          <div className="loading-ring" />
          <div className="loading-text">{mode === "custom" ? "Interpreting criteria & scoring" : "Scoring patients against trial"}</div>
          <div className="load-pills">
            {(mode === "custom" ? ["Interpreting", "Matching", "Scoring", "Ranking"] : ["Pre-filtering", "Matching", "Scoring", "Ranking"])
              .map((s, i) => <span key={s} className={cx("load-pill", i <= step && "on")}>{s}</span>)}
          </div>
        </div>
      )}

      {error && <div className="error-msg">{error}</div>}

      {/* Results */}
      {data && !loading && (
        <div className="results">
          <div className="result-hero">
            <div className="result-title">{data.trial_title ?? "Results"}</div>
            <div className="result-tags">
              {data.trial_nct_id && <span className="tag tag-accent">{data.trial_nct_id}</span>}
              {data.trial_status && <span className="tag">{data.trial_status}</span>}
              {data.pipeline.total_ms != null && <span className="tag">{(data.pipeline.total_ms / 1000).toFixed(1)}s</span>}
            </div>
          </div>

          {sentence && <p className="summary-sentence">{sentence}</p>}

          <div className="metrics">
            {([
              [data.summary.total_scored, "Scored", "", "m-default"],
              [data.summary.eligible_count, "Eligible", "c-accent", "m-accent"],
              [data.summary.excluded_count, "Excluded", "c-red", "m-red"],
              [data.summary.avg_score, "Avg Score", "c-warm", "m-warm"],
              [data.summary.max_score, "High", "c-green", "m-green"],
              [data.summary.min_score, "Low", "", "m-default"],
              [data.icd10_codes_mapped, "ICD-10", "", "m-default"],
            ] as [number, string, string, string][]).map(([v, l, vc, cc], i) => (
              <div className={cx("metric", cc)} key={i}>
                <div className={cx("metric-val", vc)}>{v}</div>
                <div className="metric-label">{l}</div>
              </div>
            ))}
          </div>

          <CriteriaBlock data={data} />

          <Collapsible label="Eligibility rules">
            <EligibilityRules data={data} />
          </Collapsible>

          {eligible.length > 0 && (
            <>
              <hr className="rule" />
              <div className="charts">
                <div className="chart-pane">
                  <div className="chart-label">Score Distribution</div>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={binScores(eligible)} barCategoryGap="12%">
                      <XAxis dataKey="range" tick={{ fill: "#636D79", fontSize: 10, fontFamily: "JetBrains Mono" }} axisLine={{ stroke: "#242D3A" }} tickLine={false} interval={3} />
                      <YAxis tick={{ fill: "#636D79", fontSize: 10, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} width={28} />
                      <Tooltip contentStyle={{ background: "#131920", border: "1px solid #242D3A", borderRadius: 8, fontSize: 12, fontFamily: "Manrope", color: "#E2E6EB" }} cursor={{ fill: "rgba(77,155,138,0.06)" }} />
                      <Bar dataKey="count" fill="#4D9B8A" radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="chart-pane">
                  <div className="chart-label">Top Patient</div>
                  <div style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: "var(--text-3)", marginBottom: 4 }}>
                    {eligible[0].display_patient_id ?? eligible[0].patient_id.slice(0, 8)} — {eligible[0].composite_score}/100
                  </div>
                  <ResponsiveContainer width="100%" height={210}>
                    <RadarChart data={["condition", "age", "sex", "geography", "health"].map(k => ({ f: k[0].toUpperCase() + k.slice(1), score: eligible[0].breakdown[k].score, max: eligible[0].breakdown[k].max }))} cx="50%" cy="50%" outerRadius="72%">
                      <PolarGrid stroke="#242D3A" />
                      <PolarAngleAxis dataKey="f" tick={{ fill: "#636D79", fontSize: 11, fontFamily: "Manrope" }} />
                      <PolarRadiusAxis angle={90} domain={[0, 35]} tick={false} axisLine={false} />
                      <Radar dataKey="max" stroke="#242D3A" fill="#242D3A" fillOpacity={0.35} />
                      <Radar dataKey="score" stroke="#4D9B8A" fill="#4D9B8A" fillOpacity={0.12} strokeWidth={2} />
                    </RadarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </>
          )}

          <hr className="rule" />
          <p className="sec-title">Ranked Patients</p>
          <div className="tabs">
            {([["eligible", `Eligible (${eligible.length})`], ["excluded", `Excluded (${excluded.length})`], ["raw", "Raw"]] as const).map(([id, l]) => (
              <button key={id} className={cx("tab", tab === id && "active")} onClick={() => setTab(id)}>{l}</button>
            ))}
          </div>

          {tab === "eligible" && (
            <div className="tbl-wrap"><div className="tbl-scroll">
              <table className="tbl"><thead><tr>
                <th>#</th><th>Patient</th><th>Score</th><th>Cond</th><th>Age</th><th>Sex</th><th>Geo</th><th>Health</th><th>Age</th><th>Gender</th><th>State</th><th>Conditions</th>
              </tr></thead><tbody>
                {eligible.map((p, i) => (
                  <PatientRow key={p.patient_id} rank={i + 1} patient={p}
                    isOpen={expandedId === p.patient_id}
                    onToggle={() => setExpandedId(expandedId === p.patient_id ? null : p.patient_id)} />
                ))}
              </tbody></table>
            </div></div>
          )}

          {tab === "excluded" && (
            <div className="tbl-wrap">
              {excluded.length === 0 ? <div style={{ padding: "1.5rem", color: "var(--text-3)", fontSize: "0.82rem", textAlign: "center" }}>No patients excluded.</div> : (
                <div className="tbl-scroll"><table className="tbl"><thead><tr><th>Patient</th><th>Conditions</th><th>Reasons</th></tr></thead><tbody>
                  {excluded.map(p => (
                    <tr key={p.patient_id}>
                      <td>{p.display_patient_id ?? p.patient_id.slice(0, 8)}</td>
                      <td className="c-cond">{(p.patient_summary.conditions ?? []).join(", ")}</td>
                      <td className="c-cond">{p.exclusion_reasons.join("; ")}</td>
                    </tr>
                  ))}
                </tbody></table></div>
              )}
            </div>
          )}

          {tab === "raw" && <div className="raw-json">{JSON.stringify(data, null, 2)}</div>}

          <div className="audit">audit {data.audit_log_id}</div>
        </div>
      )}

      {/* Empty */}
      {!data && !loading && !error && (
        <div className="empty">
          <div className="empty-visual"><div className="dot" /></div>
          <h2>Ready to screen</h2>
          <p>Select a clinical trial or describe patient criteria, then run scoring to see ranked matches.</p>
        </div>
      )}
    </div>
  );
}
