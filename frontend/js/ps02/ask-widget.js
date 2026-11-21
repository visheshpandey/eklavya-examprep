// "Ask a doubt": a floating button on every screen. Voice or text, Hindi / English / Hinglish. Answers from the student's notes when
// they cover it (with a "from your notes" citation), from general knowledge when they don't. Each doubt is tagged to a concept; if it
// reveals a misconception it is logged and mastery is nudged.
import { api } from './api.js';
import { h } from './dom.js';
import { createDictation } from '../lib/dictation.js';
import { getLang, getStudent, setLang } from './state.js';
import { isMuted, setMuted, speak, stop as stopSpeech } from './tts.js';
import { pct } from './ui.js';
import { compressPhoto, notebookView, postNotebook, snapControls } from './notebook.js';

const LANGS = [['hinglish', 'Hinglish'], ['english', 'English'], ['hindi', 'हिन्दी']];
const EXAMPLES = ['Current kya hota hai, aur bulb mein kam kyun nahi hota?', 'Why does a concave lens spread light?', 'Parallel mein total resistance kam kyun hota hai?'];

export function mountAskWidget() {
  let open = false, busy = false, hint = null, notesInfo = null, usedVoice = false;

  const fab = h('button', { class: 'ask-fab', type: 'button', 'aria-haspopup': 'dialog', 'aria-expanded': 'false', onClick: () => toggle(true) },
    h('span', { 'aria-hidden': 'true', class: 'ask-fab-icon' }, '?'), h('span', { class: 'ask-fab-label' }, 'Ask a doubt'));
  const chat = h('div', { class: 'chat ask-chat', role: 'log', 'aria-live': 'polite', 'aria-label': 'Your questions and Eklavya’s answers' });
  const status = h('p', { class: 'muted small', role: 'status' });
  const notesLine = h('p', { class: 'muted small' });
  const text = h('input', { class: 'input', type: 'text', maxlength: '500', autocomplete: 'off', 'aria-label': 'Type your doubt', placeholder: 'Type your doubt, or tap the mic…',
    onKeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); send(); } } });
  const sendBtn = h('button', { class: 'btn btn-primary', type: 'button', onClick: () => send() }, 'Ask');
  const wave = h('span', { class: 'wave', 'aria-hidden': 'true' }, Array.from({ length: 7 }, (_, i) => h('i', { style: { animationDelay: `${i * 90}ms` } })));
  const mic = h('button', { class: 'mic mic-small', type: 'button', 'aria-pressed': 'false', 'aria-label': 'Speak your doubt' }, h('span', { class: 'mic-dot', 'aria-hidden': 'true' }), h('span', { class: 'mic-label' }, 'Speak'), wave);
  const dictation = createDictation({
    getLanguage: getLang,
    onText: (value, final) => { text.value = value; usedVoice = true; if (final && value.trim()) send(); },
    onState: (s, detail) => {
      mic.setAttribute('aria-pressed', String(s === 'listening'));
      mic.querySelector('.mic-label').textContent = s === 'listening' ? 'Listening…' : 'Speak';
      status.textContent = s === 'error' ? (detail === 'not-allowed' ? 'The microphone is blocked. Allow it in the address bar, or type.' : detail === 'no-speech' ? 'I did not hear anything. Try again, or type.' : 'Voice input stopped. You can type instead.') : '';
    },
  });
  mic.addEventListener('click', () => { stopSpeech(); dictation.listening() ? dictation.stop() : dictation.start(''); });
  const langBar = h('div', { class: 'seg', role: 'group', 'aria-label': 'Language' }, LANGS.map(([id, label]) =>
    h('button', { type: 'button', class: 'seg-btn', 'aria-pressed': String(getLang() === id), onClick: (e) => { setLang(id); langBar.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b === e.currentTarget))); } }, label)));
  const muteBtn = h('button', { class: 'btn btn-quiet btn-small', type: 'button', 'aria-pressed': String(isMuted()), onClick: () => { setMuted(!isMuted()); muteBtn.setAttribute('aria-pressed', String(isMuted())); muteBtn.textContent = isMuted() ? '🔇 Voice off' : '🔊 Voice on'; } }, isMuted() ? '🔇 Voice off' : '🔊 Voice on');
  const examples = h('div', { class: 'chips' }, EXAMPLES.map((q) => h('button', { class: 'chip', type: 'button', onClick: () => { text.value = q; send(); } }, q)));
  const snap = snapControls({ onPhoto: (file) => readNotebook({ file }), onSample: (sample) => readNotebook({ sample }) });
  const panel = h('section', { class: 'ask-panel', role: 'dialog', 'aria-label': 'Ask a doubt', hidden: true },
    h('div', { class: 'ask-head' }, h('div', null, h('p', { class: 'eyebrow' }, 'Ask Eklavya'), h('h2', null, 'Any doubt, any language')),
      h('div', { class: 'dlg-tools' }, muteBtn, h('button', { class: 'btn btn-quiet btn-small', type: 'button', 'aria-label': 'Close', onClick: () => toggle(false) }, '✕'))),
    langBar, notesLine, chat, examples, h('div', { class: 'row tight' }, dictation.available() ? mic : h('p', { class: 'muted small' }, 'Voice input needs Chrome or Edge. You can type.')), snap.el,
    h('div', { class: 'row dlg-text' }, text, sendBtn), status);
  document.body.append(fab, panel);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && open) toggle(false); });
  globalThis.addEventListener('ps02:context', (e) => { hint = e.detail?.concept_id || null; });
  globalThis.addEventListener('ps02:ask', (e) => { if (e.detail?.concept_id) hint = e.detail.concept_id; toggle(true); });   // "Ask a doubt about this" buttons

  function bubble(role, ...content) {
    const b = h('div', { class: `bubble bubble-${role}` }, role === 'tutor' && h('span', { class: 'avatar', 'aria-hidden': 'true' }, 'E'), h('div', { class: 'bubble-body' }, ...content));
    chat.append(b); chat.scrollTop = chat.scrollHeight;
    return b;
  }

  async function refreshNotes() {
    const s = getStudent();
    if (!s) { notesLine.textContent = 'Pick a student first so Eklavya can remember your doubts.'; return; }
    try {
      notesInfo = await api(`/api/ps02/notes?student_id=${s.id}`, { timeout: 15000 });
      notesLine.replaceChildren(notesInfo.notes.length
        ? `Using your notes (${notesInfo.notes.length}). If they do not cover a doubt, Eklavya answers from general knowledge and says so. `
        : 'No notes uploaded yet, so answers come from general knowledge. ', h('a', { class: 'link', href: '#/notes', onClick: () => toggle(false) }, notesInfo.notes.length ? 'Manage notes' : 'Upload notes'));
    } catch { notesLine.textContent = ''; }
  }

  function toggle(next) {
    open = next; panel.hidden = !next; fab.setAttribute('aria-expanded', String(next)); fab.classList.toggle('ask-fab-hidden', next);
    if (next) {
      refreshNotes();
      if (!chat.children.length) bubble('tutor', h('p', null, getStudent() ? 'Ask me anything about Class 10 Physics, in Hindi, English or Hinglish. Even if it is not in your notes, I will still answer.' : 'Choose a student first (Start as student, or Try demo student), then ask me anything.'));
      setTimeout(() => text.focus(), 50);
    } else { dictation.stop(); stopSpeech(); fab.focus(); }
  }

  async function send() {
    const question = text.value.trim();
    const student = getStudent();
    if (!question || busy) return;
    if (!student) { bubble('tutor', h('p', null, 'Please pick a student first.'), h('a', { class: 'btn btn-small', href: '#/', onClick: () => toggle(false) }, 'Go to start')); return; }
    dictation.stop(); stopSpeech(); examples.hidden = true;
    busy = true; sendBtn.disabled = true; text.value = '';
    bubble('student', h('p', null, question));
    const typing = bubble('tutor', h('p', { class: 'typing-dots', 'aria-label': 'Eklavya is thinking' }, h('i'), h('i'), h('i')));
    try {
      const r = await api('/api/ps02/doubt', { method: 'POST', timeout: 40000, body: { student_id: student.id, question, language: getLang(), concept_id: hint, mode: usedVoice ? 'voice' : 'text' } });
      typing.remove();
      renderAnswer(r);
      speak(r.answer, getLang());
    } catch (err) {
      typing.remove();
      bubble('tutor', h('p', null, err.message || 'Something went wrong. Please try again.'));
    } finally { busy = false; sendBtn.disabled = false; usedVoice = false; text.focus(); }
  }

  // 📸 a photo of your working: read it, find the first wrong line, log the misconception, offer to talk it through
  async function readNotebook({ file = null, sample = null }) {
    const student = getStudent();
    if (!student) { bubble('tutor', h('p', null, 'Please pick a student first.')); return; }
    if (busy) return;
    busy = true; snap.setBusy(true); stopSpeech();
    const photoUrl = file ? URL.createObjectURL(file) : sample ? sample.image : null;
    bubble('student', h('p', null, sample ? `📸 Sample: ${sample.title}` : '📸 My working'), photoUrl && h('img', { src: photoUrl, alt: 'Your notebook page', class: 'nb-thumb' }));
    const typing = bubble('tutor', h('p', { class: 'typing-dots', 'aria-label': 'Reading your handwriting' }, h('i'), h('i'), h('i')));
    try {
      const blob = file ? await compressPhoto(file) : sample ? await (await fetch(sample.image)).blob() : null;
      const res = await postNotebook({ studentId: student.id, sampleId: sample ? sample.id : null, conceptId: hint, blob });
      typing.remove();
      if (!res.readable) { bubble('tutor', h('p', null, res.message || 'Couldn’t read that clearly. Try again, or type it.')); return; }
      const extra = [];
      if (res.concept) extra.push(h('p', { class: 'small' }, 'Tagged to ', h('b', null, res.concept.name), '.'));
      if (res.misconception) extra.push(h('div', { class: 'ask-mc' }, h('b', null, `Misconception: ${res.misconception.label}`), h('p', { class: 'small' }, res.misconception.correction),
        (res.mastery_changes || []).map((m) => h('p', { class: 'small' }, `${m.name}: ${pct(m.before)} → ${pct(m.after)}`)),
        h('a', { class: 'btn btn-small btn-primary', href: `#/practice?concept=${res.concept?.id || res.sample?.concept_id || 'C1'}&talk=${res.misconception.id}`, onClick: () => toggle(false) }, 'Talk it through')));
      bubble('tutor', notebookView(res, photoUrl), ...extra);
    } catch (err) { typing.remove(); bubble('tutor', h('p', null, err.message || 'Something went wrong. Please try again.')); }
    finally { busy = false; snap.setBusy(false); }
  }

  function renderAnswer(r) {
    const meta = [];
    meta.push(r.grounded && r.sources?.length
      ? h('p', { class: 'cite cite-notes' }, '📄 From your notes: ', h('b', null, [r.source_document_name, r.source_topic].filter(Boolean).join(' · ') || 'your uploaded notes'))
      : h('p', { class: 'cite' }, r.notes_available ? 'Not in your notes, so this is from general knowledge.' : 'General knowledge (you have not uploaded notes yet).'));
    if (r.concept) meta.push(h('p', { class: 'small' }, 'Tagged to ', h('a', { class: 'link', href: `#/practice?concept=${r.concept.id}`, onClick: () => toggle(false) }, r.concept.name), '.'));
    if (r.misconception) {
      meta.push(h('div', { class: 'ask-mc' }, h('b', null, `Possible misconception: ${r.misconception.label}`), h('p', { class: 'small' }, r.misconception.correction),
        (r.mastery_changes || []).map((m) => h('p', { class: 'small' }, `${m.name}: ${pct(m.before)} → ${pct(m.after)}`)),
        h('a', { class: 'btn btn-small', href: `#/practice?concept=${r.concept?.id || ''}`, onClick: () => toggle(false) }, 'Practise this')));
    }
    if (r.follow_up_question) meta.push(h('p', { class: 'small muted' }, 'Check yourself: ', r.follow_up_question));
    bubble('tutor', h('p', null, r.answer), ...meta);
  }

  // the Practice and Map screens tell us which concept is on screen, so a doubt asked there is tagged to it
  globalThis.addEventListener('hashchange', () => { hint = null; if (open) toggle(false); });   // navigating closes the panel
  return { open: () => toggle(true) };
}
