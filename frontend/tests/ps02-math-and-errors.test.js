// LaTeX stripping and the 404 / error-body handling (run with: node --test).
import test from 'node:test';
import assert from 'node:assert/strict';

import { deepMath, mathText } from '../js/ps02/math-text.js';
import { errorText, maybeStudentGone } from '../js/ps02/api.js';

test('LaTeX inside $...$ becomes readable text; text outside is untouched', () => {
  assert.equal(mathText('Power is $P = 1/f$ in dioptres.'), 'Power is P = 1/f in dioptres.');
  assert.equal(mathText('$V = IR$'), 'V = IR');
  assert.equal(mathText('$I = \\frac{V}{R}$'), 'I = V/R');
  assert.equal(mathText('$\\frac{1}{R_p} = \\frac{1}{R_1} + \\frac{1}{R_2}$'), '1/Rp = 1/R₁ + 1/R₂');
  assert.equal(mathText('A $10\\,\\Omega$ resistor'), 'A 10 Ω resistor');
  assert.equal(mathText('$Q = I \\times t$'), 'Q = I × t');
  assert.equal(mathText('$H = I^{2}Rt$ and $x^2$'), 'H = I²Rt and x²');
  assert.equal(mathText('$\\frac{a+b}{c}$'), '(a+b)/c');
  assert.equal(mathText('$\\text{Power} = \\frac{V^2}{R}$'), 'Power = V²/R');
  assert.equal(mathText('between \\(m_1\\) and \\(m_2\\)'), 'between m₁ and m₂');
});

test('plain text with underscores, carets or ids is never altered', () => {
  for (const s of ['MC_UNKNOWN', 'concept_id', 'x ^ y without dollars', 'H = I²Rt', 'Cost is 5 rupees', '']) assert.equal(mathText(s), s);
  assert.equal(mathText(42), 42);
  assert.equal(mathText(null), null);
});

test('deepMath cleans every string in a response object, leaving other values alone', () => {
  const out = deepMath({ headline: '$P=1/f$', items: [{ q: 'Find $R_1$', n: 3, ok: true }], none: null });
  assert.deepEqual(out, { headline: 'P=1/f', items: [{ q: 'Find R₁', n: 3, ok: true }], none: null });
});

test('the error message is read from this app\'s {"error": ...} body, and from FastAPI\'s {"detail": ...}', () => {
  assert.equal(errorText({ error: 'Student not found', code: 'http_error' }), 'Student not found');
  assert.equal(errorText({ detail: 'Not found' }), 'Not found');
  assert.equal(errorText({ message: 'x' }), 'x');
  assert.equal(errorText({}), '');
  assert.equal(errorText(null), '');
});

test('a 404 about the student asks the app to start over; other 404s and other statuses do not', () => {
  const events = [];
  globalThis.dispatchEvent = (e) => events.push(e.type);
  globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
  assert.equal(maybeStudentGone(404, 'Student not found', '/api/practice/next?student_id=9999', null), true);
  assert.deepEqual(events, ['ps02:student-gone']);
  assert.equal(maybeStudentGone(404, 'Question expired. Please fetch the next one.', '/api/practice/answer', { student_id: 1 }), false);
  assert.equal(maybeStudentGone(404, 'Attempt not found', '/api/practice/reasoning', { student_id: 1 }), false);
  assert.equal(maybeStudentGone(404, 'Dialogue not found', '/api/dialogue/reply', { student_id: 1 }), false);
  assert.equal(maybeStudentGone(500, 'Student not found', '/api/x', null), false);
  assert.equal(maybeStudentGone(422, 'Student not found', '/api/x', null), false);
  assert.equal(events.length, 1);
});
