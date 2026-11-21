// Hash router + shell. Every screen is `async (root, ctx)`; ctx.live() turns false once the user has navigated elsewhere.
import { api, qs, warmUp } from './api.js';
import { h } from './dom.js';
import { clearStudent, getStudent } from './state.js';
import { errorCard, loading, toast } from './ui.js';
import { landing } from './screens/landing.js';
import { diagnostic } from './screens/diagnostic.js';
import { mapScreen } from './screens/map.js';
import { practice } from './screens/practice.js';
import { reviews } from './screens/reviews.js';
import { teacher } from './screens/teacher.js';
import { how } from './screens/how.js';

const ROUTES = { '': landing, diagnostic, map: mapScreen, practice, reviews, teacher, student: mapScreen, how };
const NEEDS_STUDENT = new Set(['diagnostic', 'map', 'practice', 'reviews']);
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
    a.hidden = a.hasAttribute('data-student') && !student;
    if (a.dataset.route === name || (name === 'student' && a.dataset.route === 'teacher')) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  const who = document.getElementById('who');
  who.hidden = !student;
  who.replaceChildren();
  if (student) {
    who.append(h('span', { class: 'who-name' }, student.name),
      h('button', { class: 'link-btn', type: 'button', onClick: () => { clearStudent(); location.hash = '#/'; render(); } }, 'Switch'));
  }
}

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
  if (NEEDS_STUDENT.has(name) && !getStudent()) { toast('Pick a student first.'); location.hash = '#/'; return; }
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
window.addEventListener('ps02:student-gone', () => {   // the saved student id no longer exists on the server (database reset)
  clearStudent(); toast('That student no longer exists, so we started you fresh.'); if (location.hash === '#/' || location.hash === '') render(); else location.hash = '#/';
});

// A service worker from the old Eklavya build (same address while developing) would serve stale files: remove it.
navigator.serviceWorker?.getRegistrations().then((rs) => rs.forEach((r) => r.unregister())).catch(() => {});
globalThis.caches?.keys().then((keys) => keys.forEach((k) => globalThis.caches.delete(k))).catch(() => {});

const banner = document.getElementById('banner');
warmUp(
  () => { banner.textContent = 'Waking up the server… the free host can take up to a minute on the first visit. You can keep browsing.'; banner.hidden = false; },
  () => { banner.hidden = true; },
);
render();
