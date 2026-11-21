// Mastery map: the concept graph as nodes + prerequisite edges, coloured red -> amber -> green by p_known.
// Wide screens get the SVG graph; phones get the same nodes as a chapter-grouped list. Both open the same detail panel.
import { api, qs } from '../api.js';
import { h, s } from '../dom.js';
import { getLang, getStudent } from '../state.js';
import { countUp, level, loading, masteryColors, pct, sparkline } from '../ui.js';
import { assignmentBanner } from './assignment-banner.js';
import { chain, verifiedBadge } from './chain.js';
import { diffSnap, readSnap, writeSnap } from '../snapshot.js';

const CHAPTERS = ['Light', 'Human Eye', 'Electricity', 'Magnetism'];
const NODE_W = 112, NODE_H = 58, SLOT = 128, CHAPTER_GAP = 30, ROW_H = 92, PAD = 14;

function layout(nodes) {
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const depth = {};
  const dig = (id) => (depth[id] ??= byId[id].prerequisites.length ? 1 + Math.max(...byId[id].prerequisites.map(dig)) : 0);
  nodes.forEach((n) => dig(n.id));
  const cells = {};
  for (const n of nodes) (cells[`${n.chapter}|${depth[n.id]}`] ??= []).push(n);
  const slots = Object.fromEntries(CHAPTERS.map((c) => [c, Math.max(1, ...Object.entries(cells).filter(([k]) => k.startsWith(`${c}|`)).map(([, v]) => v.length))]));
  const originX = {};
  let x = PAD;
  for (const c of CHAPTERS) { originX[c] = x; x += slots[c] * SLOT + CHAPTER_GAP; }
  const pos = {};
  for (const [key, group] of Object.entries(cells)) {
    const [chapter, row] = key.split('|');
    const used = group.length * SLOT;
    const start = originX[chapter] + (slots[chapter] * SLOT - used) / 2;
    group.forEach((n, i) => { pos[n.id] = { x: start + i * SLOT + (SLOT - NODE_W) / 2, y: 38 + Number(row) * ROW_H }; });
  }
  const rows = Math.max(...Object.values(depth)) + 1;
  return { pos, originX, slots, width: x - CHAPTER_GAP + PAD, height: 38 + rows * ROW_H };
}

const wrap = (text, max = 17) => {
  const lines = []; let line = '';
  for (const word of text.split(' ')) {
    if ((line + ' ' + word).trim().length > max && line) { lines.push(line); line = word; } else line = (line + ' ' + word).trim();
  }
  if (line) lines.push(line);
  return lines.slice(0, 2);
};

