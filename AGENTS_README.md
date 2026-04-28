# Ulalo Agents — Quick Start

## Setup

```bash
cd ulalo-backend
cp .env.example .env         
uv sync                     
```

Required `.env` keys:
```
DATABASE_URL=postgresql://user:pass@host:port/db
OPENROUTER_API_KEY=sk-or-v1-...
```

## Start Backend

```bash
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger docs: http://localhost:8000/docs

## Start Streamlit UI

```bash
.venv/bin/python -m streamlit run streamlit_app.py
```

Opens at http://localhost:8501

## Agents

| Agent | Tab in Streamlit | What it does |
|---|---|---|
| **Text-to-SQL** | Text-to-SQL | Ask questions in English, get SQL + results |
| **Root Word Search** | Root Word Search | Filter patients by condition using PostgreSQL stemming |
| **Orchestrator** | Orchestrator | Match patients to a trial (by NCT ID or manual criteria) |
| **Scoring Agent** | Scoring Agent | Score matched patients 0-100 with breakdown |

## Testing Each Agent

### Text-to-SQL
- Go to **Text-to-SQL** tab
- Type: `How many patients have diabetes?`
- Click **Run Query**

### Root Word Search
- Go to **Root Word Search** tab
- Type: `diabetes cardiac`
- Click **Search Patients**

### Orchestrator
- Go to **Orchestrator** tab
- Enter Trial ID: `NCT06230718`
- Click **Match Patients**

### Scoring Agent
- Go to **Scoring Agent** tab
- Enter Trial ID: `NCT06230718` (Stroke) or `NCT07003997` (Depression)
- Click **Run Scoring**
- Check the score distribution, radar chart, ranked table, and exclusion details


