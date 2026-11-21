// Remembers the mastery the student last SAW on the map, so the next visit can animate what changed since then.
const key = (studentId) => `ps02.snap.${studentId}`;

export function readSnap(studentId) {
  try { return JSON.parse(localStorage.getItem(key(studentId)) || 'null'); } catch { return null; }
}

export function writeSnap(studentId, nodes) {
  try { localStorage.setItem(key(studentId), JSON.stringify(Object.fromEntries(nodes.map((n) => [n.id, Math.round(n.p_known * 1000) / 1000])))); } catch { /* private window: no animation, no harm */ }
}

/** Pure: the concepts whose mastery moved by at least `threshold` since `prev` -> [{id, before, after}]. No previous snapshot means no changes (first visit). */
export function diffSnap(prev, nodes, threshold = 0.02) {
  if (!prev) return [];
  return nodes.filter((n) => prev[n.id] !== undefined && Math.abs(prev[n.id] - n.p_known) >= threshold)
    .map((n) => ({ id: n.id, before: prev[n.id], after: n.p_known }));
}
