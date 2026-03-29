# HealthScribe — PROJECT.md

## What is this project?
HealthScribe is a personal medical records management system with a hybrid AI extraction pipeline and a RAG-powered chat interface.

## Tech Stack
- **Frontend**: React (Vite), Vanilla CSS, Axios
- **Backend**: Django 5.2, Django REST Framework, SimpleJWT, SQLite (dev) / PostgreSQL (prod)
- **AI Service**: FastAPI, Google Gemini 2.5 Flash, Sarvam AI (OCR), LangChain, ChromaDB
- **Testing**: pytest (18 AI service tests), Django TestCase (30 backend tests)

## Architecture
3-tier microservice:
1. `frontend/` — React SPA on port 5173
2. `backend/` — Django REST API on port 8000
3. `ai_service/` — FastAPI AI service on port 8001

## How to run (all 3 services)
```bash
# Terminal 1
cd frontend && npm run dev

# Terminal 2
cd backend && python manage.py runserver

# Terminal 3
cd ai_service && uvicorn main:app --reload --port 8001
```

## Key Decisions Made
- **SQLite in dev** — Settings configured for SQLite; env vars exist for switching to Postgres.
- **gemini-2.5-flash** — Upgraded from 2.0-flash due to free-tier quota limits (limit: 0 on flash 2.0 for this API key).
- **models/gemini-embedding-001** — Only embedding model available on this API key (text-embedding-004 returns 404).
- **Vanilla CSS** — Replaced Tailwind with plain CSS to eliminate AI-generated aesthetic. Uses system fonts, teal color (#1a8a6e), no glassmorphism.
- **ChromaDB on disk** — Persisted to `ai_service/chroma_db/`. Clear this folder if switching embedding models.

## Constraints
- No paid AI plan — free tier only. Gemini 2.5 Flash works; 2.0 Flash does not.
- Windows dev environment (PowerShell).
- User is a junior/student developer — code style and comments should reflect this.
