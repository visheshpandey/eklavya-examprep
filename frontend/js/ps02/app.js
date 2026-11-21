// Hash router + shell. Every screen is `async (root, ctx)`; ctx.live() turns false once the user has navigated elsewhere.
import { api, qs, warmUp } from './api.js';
import { h } from './dom.js';
import { clearSession, getRole, getStudent, getToken } from './state.js';
import { errorCard, loading, toast } from './ui.js';
import { landing } from './screens/landing.js';
import { diagnostic } from './screens/diagnostic.js';
import { mapScreen } from './screens/map.js';
import { practice } from './screens/practice.js';
import { reviews } from './screens/reviews.js';
import { teacher } from './screens/teacher.js';
import { how } from './screens/how.js';
import { notes } from './screens/notes.js';
import { verify } from './screens/verify.js';
import { loginScreen } from './screens/login.js';
import { mountAskWidget } from './ask-widget.js';
import { startTour } from './tour.js';

const ROUTES = { '': landing, diagnostic, map: mapScreen, practice, reviews, teacher, student: mapScreen, how, notes, verify, login: loginScreen };
const NEEDS_STUDENT = new Set(['diagnostic', 'map', 'practice', 'reviews', 'notes', 'verify']);
const NEEDS_TEACHER = new Set(['teacher']);   // '#/student/<id>' (a teacher opening one student's map) is a teacher page too
const app = document.getElementById('app');
let renderId = 0;

function parse() {
  const [path, query = ''] = location.hash.replace(/^#\/?/, '').split('?');
  const [name = '', arg = ''] = path.split('/');
  return { name, arg, query: Object.fromEntries(new URLSearchParams(query)) };
}

function paintShell(name) {
  const student = getStudent();
  document.querySelectorAll('#nav a').forEach((a) => {
    a.hidden = (a.hasAttribute('data-student') && !student) || (a.hasAttribute('data-teacher') && getRole() !== 'teacher');
    if (a.dataset.route === name || (name === 'student' && a.dataset.route === 'teacher')) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  const who = document.getElementById('who');
  who.hidden = !student;
  who.replaceChildren();
  if (student) {
    who.append(h('span', { class: 'who-name' }, student.name),
      h('button', { class: 'link-btn', type: 'button', onClick: logout }, 'Log out'));
  } else if (getRole() === 'teacher') {
    who.hidden = false;
    who.append(h('span', { class: 'who-name' }, 'Teacher'), h('button', { class: 'link-btn', type: 'button', onClick: logout }, 'Log out'));
  } else {
    who.hidden = false;
    who.append(h('a', { class: 'link-btn', href: '#/login' }, 'Log in'));
  }
}

function logout() { clearSession(); location.hash = '#/'; render(); }

async function refreshDueBadge() {
  const badge = document.getElementById('dueBadge');
  const student = getStudent();
  if (!student) { badge.hidden = true; return; }
  try {
    const r = await api(`/api/reviews/due?${qs({ student_id: student.id })}`, { timeout: 15000 });
    badge.textContent = r.due.length;
    badge.hidden = r.due.length === 0;
  } catch { badge.hidden = true; }
}

async function render() {
  const id = ++renderId;
  const { name, arg, query } = parse();
  const screen = ROUTES[name] ?? landing;
  if (name !== 'login' && (NEEDS_STUDENT.has(name) || NEEDS_TEACHER.has(name) || name === 'student') && !getToken()) { toast('Please log in first.'); location.hash = NEEDS_STUDENT.has(name) ? '#/login' : '#/login?as=teacher'; return; }
  if ((NEEDS_TEACHER.has(name) || name === 'student') && getRole() !== 'teacher') { toast('That page is for teachers. Log in as a teacher.'); location.hash = '#/login?as=teacher'; return; }
  if (NEEDS_STUDENT.has(name) && !getStudent()) { toast('Please log in as a student.'); location.hash = '#/login'; return; }
  paintShell(name);
  app.replaceChildren(loading('Loading…'));
  const ctx = { arg, query, live: () => id === renderId, refreshDue: refreshDueBadge };
  try {
    await screen(app, ctx);
  } catch (err) {
    if (ctx.live()) app.replaceChildren(errorCard(err.message || 'Something went wrong.', render));
  }
  if (ctx.live()) { app.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); refreshDueBadge(); }
}

window.addEventListener('hashchange', render);
window.addEventListener('ps02:auth-needed', () => {   // the token expired or is not allowed: sign in again
  if (location.hash.startsWith('#/login')) return;
  clearSession(); toast('Please log in again.'); location.hash = '#/login'; render();
});
let startingOver = false;
window.addEventListener('ps02:student-gone', () => {   // the saved student id no longer exists on the server (database reset): forget it and go to the landing page
  if (startingOver) return;   // several requests fail at once; handle it once
  startingOver = true;
  clearSession(); toast('Your session expired, start again.');
  if (location.hash === '#/' || location.hash === '') render(); else location.hash = '#/';
  setTimeout(() => { startingOver = false; }, 1500);
});

// A service worker from the old Eklavya build (same address while developing) would serve stale files: remove it.
navigator.serviceWorker?.getRegistrations().then((rs) => rs.forEach((r) => r.unregister())).catch(() => {});
globalThis.caches?.keys().then((keys) => keys.forEach((k) => globalThis.caches.delete(k))).catch(() => {});

document.getElementById('tourNav').addEventListener('click', () => startTour());
mountAskWidget();   // the floating "Ask a doubt" button lives on every screen

const banner = document.getElementById('banner');
warmUp(
  () => { banner.textContent = 'Waking up the server… the free host can take up to a minute on the first visit. You can keep browsing.'; banner.hidden = false; },
  () => { banner.hidden = true; },
);
render();
