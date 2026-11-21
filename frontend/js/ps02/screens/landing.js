import { api } from '../api.js';
import { h } from '../dom.js';
import { getStudent, setStudent } from '../state.js';
import { toast } from '../ui.js';

export async function landing(root) {
  const existing = getStudent();
  const status = h('p', { class: 'form-status', role: 'status' });
  const nameInput = h('input', { id: 'studentName', class: 'input', type: 'text', maxlength: '40', autocomplete: 'given-name', placeholder: 'Your first name', required: true });
  const startBtn = h('button', { class: 'btn btn-primary', type: 'submit' }, 'Begin the diagnostic');
  const form = h('form', { class: 'start-form', hidden: true, onSubmit: async (e) => {
    e.preventDefault();
    startBtn.disabled = true; status.textContent = 'Creating your profile…';
    try {
      const s = await api('/api/students', { method: 'POST', body: { name: nameInput.value.trim() || 'Student', class_section: '' } });
      setStudent({ id: s.id, name: s.name });
      location.hash = '#/diagnostic';
    } catch (err) { status.textContent = err.message; startBtn.disabled = false; }
  } },
  h('label', { for: 'studentName' }, 'What should we call you?'), h('div', { class: 'row' }, nameInput, startBtn),
  h('p', { class: 'muted small' }, '14 short questions across Light, Human Eye, Electricity and Magnetism. No feedback until the end; it is a diagnostic, not a test.'));

  const demoBtn = h('button', { class: 'btn', type: 'button', onClick: async () => {
    demoBtn.disabled = true; status.textContent = 'Loading a demo student…';
    try {
      const { students } = await api('/api/students');
      if (!students.length) throw new Error('The demo class is still being prepared. Try again in a moment.');
      const demo = students[0];
      setStudent({ id: demo.id, name: demo.name, demo: true });
      location.hash = '#/map';
    } catch (err) { status.textContent = err.message; demoBtn.disabled = false; toast(err.message); }
  } }, 'Try demo student');

  root.replaceChildren(
    h('section', { class: 'hero' },
      h('p', { class: 'eyebrow' }, 'CBSE Class 10 Physics · English, Hindi, Hinglish'),
      h('h1', { class: 'hero-title' }, 'Generic AI tutors answer questions. Eklavya knows what you don’t understand, and why.'),
      h('p', { class: 'hero-sub' }, 'Take a 14-question diagnostic, see your concept map, then practise on exactly what is weak. When you get one wrong, say why in your own words (by voice, if you like) and Eklavya names the misconception behind it.'),
      h('div', { class: 'hero-actions' },
        existing && h('a', { class: 'btn btn-primary', href: '#/map' }, `Continue as ${existing.name}`),
        h('button', { class: `btn ${existing ? '' : 'btn-primary'}`, type: 'button', onClick: () => { form.hidden = false; nameInput.focus(); } }, 'Start as student'),
        h('a', { class: 'btn', href: '#/teacher' }, 'Open teacher dashboard'),
        demoBtn),
      form, status),
    h('section', { class: 'pillars', 'aria-label': 'What is inside' },
      pillar('1', 'Diagnose', 'A hand-written diagnostic whose wrong options are built from real misconceptions.', '#/how'),
      pillar('2', 'Model', 'Per-concept mastery (Bayesian Knowledge Tracing) over a prerequisite graph, updated after every answer.', '#/how'),
      pillar('3', 'Understand why', 'Explain your reasoning aloud; the AI finds the misconception, not just the wrong option.', '#/how'),
      pillar('4', 'Remember', 'Spaced repetition brings each concept back just before you would forget it.', '#/how'),
      pillar('5', 'Teach', 'A teacher dashboard shows class-wide gaps and a ready “reteach tomorrow” plan.', '#/teacher')));
}

const pillar = (n, title, text, href) => h('a', { class: 'pillar', href }, h('span', { class: 'pillar-n', 'aria-hidden': 'true' }, n), h('h2', null, title), h('p', null, text));
