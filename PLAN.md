# Build Prompt — Eklavya Exam Prep (Product Space Agentic AI Hackathon, PS02)

> Paste this whole file into Claude Code (or save it as `PLAN.md` in the new repo and say "follow PLAN.md").
> Replace `<EKLAVYA_PATH>` and `<NEW_PATH>` before pasting.

---

## 0. Context

You are building a hackathon submission for **Problem Statement 02: Adaptive exam-prep tutor with a learner model** (Product Space Agentic AI Hackathon). Deadline: **21 Nov 2026, 11:59 PM IST**. Target: everything deployed and submitted by **11:00 PM**.

We start from a **copy** of my existing app *Eklavya* (voice-first study mentor, English/Hindi/Hinglish). We reuse its stack, voice input, LLM setup and deploy config, but **this project is built fully around PS02**. Eklavya's notes-upload chat can stay as a secondary feature, but it is NOT the focus.

**Problem statement (must cover ALL 7):**
1. A diagnostic test
2. A concept graph for one syllabus — **CBSE Class 10 Physics**
3. A learner model that updates mastery per concept after every answer
4. Question generation targeted at weak concepts, with difficulty calibration
5. Misconception detection from the *reasoning* in wrong answers, not just the wrong final answer
6. Spaced-repetition scheduling
7. A teacher dashboard showing class-wide gaps

**Judging weights (optimise for these):**
| Criterion | Weight | What it means for the build |
|---|---|---|
| Prototype quality & UX | 25% | Fast, smooth, no dead ends, realistic demo data |
| AI integration | 25% | AI makes visible decisions (structured outputs), not just chat |
| Problem understanding | 20% | Every one of the 7 requirements clearly visible |
| LinkedIn content | 15% | Demo video + post (done at the end) |
| Innovation | 15% | Voice/Hinglish reasoning → misconception detection; misconception-based distractors |

---

## 1. Step 1 — Copy Eklavya safely (DO THIS FIRST)

**Hard rule: never modify, commit to, or push anything in `<EKLAVYA_PATH>`. Read-only.**

1. Inspect `<EKLAVYA_PATH>`: identify the frontend/backend stack, LLM provider + model, voice (STT/TTS) implementation, env vars, and deploy config. Write a 10-line summary into `NOTES.md` in the new folder.
2. Copy to `<NEW_PATH>` **excluding** `.git`, `node_modules`, `venv`/`.venv`, `__pycache__`, `dist`, `build`, `.next`, `.vercel`, and any `.env*` files except `.env.example`. Example:
   ```bash
   rsync -a --exclude .git --exclude node_modules --exclude venv --exclude .venv \
     --exclude __pycache__ --exclude dist --exclude build --exclude .next --exclude .vercel \
     --exclude '.env' --exclude '.env.local' --exclude '.env.production' \
     <EKLAVYA_PATH>/ <NEW_PATH>/
   ```
3. In `<NEW_PATH>`: `git init`, create a `.gitignore` that covers env files and the excluded folders, first commit "Copy of Eklavya as base for PS02".
4. Create `.env` from `.env.example` and **ask me** for the keys — do not copy secrets automatically.
5. Rename user-facing branding to **"Eklavya Exam Prep"** (title, header, meta, README). Keep code identifiers as they are unless trivial.
6. Run frontend + backend locally and confirm the copy works before adding features.
7. Run `git -C <EKLAVYA_PATH> status` at the end of this step and confirm the original is untouched.

If the existing stack is Python/FastAPI + React, keep it. If it's something else, keep whatever it is — don't rewrite the stack.

---

## 2. Data layer (static JSON, hand-authored — do not generate at runtime)

Create `backend/data/` (or the equivalent location):

### 2.1 `concept_graph.json` — CBSE Class 10 Physics (rationalised syllabus)
Each node: `id`, `name`, `chapter`, `prerequisites[]`, `description` (1 line), `key_formulas[]`.

