// "Eklavya's thinking": a collapsible log of the tutor agent's tool calls (what it checked and decided, and why).
import { h } from './dom.js';

const OPEN_KEY = 'ps02.think';
const LABELS = {
  get_mastery: 'Checked mastery', trace_root_cause: 'Traced root cause', pick_concept: 'Chose the concept', calibrate_difficulty: 'Set the difficulty',
  generate_question: 'Wrote the question', update_mastery: 'Updated mastery', detect_misconception: 'Read your reasoning', schedule_review: 'Scheduled a review', start_dialogue: 'Started a conversation',
};
const readOpen = () => { try { return localStorage.getItem(OPEN_KEY) !== '0'; } catch { return true; } };
// the first question of a browser session always opens the panel, so a first-time viewer sees the agent thinking
const firstThisSession = () => { try { if (sessionStorage.getItem('ps02.thinkSeen')) return false; sessionStorage.setItem('ps02.thinkSeen', '1'); return true; } catch { return false; } };
export const fmtMs = (ms) => (ms == null ? '' : ms < 10 ? 'instant' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);

export function thinkingPanel(initial = []) {
  const list = h('ol', { class: 'think-list' });
  const count = h('span', { class: 'think-count' });
  const details = h('details', { class: 'think', open: firstThisSession() || readOpen(), onToggle: () => { try { localStorage.setItem(OPEN_KEY, details.open ? '1' : '0'); } catch { /* ignore */ } } },
    h('summary', null, h('span', { class: 'think-icon', 'aria-hidden': 'true' }, '🧠'), h('b', null, 'Eklavya’s thinking'), count, h('span', { class: 'muted small' }, ' · what the tutor checked and decided')),
    list);
  let n = 0;
  function add(steps = []) {
    steps.forEach((s, i) => {
      list.append(h('li', { class: 'think-step', style: { animationDelay: `${i * 90}ms` } },
        h('span', { class: `think-tool tool-${s.tool}` }, LABELS[s.tool] || s.tool),
        h('span', { class: 'think-text' }, s.summary), s.ms != null && h('span', { class: 'think-ms muted small' }, fmtMs(s.ms))));
      n += 1;
    });
    count.textContent = ` ${n} step${n === 1 ? '' : 's'}`;
  }
  add(initial);
  return { el: details, add };
}
