// 👩‍⚖️ Judge tour (about 2 minutes): a guided walk through the product on the demo student, with a spotlight, a tooltip, Back / Next and a step counter.
// Every step works with NO microphone and NO camera: the tour performs the actions itself (a wrong answer, a pre-filled Hinglish explanation, a built-in
// sample notebook page). A step whose feature is not available is skipped, and a step that is slow still lets you continue. "Exit tour" is always visible.
import { api } from './api.js';
import { API_BASE } from '../lib/config.js';
import { h } from './dom.js';
import { getStudent, setLang, setStudent } from './state.js';
import { toast } from './ui.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (s) => document.querySelector(s);
const byText = (sel, re) => [...document.querySelectorAll(sel)].find((e) => re.test(e.textContent) && !e.hidden && !e.disabled);
async function waitFor(fn, ms = 20000) {
  const t = Date.now();
  while (Date.now() - t < ms) { try { const v = fn(); if (v) return v; } catch { /* keep waiting */ } await sleep(150); }
  return null;
}
async function typeInto(el, text, delay = 16) {
  el.focus(); el.value = '';
  for (const ch of text) { el.value += ch; el.dispatchEvent(new Event('input', { bubbles: true })); await sleep(delay); }
}
/** Pick the prepared wrong option of the tour's fixed question (a normal student step, done for the viewer). Never waits long: false means "skip this step". */
async function answerWrong() {
  if (!await waitFor(() => $('.opt:not(:disabled)') && $('.stage')?.dataset.tourWrong !== undefined, 10000)) return false;
  const pick = document.querySelectorAll('.opt')[Number($('.stage').dataset.tourWrong)];
  if (!pick) return false;
  pick.click(); await sleep(200);
  byText('button', /^Check answer$/)?.click();
  if (!await waitFor(() => $('.result'), 8000)) return false;
  return Boolean($('.result-bad'));
}

/** Does this endpoint exist? A plain fetch, so a 404 here can never be mistaken for "the student is gone". */
async function exists(path) {
  try { const res = await fetch(`${API_BASE}${path}`); return res.ok; } catch { return false; }
}

const HINGLISH = 'bulb mein current kha jaata hai, isliye resistor ke baad current kam bachta hai';
const UNIT_EXPLANATION = 'Pehle mA ko A mein badalna padta hai: 200 mA = 0.2 A, phir Q = I × t = 0.2 × 10 = 2 C, isliye answer 2 coulomb hai';

