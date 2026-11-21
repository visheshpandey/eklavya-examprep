// 📸 Snap your notebook: take / choose a photo of your handwritten working (or try a built-in sample), then see it read back to you with the first
// wrong line in red. The photo is sent to the AI for reading only; the server keeps no copy.
import { api, apiUpload } from './api.js';
import { h } from './dom.js';
import { getLang } from './state.js';

/** Shrink a big phone photo in the browser first (faster upload, same legibility). Falls back to the original file. */
export async function compressPhoto(file, maxSide = 1600) {
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
    const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bmp.width * scale); canvas.height = Math.round(bmp.height * scale);
    canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85));
    return blob || file;
  } catch { return file; }
}

/** POST the photo (and/or the sample id) to the reader. Resolves with the server's result ({readable: false, message} when it could not be read). */
export async function postNotebook({ studentId, attemptId = null, sampleId = null, conceptId = null, blob = null }) {
  const form = new FormData();
  form.append('student_id', String(studentId));
  form.append('language', getLang());
  if (attemptId != null) form.append('attempt_id', String(attemptId));
  if (sampleId) form.append('sample_id', sampleId);
  if (conceptId) form.append('concept_id', conceptId);
  if (blob) form.append('file', blob, 'working.jpg');
  return apiUpload('/api/ps02/notebook', form, { timeout: 90000 });
}

/** The result: your photo on the left, the transcribed steps on the right, the first wrong line in red, and a callout saying what is wrong. */
export function notebookView(res, photoUrl) {
  const nb = res.notebook;
  const english = getLang() === 'english';
  const feedback = english ? res.diagnosis?.feedback_english : res.diagnosis?.feedback_hinglish || res.diagnosis?.feedback_english;
  const wrong = nb.first_wrong_step;
  const picked = res.sample ? res.sample.options[res.sample.picked] : null;
  return h('section', { class: 'nb-view', 'aria-label': 'Your notebook, read back' },
    res.sample && h('div', { class: 'nb-sample' }, h('b', null, 'Sample question: '), res.sample.stem, h('span', { class: 'muted small' }, ` The student picked “${picked}”.`)),
    h('div', { class: 'nb-grid' },
      h('figure', { class: 'nb-photo' }, photoUrl && h('img', { src: photoUrl, alt: 'Your notebook page' }),
        h('figcaption', { class: 'small muted' }, nb.source === 'sample-prepared' ? 'Sample page (pre-read)' : nb.source === 'ai' ? 'Your page, read by AI' : 'Your page')),
      h('div', { class: 'nb-read' },
        h('h3', null, 'What I read'),
        h('ol', { class: 'nb-steps' }, nb.steps.map((s, i) => h('li', { class: `nb-step ${i === wrong ? 'nb-wrong' : ''}`, 'aria-current': i === wrong ? 'true' : null },
          h('span', { class: 'nb-no', 'aria-hidden': 'true' }, String(i + 1)), h('span', { class: 'nb-text' }, s), i === wrong && h('b', { class: 'nb-x', 'aria-label': 'first wrong line' }, '✗')))),
        wrong != null ? h('div', { class: 'nb-callout' }, h('b', null, `Line ${wrong + 1}: `), nb.error) : h('div', { class: 'nb-callout nb-ok' }, 'Every line of your working looks right.'),
        h('span', { class: `chip ${nb.confidence === 'high' ? 'chip-ok' : ''}` }, `Confidence: ${nb.confidence[0].toUpperCase()}${nb.confidence.slice(1)}`))),
    feedback && h('p', { class: 'nb-feedback' }, feedback));
}

/** "📸 Snap your working" + "Try a sample". onPhoto(file) / onSample(sample). Returns { el, setBusy }. */
export function snapControls({ onPhoto, onSample }) {
  const input = h('input', { type: 'file', accept: 'image/*', capture: 'environment', class: 'visually-hidden', 'aria-label': 'Take or choose a photo of your working',
    onChange: () => { const f = input.files[0]; input.value = ''; if (f) onPhoto(f); } });
  const snap = h('button', { class: 'btn snap-btn', type: 'button', onClick: () => input.click() }, '📸 Snap your working');
  const picker = h('div', { class: 'snap-samples', hidden: true });
  let loaded = false;
  const sampleBtn = h('button', { class: 'btn btn-quiet btn-small', type: 'button', 'aria-expanded': 'false', onClick: async () => {
    picker.hidden = !picker.hidden; sampleBtn.setAttribute('aria-expanded', String(!picker.hidden));
    if (picker.hidden || loaded) return;
    try {
      const { samples } = await api('/api/ps02/notebook/samples', { timeout: 15000 });
      picker.replaceChildren(...samples.map((s) => h('button', { class: 'snap-sample', type: 'button', onClick: () => { picker.hidden = true; sampleBtn.setAttribute('aria-expanded', 'false'); onSample(s); } },
        h('img', { src: s.image, alt: '', loading: 'lazy' }), h('span', null, h('b', null, s.title), h('small', null, s.subtitle)))));
      loaded = true;
    } catch { picker.replaceChildren(h('p', { class: 'muted small' }, 'Samples are unavailable right now.')); }
  } }, 'Try a sample');
  const el = h('div', { class: 'snap' }, h('div', { class: 'row tight' }, snap, sampleBtn, input), picker);
  return { el, setBusy: (busy) => { snap.disabled = busy; sampleBtn.disabled = busy; } };
}