| id | name | chapter | prerequisites |
|---|---|---|---|
| L1 | Laws of reflection | Light | — |
| L2 | Spherical mirrors & image formation | Light | L1 |
| L3 | Mirror formula, sign convention & magnification | Light | L2 |
| L4 | Refraction & refractive index | Light | L1 |
| L5 | Lenses & image formation | Light | L4 |
| L6 | Lens formula & power of a lens | Light | L5, L3 |
| E1 | Human eye & accommodation | Human Eye | L5 |
| E2 | Defects of vision & correction | Human Eye | E1, L6 |
| E3 | Refraction through prism & dispersion | Human Eye | L4 |
| E4 | Atmospheric refraction & scattering | Human Eye | L4, E3 |
| C1 | Electric charge & current | Electricity | — |
| C2 | Potential difference | Electricity | C1 |
| C3 | Ohm's law & resistance | Electricity | C1, C2 |
| C4 | Factors affecting resistance (resistivity) | Electricity | C3 |
| C5 | Resistors in series | Electricity | C3 |
| C6 | Resistors in parallel | Electricity | C3, C5 |
| C7 | Heating effect & electric power | Electricity | C3 |
| M1 | Magnetic field & field lines | Magnetism | — |
| M2 | Magnetic field due to current (wire, loop, solenoid) | Magnetism | M1, C1 |
| M3 | Force on current-carrying conductor (Fleming's LHR) | Magnetism | M2 |
| M4 | Domestic electric circuits & safety | Magnetism | C7 |

### 2.2 `misconceptions.json`
Each: `id`, `concept_ids[]`, `label` (short), `description` (what the student wrongly believes), `telltale_phrases[]` (English + Hinglish examples), `correction` (1–2 lines, simple).

| id | concepts | wrong belief |
|---|---|---|
| MC01 | C1, C5 | Current gets "used up" by a bulb/resistor |
| MC02 | C3 | A battery always gives the same current whatever the circuit |
| MC03 | C6 | Adding resistors in parallel increases total resistance |
| MC04 | C2 | Voltage "flows" through the circuit like current |
| MC05 | C4 | Resistance depends only on material, not length/area |
| MC06 | C7, C5 | Higher-wattage bulb always glows brighter, even in series |
| MC07 | C3 | Resistance of an ohmic conductor changes with applied voltage |
| MC08 | L2 | All mirror images are virtual / images behind mirror are real |
| MC09 | L3, L6 | Ignoring sign convention (e.g., concave mirror focal length positive) |
| MC10 | L4 | Light speeds up when entering a denser medium |
| MC11 | L5 | Covering half a lens removes half the image |
| MC12 | L6 | Longer focal length means more powerful lens |
| MC13 | E2 | Myopia is corrected with a convex lens |
| MC14 | E3 | A prism adds colours to white light |
| MC15 | E4 | Sky is blue because it reflects the ocean / red light scatters most |
| MC16 | M1 | Magnetic field lines can intersect |
| MC17 | M2 | Only magnets produce magnetic fields, not currents |
| MC18 | M3 | Force on a conductor acts along the magnetic field direction |
| MC19 | M4 | Earth wire normally carries current / fuse goes in the neutral wire |

Add `"MC_UNKNOWN"` as a catch-all for "wrong but not a known misconception" — the classifier may also propose a new short label for it.

### 2.3 `diagnostic.json` — 14 hand-written MCQs
- Cover all 4 chapters, at least one question per 1–2 concepts, spanning difficulty 1–3.
- Each question: `id`, `concept_id`, `difficulty` (1–3), `stem`, `options[4]`, `correct_index`, `distractor_misconceptions` (map wrong option index → misconception id), `explanation`.
- **Distractors must be built from misconceptions** — a wrong pick already hints at the misconception.
- Pre-written, not LLM-generated, so the diagnostic is fast and reliable.

---

## 3. Backend

### 3.1 Database (SQLite, or reuse whatever DB Eklavya uses)
Tables (adapt names to the existing style):
- `students(id, name, class_section, created_at)`
- `mastery(student_id, concept_id, p_known, attempts, correct, last_seen, updated_at)`
- `attempts(id, student_id, question_json, concept_id, difficulty, chosen_index, correct, reasoning_text, reasoning_mode[voice|text], misconception_id, misconception_confidence, created_at)`
- `reviews(student_id, concept_id, easiness, interval_days, repetitions, due_at)`
- `student_misconceptions(student_id, misconception_id, count, last_seen, resolved)`

### 3.2 Learner model — Bayesian Knowledge Tracing (`learner_model.py`)
Per concept, standard BKT:
- Params: `p_init` (from diagnostic), `p_learn=0.15`, `p_slip=0.10`, `p_guess=0.25` (4-option MCQ).
- After each answer: Bayesian posterior update on `p_known`, then apply learning transition.
- **Prerequisite propagation:** if a wrong answer's detected misconception belongs to a prerequisite concept, also apply a smaller negative update (×0.5 weight) to that prerequisite. If the student is correct on a hard question (difficulty 3), apply a small positive nudge (×0.3) to its prerequisites.
- **Diagnostic seeding:** concepts tested → initial `p_known` from the result (correct: 0.6–0.7 by difficulty; wrong: 0.15–0.25). Untested concepts → average of their prerequisites' values, default 0.3.
- Expose `get_mastery(student_id) → {concept_id: p_known}` and `weakest_concepts(student_id, k)`: lowest `p_known` among concepts whose prerequisites are ≥ 0.5 (the "frontier"). If none qualify, fall back to the lowest overall.

Write unit tests for the BKT update and the propagation logic.

### 3.3 Difficulty calibration
- Map mastery → target difficulty: `p<0.4 → 1`, `0.4–0.7 → 2`, `>0.7 → 3`.
- Aim for ~70% expected success. Track the rolling accuracy per student; if the last 3 at a level are all correct, step up; if 2 consecutive wrong, step down.
- Return a human-readable `why` string with every question, e.g. *"You're at 32% on Ohm's law (prerequisite for Series circuits) → difficulty 1."*

### 3.4 Question generation (`question_gen.py`) — LLM, structured JSON
Input: concept node, target difficulty, the student's active misconceptions for that concept, and the last 5 question stems (to avoid repeats).
Output JSON (validate with Pydantic/zod; retry once on invalid):
```json
{
  "stem": "...",
  "options": ["...", "...", "...", "..."],
  "correct_index": 2,
  "distractor_misconceptions": {"0": "MC01", "1": "MC03", "3": "MC_UNKNOWN"},
  "difficulty": 2,
  "concept_id": "C6",
  "explanation": "..."
}
```
Prompt rules: CBSE Class 10 level, numeric values sensible, units correct, distractors deliberately built from the listed misconceptions, exactly one correct option.
**Speed:** pre-generate the next question in the background while the student is answering the current one. Keep a small per-concept cache of generated questions as a fallback.

### 3.5 Misconception detection (`misconception.py`) — the core differentiator
After a **wrong** answer, the student must explain their reasoning ("Why did you pick this?") by **voice (reuse Eklavya's STT, Hindi/English/Hinglish)** or text.
LLM input: question, correct answer, chosen option, the distractor's mapped misconception (a prior, not the answer), the student's reasoning text, and the misconception list for that concept plus its prerequisites.
Output JSON:
```json
{
  "misconception_id": "MC01",
  "confidence": 0.82,
  "evidence": "student said 'bulb current kha jaata hai'",
  "is_careless_error": false,
  "feedback_hinglish": "...",
  "feedback_english": "..."
}
```
- If the reasoning is actually correct but the answer was a slip → `is_careless_error: true` → treat it as a slip in BKT (smaller penalty).
- Show the student a friendly correction card in their language: the misconception named, why it's wrong, and a 1-line intuitive analogy.
- Optional: also ask for reasoning on ~1 in 4 **correct** answers to catch lucky guesses (lower confidence → smaller mastery gain).

### 3.6 Spaced repetition — SM-2 per concept (`srs.py`)
- After each practice answer on a concept, compute quality 0–5 from correctness + misconception severity (correct fast = 5, correct = 4, careless error = 3, wrong with misconception = 1, wrong unknown = 2).
- Standard SM-2 updates `easiness`, `interval_days`, `repetitions`, `due_at`.
- **Demo mode:** add a "time travel" toggle (or env flag) that treats 1 day = 1 minute so judges can see reviews become due.

### 3.7 Teacher analytics (`teacher.py`)
- Class heatmap: students × concepts mastery matrix.
- Concept gaps: class-average mastery per concept, sorted ascending.
- Top misconceptions: count of students currently holding each, with example quotes.
- Students at risk: lowest average mastery / most active misconceptions.
- **"Reteach tomorrow" (LLM):** takes the top 3 gaps + top 3 misconceptions → returns a short plan: what to reteach, one demo/analogy each, and 2 check questions. Cache per class per hour.

### 3.8 API endpoints (adapt to existing routing style)
```
POST /api/students                       create/select student
GET  /api/diagnostic                     14 questions
POST /api/diagnostic/submit              answers → seed mastery → return mastery map
GET  /api/practice/next?student_id=      next targeted question + "why"
POST /api/practice/answer                answer → BKT update → if wrong, needs_reasoning=true
POST /api/practice/reasoning             reasoning text (from voice/text) → misconception result → BKT/SRS update
GET  /api/mastery?student_id=            concept graph + mastery per node
GET  /api/reviews/due?student_id=        due concepts (SM-2)
GET  /api/teacher/overview               heatmap, gaps, misconceptions, at-risk
GET  /api/teacher/reteach                LLM reteach plan
POST /api/demo/seed                      reseed demo class
```

### 3.9 Seed data (`seed.py`)
Create a class "10-B" with **6 students**, each with a distinct profile, by simulating ~25–40 attempts per student through the real BKT/SRS code (not hardcoded mastery):
- Strong in Light, weak in Electricity (holds MC01, MC03)
- Weak at sign convention (MC09, MC12)
- Mostly strong, one gap in magnetism (MC18)
- Struggling overall (many misconceptions)
- Careless-error profile (right reasoning, wrong picks)
- Average, with Human Eye gaps (MC13, MC15)
Include realistic Hinglish reasoning quotes. The teacher dashboard must look alive on first load.

---

## 4. Frontend — screens and flow

Reuse Eklavya's design system, components and voice UI. Main flow:
**Landing → Pick role (Student / Teacher) → Diagnostic → Mastery map → Practice loop → Reviews due → Teacher dashboard**

1. **Landing:** one-line pitch — *"Generic AI tutors answer questions. Eklavya knows what you don't understand — and why."* Buttons: "Start as student", "Open teacher dashboard", "Try demo student".
2. **Diagnostic:** 14 questions, progress bar, no feedback until the end (it's a diagnostic). End → animated reveal of the mastery map.
3. **Mastery map (hero screen):** the concept graph rendered as nodes + prerequisite edges (React Flow or similar), grouped by chapter, colored red→amber→green by `p_known`, with % on each node. Click a node → details: mastery history sparkline, active misconceptions, "Practice this".
4. **Practice:**
   - Question card with difficulty badge + "Why this question?" chip showing the `why` string.
   - On wrong answer → "Explain your thinking" with a big **mic button** (Hindi/English/Hinglish) + text fallback.
   - Misconception card: name of misconception, evidence quote, correction, analogy, in the student's language.
   - Live mastery delta animation (e.g., "Ohm's law 42% → 35%", "Series circuits 50% → 46% (prerequisite effect)").
5. **Reviews due:** list of concepts due by SM-2 with next-due times; "Start review" runs a short practice set on due concepts.
6. **Teacher dashboard:** class heatmap (students × concepts), concept gaps bar chart, top misconceptions with counts + example student quotes, at-risk students, and the **"Reteach tomorrow"** card. Click a student → their mastery map.
7. **"How it works" page/modal:** the 7 requirements, each with where it lives in the app, plus a simple diagram: Answer → BKT update → Misconception detection → SRS → Next question. This page is aimed at the "problem understanding" score.

UX rules:
- A loading skeleton or streaming text for every LLM call; never a blank wait.
- Every screen reachable in ≤ 2 clicks from the nav; no dead ends.
- Mobile-responsive (judges may open it on a phone).
- No 3D/heavy effects this time — clean, fast, readable.

---

## 5. Performance and deploy
- Fix the known lag: backend warm-up endpoint (`/api/health`) hit on page load; keep-alive ping (e.g., cron-job.org / UptimeRobot every 10 min) if on Render free tier.
- Pre-generate the next question; cache generated questions and the reteach plan.
- Use the fastest suitable model for question gen + misconception classification; set timeouts with a fallback to cached questions.
- Deploy as **new, separate** Vercel + Render projects — never reuse Eklavya's deployments or env.
- Seed the demo class on first deploy.

---

## 6. Milestones (IST, Sat 21 Nov) — commit after each

| Time | Milestone | Done when |
|---|---|---|
| 13:45–14:30 | Copy + run + branding + NOTES.md | App runs locally from `<NEW_PATH>`; original untouched |
| 14:30–15:15 | JSON data: graph, misconceptions, diagnostic | Files validate; every concept has ≥1 diagnostic question or a prerequisite with one |
| 15:15–17:30 | Backend: BKT, propagation, calibration, SRS, question gen, misconception classifier, endpoints | Unit tests pass; can run a full practice loop via curl |
| 17:30–20:00 | Frontend: diagnostic, mastery map, practice + voice reasoning, reviews | Full student flow works end-to-end locally |
| 20:00–21:00 | Teacher dashboard + seed + reteach plan + How-it-works page | Dashboard looks alive on first load |
| 21:00–21:45 | Deploy, warm-up, test on deployed URL (desktop + phone) | Full flow works on live URLs, no step > 3s without a loader |
| 21:45–22:30 | README + demo recording | README has the requirement→feature table + screenshots |
| 22:30–23:00 | LinkedIn post + submit | Submitted before 23:00 |

If behind schedule, cut in this order: optional reasoning on correct answers → time-travel toggle → reteach LLM plan (replace with a static top-gaps list) → sparkline history. **Never cut any of the 7 required features.**

---

## 7. README (required content)
- One-line pitch + problem framing (why generic tutors fail)
- **Requirement → feature table** (all 7, with screenshot/route for each)
- Architecture diagram: Diagnostic → BKT learner model ↔ Concept graph → Question gen (calibrated) → Answer → Reasoning (voice/Hinglish) → Misconception classifier → BKT + SM-2 → Teacher analytics
- AI components: what the LLM decides vs. what the deterministic model computes
- Tech stack, live URL, demo credentials/demo student, how to run locally
- Note: "Built on top of the Eklavya codebase (voice + Hinglish layer), with organiser permission."

---

## 8. Working rules for you (Claude Code)
- Never touch `<EKLAVYA_PATH>`.
- Never commit `.env` or keys.
- Commit after each milestone with a clear message.
- Prefer simple, working code over clever code — this is a one-day build.
- When a decision is ambiguous, pick the option that makes the demo clearer and note it in `NOTES.md`.
- Before saying a milestone is done, actually run it and confirm it works.
