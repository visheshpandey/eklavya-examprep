// "Your teacher assigned this": shown on the student's Map and Practice screens while an assignment is pending.
import { api, qs } from '../api.js';
import { h } from '../dom.js';

export async function assignmentBanner(student, { compact = false } = {}) {
  try {
    const { assignments } = await api(`/api/ps02/assignments?${qs({ student_id: student.id })}`, { timeout: 12000 });
    if (!assignments.length) return null;
    const a = assignments[0];
    return h('section', { class: 'card assign-banner', 'aria-label': 'Assigned by your teacher' },
      h('p', { class: 'eyebrow' }, '📌 Your teacher assigned this'),
      h('h2', null, a.misconception.label),
      !compact && h('p', null, `A short conversation about this idea, then practice on ${a.concept_name || 'the concept'}. About 5 minutes.`),
      h('a', { class: 'btn btn-primary', href: `#/practice?concept=${a.concept_id}&talk=${a.misconception.id}&assignment=${a.assignment_id}` }, 'Start now'),
      assignments.length > 1 && h('span', { class: 'muted small' }, ` +${assignments.length - 1} more`));
  } catch { return null; }
}
