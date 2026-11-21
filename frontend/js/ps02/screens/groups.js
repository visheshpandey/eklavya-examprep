// Teacher co-pilot UI: students grouped by a shared misconception -> a 10-minute mini-lesson -> assign targeted practice -> before / after.
import { api, qs } from '../api.js';
import { h } from '../dom.js';
import { setStudent } from '../state.js';
import { errorCard, skeleton, toast } from '../ui.js';
import { stageChip } from './chain.js';

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

function lessonView(l, { onRegenerate }) {
  const copy = async () => { try { await navigator.clipboard.writeText(l.script_hinglish); toast('Script copied.'); } catch { toast('Select the text and copy it.'); } };
  return h('div', { class: 'lesson' },
    h('div', { class: 'row between wrap' }, h('h4', null, l.title), h('span', { class: `chip ${l.source === 'ai' ? 'chip-action' : ''}` }, l.source === 'ai' ? 'AI-written' : 'Prepared lesson (AI was unavailable)')),
    h('div', { class: 'lesson-grid' },
      h('div', null, h('h5', null, '1 · Hook (2–3 min)'), h('p', null, l.hook_demo)),
      h('div', null, h('h5', null, '2 · Analogy'), h('p', null, l.analogy))),
    h('h5', null, '3 · Check questions'),
    h('ol', { class: 'checks' }, l.check_questions.map((q) => h('li', null, h('details', null, h('summary', null, q.q), h('p', { class: 'small ok-text' }, `Answer: ${q.a}`))))),
    l.board_notes?.length > 0 && h('div', null, h('h5', null, 'On the board'), h('ul', { class: 'bullets' }, l.board_notes.map((n) => h('li', null, n)))),
    h('div', { class: 'script' }, h('div', { class: 'row between wrap' }, h('h5', null, 'What to say (Hinglish script)'), h('button', { class: 'btn btn-small', type: 'button', onClick: copy }, 'Copy')), h('p', null, l.script_hinglish)),
    h('div', { class: 'row' }, h('button', { class: 'btn btn-quiet btn-small', type: 'button', onClick: onRegenerate }, 'Regenerate'), l.cached && h('span', { class: 'muted small' }, 'Saved from earlier, so it opens instantly.')));
}

function statusView(a) {
  if (!a) return h('p', { class: 'muted small' }, 'Not assigned yet. Assigning sends each student a short conversation about this misconception plus practice on the concept.');
  const cleared = a.after === 0;
  return h('div', { class: 'assign-state' },
    h('p', null, h('b', null, `Assigned to ${plural(a.assigned, 'student')}`), ` · ${a.done} done${a.resolved ? `, ${a.resolved} explained it themselves` : ''}`),
    h('div', { class: 'before-after', 'aria-label': `Before: ${a.before} held it. Now: ${a.after} still hold it.` },
      h('span', { class: 'ba before' }, h('b', null, a.before), h('small', null, 'held it')), h('span', { class: 'ba-arrow', 'aria-hidden': 'true' }, '→'),
      h('span', { class: `ba after ${cleared ? 'cleared' : ''}` }, h('b', null, a.after), h('small', null, cleared ? 'still hold it: cleared!' : 'still hold it'))),
    a.verified > 0 && h('p', { class: 'small ok-text' }, `✅ ${a.verified} of ${a.assigned} verified fixed by a trap question`),
    h('div', { class: 'chips' }, a.students.map((s) => h('span', { class: `chip ${s.outcome === 'resolved' ? 'chip-ok' : s.status === 'done' ? 'chip-warn' : ''}` },
      `${s.name}: ${s.outcome === 'resolved' ? '✓ explained it' : s.status === 'done' ? 'tried, still unsure' : 'not started'}`), stageChip(s.stage))));
}

