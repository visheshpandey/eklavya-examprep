// "Eklavya talks you out of it": a short Socratic voice chat that helps the student un-learn a misconception.
// The tutor asks guiding questions and never gives the answer; it counts as fixed only when the student explains the idea in their own words.
import { api } from '../api.js';
import { h } from '../dom.js';
import { createDictation } from '../../lib/dictation.js';
import { getLang } from '../state.js';
import { deltaList, animateBars } from './deltas.js';

const STEPS = [['holds', 'Still holds it'], ['wavering', 'Wavering'], ['resolved', 'Resolved']];
const MUTE_KEY = 'ps02.mute';
const readMute = () => { try { return localStorage.getItem(MUTE_KEY) === '1'; } catch { return false; } };
const writeMute = (v) => { try { localStorage.setItem(MUTE_KEY, v ? '1' : '0'); } catch { /* ignore */ } };

/** Speak with the browser's own text-to-speech (Hindi voice for Hinglish/Hindi, Indian English otherwise). */
function speak(text, language) {
  const synth = globalThis.speechSynthesis;
  if (!synth || !text) return;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = language === 'english' ? 'en-IN' : 'hi-IN';
  u.rate = 0.95;
  synth.speak(u);
}

/**
 * mountDialogue({ student, attempt_id, misconception, onDone, onUnavailable }) returns the element to insert.
 * onDone(result) fires once, when the dialogue is resolved, unresolved after 4 turns, or skipped.
 */
