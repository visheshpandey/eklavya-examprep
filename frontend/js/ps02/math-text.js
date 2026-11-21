// The AI sometimes writes maths as LaTeX ("$P = \frac{1}{f}$"). The UI shows plain text, so convert what is inside $...$ (or \( \) / \[ \])
// to readable Unicode: P = 1/f, R₁, x², 10 Ω, ×. Text outside the maths delimiters is never touched.
const SUP = { 0: '⁰', 1: '¹', 2: '²', 3: '³', 4: '⁴', 5: '⁵', 6: '⁶', 7: '⁷', 8: '⁸', 9: '⁹', '+': '⁺', '-': '⁻', '−': '⁻' };
const SUB = { 0: '₀', 1: '₁', 2: '₂', 3: '₃', 4: '₄', 5: '₅', 6: '₆', 7: '₇', 8: '₈', 9: '₉' };
const SYMBOLS = {
  times: '×', cdot: '·', div: '÷', pm: '±', approx: '≈', neq: '≠', ne: '≠', leq: '≤', le: '≤', geq: '≥', ge: '≥', rightarrow: '→', to: '→', leftarrow: '←', propto: '∝',
  infty: '∞', degree: '°', circ: '°', Omega: 'Ω', omega: 'ω', Delta: 'Δ', delta: 'δ', theta: 'θ', mu: 'μ', lambda: 'λ', pi: 'π', rho: 'ρ', alpha: 'α', beta: 'β',
  sigma: 'σ', phi: 'φ', epsilon: 'ε', varepsilon: 'ε', gamma: 'γ', eta: 'η', tau: 'τ', nu: 'ν',
};
const mapAll = (text, table) => ([...text].every((c) => table[c] !== undefined) ? [...text].map((c) => table[c]).join('') : null);
const SIMPLE = /^[\w.₀-₉⁰-⁹²³¹]+$/;

function convert(math) {
  let t = String(math);
  // 1) unwrap \text{..} and \sqrt{..}; 2) super/subscripts (so a fraction's parts are already plain); 3) fractions; 4) leftover commands, symbols, braces
  for (let i = 0; i < 3; i++) {
    t = t.replace(/\\(?:text|mathrm|mathbf|textbf|mathit|operatorname)\s*\{([^{}]*)\}/g, '$1').replace(/\\sqrt\s*\{([^{}]*)\}/g, '√($1)');
  }
  t = t.replace(/\^\s*\{([^{}]*)\}/g, (_, x) => mapAll(x, SUP) ?? `^(${x})`)
    .replace(/\^\s*([0-9+\-−])/g, (_, x) => SUP[x])
    .replace(/_\s*\{([^{}]*)\}/g, (_, x) => mapAll(x, SUB) ?? x)
    .replace(/_\s*([0-9])/g, (_, x) => SUB[x])
    .replace(/_\s*([A-Za-z])/g, '$1');
  for (let i = 0; i < 3; i++) {
    t = t.replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, (_, a, b) => `${SIMPLE.test(a) ? a : `(${a})`}/${SIMPLE.test(b) ? b : `(${b})`}`);
  }
  return t.replace(/\\left|\\right/g, '').replace(/\\[,;:! ]/g, ' ').replace(/\\%/g, '%').replace(/\\\\/g, ' ')
    .replace(/\\([A-Za-z]+)/g, (_, name) => SYMBOLS[name] ?? name)
    .replace(/[{}]/g, '').replace(/[ \t]{2,}/g, ' ').trim();
}

const MATH_REGION = /\$\$([^$]+)\$\$|\$([^$\n]+)\$|\\\(([\s\S]*?)\\\)|\\\[([\s\S]*?)\\\]/g;

export function mathText(input) {
  if (typeof input !== 'string' || !/[$\\]/.test(input)) return input;
  return input.replace(MATH_REGION, (_, a, b, c, d) => convert(a ?? b ?? c ?? d));
}

/** Apply mathText to every string inside an object / array (API responses). */
export function deepMath(value) {
  if (typeof value === 'string') return mathText(value);
  if (Array.isArray(value)) return value.map(deepMath);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, deepMath(v)]));
  return value;
}
