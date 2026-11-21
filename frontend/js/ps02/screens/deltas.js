// Mastery-change card: always "current -> new", shown immediately and never counting through intermediate values (no flicker).
// One card per attempt is updated IN PLACE (provisional answer -> after the explanation), so the numbers never jump back.
import { h } from '../dom.js';
import { pct } from '../ui.js';

function rowFor(d) {
  const from = h('span', { class: 'from' }), to = h('span', { class: 'to' }), arrow = h('span', { class: 'arrow', 'aria-hidden': 'true' });
  const fill = h('i', { style: { width: `${d.before * 100}%` } });
  const name = h('span', { class: 'delta-name' });
  const el = h('div', { class: 'delta' }, name, h('span', { class: 'delta-vals' }, from, ' → ', to, arrow), h('span', { class: 'delta-bar', 'aria-hidden': 'true' }, fill));
  return { el, from, to, arrow, fill, name, shown: null };
}

function paint(row, d) {
  const up = d.after > d.before + 0.0005, down = d.after < d.before - 0.0005;
  const label = d.reason.startsWith('prerequisite') ? ' (prerequisite effect)' : d.reason === 'careless slip' ? ' (treated as a slip)' : '';
  row.name.replaceChildren(d.name, label && h('small', null, label));
  row.from.textContent = pct(d.before);
  const text = pct(d.after);
  if (row.to.textContent !== text) {
    row.to.textContent = text;
    if (row.shown !== null) { row.to.classList.remove('bump'); void row.to.offsetWidth; row.to.classList.add('bump'); }
  }
  row.arrow.textContent = up ? ' ▲' : down ? ' ▼' : '';
  row.el.className = `delta ${up ? 'delta-up' : down ? 'delta-down' : ''}`;
  requestAnimationFrame(() => { row.fill.style.width = `${d.after * 100}%`; });
  row.shown = d.after;
}

/** deltaList(deltas, {title}) -> element; el.update(newDeltas, newTitle) changes it in place. */
export function deltaList(deltas, { title = 'Your mastery just changed' } = {}) {
  const heading = h('h3', null, title);
  const el = h('div', { class: 'deltas', 'aria-live': 'polite' }, heading);
  const rows = new Map();
  el.update = (next, nextTitle) => {
    if (nextTitle) heading.textContent = nextTitle;
    for (const d of next) {
      let row = rows.get(d.concept_id);
      if (!row) { row = rowFor(d); rows.set(d.concept_id, row); el.append(row.el); }
      paint(row, d);
    }
  };
  el.update(deltas);
  return el;
}
