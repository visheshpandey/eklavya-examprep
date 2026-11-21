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

## Backend (milestone 3) — decisions
- New code lives in `backend/app/ps02/` (content, learner_model, calibration, srs, question_gen, misconception, service, teacher, seed) + routes in `app/api/routes/ps02.py`. Tables are appended to `db.SCHEMA` (works on SQLite and Postgres). PS02 router is registered first, so `POST /api/demo/seed` is the PS02 seed (Eklavya's old one is shadowed).
- BKT deviations (documented for the README): the learning transition applies only after a CORRECT answer, and a wrong answer moves p 60% of the way to the Bayesian posterior (one MCQ miss can be a slip). Without this a miss at low mastery *raised* p (15% -> 17%), which reads as a bug. Careless slip = weight 0.2; lucky correct = 0.5; prerequisite effect = half the main drop (neg.) / x0.3 (pos., difficulty-3 correct). p is clamped to [5%, 99%].
- A wrong answer is applied provisionally (distractor misconception as prior); `/api/practice/reasoning` rolls it back and re-applies with the classifier's result (careless -> softer, prerequisite misconception -> propagation). SM-2 is rolled back/re-applied the same way. Skipping the explanation keeps the provisional update.
- LLM never decides concept/difficulty: planner + BKT do. LLM only writes questions, classifies reasoning, and writes the reteach plan. All three have deterministic fallbacks (hand-written bank / telltale-phrase matcher / static top-gaps list).
- Added MC20 (angle measured from surface) for diagnostic D01. Correct answers resolve the misconceptions their distractors were built from; reasoning-check is asked on ~1 in 4 correct answers.
- Demo class: `backend/data/demo_class.json` is a snapshot produced by running the six scripted profiles through the real BKT/SM-2 code (`python -m app.ps02.seed` regenerates it; takes ~25s because of thousands of tiny DB writes). Loading is instant and timestamps are shifted to "now". The class is auto-seeded at startup if missing.
- Gemini verified live: question ~2s, misconception classification ~3.5s (Hinglish quote -> MC01 with Hinglish feedback).

## Phases 2-4 (agentic upgrade)
- Phase 2: `app/ps02/rootcause.py` (score = (1-p) x misconception evidence x 0.8^(distance-1); the LLM only words the explanation), `app/ps02/agent.py` (tool-call log shown as "Eklavya's thinking"). Root cause is applied automatically only on auto-picked concepts; explicit choices get a "Fix the root first" suggestion.
- Streaming: `llm_stream.py` + `/api/practice/reasoning/stream` and `/api/dialogue/reply/stream` (NDJSON). Two models are raced (`GEMINI_MODEL` primary, `GEMINI_FALLBACK_MODEL` backup). gemini-3.1-flash-lite was ~10x slower than 3.5-flash-lite in testing (Gemini demand spikes), so 3.5 is now primary. First-text latency is dominated by Gemini variance (2-8 s), not guaranteed < 3 s.
- Phase 3: `app/ps02/copilot.py` (groups, cached mini-lessons, assignments, before/after). A finished dialogue completes the student's assignment.
- Phase 4: `hero-demo.js` (landing storyboard, pauses off-screen / on request, static for reduced motion), `snapshot.js` (map nodes that changed since the last visit animate).
- Commands: `python -m app.ps02.reseed` (fresh demo class, before deploy / demo), `--delete "A,B"`, `--regenerate`.
- Known: 3 original frontend tests (`node --test`) check the old index.html and fail by design; use `legacy-eklavya.html` for the original UI.
