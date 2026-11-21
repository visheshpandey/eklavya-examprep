// 🎯 Board-exam marks: a predicted CBSE Physics score (always labelled as an estimate) and the fixes ranked by the marks they could win back.
import { api, qs } from '../api.js';
import { h } from '../dom.js';

export const fmt = (n) => (Math.round(n * 10) / 10).toString();
export const loadBoard = (studentId) => api(`/api/ps02/board?${qs({ student_id: studentId })}`, { timeout: 15000 });

/** "Highest-marks fix first": the student's active misconceptions, biggest marks first. */
export function fixList(board, { max = 3 } = {}) {
  if (!board.fixes.length) return h('p', { class: 'muted small' }, 'No active misconceptions to fix right now.');
  return h('ol', { class: 'fix-list' }, board.fixes.slice(0, max).map((f) => h('li', null,
    h('span', { class: 'fix-rank', 'aria-hidden': 'true' }, `#${f.rank}`),
    h('div', null, h('b', null, f.label), h('p', { class: 'muted small' }, `${f.concept_name || 'Physics'} · wins back about ${fmt(f.marks)} marks`)),
    f.concept_id && h('a', { class: `btn btn-small ${f.rank === 1 ? 'btn-primary' : ''}`, href: `#/practice?concept=${f.concept_id}&talk=${f.misconception_id}` }, 'Fix it'))));
}

/** The predicted-score card for the map header. */
export function marksCard(board) {
  const pctOf = (v) => `${Math.min(100, (v / board.total) * 100)}%`;
  return h('section', { class: 'card marks-card', 'aria-label': 'Predicted board-exam score' },
    h('div', { class: 'marks-head' },
      h('div', null, h('p', { class: 'eyebrow' }, '🎯 Board-exam marks (estimate)'),
        h('p', { class: 'marks-score' }, h('b', null, `≈ ${fmt(board.predicted)}`), h('span', null, ` / ${fmt(board.total)} in CBSE Physics`)),
        h('p', { class: 'muted small' }, `Likely range ${fmt(board.low)} to ${fmt(board.high)}. It narrows as you practise.`)),
      h('div', { class: 'marks-range', role: 'img', 'aria-label': `Likely range ${fmt(board.low)} to ${fmt(board.high)} out of ${fmt(board.total)}` },
        h('i', { class: 'marks-band', style: { left: pctOf(board.low), width: `${Math.max(2, (board.high - board.low) / board.total * 100)}%` } }),
        h('b', { class: 'marks-dot', style: { left: pctOf(board.predicted) } }))),
    h('ul', { class: 'marks-chapters' }, board.chapters.map((c) => h('li', null, h('span', null, c.chapter), h('i', null, h('u', { style: { width: `${(c.predicted / c.marks) * 100}%` } })), h('small', null, `${fmt(c.predicted)}/${fmt(c.marks)}`)))),
    h('h3', null, 'Highest-marks fix first'), fixList(board),
    h('p', { class: 'muted small marks-note' }, board.label));
}

/** The teacher's class view: average predicted score and the top three misconceptions by marks at stake. */
export function classMarksCard(b) {
  return h('section', { class: 'card marks-card' },
    h('p', { class: 'eyebrow' }, '🎯 Board-exam marks (estimate)'),
    h('p', { class: 'marks-score' }, h('b', null, `≈ ${fmt(b.predicted_avg)}`), h('span', null, ` / ${fmt(b.total)} class average in CBSE Physics`)),
    h('h3', null, 'Top misconceptions by marks at stake'),
    b.top.length ? h('ol', { class: 'fix-list' }, b.top.map((t, i) => h('li', null, h('span', { class: 'fix-rank', 'aria-hidden': 'true' }, `#${i + 1}`),
      h('div', null, h('b', null, t.label), h('p', { class: 'muted small' }, `${t.students} student${t.students === 1 ? '' : 's'} · about ${fmt(t.marks)} marks across the class (${fmt(t.marks_each)} each)`)))))
      : h('p', { class: 'muted small' }, 'No active misconceptions in the class.'),
    h('p', { class: 'muted small marks-note' }, b.label));
}
