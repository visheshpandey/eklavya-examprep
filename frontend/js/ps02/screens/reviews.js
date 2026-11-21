// Spaced repetition: concepts due for review (SM-2), upcoming schedule, and the demo "time travel" switch (1 day = 1 minute).
import { api, qs } from '../api.js';
import { h } from '../dom.js';
import { getStudent } from '../state.js';
import { toast, when } from '../ui.js';
import { chain } from './chain.js';

export async function reviews(root, ctx) {
  const student = getStudent();
  const [data, checks] = await Promise.all([api(`/api/reviews/due?${qs({ student_id: student.id })}`),
    api(`/api/ps02/checks?${qs({ student_id: student.id })}`).catch(() => ({ due: [], upcoming: [], verified: [] }))]);
  if (!ctx.live()) return;
  const unit = data.time_travel ? 'minute' : 'day';
  const row = (r) => h('li', { class: `review ${r.due ? 'review-due' : ''}` },
    h('div', null, h('b', null, r.name), h('p', { class: 'muted small' }, `${r.concept_id} · reviewed ${r.repetitions}× · interval ${r.interval_days} ${unit}${r.interval_days === 1 ? '' : 's'} · ease ${Number(r.easiness).toFixed(1)}`)),
    h('span', { class: `chip ${r.due ? 'chip-warn' : ''}` }, when(r.due_at)),
    h('a', { class: 'btn btn-small', href: `#/practice?concept=${r.concept_id}` }, 'Practise'));

  const toggle = h('button', { class: 'seg-btn toggle', type: 'button', 'aria-pressed': String(data.time_travel), onClick: async () => {
    toggle.disabled = true;
    try { await api('/api/demo/time-travel', { method: 'POST', body: { on: !data.time_travel } }); toast(!data.time_travel ? 'Time travel on: 1 day now counts as 1 minute.' : 'Time travel off.'); await reviews(root, ctx); }
    catch (err) { toast(err.message); toggle.disabled = false; }
  } }, data.time_travel ? 'Time travel: ON (1 day = 1 min)' : 'Time travel: off');

  const checkRow = (c) => h('li', { class: `review ${c.due ? 'review-due' : ''}` },
    h('div', null, h('b', null, c.label), h('p', { class: 'muted small' }, `${c.concept_name}${c.attempts ? ` · tried ${c.attempts}×` : ''}`), chain('resolved')),
    h('span', { class: `chip ${c.due ? 'chip-warn' : ''}` }, c.due ? 'due now' : `in ${c.seconds_left >= 3600 ? Math.round(c.seconds_left / 3600) + ' h' : c.seconds_left >= 60 ? Math.round(c.seconds_left / 60) + ' min' : c.seconds_left + ' s'}`),
    c.due && h('a', { class: 'btn btn-small btn-primary', href: `#/verify?mc=${c.misconception_id}` }, 'Check it'));
  const verifyCard = (checks.due.length + checks.upcoming.length + checks.verified.length) > 0 && h('div', { class: 'card checks-card' },
    h('h2', null, '🔒 Verification checks'),
    h('p', { class: 'muted small' }, 'After you explain a misconception, a trap question brings it back later. Avoid the trap and it is marked Verified fixed.'),
    h('ul', { class: 'review-list' }, [...checks.due, ...checks.upcoming].map(checkRow),
      checks.verified.map((v) => h('li', { class: 'review' }, h('div', null, h('b', null, v.label), chain('verified')), h('span', { class: 'chip chip-ok' }, '✅ Verified fixed')))));

  root.replaceChildren(h('section', { class: 'narrow' },
    h('p', { class: 'eyebrow' }, 'Spaced repetition (SM-2)'), h('h1', { class: 'page-title' }, data.due.length ? `${data.due.length} concept${data.due.length > 1 ? 's' : ''} due for review` : 'You are all caught up'),
    h('p', { class: 'lede' }, 'Each concept comes back at growing gaps. A confident answer pushes it further away; a miss brings it back tomorrow.'),
    h('div', { class: 'row between wrap' },
      data.due.length > 0 ? h('a', { class: 'btn btn-primary', href: '#/practice?review=1' }, `Start review (${Math.min(5, data.due.length)} questions)`) : h('a', { class: 'btn btn-primary', href: '#/practice' }, 'Practise new questions'), toggle),
    verifyCard,
    data.due.length > 0 && h('div', { class: 'card' }, h('h2', null, 'Due now'), h('ul', { class: 'review-list' }, data.due.map(row))),
    data.upcoming.length > 0 && h('div', { class: 'card' }, h('h2', null, 'Coming up'), h('ul', { class: 'review-list' }, data.upcoming.map(row))),
    !data.due.length && !data.upcoming.length && !verifyCard && h('div', { class: 'card' }, h('p', null, 'Reviews are scheduled after you practise. Answer a few questions first.')),
    h('p', { class: 'muted small' }, 'For judges: turn on time travel, answer a question, and watch it fall due within minutes instead of days.')));
}