export function mountDialogue({ student, attemptId, onDone, onUnavailable }) {
  let state = null, busy = false, finished = false, usedVoice = false, muted = readMute();
  const language = () => getLang();

  const chat = h('div', { class: 'chat', role: 'log', 'aria-live': 'polite', 'aria-label': 'Conversation with Eklavya' });
  const chip = h('span', { class: 'chip chip-bad' }, 'Starting…');
  const turns = h('span', { class: 'muted small' }, '');
  const fill = h('i', { class: 'track-fill' });
  const marker = h('b', { class: 'track-marker', 'aria-hidden': 'true' });
  const stepLabels = STEPS.map(([id, label]) => h('span', { class: 'track-step', dataset: { step: id } }, label));
  const track = h('div', { class: 'track', role: 'img', 'aria-label': 'Progress: still holds it' }, h('div', { class: 'track-bar' }, fill, marker), h('div', { class: 'track-steps' }, stepLabels));
  const muteBtn = h('button', { class: 'btn btn-quiet btn-small', type: 'button', 'aria-pressed': String(muted), onClick: () => {
    muted = !muted; writeMute(muted); muteBtn.setAttribute('aria-pressed', String(muted)); muteBtn.textContent = muted ? '🔇 Voice off' : '🔊 Voice on';
    if (muted) globalThis.speechSynthesis?.cancel();
  } }, muted ? '🔇 Voice off' : '🔊 Voice on');

  const status = h('p', { class: 'muted small', role: 'status' });
  const text = h('input', { class: 'input', type: 'text', maxlength: '600', autocomplete: 'off', 'aria-label': 'Type your answer', placeholder: 'Type your answer here, or tap the mic and speak…',
    onKeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); send(); } } });
  const sendBtn = h('button', { class: 'btn btn-primary', type: 'button', onClick: () => send() }, 'Send');
  const wave = h('span', { class: 'wave', 'aria-hidden': 'true' }, Array.from({ length: 7 }, (_, i) => h('i', { style: { animationDelay: `${i * 90}ms` } })));
  const mic = h('button', { class: 'mic', type: 'button', 'aria-pressed': 'false', 'aria-label': 'Speak your answer' }, h('span', { class: 'mic-dot', 'aria-hidden': 'true' }), h('span', { class: 'mic-label' }, 'Tap and speak'), wave);
  const dictation = createDictation({
    getLanguage: language,
    onText: (value, final) => { text.value = value; usedVoice = true; if (final && value.trim()) send(); },
    onState: (s, detail) => {
      mic.setAttribute('aria-pressed', String(s === 'listening'));
      mic.querySelector('.mic-label').textContent = s === 'listening' ? 'Listening…' : 'Tap and speak';
      status.textContent = s === 'error' ? (detail === 'not-allowed' ? 'The microphone is blocked. Allow it in the address bar, or type instead.' : detail === 'no-speech' ? 'I did not hear anything. Try again, or type.' : 'Voice input stopped. You can type instead.') : '';
    },
  });
  mic.addEventListener('click', () => { globalThis.speechSynthesis?.cancel(); dictation.listening() ? dictation.stop() : dictation.start(''); });
  const controls = h('div', { class: 'dlg-controls' }, dictation.available() ? mic : h('p', { class: 'muted small' }, 'Voice input needs Chrome or Edge. Type your answer instead.'),
    h('div', { class: 'row dlg-text' }, text, sendBtn), status);
  const skip = h('button', { class: 'btn btn-quiet btn-small', type: 'button', onClick: () => finish({ skipped: true }) }, 'Skip, just show me the explanation');
  const root = h('section', { class: 'card dialogue', 'aria-label': 'Talk it through with Eklavya' },
    h('div', { class: 'dlg-head' }, h('div', null, h('p', { class: 'eyebrow' }, 'Talk it through'), chip), h('div', { class: 'dlg-tools' }, turns, muteBtn)),
    track, chat, controls, h('p', { class: 'muted small' }, 'Eklavya will not hand you the answer. Explain the idea in your own words and it counts as fixed.'), skip);

  function bubble(role, content, move) {
    const b = h('div', { class: `bubble bubble-${role}` }, role === 'tutor' && h('span', { class: 'avatar', 'aria-hidden': 'true' }, 'E'), h('p', null, content), move && role === 'tutor' && h('small', { class: 'move' }, move));
    chat.append(b); chat.scrollTop = chat.scrollHeight;
    return b;
  }
  function typing(on) {
    chat.querySelector('.typing')?.remove();
    if (on) { chat.append(h('div', { class: 'bubble bubble-tutor typing', 'aria-label': 'Eklavya is thinking' }, h('span', { class: 'avatar', 'aria-hidden': 'true' }, 'E'), h('p', null, h('i'), h('i'), h('i')))); chat.scrollTop = chat.scrollHeight; }
  }
  function paint(s) {
    state = s;
    const idx = STEPS.findIndex(([id]) => id === s.progress);
    fill.style.width = `${(idx / (STEPS.length - 1)) * 100}%`;
    marker.style.left = `${(idx / (STEPS.length - 1)) * 100}%`;
    track.setAttribute('aria-label', `Progress: ${STEPS[idx][1]}`);
    stepLabels.forEach((el, i) => el.classList.toggle('on', i <= idx));
    root.dataset.progress = s.progress;
    chip.textContent = `Working on: ${s.misconception.label}`;
    chip.className = `chip ${s.progress === 'resolved' ? 'chip-ok' : 'chip-bad'}`;
    turns.textContent = s.status === 'open' ? `Turn ${Math.min(s.turns_used + 1, s.turns_max)} of ${s.turns_max}` : '';
  }

  async function send() {
    const value = text.value.trim();
    if (!value || busy || finished) return;
    dictation.stop(); globalThis.speechSynthesis?.cancel();
    busy = true; sendBtn.disabled = true; text.value = '';
    bubble('student', value);
    typing(true);
    try {
      const r = await api('/api/dialogue/reply', { method: 'POST', body: { student_id: student.id, dialogue_id: state.dialogue_id, text: value, mode: usedVoice ? 'voice' : 'text', language: language() }, timeout: 30000 });
      typing(false);
      const last = r.transcript[r.transcript.length - 1];
      bubble('tutor', last.text, r.status === 'open' ? last.move : null);
      if (!muted) speak(last.text, language());
      paint(r);
      usedVoice = false;
      if (r.status !== 'open') finish(r);
    } catch (err) {
      typing(false);
      bubble('tutor', 'I could not reach the server just now. Try sending that again.');
    } finally { busy = false; sendBtn.disabled = false; if (!finished) text.focus(); }
  }

  function finish(result) {
    if (finished) return;
    finished = true; dictation.stop(); globalThis.speechSynthesis?.cancel();
    controls.hidden = true; skip.hidden = true;
    const outro = h('div', { class: `dlg-outro ${result.status === 'resolved' ? 'dlg-won' : ''}` });
    if (result.status === 'resolved') {
      outro.append(h('h3', null, 'You un-learned it. 🎉'), h('p', null, 'You explained it yourself, so this counts as fixed, not just a lucky click.'));
      if (result.mastery_changes) { const d = deltaList(result.mastery_changes, { title: 'Your mastery jumped' }); outro.append(d); animateBars(d, result.mastery_changes); }
    } else if (result.status === 'unresolved') {
      outro.append(h('h3', null, 'Not quite there yet, and that is okay'), h('p', null, 'We will bring this concept back for a quick review soon, so it sticks.'));
    }
    root.append(outro);
    onDone(result);
  }

  (async () => {
    try {
      const s = await api('/api/dialogue/start', { method: 'POST', body: { student_id: student.id, attempt_id: attemptId, language: language() }, timeout: 20000 });
      s.transcript.forEach((t) => bubble(t.role, t.text, t.role === 'tutor' ? t.move : null));
      paint(s);
      if (!muted) speak(s.transcript[0].text, language());
      text.focus({ preventScroll: true });
    } catch (err) { root.remove(); onUnavailable?.(err); }
  })();

  return root;
}
