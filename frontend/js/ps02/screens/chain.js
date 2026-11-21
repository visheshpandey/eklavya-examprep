// The misconception status chain: Detected -> Resolved -> Verified. Shown on the concept panel, the Reviews screen and teacher group cards.
import { h } from '../dom.js';

export const STAGES = [['detected', 'Detected'], ['resolved', 'Resolved'], ['verified', 'Verified']];

/** A three-step chain: every stage reached is ticked, and the next one still to come is highlighted (Detected ✓ → Resolved ✓ → Verified pending). */
export function chain(stage) {
  const at = Math.max(0, STAGES.findIndex(([id]) => id === stage));
  return h('ol', { class: `mc-chain stage-${stage}`, 'aria-label': `Status: ${STAGES[at][1]}` },
    STAGES.map(([id, label], i) => h('li', { class: i <= at ? 'done' : i === at + 1 ? 'current' : '', 'aria-current': i === at + 1 ? 'step' : null },
      h('span', { class: 'chain-dot', 'aria-hidden': 'true' }, i <= at ? '✓' : String(i + 1)), label)));
}

export const verifiedBadge = () => h('span', { class: 'chip chip-ok verified-badge' }, '✅ Verified fixed');

/** A one-word chip for a stage, for compact lists (teacher groups). */
export function stageChip(stage) {
  return h('span', { class: `chip stage-chip stage-chip-${stage}` }, stage === 'verified' ? '✅ Verified' : stage === 'resolved' ? '🟡 Resolved' : '🔴 Detected');
}
