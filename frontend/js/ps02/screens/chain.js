// The misconception status chain: Detected -> Resolved -> Verified. Shown on the concept panel, the Reviews screen and teacher group cards.
import { h } from '../dom.js';

export const STAGES = [['detected', 'Detected'], ['resolved', 'Resolved'], ['verified', 'Verified']];

/** A three-step chain with the current stage highlighted and earlier ones ticked. */
export function chain(stage) {
  const at = Math.max(0, STAGES.findIndex(([id]) => id === stage));
  return h('ol', { class: `mc-chain stage-${stage}`, 'aria-label': `Status: ${STAGES[at][1]}` },
    STAGES.map(([id, label], i) => h('li', { class: i < at ? 'done' : i === at ? 'current' : '', 'aria-current': i === at ? 'step' : null },
      h('span', { class: 'chain-dot', 'aria-hidden': 'true' }, i < at || (i === at && id === 'verified') ? '✓' : String(i + 1)), label)));
}

export const verifiedBadge = () => h('span', { class: 'chip chip-ok verified-badge' }, '✅ Verified fixed');

/** A one-word chip for a stage, for compact lists (teacher groups). */
export function stageChip(stage) {
  return h('span', { class: `chip stage-chip stage-chip-${stage}` }, stage === 'verified' ? '✅ Verified' : stage === 'resolved' ? '🟡 Resolved' : '🔴 Detected');
}
