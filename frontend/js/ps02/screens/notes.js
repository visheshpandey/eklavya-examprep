// Notes: upload your own notes or an NCERT chapter PDF (students), or class notes for everyone (teacher). Eklavya's retrieval then grounds
// practice questions, explanations and doubts in them, with a "from your notes" citation.
import { api, apiUpload, qs } from '../api.js';
import { h } from '../dom.js';
import { getStudent } from '../state.js';
import { errorCard, toast } from '../ui.js';

/** The upload card. `section` makes it a class upload (teacher); otherwise it is the student's own. onDone() refreshes the list. */
export function notesUploader({ studentId, section = null, onDone }) {
  const status = h('p', { class: 'form-status', role: 'status' });
  const file = h('input', { type: 'file', id: `notes-file-${section || 'me'}`, accept: '.pdf,.txt,.png,.jpg,.jpeg,.webp', class: 'file-input' });
  const paste = h('textarea', { class: 'input', rows: '3', maxlength: '60000', 'aria-label': 'Or paste your notes', placeholder: 'Or paste notes here…' });
  const btn = h('button', { class: 'btn btn-primary', type: 'button', onClick: async () => {
    const f = file.files[0], t = paste.value.trim();
    if (!f && t.length < 50) { status.textContent = 'Choose a PDF, TXT or photo of your notes, or paste at least a few sentences.'; return; }
    btn.disabled = true; status.textContent = f?.name.toLowerCase().endsWith('.pdf') ? 'Reading the PDF and indexing it. A long chapter can take up to a minute…' : 'Reading and indexing your notes…';
    const form = new FormData();
    if (section) form.append('class_section', section); else form.append('student_id', String(studentId));
    if (f) form.append('file', f); else form.append('text', t);
    try {
      const r = await apiUpload('/api/ps02/notes', form);
      status.textContent = '';
      toast(`Added “${r.file_name}”: ${r.chunks} passages, ${r.topics.length} topics.`);
      file.value = ''; paste.value = '';
      onDone?.();
    } catch (err) { status.textContent = err.message; } finally { btn.disabled = false; }
  } }, section ? 'Upload for the class' : 'Upload my notes');
  return h('div', { class: 'card notes-up' },
    h('h2', null, section ? `Class notes for ${section}` : 'Add notes'),
    h('p', { class: 'muted small' }, section ? 'Every student in the class gets answers, questions and explanations grounded in these.' : 'Your own notes, or an NCERT chapter PDF (for example Class 10 Science: Electricity). Up to 10 MB.'),
    h('label', { class: 'small', for: file.id }, 'PDF, TXT or a photo of a page'), file, paste, h('div', { class: 'row' }, btn), status);
}

export function noteList(notes, { onDelete }) {
  if (!notes.length) return h('p', { class: 'muted' }, 'No notes yet.');
  return h('ul', { class: 'review-list' }, notes.map((n) => h('li', { class: 'review' },
    h('div', null, h('b', null, n.file_name), h('p', { class: 'muted small' }, `${n.chunks} passages · ${n.topics.slice(0, 4).join(', ') || 'no topics found'}`)),
    h('span', { class: `chip ${n.scope === 'class' ? 'chip-action' : ''}` }, n.scope === 'class' ? 'Class notes' : 'My notes'),
    n.scope === 'class' && !onDelete.allowClass ? h('span') : h('button', { class: 'btn btn-small', type: 'button', onClick: () => onDelete(n) }, 'Delete'))));
}

export async function notes(root, ctx) {
  const student = getStudent();
  const box = h('div');
  async function load() {
    try {
      const r = await api(`/api/ps02/notes?${qs({ student_id: student.id })}`);
      if (!ctx.live()) return;
      box.replaceChildren(h('div', { class: 'card' }, h('h2', null, 'Your notes'), noteList(r.notes, {
        onDelete: async (n) => { try { await api(`/api/ps02/notes/${n.id}?${qs({ student_id: student.id })}`, { method: 'DELETE' }); toast('Deleted.'); load(); } catch (err) { toast(err.message); } } })));
    } catch (err) { box.replaceChildren(errorCard(err.message, load)); }
  }
  root.replaceChildren(h('section', { class: 'narrow' },
    h('p', { class: 'eyebrow' }, 'Your notes'), h('h1', { class: 'page-title' }, 'Practise from your own notes'),
    h('p', { class: 'lede' }, 'Upload notes or an NCERT chapter. Practice questions and explanations will use them when they are relevant, and say “from your notes”. Ask a doubt also searches them.'),
    notesUploader({ studentId: student.id, onDone: load }), box));
  await load();
}
