import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
import os
from pathlib import Path

API_BASE = "http://localhost:8001/api/v1/agents"
API_KEY = os.getenv("API_KEY", "I1yRx5ycm2uwuYR6RcNgm9HeGxiNctSe")
API_HEADERS = {"X-API-Key": API_KEY}

st.set_page_config(page_title="Ulalo", layout="wide", page_icon="U")

# ── Palette ──────────────────────────────────────────────────────────────
_BG         = "#0C1117"
_SURFACE    = "#141C24"
_SURFACE_HI = "#1B2530"
_BORDER     = "#243040"
_TEXT        = "#D8DEE4"
_TEXT_DIM    = "#7B8794"
_ACCENT      = "#5A9E94"   # teal
_ACCENT_DIM  = "#3D6E66"
_WARM        = "#C8965A"   # amber
_RED         = "#C06058"   # muted coral
_GREEN       = "#5A9E6A"

# ── Plotly theme ─────────────────────────────────────────────────────────
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Figtree, sans-serif", color=_TEXT_DIM, size=12),
    margin=dict(l=0, r=0, t=32, b=0),
    xaxis=dict(gridcolor=_BORDER, zerolinecolor=_BORDER),
    yaxis=dict(gridcolor=_BORDER, zerolinecolor=_BORDER),
)

# ── Load valid trial IDs ────────────────────────────────────────────────
VALID_TRIALS_PATH = Path(__file__).resolve().parent / "data" / "valid_trial_ids.json"

@st.cache_data
def load_valid_trials() -> list[dict]:
    if not VALID_TRIALS_PATH.exists():
        return []
    with open(VALID_TRIALS_PATH) as f:
        return json.load(f)

VALID_TRIALS = load_valid_trials()
TRIAL_OPTIONS = {
    f"{t['nct_id']}  —  {', '.join(t['conditions'][:2])}": t["nct_id"]
    for t in VALID_TRIALS
}
DEFAULT_TRIAL_IDX = next(
    (i for i, t in enumerate(VALID_TRIALS) if t["nct_id"] == "NCT06230718"), 0
)

# ── Global styles ────────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&family=Overpass+Mono:wght@400;600&display=swap');

/* ---- base ---- */
html, body, [class*="css"] {{
    font-family: 'Figtree', sans-serif;
}}
.block-container {{
    padding-top: 2rem;
    padding-bottom: 2rem;
    max-width: 1200px;
}}

/* ---- hide default streamlit chrome ---- */
#MainMenu, footer, header {{visibility: hidden;}}

/* ---- headings ---- */
h1 {{
    font-weight: 700 !important;
    letter-spacing: -0.03em !important;
    font-size: 1.75rem !important;
    color: {_TEXT} !important;
}}
h2 {{
    font-weight: 600 !important;
    letter-spacing: -0.02em !important;
    font-size: 1.2rem !important;
    color: {_TEXT} !important;
    margin-top: 1.5rem !important;
}}
h3 {{
    font-weight: 600 !important;
    font-size: 1rem !important;
    color: {_TEXT_DIM} !important;
    text-transform: uppercase;
    letter-spacing: 0.06em !important;
    font-size: 0.75rem !important;
}}

/* ---- stat blocks ---- */
.stat-row {{
    display: flex;
    gap: 1px;
    background: {_BORDER};
    border-radius: 8px;
    overflow: hidden;
    margin: 1rem 0;
}}
.stat-cell {{
    flex: 1;
    background: {_SURFACE};
    padding: 1rem 1.2rem;
    text-align: left;
}}
.stat-cell:first-child {{
    border-radius: 8px 0 0 8px;
}}
.stat-cell:last-child {{
    border-radius: 0 8px 8px 0;
}}
.stat-val {{
    font-family: 'Overpass Mono', monospace;
    font-size: 1.6rem;
    font-weight: 600;
    line-height: 1.1;
    color: {_TEXT};
}}
.stat-val.accent {{ color: {_ACCENT}; }}
.stat-val.warm   {{ color: {_WARM}; }}
.stat-val.red    {{ color: {_RED}; }}
.stat-val.green  {{ color: {_GREEN}; }}
.stat-label {{
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: {_TEXT_DIM};
    margin-top: 0.3rem;
}}

