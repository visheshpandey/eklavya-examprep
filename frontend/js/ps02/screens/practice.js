// Practice loop: targeted question -> answer -> (explain your thinking, by voice or text) -> misconception card + live mastery changes.
import { api, apiStream, qs } from '../api.js';
import { h } from '../dom.js';
import { createDictation } from '../../lib/dictation.js';
import { getLang, getStudent, setLang } from '../state.js';
import { errorCard, loading, skeleton } from '../ui.js';
import { deltaList } from './deltas.js';
import { thinkingPanel } from '../thinking-panel.js';
import { compressPhoto, notebookView, postNotebook, snapControls } from '../notebook.js';
import { assignmentBanner } from './assignment-banner.js';
import { mountDialogue } from './dialogue.js';
import { fixList, loadBoard } from './marks.js';
import { speak, stop as stopSpeech } from '../tts.js';
import { matchSpokenOption, questionToSpeech } from '../spoken-answer.js';
import { listenOnce, readVoiceMode, voiceSupported, writeVoiceMode } from '../voice-io.js';

const LANGS = [['hinglish', 'Hinglish'], ['english', 'English'], ['hindi', 'हिन्दी']];
const DIFF = { 1: 'Easier', 2: 'Medium', 3: 'Harder' };

export async function practice(root, ctx) {
  const student = getStudent();
  const review = ctx.query.review === '1';
  let firstConcept = ctx.query.concept || null;
  let done = 0, total = null;
  let tourKind = ctx.query.tour || null;   // the Judge tour asks for a fixed, prepared question
  const targetMc = ctx.query.talk || null, rootConcept = ctx.query.talk ? ctx.query.concept || null : null;   // after "Fix the root first"
  let targetLeft = 0;   // the next 3 questions are aimed at that misconception
  const stage = h('div', { class: 'stage' });
  const counter = h('p', { class: 'muted small' });

  if (review) {
    const due = await api(`/api/reviews/due?${qs({ student_id: student.id })}`);
    if (!ctx.live()) return;
    total = Math.min(5, due.due.length);
    if (total === 0) {
      root.replaceChildren(h('section', { class: 'narrow card center' }, h('h1', { class: 'page-title' }, 'Nothing due right now'),
        h('p', null, 'Nice, every concept is fresh. Check back later, or practise something new.'), h('a', { class: 'btn btn-primary', href: '#/practice' }, 'Practise new questions')));
      return;
    }
  }

  const langBar = h('div', { class: 'seg', role: 'group', 'aria-label': 'Language for the microphone and explanations' },
    LANGS.map(([id, label]) => h('button', { type: 'button', class: 'seg-btn', 'aria-pressed': String(getLang() === id), onClick: (e) => {
      setLang(id); langBar.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b === e.currentTarget)));
      stage.querySelector('.mc-card')?.dispatchEvent(new CustomEvent('lang'));
    } }, label)));

  let voice = readVoiceMode();   // voice mode: questions read aloud, answer and reasoning by voice
  const voiceBtn = h('button', { class: 'seg-btn toggle voice-toggle', type: 'button', 'aria-pressed': String(voice), disabled: !voiceSupported(),
    title: voiceSupported() ? 'Hear each question, answer by voice, explain by voice' : 'Voice mode needs Chrome or Edge', onClick: () => {
      voice = !voice; writeVoiceMode(voice); voiceBtn.setAttribute('aria-pressed', String(voice)); voiceBtn.textContent = voice ? '🎙 Voice mode: on' : '🎙 Voice mode: off';
      if (!voice) stopSpeech();
    } }, voice ? '🎙 Voice mode: on' : '🎙 Voice mode: off');
  globalThis.addEventListener('hashchange', stopSpeech, { once: true });   // leaving the screen silences it

  const assignSlot = h('div');
  root.replaceChildren(h('section', { class: 'narrow' },
    h('div', { class: 'row between wrap' }, h('div', null, h('p', { class: 'eyebrow' }, review ? 'Spaced-repetition review' : 'Adaptive practice'), counter), h('div', { class: 'row tight' }, voiceBtn, langBar)), assignSlot, stage));
  const fixSlot = h('div');
  assignSlot.after(fixSlot);
  if (!ctx.query.talk && !review) loadBoard(student.id).then((b) => { if (ctx.live() && b.fixes.length) fixSlot.replaceChildren(h('section', { class: 'card fix-strip' }, h('h3', null, '🎯 Highest-marks fix first'), fixList(b, { max: 3 }))); }).catch(() => {});
  if (!ctx.query.talk) assignmentBanner(student, { compact: true }).then((b) => { if (b && ctx.live()) assignSlot.replaceChildren(b); });

  async function nextQuestion() {
    if (review && done >= total) return summary();
    counter.textContent = review ? `Review ${done + 1} of ${total}` : '';
    stage.replaceChildren(loading('Choosing the best next question for you…', 4));
    try {
      const params = { student_id: student.id, ...(review ? { review: 1 } : {}) };
      let aimed = 0;
      if (targetLeft > 0 && rootConcept) { params.concept_id = rootConcept; params.target_mc = targetMc; aimed = 4 - targetLeft; targetLeft -= 1; }
      else if (firstConcept) params.concept_id = firstConcept;
      if (tourKind) { params.tour = tourKind; tourKind = null; }
      const q = await api(`/api/practice/next?${qs(params)}`);
      if (q.tour_wrong_index !== undefined) stage.dataset.tourWrong = String(q.tour_wrong_index);
      q.aimed = aimed;
      firstConcept = null;
      if (ctx.live()) showQuestion(q);
    } catch (err) { if (ctx.live()) stage.replaceChildren(errorCard(err.message, nextQuestion)); }
  }

  function summary() {
    counter.textContent = '';
    stage.replaceChildren(h('div', { class: 'card center' }, h('h1', { class: 'page-title' }, 'Review complete'),
      h('p', null, `You worked through ${total} due concept${total > 1 ? 's' : ''}. They are rescheduled based on how you did.`),
      h('div', { class: 'row center' }, h('a', { class: 'btn btn-primary', href: '#/map' }, 'See my map'), h('a', { class: 'btn', href: '#/reviews' }, 'Back to reviews'))));
    ctx.refreshDue();
  }

  function showQuestion(q) {
    const started = Date.now();
    let chosen = null;
    const submit = h('button', { class: 'btn btn-primary', type: 'button', disabled: true, onClick: () => send() }, 'Check answer');
    const options = q.options.map((text, i) => h('button', { class: 'opt', type: 'button', role: 'radio', 'aria-checked': 'false', onClick: () => pick(i) },
      h('span', { class: 'opt-key', 'aria-hidden': 'true' }, 'ABCD'[i]), h('span', null, text)));
    function pick(i) {
      if (stage.dataset.locked === q.question_id) return;
      chosen = i; submit.disabled = false;
      options.forEach((o, k) => o.setAttribute('aria-checked', String(k === i)));
    }
    const onKey = (e) => {
      if (!ctx.live()) return document.removeEventListener('keydown', onKey);
      if (e.target.closest?.('textarea,input')) return;
      const k = { '1': 0, '2': 1, '3': 2, '4': 3, a: 0, b: 1, c: 2, d: 3 }[e.key.toLowerCase()];
      if (k !== undefined) pick(k);
    };
    document.addEventListener('keydown', onKey);
    const feedback = h('div', { class: 'feedback' });
    const thinking = thinkingPanel(q.trace || []);
    const rc = q.root_cause;
    const voiceStatus = h('p', { class: 'muted small', role: 'status' });
    stage.dataset.locked = '';
    stage.replaceChildren(h('div', { class: 'card question' },
      h('div', { class: 'q-meta' },
        h('span', { class: `pill diff-${q.difficulty}` }, `${DIFF[q.difficulty]} · level ${q.difficulty}`), h('span', { class: 'chip' }, `${q.chapter} · ${q.concept_name}`),
        q.source !== 'ai' && h('span', { class: 'chip', title: 'The AI was slow, so a prepared question was used' }, 'prepared question')),
      h('p', { class: 'why' }, h('b', null, 'Why this question? '), q.why),
      rc && h('p', { class: `root-chip ${rc.applied ? 'root-applied' : ''}` }, rc.applied ? '🎯 Root first: ' : '💡 Heads up: ',
        rc.applied ? `${rc.name} is what is holding things back (${rc.misconception?.label || 'weak basics'}), so we start there.` : `if this keeps going wrong, the root cause may be in ${rc.name}${rc.misconception ? ` (${rc.misconception.label})` : ''}. `,
        !rc.applied && h('a', { class: 'link', href: `#/practice?concept=${rc.concept_id}${rc.misconception ? `&talk=${rc.misconception.id}` : ''}` }, 'Fix the root first')),
      q.target && q.aimed > 0 && h('p', { class: 'root-chip root-applied' }, `🎯 Aimed at “${q.target.label}” · question ${q.aimed} of 3`),
      q.note && h('p', { class: 'cite cite-notes' }, '📄 From your notes: ', h('b', null, [q.note.file_name, q.note.heading || q.note.topic].filter(Boolean).join(' · '))),
      h('h2', { class: 'stem' }, q.stem), h('div', { class: 'options', role: 'radiogroup', 'aria-label': 'Answer options' }, options),
      h('div', { class: 'row' }, submit, h('button', { class: 'btn btn-quiet btn-small', type: 'button', onClick: () => speak(questionToSpeech(q), getLang(), { force: true }) }, '🔊 Read aloud')), voiceStatus),
      thinking.el, feedback);
    options[0].focus({ preventScroll: true });
    window.dispatchEvent(new CustomEvent('ps02:context', { detail: { concept_id: q.concept_id } }));
    if (voice) voiceAnswer();

    // voice mode: read the question, listen for "A / B / option c / dusra / the option's own words", pick it and check it
    async function voiceAnswer() {
      await speak(questionToSpeech(q), getLang(), { force: true });
      for (let tries = 0; tries < 2 && voice && ctx.live() && stage.dataset.locked !== q.question_id; tries++) {
        voiceStatus.textContent = '🎙 Listening: say A, B, C or D…';
        const said = await listenOnce({ language: getLang(), onInterim: (t) => { voiceStatus.textContent = `🎙 Heard: “${t}”`; } });
        if (!ctx.live() || stage.dataset.locked === q.question_id) return;
        const idx = matchSpokenOption(said, q.options);
        if (idx !== null) { pick(idx); voiceStatus.textContent = `Option ${'ABCD'[idx]} selected.`; await speak(`Option ${'ABCD'[idx]}. Checking.`, getLang(), { force: true }); send(); return; }
        voiceStatus.textContent = said ? `I heard “${said}” but could not match it to an option.` : 'I did not hear anything.';
        await speak(said ? 'I did not catch that. Please say A, B, C or D.' : 'I did not hear you. Please say A, B, C or D.', getLang(), { force: true });
      }
      if (ctx.live() && stage.dataset.locked !== q.question_id) voiceStatus.textContent = 'Tap an option, or press Read aloud and say A, B, C or D.';
    }

    async function send() {
      stage.dataset.locked = q.question_id; submit.disabled = true; submit.textContent = 'Checking…';
      options.forEach((o) => { o.disabled = true; });
      document.removeEventListener('keydown', onKey);
      try {
        const a = await api('/api/practice/answer', { method: 'POST', body: { student_id: student.id, question_id: q.question_id, chosen_index: chosen, elapsed_seconds: (Date.now() - started) / 1000 } });
        if (!ctx.live()) return;
        options.forEach((o, k) => {
          const right = k === a.correct_index, wrong = k === chosen && !a.correct;
          o.classList.toggle('opt-correct', right); o.classList.toggle('opt-wrong', wrong);
          if (right || wrong) o.querySelector('.opt-key').textContent = right ? '✓' : '✗';
        });
        submit.remove();
        const deltas = deltaList(a.mastery_changes, { title: a.correct ? 'Your mastery' : 'Your mastery (we’ll refine this after your explanation)' });
        feedback.replaceChildren(
          h('div', { class: `result ${a.correct ? 'result-ok' : 'result-bad'}`, role: 'status' }, h('b', null, a.correct ? 'Correct!' : 'Not quite.'), ' ', a.explanation,
            q.note && h('p', { class: 'cite cite-notes' }, '📄 From your notes: ', h('b', null, [q.note.file_name, q.note.heading || q.note.topic].filter(Boolean).join(' · ')))),
          deltas);
        thinking.add(a.trace);
        const spoke = voice ? speak(`${a.correct ? 'Correct.' : 'Not quite.'} ${a.explanation}`, getLang(), { force: true }) : Promise.resolve();
        if (a.needs_reasoning) reasoning(a, feedback, spoke, thinking); else finishRow(feedback, spoke);
      } catch (err) {
        submit.disabled = false; submit.textContent = 'Check answer'; options.forEach((o) => { o.disabled = false; }); stage.dataset.locked = '';
        feedback.replaceChildren(errorCard(err.message.includes('expired') ? 'That question expired. Let’s get a new one.' : err.message, nextQuestion));
      }
    }
  }

  function finishRow(box, spoke = Promise.resolve()) {
    const next = h('button', { class: 'btn btn-primary', type: 'button', onClick: () => { stopSpeech(); done += review ? 1 : 0; nextQuestion(); } }, review && done + 1 >= total ? 'Finish review' : 'Next question');
    box.append(h('div', { class: 'row' }, next, h('a', { class: 'btn btn-quiet', href: '#/map' }, 'See my map')));
    next.focus({ preventScroll: false });
    if (voice) {   // voice mode: "say next" moves on
      (async () => {
        await spoke; if (!ctx.live()) return;
        await speak('Say next for the next question.', getLang(), { force: true });
        const said = (await listenOnce({ language: getLang(), timeoutMs: 8000 })).toLowerCase();
        if (ctx.live() && /\b(next|agla|agli|aage|continue|haan|yes|ok|okay)\b/.test(said)) next.click();
      })();
    }
  }

  function reasoning(a, box, spoke = Promise.resolve(), thinking = null) {
    const check = a.reasoning_kind === 'check';
    let usedVoice = false;
    const status = h('p', { class: 'muted small', role: 'status' });
    const text = h('textarea', { class: 'input', rows: '3', maxlength: '1500', 'aria-label': 'Your explanation', placeholder: 'e.g. “bulb mein current kha jaata hai, isliye…”', onInput: () => { sendBtn.disabled = !text.value.trim(); } });
    const sendBtn = h('button', { class: 'btn btn-primary', type: 'button', disabled: true, onClick: sendReasoning }, 'Send my explanation');
    const mic = h('button', { class: 'mic', type: 'button', 'aria-pressed': 'false', 'aria-label': 'Speak your explanation' }, h('span', { class: 'mic-dot', 'aria-hidden': 'true' }), h('span', { class: 'mic-label' }, 'Tap and speak'));
    const dictation = createDictation({
      getLanguage: getLang,
      onText: (value) => { text.value = value; usedVoice = true; sendBtn.disabled = !value.trim(); },
      onState: (state, detail) => {
        mic.setAttribute('aria-pressed', String(state === 'listening'));
        mic.querySelector('.mic-label').textContent = state === 'listening' ? 'Listening… tap to stop' : 'Tap and speak';
        status.textContent = state === 'listening' ? 'Listening. Speak in Hindi, English or Hinglish.'
          : state === 'error' ? (detail === 'not-allowed' ? 'The microphone is blocked. Allow it in the address bar, or type instead.' : detail === 'no-speech' ? 'I did not hear anything. Try again, or type.' : 'Voice input stopped. You can type instead.') : '';
      },
    });
    mic.addEventListener('click', () => (dictation.listening() ? dictation.stop() : dictation.start(text.value)));
    const snap = snapControls({ onPhoto: (file) => readNotebook({ file }), onSample: (sample) => readNotebook({ sample }) });
    const panel = h('div', { class: 'card reasoning' },
      h('h2', null, check ? 'Quick check: how did you get it?' : 'Explain your thinking'),
      h('p', null, a.reasoning_prompt),
      h('div', { class: 'row tight' }, dictation.available() ? mic : h('p', { class: 'muted small' }, 'Voice input is not supported in this browser (try Chrome or Edge). You can type below.')),
      snap.el,
      text, status, h('div', { class: 'row' }, sendBtn, h('button', { class: 'btn btn-quiet', type: 'button', onClick: () => { dictation.stop(); panel.remove(); finishRow(box); } }, 'Skip')));
    box.append(panel);
    if (voice) {   // voice mode: read the prompt, listen for the explanation, send it
      (async () => {
        await spoke; if (!ctx.live()) return;
        await speak(a.reasoning_prompt, getLang(), { force: true });
        status.textContent = '🎙 Listening: explain your thinking…';
        const said = await listenOnce({ language: getLang(), timeoutMs: 15000, onInterim: (t) => { text.value = t; } });
        if (!ctx.live() || !panel.isConnected) return;
        if (said) { text.value = said; usedVoice = true; sendBtn.disabled = false; sendReasoning(); }
        else status.textContent = 'I did not hear anything. Tap the mic, or type.';
      })();
    }

    async function sendReasoning() {
      dictation.stop(); sendBtn.disabled = true;
      // streamed: a first impression within a second, the AI's wording as it is written, then the authoritative result
      const quick = h('p', { class: 'muted', role: 'status' }, 'Looking for the idea behind your answer, not just the option you picked.');
      const live = h('p', { class: 'stream-text' });
      panel.replaceChildren(h('h2', null, 'Reading your reasoning…'), quick, live, skeleton(2));
      try {
        let r = null, hide = false;
        await apiStream('/api/practice/reasoning/stream', { student_id: student.id, attempt_id: a.attempt_id, reasoning_text: text.value.trim(), reasoning_mode: usedVoice ? 'voice' : 'text', language: getLang() }, (ev) => {
          if (ev.type === 'quick') {
            const d = ev.diagnosis;
            hide = d.misconception_id && d.misconception_id !== 'MC_UNKNOWN' && d.misconception_id !== 'NONE';   // a known misconception: the wording would give the answer away (we talk it through instead)
            quick.textContent = hide ? `First impression: this sounds like “${d.label}”. Checking…` : 'First impression ready. Checking your wording…';
          } else if (ev.type === 'delta' && !hide) live.textContent += ev.text;
          else if (ev.type === 'final') r = ev.result;
        }, { timeout: 45000 });
        if (!ctx.live()) return;
        finishReasoning(r, { panel, box, thinking, said: text.value.trim() });
      } catch (err) { panel.replaceChildren(errorCard(err.message, () => { panel.remove(); reasoning(a, box); })); }
    }

    // 📸 the student shows their written working (a photo, or a built-in sample) instead of typing / speaking
    async function readNotebook({ file = null, sample = null }) {
      dictation.stop(); snap.setBusy(true); status.textContent = '';
      const photoUrl = file ? URL.createObjectURL(file) : sample ? sample.image : null;
      const busy = h('div', { class: 'nb-busy', role: 'status' }, h('p', { class: 'muted' }, '📸 Reading your handwriting…'), photoUrl && h('img', { src: photoUrl, alt: '', class: 'nb-thumb' }), skeleton(3));
      panel.append(busy);
      try {
        const blob = file ? await compressPhoto(file) : sample ? await (await fetch(sample.image)).blob() : null;
        const res = await postNotebook({ studentId: student.id, attemptId: sample ? null : a.attempt_id, sampleId: sample ? sample.id : null, blob });
        busy.remove(); snap.setBusy(false);
        if (!ctx.live()) return;
        if (!res.readable) { status.textContent = res.message || 'Couldn’t read that clearly. Try again, or type it.'; text.focus(); return; }
        finishReasoning(res, { panel, box, thinking, said: '📸 notebook', nbView: notebookView(res, photoUrl), isSample: Boolean(sample) });
      } catch (err) { busy.remove(); snap.setBusy(false); status.textContent = err.message || 'Couldn’t read that. Try again, or type it.'; }
    }
  }

  /** Whatever the student used to explain (voice, text or a notebook photo): show the misconception, update mastery, then talk it through. */
  function finishReasoning(r, { panel, box, thinking, said, nbView = null, isSample = false }) {
    if (thinking) thinking.add(r.trace);
    const talk = Boolean(r.misconception) && !r.diagnosis.is_careless_error;   // a known misconception: talk it through instead of just correcting
    const card = misconceptionCard(r, said, talk);
    panel.replaceChildren(...[nbView, card].filter(Boolean));
    const shown = isSample ? null : box.querySelector('.deltas');   // update the SAME card in place: current -> new, no second card and no jump back
    if (shown) shown.update(r.mastery_changes, 'Your mastery, updated with your explanation');
    else panel.after(deltaList(r.mastery_changes, { title: isSample ? 'Your mastery, from the sample page' : 'Your mastery, updated with your explanation' }));
    if (!talk) { finishRow(box); return; }
    const done = () => { card.reveal(); finishRow(box); };
    panel.after(mountDialogue({ student, attemptId: r.attempt_id, onDone: done, onUnavailable: done }));
  }

  function misconceptionCard(r, said, talk = false) {
    const d = r.diagnosis;
    const card = h('div', { class: 'mc-card' });
    let revealed = !talk;   // while Eklavya is talking the student through it, the fix and the explanation stay hidden
    const paint = () => {
      const english = getLang() === 'english';
      const feedback = english ? d.feedback_english : d.feedback_hinglish || d.feedback_english;
      const evidence = d.evidence || said;
      if (d.is_careless_error) {
        card.replaceChildren(h('p', { class: 'eyebrow' }, 'Looks like a slip'), h('h2', null, 'Your thinking was right'),
          h('p', null, feedback), h('p', { class: 'muted small' }, 'We treated this as a small slip, so your mastery drops only a little.'));
      } else if (r.misconception) {
        card.replaceChildren(h('p', { class: 'eyebrow' }, `Misconception spotted · Confidence: ${d.confidence_label || (d.confidence >= 0.75 ? 'High' : d.confidence >= 0.5 ? 'Medium' : 'Low')}`), h('h2', null, r.misconception.label),
          h('blockquote', { class: 'quote' }, h('small', null, said === '📸 notebook' ? 'From your notebook' : 'You said'), `“${evidence}”`),
          revealed ? [h('p', null, feedback), h('div', { class: 'fix' }, h('b', null, 'The fix: '), r.misconception.correction),
            r.misconception.analogy && h('p', { class: 'analogy' }, h('b', null, 'Think of it like this: '), r.misconception.analogy)]
            : h('p', { class: 'lede-small' }, 'Let’s talk it through. I will not just tell you the answer: work it out with me below.'));
      } else {
        card.replaceChildren(h('p', { class: 'eyebrow' }, r.lucky_guess ? 'Reasoning check' : 'A new pattern, not in our list yet'),
          h('h2', null, r.lucky_guess ? 'Right answer, shaky reasoning' : (d.new_label || 'Let’s tighten this up')),
          d.evidence && h('blockquote', { class: 'quote' }, h('small', null, said === '📸 notebook' ? 'From your notebook' : 'You said'), `“${d.evidence}”`), h('p', null, feedback),
          d.fix && h('div', { class: 'fix' }, h('b', null, 'The fix: '), d.fix),
          r.lucky_guess && h('p', { class: 'muted small' }, 'Because the reasoning was unsure, this answer raised your mastery less than usual.'));
      }
    };
    card.addEventListener('lang', paint);
    card.reveal = () => { revealed = true; paint(); };
    paint();
    return card;
  }

  // "Fix the root first" from the map: a short conversation about the root misconception, then practice on that concept
  function rootFirst(conceptId, misconceptionId) {
    const concept = misconceptionId && conceptId;
    const assigned = Boolean(ctx.query.assignment);
    const intro = h('div', { class: 'card' }, h('p', { class: 'eyebrow' }, assigned ? '📌 Your teacher assigned this' : 'Fix the root first'),
      h('h2', null, assigned ? 'A short conversation, then practice' : 'Let’s talk about the real cause'),
      h('p', null, assigned ? 'Your teacher noticed a few students share this idea. Talk it through with Eklavya in your own words, then practise.' : 'Before more practice, let’s clear the idea underneath. Explain it in your own words.'));
    const startTargeted = () => { targetLeft = 3; firstConcept = null; nextQuestion(); };
    const go = h('button', { class: 'btn btn-primary', type: 'button', hidden: true, onClick: startTargeted }, 'Now practise this concept');
    const dlg = mountDialogue({ student, misconceptionId, conceptId: concept, onDone: () => { go.hidden = false; go.focus(); }, onUnavailable: startTargeted });
    stage.replaceChildren(intro, dlg, h('div', { class: 'row' }, go, h('button', { class: 'btn btn-quiet', type: 'button', onClick: startTargeted }, 'Skip to practice')));
  }

  if (ctx.query.talk && firstConcept) rootFirst(firstConcept, ctx.query.talk); else nextQuestion();
}
