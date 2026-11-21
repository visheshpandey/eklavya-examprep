// Mastery-change list with animated numbers and bars (shared by Practice and the Socratic dialogue).
import { h } from '../dom.js';
import { countUp, pct } from '../ui.js';

export function deltaList(deltas, { title = 'Your mastery just changed' } = {}) {
  return h('div', { class: 'deltas', 'aria-live': 'polite' }, h('h3', null, title),
    deltas.map((d) => {
      const up = d.after > d.before, same = Math.abs(d.after - d.before) < 0.0005;
      const num = h('span', { class: 'delta-num' }, pct(d.before));
      const prereq = d.reason.startsWith('prerequisite');
      setTimeout(() => countUp(num, d.before * 100, d.after * 100), 250);
      return h('div', { class: `delta ${same ? '' : up ? 'delta-up' : 'delta-down'}` },
        h('span', { class: 'delta-name' }, d.name, prereq && h('small', null, ' (prerequisite effect)'), d.reason === 'careless slip' && h('small', null, ' (treated as a slip)')),
        h('span', { class: 'delta-vals' }, pct(d.before), ' → ', num, h('span', { class: 'arrow', 'aria-hidden': 'true' }, same ? '' : up ? ' ▲' : ' ▼')),
        h('span', { class: 'delta-bar', 'aria-hidden': 'true' }, h('i', { style: { width: `${d.before * 100}%` } })));
    }));
}

export function animateBars(container, deltas) {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    container.querySelectorAll('.delta-bar i').forEach((bar, i) => { bar.style.width = `${deltas[i].after * 100}%`; });
  }));
}