const STEPS = [
  { id: 'problem', title: 'The problem', route: '#/', target: () => $('.hero-wrap'),
    text: 'Generic AI tutors answer questions. Eklavya models what a student does and does not understand, finds the misconception behind a wrong answer, and talks them out of it, in Hindi, English or Hinglish. Watch the loop on the right, then let’s see it live.' },
  { id: 'map', title: 'Mastery map + root cause', route: '#/map', wait: '.root-card:not([hidden])', waitMs: 25000, target: () => $('.root-card') || $('.graph-card'),
    text: 'Aarav keeps getting Series circuits wrong. Eklavya traced it back through the prerequisite graph: he believes “current gets used up”, in Charge & current. The animated line on the map is that path. The fix starts at the root, not at the symptom.' },
  { id: 'thinking', title: 'A visible agent', route: '#/practice?tour=misconception', wait: '.opt', waitMs: 15000, target: () => $('.think') || $('.question'),
    text: 'This is “Eklavya’s thinking”: every question is the result of tool calls (check mastery, trace the root cause, set the difficulty, write the question with wrong options built from misconceptions). The AI writes words; the model decides what to ask.' },
  { id: 'misconception', title: 'Named from his own words', route: '#/practice?tour=misconception',
    async enter(s) {
      s.status('Answering wrong on purpose…');
      if (!await answerWrong()) return;
      const ta = await waitFor(() => $('.reasoning textarea'), 15000);
      if (!ta) return;
      s.status('Typing his explanation in Hinglish (no microphone needed)…');
      await typeInto(ta, HINGLISH);
      byText('.reasoning button', /Send my explanation/)?.click();
      s.status('Eklavya is reading his words…');
      await waitFor(() => $('.mc-card h2'), 12000);
    },
    target: () => $('.mc-card') || $('.reasoning'),
    text: () => ($('.mc-card h2') ? `From “${HINGLISH}” Eklavya named the idea: “${$('.mc-card h2').textContent}”. The wrong option alone could not tell us that. It is shown here with a confidence label, then a conversation starts instead of a correction.`
      : 'Eklavya reads the reasoning (voice or text, Hindi, English or Hinglish) and names the misconception behind the wrong answer.') },
  { id: 'notebook', title: '📸 Snap your notebook', route: '#/practice?tour=notebook',
    async enter(s) {
      s.status('Answering wrong, then using a built-in sample page (no camera needed)…');
      if (!await answerWrong()) return;
      const btn = await waitFor(() => byText('.reasoning button', /Try a sample/), 15000);
      if (!btn) return;
      btn.click();
      await waitFor(() => document.querySelectorAll('.snap-sample').length === 2, 10000);
      document.querySelectorAll('.snap-sample')[0]?.click();
      s.status('Reading the handwriting…');
      await waitFor(() => $('.nb-view'), 12000);
    },
    target: () => $('.nb-view') || $('.reasoning'),
    text: 'A photo of handwritten working, read by AI. It transcribes every line and flags the FIRST wrong one: here line 3, because 200 mA was used as 200 instead of 0.2 A. This is a built-in sample page, so it works without a camera. On a phone the button opens the camera.' },
  { id: 'dialogue', title: 'Talk it out, then it’s fixed', route: '#/practice?tour=notebook',
    async enter(s) {
      const input = await waitFor(() => $('.dialogue input'), 25000);
      if (!input) return;
      s.status('Aarav explains it in his own words…');
      await typeInto(input, UNIT_EXPLANATION, 12);
      byText('.dialogue button', /^Send$/)?.click();
      await waitFor(() => $('.dialogue .dlg-outro'), 30000);
    },
    target: () => $('.dialogue'),
    text: () => ($('.dialogue .dlg-won') ? 'Eklavya never gave the answer: it asked guiding questions in Hinglish (and spoke them aloud), and the misconception counts as fixed only when Aarav explained the correct idea himself. His mastery jumped, capped so one conversation can’t over-credit.'
      : 'Eklavya asks guiding questions and never hands over the answer. The misconception counts as fixed only when the student explains the idea in their own words; after four turns it explains and schedules an early review.') },
  { id: 'reviews', title: 'Reviews + 🔒 Verified fixed', route: '#/reviews', async before() { await api('/api/demo/time-travel', { method: 'POST', body: { on: true } }); const s = getStudent(); if (s) await api(`/api/demo/checks-due?student_id=${s.id}`, { method: 'POST' }).catch(() => {}); }, wait: 'h1', target: () => $('.checks-card') || $('.review-list') || $('h1'),
    text: () => ($('.checks-card') ? '🔒 Verified fixed: once Aarav explained the idea, Eklavya scheduled a trap question for later (two days normally; for the demo time travel makes it minutes). Avoid the trap and the misconception becomes Verified; fall for it and it reopens with a fresh conversation. Concepts also return on an SM-2 schedule.'
      : 'Every concept comes back just before it would be forgotten (SM-2). For the demo, time travel makes one day equal one minute, so reviews fall due while you watch.') },
  { id: 'board', title: '🎯 Board-exam marks', route: '#/map', available: (student) => exists(`/api/ps02/board?student_id=${student.id}`),
    wait: '.marks-card', target: () => $('.marks-card'), text: 'Mastery is turned into marks: a predicted CBSE Physics score, and the fix that unlocks the most marks first.' },
  { id: 'teacher', title: 'The teacher’s co-pilot', route: '#/teacher', wait: '.group-card', waitMs: 25000, target: () => $('.group-card'),
    async enter(s) {
      const btn = byText('.group-card button', /mini-lesson/);
      if (!btn) return;
      btn.click();
      s.status('Writing a 10-minute lesson for the group…');
      await waitFor(() => $('.group-card .lesson'), 55000);
    },
    text: 'The class view groups students who share a misconception (Group A: Aarav and Rohan believe current gets used up). One click writes a 10-minute lesson with a demo, an analogy, check questions and a Hinglish script; “Assign to group” sends those students the conversation you just saw.' },
];

let state = null;

export function tourActive() { return Boolean(state); }

export async function startTour() {
  if (state) return;
  let student;
  try { ({ student } = await api('/api/demo/tour-reset', { method: 'POST', timeout: 30000 })); }
  catch (err) { toast(err.message || 'Could not prepare the demo. Please try again.'); return; }
  setStudent({ id: student.id, name: student.name, demo: true });
  setLang('hinglish');
  try { sessionStorage.removeItem('ps02.thinkSeen'); localStorage.removeItem(`ps02.snap.${student.id}`); } catch { /* ignore */ }
  const steps = [];
  for (const s of STEPS) { if (!s.available || await s.available(student)) steps.push(s); }
  state = { steps, index: 0, token: 0, student, raf: 0 };
  build();
  document.body.classList.add('tour-on');
  globalThis.addEventListener('ps02:student-gone', end);
  document.addEventListener('keydown', onKey);
  go(0);
}

