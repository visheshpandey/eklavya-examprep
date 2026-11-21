# NOTES — Eklavya Exam Prep (PS02)

Base: copy of Eklavya (source folder untouched, read-only). Stack kept as-is.

1. Backend: FastAPI (Python 3.11) in `backend/` — `main.py`, `app/{api/routes,ai,domain,services,agents,prompts}`.
2. Frontend: plain JavaScript ES modules + CSS (NO React/bundler) in `frontend/`; served locally by `frontend/serve.py`. Graph UI must be hand-built (SVG/canvas), not React Flow.
3. LLM: Google Gemini via `google-genai` (`GEMINI_MODEL=gemini-3.1-flash-lite`, embeddings `gemini-embedding-001`); wrapper in `backend/app/ai/gemini.py`.
4. Voice: live voice tutor via Gemini Live (`app/ai/live.py`, `frontend/js/services/voice-client.js`); browser dictation (SpeechRecognition) in `frontend/js/lib/dictation.js` — use this for the "explain your reasoning" mic.
5. DB: SQLite (`backend/data/eklavya.db`, gitignored) or Postgres via `DATABASE_URL`; see `app/db.py`.
6. Env: `backend/.env` (from `.env.example`; only `app/config.py` reads it). Needs `GEMINI_API_KEY`. Ports: backend 5002 locally (frontend/config.js).
7. Deploy: backend on Render (`render.yaml`, free plan, rootDir backend), frontend on Vercel (`frontend/vercel.json`, CSP lists the API origin).
8. Existing reusable domain code: `domain/misconceptions.py`, `domain/mastery.py`, `domain/revision.py` (spaced repetition), `domain/concept_map.py`.
9. DEPLOY SAFETY: original Eklavya URLs (Render/Vercel) were replaced with `REPLACE-ME-ps02*` placeholders in `frontend/config.js`, `frontend/vercel.json`, `render.yaml`. Fill in after creating NEW projects.
10. Branding: user-facing title now "Eklavya Exam Prep"; full UI/README rebrand continues during frontend milestone.

## Decisions
- No React Flow (plain JS) → mastery map drawn with SVG.
- `.claude/`, `*.db`, real `.env` files were not copied; `backend/.env` is created from the example with no key (user must add GEMINI_API_KEY).