function groupCard(g, reload) {
  const lessonBox = h('div');
  const statusBox = h('div', null, statusView(g.assignment));
  const lessonBtn = h('button', { class: 'btn', type: 'button' }, g.lesson_ready ? 'Open mini-lesson' : 'Generate 10-min mini-lesson');
  async function loadLesson(refresh = false) {
    lessonBtn.disabled = true;
    lessonBox.replaceChildren(h('div', { class: 'loading-card', role: 'status' }, h('p', { class: 'muted' }, 'Writing a 10-minute lesson for this group…'), skeleton(4)));
    try {
      const l = await api(`/api/teacher/lesson?${qs({ misconception_id: g.id, ...(refresh ? { refresh: 'true' } : {}) })}`, { timeout: 60000 });
      lessonBox.replaceChildren(lessonView(l, { onRegenerate: () => loadLesson(true) }));
      lessonBtn.textContent = 'Refresh mini-lesson';
    } catch (err) { lessonBox.replaceChildren(errorCard(err.message, () => loadLesson(refresh))); } finally { lessonBtn.disabled = false; }
  }
  lessonBtn.addEventListener('click', () => loadLesson(false));
  const assignBtn = h('button', { class: 'btn btn-primary', type: 'button', disabled: g.size === 0, onClick: async () => {
    assignBtn.disabled = true;
    try {
      const r = await api('/api/teacher/assign', { method: 'POST', body: { misconception_id: g.id } });
      statusBox.replaceChildren(statusView(r.state));
      toast(r.topped_up ? 'Updated the existing assignment.' : `Assigned to ${plural(r.students.length, 'student')}. They will see it as "Your teacher assigned this".`);
    } catch (err) { toast(err.message); } finally { assignBtn.disabled = false; }
  } }, g.assignment ? 'Assign again / top up' : 'Assign to group');
  const first = g.students[0];
  const preview = first && h('button', { class: 'btn btn-quiet btn-small', type: 'button', title: 'Open the student side as this student, to see what they will see',
    onClick: () => { setStudent({ id: first.student_id, name: first.name, demo: true }); location.hash = '#/map'; } }, `Preview as ${first.name.split(' ')[0]}`);
  return h('article', { class: `group-card ${g.size === 0 ? 'group-clear' : ''}` },
    h('div', { class: 'row between wrap tight' }, h('h3', null, `${g.name} · ${plural(g.size, 'student')}`), h('span', { class: 'chip' }, g.concept_names[0] || 'Physics')),
    h('p', null, h('b', null, g.misconception.label), ': ', g.misconception.description),
    g.size > 0 && h('div', { class: 'chips' }, g.students.map((s) => h('a', { class: 'chip chip-action', href: `#/student/${s.student_id}`, title: s.quote ? `“${s.quote}”` : '' }, s.name))),
    g.size > 0 && g.students.filter((s) => s.quote).slice(0, 2).map((s) => h('blockquote', { class: 'quote' }, `“${s.quote}”`, h('small', null, ` ${s.name}`), s.source === 'notebook' && h('span', { class: 'chip chip-action' }, '📸 from notebook'))),
    statusBox,
    h('div', { class: 'row' }, lessonBtn, assignBtn, preview), lessonBox);
}

/** The "Groups by shared misconception" section. */
export function groupsSection(ctx) {
  const body = h('div', { class: 'groups' }, h('div', { class: 'loading-card' }, skeleton(3)));
  async function load() {
    try {
      const data = await api('/api/teacher/groups');
      if (!ctx.live()) return;
      body.replaceChildren(
        data.groups.length ? data.groups.map((g) => groupCard(g, load)) : h('p', { class: 'muted' }, 'No two students share an active misconception right now.'),
        data.individual_misconceptions > 0 && h('p', { class: 'muted small' }, `${plural(data.individual_misconceptions, 'other misconception')} held by single students (see the heatmap and at-risk list).`));
    } catch (err) { if (ctx.live()) body.replaceChildren(errorCard(err.message, load)); }
  }
  load();
  return h('section', { class: 'card' }, h('p', { class: 'eyebrow' }, 'Teacher co-pilot'), h('h2', null, 'Groups by shared misconception'),
    h('p', { class: 'muted small' }, 'Students who believe the same wrong idea, grouped for you. Generate a 10-minute lesson for the group, assign them targeted practice, and watch how many still hold it afterwards.'), body);
}
