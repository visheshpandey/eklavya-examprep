// Shared UI pieces: colours for mastery, skeletons, toasts, error cards, count-up numbers.
import { h } from './dom.js';

export const pct = (p) => `${Math.round(p * 100)}%`;
const reduced = () => globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/** Red -> amber -> green. Returns self-contained colours so a cell reads the same in light and dark mode. */
export function masteryColors(p) {
  const hue = p < 0.5 ? 5 + p * 2 * 38 : 43 + (p - 0.5) * 2 * 82;
  return { bg: `hsl(${Math.round(hue)} 62% 82%)`, border: `hsl(${Math.round(hue)} 45% 36%)`, ink: `hsl(${Math.round(hue)} 70% 13%)` };
}

export const level = (p) => (p < 0.4 ? 'Needs work' : p < 0.7 ? 'Getting there' : 'Strong');

export function skeleton(lines = 3, kind = '') {
  return h('div', { class: `skeleton ${kind}`, 'aria-hidden': 'true' }, Array.from({ length: lines }, (_, i) => h('div', { class: 'sk-line', style: { width: `${92 - i * 14}%` } })));
}

export function loading(message, lines = 3) {
  return h('div', { class: 'loading-card', role: 'status' }, h('p', { class: 'muted' }, message), skeleton(lines));
}

export function errorCard(message, onRetry) {
  return h('div', { class: 'card error-card', role: 'alert' },
    h('h2', null, 'That did not work'), h('p', null, message),
    onRetry && h('button', { class: 'btn', type: 'button', onClick: onRetry }, 'Try again'));
}

export function toast(message) {
  const box = document.getElementById('toasts');
  const t = h('div', { class: 'toast' }, message);
  box.append(t);
  setTimeout(() => t.remove(), 3500);
}

/** Animate a number inside `node` from `from` to `to` (percent points), calling format(value). */
export function countUp(node, from, to, format = (v) => `${Math.round(v)}%`, ms = 700) {
  if (reduced() || from === to) { node.textContent = format(to); return; }
  const start = performance.now();
  const tick = (now) => {
    const t = Math.min(1, (now - start) / ms);
    node.textContent = format(from + (to - from) * (1 - Math.pow(1 - t, 3)));
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/** "in 6 days" / "in 4 minutes" / "overdue by 2 days". `unit` is 'day' normally, 'minute' in time-travel mode. */
export function when(iso, nowMs = Date.now()) {
  const diff = new Date(iso).getTime() - nowMs;
  const abs = Math.abs(diff);
  const m = Math.round(abs / 60000), hr = Math.round(abs / 3600000), d = Math.round(abs / 86400000);
  const text = m < 1 ? 'now' : m < 90 ? `${m} min` : hr < 36 ? `${hr} h` : `${d} day${d === 1 ? '' : 's'}`;
  return diff <= 0 ? (m < 1 ? 'due now' : `overdue by ${text}`) : `in ${text}`;
}

export function sparkline(points, { width = 220, height = 48 } = {}) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('class', 'spark');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `Mastery over time: ${points.map((p) => pct(p)).join(', ')}`);
  if (points.length < 2) return svg;
  const x = (i) => 4 + (i * (width - 8)) / (points.length - 1);
  const y = (p) => height - 4 - p * (height - 8);
  const line = document.createElementNS(ns, 'polyline');
  line.setAttribute('points', points.map((p, i) => `${x(i).toFixed(1)},${y(p).toFixed(1)}`).join(' '));
  line.setAttribute('class', 'spark-line');
  const dot = document.createElementNS(ns, 'circle');
  dot.setAttribute('cx', x(points.length - 1).toFixed(1));
  dot.setAttribute('cy', y(points[points.length - 1]).toFixed(1));
  dot.setAttribute('r', '3.5');
  dot.setAttribute('class', 'spark-dot');
  svg.append(line, dot);
  return svg;
}
