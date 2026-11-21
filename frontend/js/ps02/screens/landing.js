import { api } from '../api.js';
import { h } from '../dom.js';
import { getRole, getStudent, getToken } from '../state.js';
import { toast } from '../ui.js';
import { heroDemo } from '../hero-demo.js';
import { startTour } from '../tour.js';

export async function landing(root) {
  const existing = getToken() && getRole() === 'student' ? getStudent() : null;
  const status = h('p', { class: 'form-status', role: 'status' });

  root.replaceChildren(
    h('div', { class: 'hero-wrap' }, h('section', { class: 'hero' },
      h('p', { class: 'eyebrow' }, 'CBSE Class 10 Physics · English, Hindi, Hinglish'),
      h('h1', { class: 'hero-title' }, 'Generic AI tutors answer questions. Eklavya knows what you don’t understand, and why.'),
      h('p', { class: 'hero-sub' }, 'Take a 14-question diagnostic, see your concept map, then practise on exactly what is weak. When you get one wrong, say why in your own words (by voice, if you like) and Eklavya names the misconception behind it.'),
      h('div', { class: 'hero-actions' },
        h('button', { class: 'btn btn-judge', type: 'button', onClick: async (e) => { const b = e.currentTarget; b.disabled = true; b.textContent = 'Preparing the demo…'; await startTour(); b.disabled = false; b.textContent = '👩‍⚖️ Judge tour (2 min)'; } }, '👩‍⚖️ Judge tour (2 min)'),
        existing ? h('a', { class: 'btn btn-primary', href: '#/map' }, `Continue as ${existing.name}`) : h('a', { class: 'btn btn-primary', href: '#/login' }, 'Student login'),
        getToken() && getRole() === 'teacher' ? h('a', { class: 'btn btn-primary', href: '#/teacher' }, 'Open teacher dashboard') : h('a', { class: 'btn', href: '#/login?as=teacher' }, 'Teacher login')),
      status), heroDemo()),
    h('section', { class: 'pillars', 'aria-label': 'What is inside' },
      pillar('1', 'Diagnose', 'A hand-written diagnostic whose wrong options are built from real misconceptions.', '#/how'),
      pillar('2', 'Model', 'Per-concept mastery (Bayesian Knowledge Tracing) over a prerequisite graph, updated after every answer.', '#/how'),
      pillar('3', 'Understand why', 'Explain your reasoning aloud; the AI finds the misconception, not just the wrong option.', '#/how'),
      pillar('4', 'Remember', 'Spaced repetition brings each concept back just before you would forget it.', '#/how'),
      pillar('5', 'Teach', 'A teacher dashboard shows class-wide gaps and a ready “reteach tomorrow” plan.', '#/teacher')));
}

const pillar = (n, title, text, href) => h('a', { class: 'pillar', href }, h('span', { class: 'pillar-n', 'aria-hidden': 'true' }, n), h('h2', null, title), h('p', null, text));
