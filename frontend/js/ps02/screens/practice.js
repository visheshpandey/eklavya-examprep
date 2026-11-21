// Practice loop: targeted question -> answer -> (explain your thinking, by voice or text) -> misconception card + live mastery changes.
import { api, qs } from '../api.js';
import { h } from '../dom.js';
import { createDictation } from '../../lib/dictation.js';
import { getLang, getStudent, setLang } from '../state.js';
import { errorCard, loading, skeleton } from '../ui.js';
import { deltaList } from './deltas.js';
import { mountDialogue } from './dialogue.js';

const LANGS = [['hinglish', 'Hinglish'], ['english', 'English'], ['hindi', 'हिन्दी']];
const DIFF = { 1: 'Easier', 2: 'Medium', 3: 'Harder' };

export async function practice(root, ctx) {
  const student = getStudent();
  const review = ctx.query.review === '1';
  let firstConcept = ctx.query.concept || null;
  let done = 0, total = null;
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

  root.replaceChildren(h('section', { class: 'narrow' },
    h('div', { class: 'row between wrap' }, h('div', null, h('p', { class: 'eyebrow' }, review ? 'Spaced-repetition review' : 'Adaptive practice'), counter), langBar), stage));

  async function nextQuestion() {
    if (review && done >= total) return summary();
    counter.textContent = review ? `Review ${done + 1} of ${total}` : '';
    stage.replaceChildren(loading('Choosing the best next question for you…', 4));
    try {
      const q = await api(`/api/practice/next?${qs({ student_id: student.id, ...(review ? { review: 1 } : {}), ...(firstConcept ? { concept_id: firstConcept } : {}) })}`);
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
    stage.dataset.locked = '';
    stage.replaceChildren(h('div', { class: 'card question' },
      h('div', { class: 'q-meta' },
        h('span', { class: `pill diff-${q.difficulty}` }, `${DIFF[q.difficulty]} · level ${q.difficulty}`), h('span', { class: 'chip' }, `${q.chapter} · ${q.concept_name}`),
        q.source !== 'ai' && h('span', { class: 'chip', title: 'The AI was slow, so a prepared question was used' }, 'prepared question')),
      h('p', { class: 'why' }, h('b', null, 'Why this question? '), q.why),
      h('h2', { class: 'stem' }, q.stem), h('div', { class: 'options', role: 'radiogroup', 'aria-label': 'Answer options' }, options), h('div', { class: 'row' }, submit)),
      feedback);
    options[0].focus({ preventScroll: true });

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
          h('div', { class: `result ${a.correct ? 'result-ok' : 'result-bad'}`, role: 'status' }, h('b', null, a.correct ? 'Correct!' : 'Not quite.'), ' ', a.explanation),
          deltas);
        if (a.needs_reasoning) reasoning(a, feedback); else finishRow(feedback);
      } catch (err) {
        submit.disabled = false; submit.textContent = 'Check answer'; options.forEach((o) => { o.disabled = false; }); stage.dataset.locked = '';
        feedback.replaceChildren(errorCard(err.message.includes('expired') ? 'That question expired. Let’s get a new one.' : err.message, nextQuestion));
      }
    }
  }

  function finishRow(box) {
    const next = h('button', { class: 'btn btn-primary', type: 'button', onClick: () => { done += review ? 1 : 0; nextQuestion(); } }, review && done + 1 >= total ? 'Finish review' : 'Next question');
    box.append(h('div', { class: 'row' }, next, h('a', { class: 'btn btn-quiet', href: '#/map' }, 'See my map')));
    next.focus({ preventScroll: false });
  }

  function reasoning(a, box) {
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
    const panel = h('div', { class: 'card reasoning' },
      h('h2', null, check ? 'Quick check: how did you get it?' : 'Explain your thinking'),
      h('p', null, a.reasoning_prompt),
      dictation.available() ? mic : h('p', { class: 'muted small' }, 'Voice input is not supported in this browser (try Chrome or Edge). You can type below.'),
      text, status, h('div', { class: 'row' }, sendBtn, h('button', { class: 'btn btn-quiet', type: 'button', onClick: () => { dictation.stop(); panel.remove(); finishRow(box); } }, 'Skip')));
    box.append(panel);

    async function sendReasoning() {
      dictation.stop(); sendBtn.disabled = true;
      panel.replaceChildren(h('h2', null, 'Reading your reasoning…'), h('p', { class: 'muted' }, 'Looking for the idea behind your answer, not just the option you picked.'), skeleton(4));
      try {
        const r = await api('/api/practice/reasoning', { method: 'POST', body: { student_id: student.id, attempt_id: a.attempt_id, reasoning_text: text.value.trim(), reasoning_mode: usedVoice ? 'voice' : 'text' } });
        if (!ctx.live()) return;
        const talk = Boolean(r.misconception) && !r.diagnosis.is_careless_error;   // a known misconception: talk it through instead of just correcting
        const card = misconceptionCard(r, text.value.trim(), talk);
        panel.replaceChildren(card);
        const shown = box.querySelector('.deltas');   // update the SAME card in place: current -> new, no second card and no jump back
        let finalDeltas = shown;
        if (shown) shown.update(r.mastery_changes, 'Your mastery, updated with your explanation');
        else { finalDeltas = deltaList(r.mastery_changes, { title: 'Your mastery, updated with your explanation' }); panel.after(finalDeltas); }
        if (!talk) { finishRow(box); return; }
        const done = () => { card.reveal(); finishRow(box); };
        finalDeltas.after(mountDialogue({ student, attemptId: a.attempt_id, onDone: done, onUnavailable: done }));
      } catch (err) { panel.replaceChildren(errorCard(err.message, () => { panel.remove(); reasoning(a, box); })); }
    }
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
          h('blockquote', { class: 'quote' }, h('small', null, 'You said'), `“${evidence}”`),
          revealed ? [h('p', null, feedback), h('div', { class: 'fix' }, h('b', null, 'The fix: '), r.misconception.correction),
            r.misconception.analogy && h('p', { class: 'analogy' }, h('b', null, 'Think of it like this: '), r.misconception.analogy)]
            : h('p', { class: 'lede-small' }, 'Let’s talk it through. I will not just tell you the answer: work it out with me below.'));
      } else {
        card.replaceChildren(h('p', { class: 'eyebrow' }, r.lucky_guess ? 'Reasoning check' : 'A new pattern, not in our list yet'),
          h('h2', null, r.lucky_guess ? 'Right answer, shaky reasoning' : (d.new_label || 'Let’s tighten this up')),
          d.evidence && h('blockquote', { class: 'quote' }, h('small', null, 'You said'), `“${d.evidence}”`), h('p', null, feedback),
          d.fix && h('div', { class: 'fix' }, h('b', null, 'The fix: '), d.fix),
          r.lucky_guess && h('p', { class: 'muted small' }, 'Because the reasoning was unsure, this answer raised your mastery less than usual.'));
      }
    };
    card.addEventListener('lang', paint);
    card.reveal = () => { revealed = true; paint(); };
    paint();
    return card;
  }

  nextQuestion();
}
