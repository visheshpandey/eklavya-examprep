// Turn what a student SAYS into an answer option: "B", "option c", "dusra wala", "2", or part of the option's own text.
const ORDINALS = [
  ['a', 'ay', 'ae', 'option a', 'pehla', 'pehle', 'first', 'one', 'ek', '1'],
  ['b', 'bee', 'be', 'option b', 'dusra', 'doosra', 'dusre', 'second', 'two', 'do', '2'],
  ['c', 'see', 'sea', 'ce', 'option c', 'teesra', 'tisra', 'third', 'three', 'teen', '3'],
  ['d', 'dee', 'de', 'option d', 'chautha', 'chauthe', 'fourth', 'four', 'char', 'chaar', '4'],
];
const tokens = (text) => String(text).toLowerCase().replace(/[^\p{L}\p{N}\s.]/gu, ' ').split(/\s+/).filter(Boolean);

/** Returns the option index 0..3, or null when it is not clear. */
export function matchSpokenOption(transcript, options) {
  const said = tokens(transcript).filter((w) => !['option', 'answer', 'is', 'the', 'wala', 'hai', 'ka', 'ki', 'jawab', 'i', 'choose', 'pick', 'select'].includes(w));
  if (!said.length) return null;
  // 1) the option's own words win: "0.6 A" is the 0.6 ampere option, not option A (the unit "A" is also a spoken letter)
  const scores = options.map((opt) => {
    const ow = new Set(tokens(opt));
    if (!ow.size) return 0;
    return said.filter((w) => ow.has(w)).length / Math.max(ow.size, said.length);
  });
  const best = Math.max(...scores);
  const winners = scores.map((s, i) => (s === best ? i : -1)).filter((i) => i >= 0);
  if (best >= 0.5 && winners.length === 1) return winners[0];
  // 2) otherwise a spoken letter, ordinal or number, but only in a short utterance and only when exactly one is named
  if (said.length <= 3) {
    const hits = ORDINALS.map((names, i) => (said.some((w) => names.includes(w)) ? i : -1)).filter((i) => i >= 0);
    if (hits.length === 1) return hits[0];
  }
  return null;
}

/** What to read aloud for a question: the stem, then "A: ..., B: ...". */
export function questionToSpeech(q) {
  return `${q.stem} ${q.options.map((o, i) => `Option ${'ABCD'[i]}: ${o}.`).join(' ')}`;
}
