// Teacher dashboard: class heatmap, concept gaps, top misconceptions with quotes, at-risk students, and the "Reteach tomorrow" plan.
import { api } from '../api.js';
import { h } from '../dom.js';
import { errorCard, masteryColors, pct, skeleton } from '../ui.js';

const CHAPTERS = ['Light', 'Human Eye', 'Electricity', 'Magnetism'];

export async function teacher(root, ctx) {
  const ov = await api('/api/teacher/overview');
  if (!ctx.live()) return;
  if (!ov.student_count) {
    root.replaceChildren(h('section', { class: 'narrow card center' }, h('h1', { class: 'page-title' }, 'No class yet'), h('p', null, 'Load the demo class to see the dashboard.'),
      h('button', { class: 'btn btn-primary', type: 'button', onClick: async (e) => { e.target.disabled = true; await api('/api/demo/seed', { method: 'POST' }); location.reload(); } }, 'Load demo class')));
    return;
  }
  const classAvg = ov.heatmap.reduce((a, r) => a + r.average, 0) / ov.heatmap.length;
  const holders = new Set(ov.top_misconceptions.flatMap((m) => m.examples.map((e) => e.student_id)));

  // ---- heatmap
  const groups = CHAPTERS.map((c) => ({ c, ids: ov.concepts.filter((k) => k.chapter === c) }));
  const heat = h('div', { class: 'heat-scroll', tabindex: '0', role: 'region', 'aria-label': 'Class heatmap, scrolls sideways on small screens' },
    h('table', { class: 'heat' },
      h('thead', null,
        h('tr', null, h('th', { class: 'sticky' }, ''), groups.map((g) => h('th', { colspan: String(g.ids.length), class: 'group' }, g.c)), h('th', null, 'Avg')),
        h('tr', null, h('th', { class: 'sticky' }, 'Student'), groups.flatMap((g) => g.ids.map((k) => h('th', { title: k.name, class: 'cid' }, k.id))), h('th', null, ''))),
      h('tbody', null, ov.heatmap.map((r) => h('tr', null,
        h('th', { class: 'sticky' }, h('a', { href: `#/student/${r.student_id}`, class: 'link' }, r.name)),
        ov.concepts.map((k) => { const p = r.mastery[k.id]; const c = masteryColors(p); return h('td', { style: { background: c.bg, color: c.ink }, title: `${r.name} · ${k.name}: ${pct(p)}` }, Math.round(p * 100)); }),
        h('td', { class: 'avg' }, pct(r.average)))))));

  // ---- gaps chart
  const gaps = h('ol', { class: 'bars' }, ov.gaps.map((g) => { const c = masteryColors(g.average);
    return h('li', null, h('span', { class: 'bar-label', title: g.name }, `${g.concept_id} · ${g.name}`),
      h('span', { class: 'bar-track' }, h('i', { style: { width: `${g.average * 100}%`, background: c.border } })), h('span', { class: 'bar-val' }, pct(g.average)), h('span', { class: 'bar-sub muted small' }, `${g.below_half}/${ov.student_count} below 50%`)); }));

  // ---- misconceptions
  const mcs = ov.top_misconceptions.slice(0, 6).map((m) => h('li', { class: 'mc-row' },
    h('div', { class: 'mc-count', 'aria-label': `${m.students} students` }, h('b', null, m.students), h('small', null, m.students === 1 ? 'student' : 'students')),
    h('div', null, h('b', null, m.label), h('p', { class: 'small' }, m.description),
      m.examples.slice(0, 2).map((e) => h('blockquote', { class: 'quote' }, `“${e.quote}”`, h('small', null, ` ${e.student}`))))));

  // ---- at risk
  const risk = ov.at_risk.slice(0, 3).map((r) => h('li', { class: 'risk' }, h('a', { class: 'link', href: `#/student/${r.student_id}` }, h('b', null, r.name)),
    h('span', { class: 'muted small' }, `${pct(r.average)} average · ${r.active_misconceptions} active misconception${r.active_misconceptions === 1 ? '' : 's'}`),
    h('span', { class: 'small' }, `Weakest: ${r.weakest.map((w) => `${w.name} ${pct(w.p_known)}`).join(', ')}`)));

  // ---- reteach
  const reteachBox = h('div', { class: 'card reteach' }, h('p', { class: 'eyebrow' }, 'Reteach tomorrow'), h('h2', null, 'Planning your next lesson…'), h('p', { class: 'muted' }, 'The AI is reading the class data.'), skeleton(4));
  const loadReteach = async (refresh = false) => {
    try {
      const plan = await api(`/api/teacher/reteach?${refresh ? 'refresh=true' : ''}`, { timeout: 60000 });
      if (!ctx.live()) return;
      reteachBox.replaceChildren(h('p', { class: 'eyebrow' }, `Reteach tomorrow${plan.source === 'static' ? ' · basic plan (AI unavailable)' : ''}`), h('h2', null, plan.headline),
        h('ol', { class: 'plan' }, plan.items.map((it) => h('li', null, h('b', null, it.topic), it.why && h('p', { class: 'small' }, it.why),
          it.demo && h('p', null, h('b', null, 'Show: '), it.demo),
          (it.check_questions || []).length > 0 && h('ul', { class: 'checks' }, it.check_questions.map((q) => h('li', null, h('span', null, q.q), q.a && h('small', { class: 'muted' }, ` → ${q.a}`))))))),
        h('button', { class: 'btn btn-small', type: 'button', onClick: () => { reteachBox.replaceChildren(h('p', { class: 'muted' }, 'Regenerating…'), skeleton(3)); loadReteach(true); } }, 'Regenerate'));
    } catch (err) { if (ctx.live()) reteachBox.replaceChildren(errorCard(err.message, () => loadReteach(refresh))); }
  };

  root.replaceChildren(
    h('p', { class: 'eyebrow' }, `Teacher dashboard · Class ${ov.class_section}`), h('h1', { class: 'page-title' }, 'Where the whole class is stuck'),
    h('div', { class: 'stats' }, stat(ov.student_count, 'students'), stat(pct(classAvg), 'class mastery'), stat(ov.gaps.filter((g) => g.average < 0.5).length, 'concepts below 50%'), stat(holders.size, 'students with misconceptions')),
    reteachBox,
    h('section', { class: 'card' }, h('h2', null, 'Class heatmap'), h('p', { class: 'muted small' }, 'Students × concepts, % mastery. Click a name to open that student’s concept map.'), heat),
    h('div', { class: 'two-col' },
      h('section', { class: 'card' }, h('h2', null, 'Concept gaps'), h('p', { class: 'muted small' }, 'Class average per concept, weakest first.'), gaps),
      h('div', { class: 'stack' },
        h('section', { class: 'card' }, h('h2', null, 'Top misconceptions'), h('ul', { class: 'mc-list' }, mcs)),
        h('section', { class: 'card' }, h('h2', null, 'Students at risk'), h('ul', { class: 'risk-list' }, risk)))));
  loadReteach();
}

const stat = (value, label) => h('div', { class: 'stat' }, h('b', null, String(value)), h('span', null, label));
