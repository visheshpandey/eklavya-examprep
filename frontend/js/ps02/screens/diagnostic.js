// The 14-question diagnostic: one question at a time, no feedback until the end.
import { api } from '../api.js';
import { h } from '../dom.js';
import { getStudent } from '../state.js';
import { errorCard, loading } from '../ui.js';

export async function diagnostic(root, ctx) {
  const student = getStudent();
  const { questions } = await api('/api/diagnostic');
  if (!ctx.live()) return;
  const answers = new Array(questions.length).fill(null);
  let index = 0;

  async function finish() {
    root.replaceChildren(loading('Building your concept map… working out what you know and what you don’t.', 4));
    try {
      await api('/api/diagnostic/submit', { method: 'POST', body: {
        student_id: student.id,
        answers: questions.map((q, i) => ({ question_id: q.id, chosen_index: answers[i] ?? 0 })).filter((_, i) => answers[i] !== null),
      } });
      if (ctx.live()) location.hash = '#/map?reveal=1';
    } catch (err) { if (ctx.live()) root.replaceChildren(errorCard(err.message, finish)); }
  }

  function show() {
    const q = questions[index];
    const last = index === questions.length - 1;
    const next = h('button', { class: 'btn btn-primary', type: 'button', disabled: answers[index] === null, onClick: () => (last ? finish() : (index++, show())) }, last ? 'Finish and see my map' : 'Next');
    const options = q.options.map((text, i) => h('button', { class: 'opt', type: 'button', role: 'radio', 'aria-checked': answers[index] === i ? 'true' : 'false', onClick: () => {
      answers[index] = i; next.disabled = false;
      options.forEach((o, k) => o.setAttribute('aria-checked', k === i ? 'true' : 'false'));
    } }, h('span', { class: 'opt-key', 'aria-hidden': 'true' }, 'ABCD'[i]), h('span', null, text)));
    root.replaceChildren(h('section', { class: 'narrow' },
      h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(questions.length), 'aria-valuenow': String(index + 1), 'aria-label': 'Diagnostic progress' },
        h('span', { style: { width: `${((index + 1) / questions.length) * 100}%` } })),
      h('p', { class: 'muted small' }, `Question ${index + 1} of ${questions.length} · ${q.chapter}`),
      h('div', { class: 'card question' }, h('h2', { class: 'stem' }, q.stem), h('div', { class: 'options', role: 'radiogroup', 'aria-label': 'Answer options' }, options)),
      h('div', { class: 'row between' },
        h('button', { class: 'btn btn-quiet', type: 'button', disabled: index === 0, onClick: () => { index--; show(); } }, 'Back'), next),
      h('p', { class: 'muted small' }, 'No right or wrong shown now. Your answers set your starting point.')));
    root.querySelector('.opt')?.focus({ preventScroll: true });
  }
  show();
}