/* ---- tag pills ---- */
.tag {{
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 3px;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: 0.02em;
    margin-right: 0.3rem;
    margin-bottom: 0.3rem;
    background: {_SURFACE_HI};
    color: {_TEXT_DIM};
    border: 1px solid {_BORDER};
}}
.tag.teal {{ background: rgba(90,158,148,0.12); color: {_ACCENT}; border-color: rgba(90,158,148,0.25); }}
.tag.warm {{ background: rgba(200,150,90,0.12); color: {_WARM}; border-color: rgba(200,150,90,0.25); }}
.tag.red  {{ background: rgba(192,96,88,0.12); color: {_RED}; border-color: rgba(192,96,88,0.25); }}

/* ---- section divider ---- */
.section-rule {{
    border: none;
    border-top: 1px solid {_BORDER};
    margin: 2rem 0 1.5rem 0;
}}

/* ---- criteria panel ---- */
.criteria-panel {{
    background: {_SURFACE};
    border: 1px solid {_BORDER};
    border-radius: 8px;
    padding: 1rem 1.2rem;
    margin: 0.75rem 0;
    font-size: 0.85rem;
    color: {_TEXT_DIM};
    line-height: 1.6;
}}
.criteria-panel strong {{
    color: {_TEXT};
    font-weight: 500;
}}
.criteria-panel code {{
    font-family: 'Overpass Mono', monospace;
    font-size: 0.78rem;
    background: {_SURFACE_HI};
    padding: 0.1rem 0.35rem;
    border-radius: 3px;
    color: {_ACCENT};
}}

/* ---- patient detail panel ---- */
.detail-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1px;
    background: {_BORDER};
    border-radius: 8px;
    overflow: hidden;
    margin: 0.5rem 0;
}}
.detail-item {{
    background: {_SURFACE};
    padding: 0.6rem 1rem;
}}
.detail-key {{
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: {_TEXT_DIM};
}}
.detail-value {{
    font-size: 0.95rem;
    color: {_TEXT};
    font-weight: 500;
}}

/* ---- score bar ---- */
.score-bar-wrap {{
    margin-bottom: 0.75rem;
}}
.score-bar-header {{
    display: flex;
    justify-content: space-between;
    font-size: 0.78rem;
    margin-bottom: 0.25rem;
}}
.score-bar-name {{
    color: {_TEXT};
    font-weight: 500;
    text-transform: capitalize;
}}
.score-bar-nums {{
    font-family: 'Overpass Mono', monospace;
    color: {_TEXT_DIM};
}}
.score-bar-track {{
    height: 6px;
    background: {_SURFACE_HI};
    border-radius: 3px;
    overflow: hidden;
}}
.score-bar-fill {{
    height: 100%;
    border-radius: 3px;
    background: {_ACCENT};
    transition: width 0.3s ease;
}}
.score-bar-detail {{
    font-size: 0.7rem;
    color: {_TEXT_DIM};
    margin-top: 0.15rem;
}}

/* ---- radio + tabs overrides ---- */
div[data-baseweb="radio"] label {{
    font-size: 0.85rem !important;
}}
button[data-baseweb="tab"] {{
    font-size: 0.8rem !important;
    letter-spacing: 0.03em;
}}

/* ---- button ---- */
.stButton > button[kind="primary"] {{
    background: {_ACCENT} !important;
    border: none !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em;
}}
.stButton > button[kind="primary"]:hover {{
    background: {_ACCENT_DIM} !important;
}}