export async function mapScreen(root, ctx) {
  const teacherView = ctx.arg !== '';
  const studentId = teacherView ? Number(ctx.arg) : getStudent().id;
  const data = await api(`/api/mastery?${qs({ student_id: studentId })}`);
  if (!ctx.live()) return;
  const nodes = data.nodes;
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const reveal = ctx.query.reveal === '1';
  const lay = layout(nodes);
  const changed = new Map((teacherView || reveal ? [] : diffSnap(readSnap(studentId), nodes)).map((c) => [c.id, c]));   // moved since you last looked
  const panel = h('aside', { class: 'card detail', 'aria-live': 'polite' }, h('p', { class: 'muted' }, 'Tap any concept to see its mastery, prerequisites, history and misconceptions.'));
  let selected = null;
  const nodeEls = new Map();
  let changedOrder = 0;

  // ---------- SVG graph
  const svg = s('svg', { class: 'graph', viewBox: `0 0 ${lay.width} ${lay.height}`, role: 'group', 'aria-label': 'Concept graph. Each box is a concept; lines run from a prerequisite to the concept that needs it.' });
  for (const c of CHAPTERS) {
    svg.append(s('text', { class: 'chapter-label', x: lay.originX[c], y: 18 }, c.toUpperCase()));
  }
  const edgeEls = [];
  for (const e of data.edges) {
    const a = lay.pos[e.from], b = lay.pos[e.to];
    const x1 = a.x + NODE_W / 2, y1 = a.y + NODE_H, x2 = b.x + NODE_W / 2, y2 = b.y;
    const my = (y1 + y2) / 2;
    const path = s('path', { class: 'edge', d: `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`, 'marker-end': 'url(#arrow)' });
    edgeEls.push({ e, path }); svg.append(path);
  }
  svg.prepend(s('defs', null, s('marker', { id: 'arrow', viewBox: '0 0 8 8', refX: '7', refY: '4', markerWidth: '7', markerHeight: '7', orient: 'auto' }, s('path', { d: 'M0,0 L8,4 L0,8 z', class: 'arrow' }))));
  nodes.forEach((n, i) => {
    const p = lay.pos[n.id], c = masteryColors(n.p_known);
    const ch = changed.get(n.id), old = ch && masteryColors(ch.before);
    const pctText = s('text', { class: 'node-pct', x: NODE_W / 2, y: 20, 'text-anchor': 'middle', fill: c.ink }, reveal ? '0%' : pct(ch ? ch.before : n.p_known));
    const label = wrap(n.short || n.name);
    const g = s('g', { class: `node ${reveal ? 'node-reveal' : ''}`, transform: `translate(${p.x},${p.y})`, tabindex: '0', role: 'button', 'aria-label': `${n.name}: ${pct(n.p_known)} mastery, ${level(n.p_known)}`, style: reveal ? { animationDelay: `${i * 55}ms` } : null },
      s('rect', { class: 'node-body', width: NODE_W, height: NODE_H, rx: '9', fill: ch ? old.bg : c.bg, stroke: ch ? old.border : c.border, 'stroke-width': '1.6' }),
      ch && s('rect', { class: 'node-pulse', width: NODE_W, height: NODE_H, rx: '9', fill: 'none' }),
      ch && s('text', { class: `node-delta ${ch.after > ch.before ? 'up' : 'down'}`, x: NODE_W - 6, y: -4, 'text-anchor': 'end' }, `${ch.after > ch.before ? '+' : '−'}${Math.round(Math.abs(ch.after - ch.before) * 100)}`),
      s('text', { class: 'node-id', x: 8, y: 14, fill: c.ink }, n.id), pctText,
      ...label.map((l, k) => s('text', { class: 'node-name', x: NODE_W / 2, y: 36 + k * 12, 'text-anchor': 'middle', fill: c.ink }, l)),
      n.review_due && s('circle', { cx: NODE_W - 8, cy: 8, r: '5', class: 'dot-due' }, s('title', null, 'Review due')),
      n.misconceptions.length > 0 && s('g', { transform: `translate(${NODE_W - 8},${NODE_H - 9})` }, s('circle', { r: '7', class: 'dot-mc' }), s('text', { class: 'dot-mc-text', 'text-anchor': 'middle', y: 3.5 }, '!')));
    g.addEventListener('click', () => select(n.id));
    g.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); select(n.id); } });
    nodeEls.set(n.id, g); svg.append(g);
    if (reveal) setTimeout(() => ctx.live() && countUp(pctText, 0, n.p_known * 100), i * 55 + 150);
    if (ch) {   // glide from the old colour and number to the new ones
      setTimeout(() => {
        if (!ctx.live()) return;
        const body = g.querySelector('.node-body');
        body.setAttribute('fill', c.bg); body.setAttribute('stroke', c.border);
        pctText.setAttribute('fill', c.ink); countUp(pctText, ch.before * 100, ch.after * 100, undefined, 900);
        g.querySelectorAll('text:not(.node-delta)').forEach((t) => t.setAttribute('fill', c.ink));
      }, 450 + changedOrder++ * 140);
    }
  });

  // ---------- phone list
  const list = h('div', { class: 'node-list' }, CHAPTERS.map((chapter) => h('section', null,
    h('h3', { class: 'chapter-h' }, chapter),
    nodes.filter((n) => n.chapter === chapter).map((n) => {
      const c = masteryColors(n.p_known);
      return h('button', { class: 'node-card', type: 'button', style: { borderColor: c.border }, onClick: () => select(n.id) },
        h('span', { class: 'nc-pct', style: { background: c.bg, color: c.ink } }, pct(n.p_known)),
        h('span', { class: 'nc-body' }, h('b', null, `${n.id} · ${n.name}`),
          n.prerequisites.length > 0 && h('small', null, `Needs: ${n.prerequisites.map((p) => byId[p].short).join(', ')}`)),
        n.misconceptions.length > 0 && h('span', { class: 'chip chip-bad' }, `${n.misconceptions.length} misconception${n.misconceptions.length > 1 ? 's' : ''}`),
        n.review_due && h('span', { class: 'chip chip-warn' }, 'review due'));
    }))));

  // ---------- detail panel
  async function select(id) {
    selected = id;
    nodeEls.forEach((g, k) => g.classList.toggle('selected', k === id));
    window.dispatchEvent(new CustomEvent('ps02:context', { detail: { concept_id: id } }));
    edgeEls.forEach(({ e, path }) => path.classList.toggle('edge-hot', e.from === id || e.to === id));
    const n = byId[id], c = masteryColors(n.p_known);
    const spark = h('div', { class: 'spark-wrap' }, h('p', { class: 'muted small' }, 'Loading history…'));
    panel.replaceChildren(
      h('div', { class: 'detail-head' }, h('span', { class: 'big-pct', style: { background: c.bg, color: c.ink, borderColor: c.border } }, pct(n.p_known)),
        h('div', null, h('p', { class: 'eyebrow' }, `${n.chapter} · ${n.id}`), h('h2', null, n.name), h('p', { class: 'muted small' }, `${level(n.p_known)} · ${n.attempts} attempt${n.attempts === 1 ? '' : 's'}, ${n.correct} correct`))),
      h('p', null, n.description),
      n.key_formulas.length > 0 && h('p', { class: 'formulas' }, n.key_formulas.map((f) => h('code', null, f))),
      n.prerequisites.length > 0 && h('div', null, h('h3', null, 'Builds on'),
        h('div', { class: 'chips' }, n.prerequisites.map((p) => h('button', { class: 'chip', type: 'button', onClick: () => select(p) }, `${byId[p].short} ${pct(byId[p].p_known)}`)))),
      h('div', null, h('h3', null, 'Mastery over time'), spark),
      n.misconceptions.length > 0
        ? h('div', null, h('h3', null, 'Active misconceptions'), n.misconceptions.map((m) => h('div', { class: 'mc-mini' },
          h('b', null, m.label), h('p', { class: 'small' }, m.description),
          m.quote && h('blockquote', { class: 'quote' }, `“${m.quote}”`), h('p', { class: 'small ok-text' }, m.correction))))
        : h('p', { class: 'muted small' }, 'No active misconceptions on this concept.'),
      (n.misconception_chain || []).length > 0 && h('div', null, h('h3', null, 'Misconception status'),
        n.misconception_chain.map((m) => h('div', { class: 'mc-status' }, h('b', { class: 'small' }, m.label), chain(m.stage), m.stage === 'verified' && verifiedBadge()))),
      h('div', null, h('h3', null, `Doubts asked (${n.doubts_count || 0})`),
        n.doubts_count ? n.recent_doubts.map((d) => h('p', { class: 'small doubt-row' }, `“${d.question}”`, d.misconception_id && h('span', { class: 'chip chip-bad' }, 'misconception')))
          : h('p', { class: 'muted small' }, 'No doubts asked about this concept yet.'),
        !teacherView && h('button', { class: 'btn btn-small', type: 'button', onClick: () => window.dispatchEvent(new CustomEvent('ps02:ask', { detail: { concept_id: n.id } })) }, 'Ask a doubt about this')),
      n.review_due && h('p', { class: 'chip chip-warn' }, 'A spaced-repetition review is due for this concept.'),
      !teacherView && h('a', { class: 'btn btn-primary', href: `#/practice?concept=${n.id}` }, 'Practise this'));
    if (matchMedia('(max-width: 899px)').matches) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    try {
      const hist = await api(`/api/mastery/history?${qs({ student_id: studentId, concept_id: id })}`, { timeout: 15000 });
      if (selected !== id || !ctx.live()) return;
      const pts = hist.points.map((p) => p.p_known);
      spark.replaceChildren(pts.length > 1 ? h('div', { class: 'spark-row' }, sparkline(pts), h('span', { class: 'muted small' }, `${pct(pts[0])} → ${pct(pts[pts.length - 1])} over ${pts.length} updates`))
        : h('p', { class: 'muted small' }, 'Not enough practice yet to draw a trend.'));
    } catch { spark.replaceChildren(h('p', { class: 'muted small' }, 'History is unavailable right now.')); }
  }

  // ---------- root cause: when the student keeps failing a concept, trace back to the real cause and draw the path on the map
  const rcBox = h('section', { class: 'card root-card', hidden: true, 'aria-live': 'polite' });
  const assignBox = h('div');
  if (!teacherView) assignmentBanner({ id: studentId }).then((b) => { if (b && ctx.live()) assignBox.replaceChildren(b); });
  function showPath(t) {
    nodeEls.forEach((g) => g.classList.remove('on-path', 'root-cause', 'struggling'));
    edgeEls.forEach(({ path }) => path.classList.remove('edge-root'));
    if (!t || !t.root) return;
    t.path.forEach((id) => nodeEls.get(id)?.classList.add('on-path'));
    nodeEls.get(t.concept_id)?.classList.add('struggling');
    nodeEls.get(t.root.concept_id)?.classList.add('root-cause');
    for (let i = 0; i < t.path.length - 1; i++) edgeEls.filter(({ e }) => e.from === t.path[i + 1] && e.to === t.path[i]).forEach(({ path }) => path.classList.add('edge-root'));
  }
  async function loadStruggles() {
    if (teacherView) return;
    try {
      const { struggles } = await api(`/api/ps02/struggles?${qs({ student_id: studentId, language: getLang() })}`, { timeout: 15000 });
      const t = struggles.find((s) => s.root);
      if (!t || !ctx.live()) return;
      const mcId = t.root.misconception?.id;
      const sentence = h('p', { class: 'lede-small' }, t.explanation);
      rcBox.hidden = false;
      rcBox.replaceChildren(h('p', { class: 'eyebrow' }, 'Root cause found'), h('h2', null, `${t.name} keeps going wrong`), sentence,
        h('p', { class: 'small muted' }, `${t.path.map((id) => byId[id].short || byId[id].name).join(' → ')}  (the line on the map)`),
        h('div', { class: 'row' }, h('a', { class: 'btn btn-primary', href: `#/practice?concept=${t.root.concept_id}${mcId ? `&talk=${mcId}` : ''}` }, 'Fix the root first'),
          h('button', { class: 'btn', type: 'button', onClick: () => { showPath(null); requestAnimationFrame(() => showPath(t)); } }, 'Replay the path'),
          h('button', { class: 'btn btn-quiet', type: 'button', onClick: () => { rcBox.hidden = true; showPath(null); } }, 'Hide')));
      showPath(t);
      // upgrade the sentence to the AI-written one when it arrives (the plain one is already on screen)
      api(`/api/ps02/root-cause?${qs({ student_id: studentId, concept_id: t.concept_id, language: getLang() })}`, { timeout: 12000 })
        .then((r) => { if (ctx.live() && r.explanation) sentence.textContent = r.explanation; }).catch(() => {});
    } catch { /* the banner is an extra: the map works without it */ }
  }

  // ---------- header
  const avg = nodes.reduce((a, n) => a + n.p_known, 0) / nodes.length;
  const weakest = data.weakest.map((id) => byId[id]);
  const dueCount = nodes.filter((n) => n.review_due).length;
  const chapterAvg = CHAPTERS.map((c) => ({ c, v: nodes.filter((n) => n.chapter === c).reduce((a, n) => a + n.p_known, 0) / nodes.filter((n) => n.chapter === c).length })).sort((a, b) => b.v - a.v);
  root.replaceChildren(
    teacherView && h('p', null, h('a', { class: 'link', href: '#/teacher' }, '← Back to teacher dashboard')),
    h('section', { class: 'map-head' },
      h('div', null, h('p', { class: 'eyebrow' }, teacherView ? 'Teacher view' : reveal ? 'Here is what the diagnostic found' : 'Your concept map'),
        h('h1', { class: 'page-title' }, teacherView ? `${data.student.name}’s concept map` : `${data.student.name}, here is where you stand`),
        h('p', { class: 'lede' }, `Overall ${pct(avg)}. Strongest in ${chapterAvg[0].c} (${pct(chapterAvg[0].v)}), weakest in ${chapterAvg[3].c} (${pct(chapterAvg[3].v)}).`)),
      h('div', { class: 'legend', 'aria-label': 'Colour legend' }, h('span', null, 'Needs work'), h('i', { class: 'legend-bar' }), h('span', null, 'Strong'))),
    !teacherView && h('section', { class: 'card next-steps' }, h('h2', null, 'Start with the weakest concepts that you are ready for'),
      h('div', { class: 'chips' }, weakest.map((n) => h('a', { class: 'chip chip-action', href: `#/practice?concept=${n.id}` }, `${n.short} · ${pct(n.p_known)}`))),
      h('div', { class: 'row' }, h('a', { class: 'btn btn-primary', href: '#/practice' }, 'Start practising'),
        dueCount > 0 && h('a', { class: 'btn', href: '#/reviews' }, `${dueCount} review${dueCount > 1 ? 's' : ''} due`))),
    assignBox,
    rcBox,
    h('div', { class: 'map-grid' }, h('div', { class: 'card graph-card' }, svg, list), panel));
  if (!teacherView) writeSnap(studentId, nodes);   // the next visit animates only what changes after this one
  if (reveal) history.replaceState(null, '', '#/map');
  loadStruggles();
  const onLang = () => { if (!ctx.live()) { globalThis.removeEventListener('ps02:lang', onLang); return; } loadStruggles(); };   // the root-cause card follows the chosen language
  globalThis.addEventListener('ps02:lang', onLang);
  if (!teacherView) api(`/api/practice/prefetch?${qs({ student_id: studentId })}`, { method: 'POST', timeout: 20000 }).catch(() => {});   // warm the first practice question
}
