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
  if (said.length <= 3) {
    const hits = ORDINALS.map((names, i) => (said.some((w) => names.includes(w)) ? i : -1)).filter((i) => i >= 0);
    if (hits.length === 1) return hits[0];
  }
  // otherwise: best overlap with the option's own words (e.g. "twenty ohm" / "4 ohm")
  const scores = options.map((opt) => {
    const ow = new Set(tokens(opt));
    if (!ow.size) return 0;
    return said.filter((w) => ow.has(w)).length / Math.max(ow.size, said.length);
  });
  const best = Math.max(...scores);
  if (best < 0.5) return null;
  const winners = scores.map((s, i) => (s === best ? i : -1)).filter((i) => i >= 0);
  return winners.length === 1 ? winners[0] : null;
}

/** What to read aloud for a question: the stem, then "A: ..., B: ...". */
export function questionToSpeech(q) {
  return `${q.stem} ${q.options.map((o, i) => `Option ${'ABCD'[i]}: ${o}.`).join(' ')}`;
}