/* ---- expander ---- */
.streamlit-expanderHeader {{
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    color: {_TEXT_DIM} !important;
}}

/* ---- dataframe ---- */
.stDataFrame {{
    border: 1px solid {_BORDER} !important;
    border-radius: 8px !important;
    overflow: hidden;
}}

/* ---- spinner ---- */
.stSpinner > div > div {{
    border-top-color: {_ACCENT} !important;
}}

/* ---- hide metric label padding ---- */
[data-testid="stMetricValue"] {{
    font-family: 'Overpass Mono', monospace !important;
}}
</style>
""", unsafe_allow_html=True)


# ── API helpers ──────────────────────────────────────────────────────────

def api_post(endpoint: str, payload: dict, timeout: int = 120) -> dict | None:
    try:
        resp = requests.post(f"{API_BASE}/{endpoint}", json=payload, headers=API_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        st.error(f"API {resp.status_code}: {resp.json().get('detail', resp.text)}")
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to backend. Is uvicorn running on port 8001?")
    except Exception as e:
        st.error(f"Request failed: {e}")
    return None


# ── Rendering helpers ────────────────────────────────────────────────────

def stat_row(cells: list[tuple[str, str, str]]):
    """Render a row of stat cells. Each tuple: (value, label, color_class)."""
    inner = ""
    for val, label, cls in cells:
        inner += f'<div class="stat-cell"><div class="stat-val {cls}">{val}</div><div class="stat-label">{label}</div></div>'
    st.markdown(f'<div class="stat-row">{inner}</div>', unsafe_allow_html=True)


def score_bar(name: str, score: float, max_score: float, detail: str):
    """Render a single horizontal score bar."""
    pct = (score / max_score * 100) if max_score > 0 else 0
    st.markdown(f"""
    <div class="score-bar-wrap">
        <div class="score-bar-header">
            <span class="score-bar-name">{name}</span>
            <span class="score-bar-nums">{score:.1f} / {max_score:.0f}</span>
        </div>
        <div class="score-bar-track"><div class="score-bar-fill" style="width:{min(pct,100):.1f}%"></div></div>
        <div class="score-bar-detail">{detail}</div>
    </div>
    """, unsafe_allow_html=True)


def render_criteria(result):
    """Render criteria panel with LLM extraction awareness."""
    crit = result["criteria_used"]
    llm = result.get("llm_extraction")
    lines = []
    if llm:
        lines.append(f'<strong>Interpreted query</strong> <code>{crit["search_query"]}</code>')
        parts = []
        if crit["sex_filter"] != "ALL":
            parts.append(f'Sex: {crit["sex_filter"]}')
        age_min = crit["age_range"]["min"]
        age_max = crit["age_range"]["max"]
        if age_min or age_max:
            parts.append(f'Age: {age_min or "?"}&ndash;{age_max or "?"}')
        if llm.get("min_bmi") or llm.get("max_bmi"):
            parts.append(f'BMI: {llm.get("min_bmi") or "?"}&ndash;{llm.get("max_bmi") or "?"}')
        if llm.get("smoker_status"):
            parts.append(f'Smoker: {llm["smoker_status"]}')
        if parts:
            lines.append(f'<strong>Filters</strong> {" &middot; ".join(parts)}')
        lines.append(f'<strong>Your input</strong> <em>{crit.get("eligibility_text", "")}</em>')
    else:
        conds = ", ".join(crit.get("conditions", []))
        kws = ", ".join(crit.get("keywords", []))
        if conds:
            lines.append(f'<strong>Conditions</strong> {conds}')
        if kws:
            lines.append(f'<strong>Keywords</strong> {kws}')
        lines.append(f'<strong>Query</strong> <code>{crit["search_query"]}</code>')
        parts = [f'Sex: {crit["sex_filter"]}']
        parts.append(f'Age: {crit["age_range"]["min"] or "?"}&ndash;{crit["age_range"]["max"] or "?"}')
        lines.append(f'<strong>Filters</strong> {" &middot; ".join(parts)}')

    html = "<br>".join(lines)
    st.markdown(f'<div class="criteria-panel">{html}</div>', unsafe_allow_html=True)


def detail_grid(items: list[tuple[str, str]]):
    """Render a key/value detail grid."""
    inner = ""
    for key, val in items:
        inner += f'<div class="detail-item"><div class="detail-key">{key}</div><div class="detail-value">{val}</div></div>'
    st.markdown(f'<div class="detail-grid">{inner}</div>', unsafe_allow_html=True)


# ── Page ─────────────────────────────────────────────────────────────────

st.markdown("# Ulalo")
st.markdown(f'<span style="color:{_TEXT_DIM}; font-size:0.85rem;">Patient screening for clinical trials</span>', unsafe_allow_html=True)
st.markdown('<hr class="section-rule">', unsafe_allow_html=True)

# ── Input ────────────────────────────────────────────────────────────────

src_col, mode_col = st.columns([1, 2])
with src_col:
    data_source = st.radio("Data source", ["Kaggle (4K patients)", "FHIR (117 patients)"], horizontal=True, key="data_source")
    source_val = "fhir" if "FHIR" in data_source else "kaggle"
with mode_col:
    input_mode = st.radio("Input mode", ["Select Trial", "Custom Input"], horizontal=True, key="score_mode")

if input_mode == "Select Trial":
    oc1, oc2 = st.columns([3, 1])
    label = oc1.selectbox(
        "Clinical trial",
        options=list(TRIAL_OPTIONS.keys()),
        index=DEFAULT_TRIAL_IDX,
        key="score_trial_select",
    )
    score_trial_id = TRIAL_OPTIONS.get(label, "")
    score_limit = oc2.slider("Max patients", 10, 500, 200, key="score_limit")
else:
    search_query = st.text_area(
        "Describe patient criteria in plain language",
        placeholder="e.g. elderly women with heart problems and high BMI, diabetic patients over 50...",
        height=100,
        key="score_query",
    )
    score_limit = st.slider("Max patients", 10, 500, 200, key="score_limit_crit")

score_btn = st.button("Run Scoring", type="primary", key="score_btn", use_container_width=False)

# ── Results ──────────────────────────────────────────────────────────────

if score_btn:
    data = None
    if input_mode == "Select Trial" and score_trial_id:
        with st.spinner("Scoring patients..."):
            data = api_post("score-patients", {"trial_id": score_trial_id, "limit": score_limit, "source": source_val})
    elif input_mode == "Custom Input" and search_query and search_query.strip():
        with st.spinner("Interpreting criteria and scoring..."):
            data = api_post("score-patients-criteria", {"search_query": search_query.strip(), "limit": score_limit, "source": source_val})
    else:
        st.warning("Provide a trial or criteria before scoring.")

    if data:
        summary = data["summary"]

        # ── Trial header ─────────────────────────────────────────────
        title = data.get("trial_title", "N/A")
        nct = data.get("trial_nct_id")
        status = data.get("trial_status")
        header_parts = []
        if nct:
            header_parts.append(f'<span class="tag teal">{nct}</span>')
        if status:
            header_parts.append(f'<span class="tag">{status}</span>')
        st.markdown(f'## {title}', unsafe_allow_html=True)
        if header_parts:
            st.markdown(" ".join(header_parts), unsafe_allow_html=True)

        # ── Key metrics ──────────────────────────────────────────────
        stat_row([
            (str(summary["total_scored"]), "Scored", ""),
            (str(summary["eligible_count"]), "Eligible", "accent"),
            (str(summary["excluded_count"]), "Excluded", "red"),
            (str(summary["avg_score"]), "Avg Score", "warm"),
            (str(summary["max_score"]), "High", "green"),
            (str(summary["min_score"]), "Low", ""),
            (str(data.get("icd10_codes_mapped", 0)), "ICD-10 Mapped", ""),
        ])

        # ── Criteria ─────────────────────────────────────────────────
        render_criteria(data)

        with st.expander("Eligibility rules"):
            parsed = data["parsed_eligibility"]
            crit = data["criteria_used"]
            lc, rc = st.columns(2)
            with lc:
                st.markdown(f"**Conditions** {', '.join(crit.get('conditions', [])) or 'None'}")
                countries = ', '.join(crit.get('location_countries', []))
                if countries:
                    st.markdown(f"**Countries** {countries}")
            with rc:
                if parsed["inclusion_rules"]:
                    st.markdown("**Inclusion**")
                    for r in parsed["inclusion_rules"][:8]:
                        st.markdown(f"- {r}")
                if parsed["exclusion_rules"]:
                    st.markdown("**Exclusion**")
                    for r in parsed["exclusion_rules"][:8]:
                        st.markdown(f"- {r}")
                if parsed["excluded_conditions"]:
                    excl_tags = " ".join(f'<span class="tag red">{c}</span>' for c in set(parsed["excluded_conditions"]))
                    st.markdown(f"**Excluded conditions** {excl_tags}", unsafe_allow_html=True)

        patients = data["scored_patients"]
        eligible_patients = [p for p in patients if not p["excluded"]]

        if not patients:
            st.info("No patients found. Try different criteria or increase the limit.")
        elif not eligible_patients:
            st.warning(f"All {len(patients)} matched patients were excluded by eligibility criteria.")

        # ── Charts ───────────────────────────────────────────────────
        if eligible_patients:
            st.markdown('<hr class="section-rule">', unsafe_allow_html=True)

            ch1, ch2 = st.columns([3, 2])

            with ch1:
                st.markdown("### Score Distribution")
                scores = [p["composite_score"] for p in eligible_patients]
                fig = px.histogram(
                    x=scores, nbins=20,
                    labels={"x": "Score", "y": "Count"},
                    color_discrete_sequence=[_ACCENT],
                )
                fig.update_layout(**PLOTLY_LAYOUT, height=300, bargap=0.08)
                fig.update_layout(xaxis_title="Composite Score", yaxis_title="Count")
                st.plotly_chart(fig, use_container_width=True)

            with ch2:
                st.markdown("### Top Patient Breakdown")
                top = eligible_patients[0]
                bd = top["breakdown"]
                cats = ["Condition", "Age", "Sex", "Geography", "Health"]
                vals = [bd["condition"]["score"], bd["age"]["score"], bd["sex"]["score"], bd["geography"]["score"], bd["health"]["score"]]
                maxv = [bd["condition"]["max"], bd["age"]["max"], bd["sex"]["max"], bd["geography"]["max"], bd["health"]["max"]]
                fig_r = go.Figure()
                fig_r.add_trace(go.Scatterpolar(
                    r=maxv + [maxv[0]], theta=cats + [cats[0]],
                    fill="toself", name="Max",
                    line=dict(color=_BORDER, width=1), fillcolor="rgba(36,48,64,0.4)",
                ))
                fig_r.add_trace(go.Scatterpolar(
                    r=vals + [vals[0]], theta=cats + [cats[0]],
                    fill="toself", name="Score",
                    line=dict(color=_ACCENT, width=2), fillcolor="rgba(90,158,148,0.15)",
                ))
                fig_r.update_layout(
                    **PLOTLY_LAYOUT, height=300, showlegend=False,
                    polar=dict(
                        bgcolor="rgba(0,0,0,0)",
                        radialaxis=dict(visible=True, range=[0, 35], gridcolor=_BORDER, color=_TEXT_DIM, tickfont=dict(size=10)),
                        angularaxis=dict(gridcolor=_BORDER, color=_TEXT_DIM),
                    ),
                )
                pid = top.get('display_patient_id') or top['patient_id'][:8]
                st.markdown(f'<span style="font-family:Overpass Mono,monospace; font-size:0.8rem; color:{_TEXT_DIM};">{pid} &mdash; {top["composite_score"]}/100</span>', unsafe_allow_html=True)
                st.plotly_chart(fig_r, use_container_width=True)

        # ── Patient table ────────────────────────────────────────────
        st.markdown('<hr class="section-rule">', unsafe_allow_html=True)
        st.markdown("### Ranked Patients")

        t_elig, t_excl, t_raw = st.tabs(["Eligible", "Excluded", "Raw"])
        with t_elig:
            if eligible_patients:
                rows = []
                for i, p in enumerate(eligible_patients, 1):
                    ps = p["patient_summary"]
                    bd = p["breakdown"]
                    rows.append({
                        "#": i,
                        "Patient": p.get("display_patient_id") or p["patient_id"][:8],
                        "Score": p["composite_score"],
                        "Cond": bd["condition"]["score"],
                        "Age": bd["age"]["score"],
                        "Sex": bd["sex"]["score"],
                        "Geo": bd["geography"]["score"],
                        "Health": bd["health"]["score"],
                        "Age Val": ps.get("age", "?"),
                        "Gender": ps.get("gender", "?"),
                        "State": ps.get("state", "?"),
                        "Conditions": ", ".join(ps.get("conditions") or []),
                    })
                df = pd.DataFrame(rows)
                st.dataframe(
                    df.style.background_gradient(
                        subset=["Score"], cmap="YlGn", vmin=0, vmax=100,
                    ),
                    use_container_width=True, height=450,
                )
            else:
                st.info("No eligible patients.")
        with t_excl:
            excl = [p for p in patients if p["excluded"]]
            if excl:
                st.dataframe(pd.DataFrame([{
                    "Patient": p.get("display_patient_id") or p["patient_id"][:8],
                    "Conditions": ", ".join(p["patient_summary"].get("conditions") or []),
                    "Reasons": "; ".join(p["exclusion_reasons"]),
                } for p in excl]), use_container_width=True)
            else:
                st.markdown(f'<span style="color:{_TEXT_DIM}; font-size:0.85rem;">No patients excluded.</span>', unsafe_allow_html=True)
        with t_raw:
            st.json(data)

        # ── Patient detail inspector ─────────────────────────────────
        if eligible_patients:
            st.markdown('<hr class="section-rule">', unsafe_allow_html=True)
            st.markdown("### Patient Inspector")

            opts = {
                f"#{i+1}  {p.get('display_patient_id', p['patient_id'][:8])}  ({p['composite_score']})": p
                for i, p in enumerate(eligible_patients)
            }
            sel = opts[st.selectbox("Select patient", list(opts.keys()), key="score_patient_sel")]

            col_info, col_score = st.columns([1, 1], gap="large")

            with col_info:
                ps = sel["patient_summary"]
                items = [
                    ("Age", str(ps.get("age", "?"))),
                    ("Gender", str(ps.get("gender", "?"))),
                    ("State", str(ps.get("state", "?"))),
                    ("Country", str(ps.get("country", "?"))),
                    ("BMI", f'{ps["bmi"]:.1f}' if ps.get("bmi") else "?"),
                    ("Smoker", str(ps.get("smoker_status", "?"))),
                    ("Health", str(ps.get("general_health", "?"))),
                    ("Conditions", ", ".join(ps.get("conditions") or []) or "None"),
                ]
                detail_grid(items)

            with col_score:
                for factor, d in sel["breakdown"].items():
                    score_bar(factor, d["score"], d["max"], d["details"])

        # ── Footer ───────────────────────────────────────────────────
        st.markdown(f'<div style="margin-top:2rem; font-size:0.72rem; color:{_TEXT_DIM};">Audit log {data.get("audit_log_id", "N/A")}</div>', unsafe_allow_html=True)
