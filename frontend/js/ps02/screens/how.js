// "How it works": the 7 problem-statement requirements, where each lives in the app, and the answer -> model -> misconception -> SRS loop.
import { h } from '../dom.js';

const REQUIREMENTS = [
  ['1', 'A diagnostic test', '14 hand-written questions across all four chapters. Every wrong option is built from a real misconception, so a wrong pick already hints at it.', 'Start as student → Diagnostic', '#/'],
  ['2', 'A concept graph for one syllabus', 'CBSE Class 10 Physics: 21 concepts in Light, Human Eye, Electricity and Magnetism, linked by prerequisites.', 'My map', '#/map'],
  ['3', 'A learner model updated after every answer', 'Bayesian Knowledge Tracing per concept (slip, guess, learn). A misconception in a prerequisite also lowers that prerequisite; a hard correct answer nudges prerequisites up.', 'My map → click a concept → history', '#/map'],
  ['4', 'Question generation for weak concepts, calibrated', 'The model picks the weakest concept you are ready for and a difficulty (~70% expected success). The AI writes the question; the “Why this question?” line shows the reasoning.', 'Practice', '#/practice'],
  ['5', 'Misconception detection from the reasoning', 'After a wrong answer you explain your thinking, by voice in Hindi/English/Hinglish or in text. The AI names the misconception from your words, or spots a careless slip.', 'Practice → wrong answer → Explain your thinking', '#/practice'],
  ['6', 'Spaced-repetition scheduling', 'SM-2 per concept: confident answers push the next review further away; misses bring it back. Time-travel mode turns 1 day into 1 minute for demos.', 'Reviews', '#/reviews'],
  ['7', 'A teacher dashboard with class-wide gaps', 'Heatmap of students × concepts, weakest concepts, top misconceptions with quotes, students at risk, and an AI “Reteach tomorrow” plan.', 'Teacher', '#/teacher'],
];

const STEPS = [
  ['Answer', 'Pick an option'],
  ['Why?', 'Explain by voice or text'],
  ['Misconception detection', 'AI reads the reasoning'],
  ['Learner model (BKT)', 'Mastery + prerequisites update'],
  ['Spaced repetition (SM-2)', 'Next review scheduled'],
  ['Next question', 'Weakest ready concept, calibrated'],
];

export async function how(root) {
  root.replaceChildren(
    h('p', { class: 'eyebrow' }, 'How it works'), h('h1', { class: 'page-title' }, 'A tutor that models what you know'),
    h('p', { class: 'lede' }, 'Eklavya Exam Prep covers all seven parts of the problem. Every one is visible in the app; here is where.'),
    h('ol', { class: 'flow', 'aria-label': 'The learning loop' }, STEPS.map(([t, d], i) => h('li', null, h('b', null, t), h('span', null, d), i < STEPS.length - 1 && h('i', { class: 'flow-arrow', 'aria-hidden': 'true' }, '→')))),
    h('div', { class: 'req-grid' }, REQUIREMENTS.map(([n, title, text, where, href]) => h('article', { class: 'card req' },
      h('span', { class: 'req-n', 'aria-hidden': 'true' }, n), h('h2', null, title), h('p', null, text), h('a', { class: 'link', href }, `See it: ${where} →`)))),
    h('section', { class: 'card split' },
      h('div', null, h('h2', null, 'What the AI decides'), h('ul', { class: 'bullets' },
        h('li', null, 'Writes each practice question, with distractors built from known misconceptions.'),
        h('li', null, 'Reads your explanation (even Hinglish) and names the misconception, or flags a careless slip.'),
        h('li', null, 'Drafts the teacher’s “reteach tomorrow” plan from class data.'))),
      h('div', null, h('h2', null, 'What plain maths decides'), h('ul', { class: 'bullets' },
        h('li', null, 'How likely you know each concept (BKT), and how that spreads to prerequisites.'),
        h('li', null, 'Which concept and difficulty come next.'),
        h('li', null, 'When each concept is reviewed again (SM-2).'))),
    ),
    h('p', { class: 'muted small' }, 'Built on top of the Eklavya codebase (voice + Hinglish layer), with organiser permission.'));
}
