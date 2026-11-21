// Unit tests for the pure PS02 frontend helpers (run with: node --test).
import test from 'node:test';
import assert from 'node:assert/strict';

import { diffSnap } from '../js/ps02/snapshot.js';
import { matchSpokenOption, questionToSpeech } from '../js/ps02/spoken-answer.js';

const OPTIONS = ['0.2 A', '0.4 A', '0.6 A', '0.8 A'];

test('spoken letters, ordinals and Hindi numbers pick the right option', () => {
  assert.equal(matchSpokenOption('B', OPTIONS), 1);
  assert.equal(matchSpokenOption('option c', OPTIONS), 2);
  assert.equal(matchSpokenOption('the answer is D', OPTIONS), 3);
  assert.equal(matchSpokenOption('pehla wala', OPTIONS), 0);
  assert.equal(matchSpokenOption('dusra', OPTIONS), 1);
  assert.equal(matchSpokenOption('teen', OPTIONS), 2);
  assert.equal(matchSpokenOption('chautha', OPTIONS), 3);
});

test('speaking the option text itself works, and ambiguity or noise returns null', () => {
  assert.equal(matchSpokenOption('0.6 A', OPTIONS), 2);
  assert.equal(matchSpokenOption('', OPTIONS), null);
  assert.equal(matchSpokenOption('hmm let me think about it for a while', OPTIONS), null);
  assert.equal(matchSpokenOption('a b', OPTIONS), null);                 // two letters: not clear
  assert.equal(matchSpokenOption('ampere', ['ampere', 'ampere ohm', 'volt', 'watt']), 0);        // an exact option beats a partial one
  assert.equal(matchSpokenOption('ampere', ['ampere hour', 'ampere second', 'volt', 'watt']), null);   // a genuine tie is not guessed
});

test('a question is read aloud with its options', () => {
  const text = questionToSpeech({ stem: 'What is I?', options: ['a', 'b', 'c', 'd'] });
  assert.match(text, /What is I\?/);
  assert.match(text, /Option A: a\./);
  assert.match(text, /Option D: d\./);
});

test('snapshot diff reports only concepts that moved by 2 points or more, and nothing on a first visit', () => {
  const nodes = [{ id: 'C1', p_known: 0.55 }, { id: 'C2', p_known: 0.30 }, { id: 'C3', p_known: 0.205 }, { id: 'NEW', p_known: 0.5 }];
  assert.deepEqual(diffSnap(null, nodes), []);
  const changes = diffSnap({ C1: 0.30, C2: 0.31, C3: 0.20 }, nodes);
  assert.deepEqual(changes.map((c) => c.id), ['C1']);
  assert.deepEqual(changes[0], { id: 'C1', before: 0.30, after: 0.55 });
  const down = diffSnap({ C2: 0.5 }, nodes);
  assert.equal(down[0].id, 'C2');
  assert.ok(down[0].after < down[0].before);
});