function build() {
  const ui = state.ui = {};
  ui.spot = h('div', { class: 'tour-spot', hidden: true });
  ui.count = h('p', { class: 'tour-count' });
  ui.title = h('h3', { class: 'tour-title' });
  ui.text = h('p', { class: 'tour-text' });
  ui.status = h('p', { class: 'tour-status', role: 'status' });
  ui.back = h('button', { class: 'btn btn-small', type: 'button', onClick: () => go(state.index - 1) }, 'Back');
  ui.next = h('button', { class: 'btn btn-primary btn-small', type: 'button', onClick: () => (state.index === state.steps.length - 1 ? end(true) : go(state.index + 1)) }, 'Next');
  ui.card = h('div', { class: 'tour-card', role: 'dialog', 'aria-label': 'Judge tour step', 'aria-live': 'polite' }, ui.count, ui.title, ui.text, ui.status, h('div', { class: 'tour-actions' }, ui.back, ui.next));
  ui.exit = h('button', { class: 'tour-exit', type: 'button', onClick: () => end(false) }, 'Exit tour ✕');
  ui.root = h('div', { class: 'tour' }, h('div', { class: 'tour-block' }), ui.spot, ui.card, ui.exit);
  document.body.append(ui.root);
  const follow = () => { position(); state.raf = requestAnimationFrame(follow); };
  state.raf = requestAnimationFrame(follow);
}

const onKey = (e) => {
  if (!state) return;
  if (e.key === 'Escape') end(false);
  else if (e.key === 'ArrowRight' && !state.ui.next.disabled) state.ui.next.click();
  else if (e.key === 'ArrowLeft' && !state.ui.back.disabled) state.ui.back.click();
};

async function go(i) {
  if (!state || i < 0 || i >= state.steps.length) return;
  const token = ++state.token;
  const step = state.steps[i];
  state.index = i; state.target = null;
  const ui = state.ui;
  ui.count.textContent = `${i + 1} of ${state.steps.length}`;
  ui.title.textContent = step.title;
  ui.text.textContent = 'Setting this up…';
  ui.status.textContent = '';
  ui.back.disabled = i === 0; ui.next.disabled = true;
  ui.next.textContent = i === state.steps.length - 1 ? 'Finish' : 'Next';
  ui.spot.hidden = true;
  const ctrl = { status: (t) => { if (state && state.token === token) ui.status.textContent = t; } };
  try {
    if (step.before) await step.before();
    if (step.route && location.hash !== step.route) { location.hash = step.route; await sleep(350); }
    if (step.wait) await waitFor(() => $(step.wait), step.waitMs || 20000);
    if (step.enter) await step.enter(ctrl);
  } catch { /* a slow or failed action never blocks the tour: the tooltip still explains the step */ }
  if (!state || state.token !== token) return;
  state.target = step.target;
  const target = step.target?.();
  if (target) { target.scrollIntoView({ block: matchMedia('(max-width: 640px)').matches ? 'start' : 'center', behavior: 'smooth' }); if (matchMedia('(max-width: 640px)').matches) setTimeout(() => globalThis.scrollBy(0, -70), 350); }
  ui.text.textContent = typeof step.text === 'function' ? step.text() : step.text;
  ui.status.textContent = '';
  ui.next.disabled = false;
  ui.next.focus({ preventScroll: true });
}

/** Keep the spotlight on the target (content moves while it loads) and the card beside it. */
function position() {
  if (!state) return;
  const { ui } = state;
  const el = state.target?.();
  const small = innerWidth < 640;
  if (!el) { ui.spot.hidden = true; ui.card.classList.toggle('tour-sheet', small); ui.card.style.cssText = small ? '' : 'left:50%;bottom:24px;transform:translateX(-50%)'; return; }
  const r = el.getBoundingClientRect();
  const top = Math.max(r.top, 10), bottom = Math.min(r.bottom, innerHeight - 10);
  if (bottom - top < 24 || r.width < 24) { ui.spot.hidden = true; return; }
  const pad = 8;
  Object.assign(ui.spot.style, { left: `${r.left - pad}px`, top: `${top - pad}px`, width: `${r.width + pad * 2}px`, height: `${bottom - top + pad * 2}px` });
  ui.spot.hidden = false;
  ui.card.classList.toggle('tour-sheet', small);
  if (small) { ui.card.style.cssText = ''; return; }
  const cw = Math.min(380, innerWidth - 24), ch = ui.card.offsetHeight || 220;
  let left, topPos;
  if (r.right + 20 + cw <= innerWidth) { left = r.right + 20; topPos = Math.min(Math.max(top, 12), innerHeight - ch - 12); }
  else if (bottom + 16 + ch <= innerHeight) { left = Math.min(Math.max(r.left, 12), innerWidth - cw - 12); topPos = bottom + 16; }
  else if (top - 16 - ch >= 0) { left = Math.min(Math.max(r.left, 12), innerWidth - cw - 12); topPos = top - 16 - ch; }
  else { left = innerWidth - cw - 16; topPos = innerHeight - ch - 16; }
  ui.card.style.cssText = `left:${left}px;top:${topPos}px;width:${cw}px`;
}

async function end(finished) {
  if (!state) return;
  cancelAnimationFrame(state.raf);
  state.ui.root.remove();
  document.body.classList.remove('tour-on');
  document.removeEventListener('keydown', onKey);
  globalThis.removeEventListener('ps02:student-gone', end);
  state = null;
  try { await api('/api/demo/time-travel', { method: 'POST', body: { on: false }, timeout: 8000 }); } catch { /* best effort */ }
  if (finished === true) { toast('Tour finished. Explore freely: you are signed in as the demo student.'); location.hash = '#/map'; }
}
