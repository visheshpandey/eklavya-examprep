// A verification check: a trap question for a misconception the student has already explained once. Passing it makes the fix "Verified".
// Falling for the trap reopens the misconception and goes straight back into the Socratic dialogue.
import { api, qs } from '../api.js';
import { h } from '../dom.js';
import { getStudent } from '../state.js';
import { errorCard, loading } from '../ui.js';
import { chain, verifiedBadge } from './chain.js';
import { mountDialogue } from './dialogue.js';

export async function verify(root, ctx) {
  const student = getStudent();
  const mcId = ctx.query.mc;
  if (!mcId) { location.hash = '#/reviews'; return; }
  let q;
  try { q = await api(`/api/ps02/checks/next?${qs({ student_id: student.id, misconception_id: mcId })}`, { timeout: 20000 }); }
  catch (err) { if (ctx.live()) root.replaceChildren(h('section', { class: 'narrow' }, errorCard(`${err.message}`, () => { location.hash = '#/reviews'; }), h('a', { class: 'btn', href: '#/reviews' }, 'Back to Reviews'))); return; }
  if (!ctx.live()) return;

  const head = h('div', null, chain('resolved'));
  const stage = h('div', { class: 'card verify-card' });
  const result = h('div', { role: 'status', 'aria-live': 'polite' });
  const options = q.options.map((text, i) => h('button', { class: 'opt', type: 'button', role: 'radio', 'aria-checked': 'false', onClick: () => pick(i) },
    h('span', { class: 'opt-key', 'aria-hidden': 'true' }, 'ABCD'[i]), h('span', null, text)));
  stage.append(h('p', { class: 'eyebrow' }, `Verification check · ${q.concept_name}`), h('div', { class: 'row between wrap tight' }, h('h2', { class: 'stem' }, q.stem)),
    h('div', { class: 'options', role: 'radiogroup', 'aria-label': 'Answer options' }, options), result);

  async function pick(i) {
    options.forEach((o, k) => { o.disabled = true; o.setAttribute('aria-checked', String(k === i)); });
    result.replaceChildren(loading('Checking…', 1));
    try {
      const r = await api('/api/ps02/checks/answer', { method: 'POST', body: { student_id: student.id, question_id: q.question_id, chosen_index: i }, timeout: 20000 });
      options.forEach((o, k) => { o.classList.toggle('opt-correct', k === r.correct_index); o.classList.toggle('opt-wrong', k === i && !r.correct); });
      show(r);
      ctx.refreshDue?.();
    } catch (err) { options.forEach((o) => { o.disabled = false; }); result.replaceChildren(h('p', { class: 'error-text' }, err.message)); }
  }

  function show(r) {
    head.replaceChildren(chain(r.stage));
    const next = h('div', { class: 'row' }, h('a', { class: 'btn btn-primary', href: '#/reviews' }, 'Back to Reviews'), h('a', { class: 'btn', href: '#/map' }, 'See my map'));
    if (r.outcome === 'verified') {
      result.replaceChildren(h('div', { class: 'verify-result verify-ok' }, verifiedBadge(), h('h3', null, 'Verified fixed. 🎉'), h('p', null, r.message), chain('verified'), h('p', { class: 'small' }, r.explanation), next));
    } else if (r.outcome === 'relapsed') {
      result.replaceChildren(h('div', { class: 'verify-result verify-bad' }, h('h3', null, 'The old idea came back'), h('p', null, r.message), chain('detected'), h('p', { class: 'small' }, r.explanation)));
      result.append(mountDialogue({ student, misconceptionId: r.misconception_id, conceptId: r.concept_id, onDone: () => result.append(next), onUnavailable: () => result.append(next) }));
    } else {
      result.replaceChildren(h('div', { class: 'verify-result' }, h('h3', null, 'Not quite, but not the old slip'), h('p', null, r.message), chain('resolved'), h('p', { class: 'small' }, r.explanation), next));
    }
  }
  root.replaceChildren(h('section', { class: 'narrow' }, h('p', { class: 'eyebrow' }, 'Checking that it really changed'), h('h1', { class: 'page-title' }, q.misconception.label), head, stage));
  options[0].focus({ preventScroll: true });
}
