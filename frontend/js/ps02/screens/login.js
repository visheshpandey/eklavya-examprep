// Two separate logins: students (register or sign in) and teachers (sign in only; teacher accounts are made by the deployer). One-click demo buttons for judges.
import { api } from '../api.js';
import { h } from '../dom.js';
import { setSession } from '../state.js';
import { toast } from '../ui.js';

function finish(session) {
  setSession(session);
  location.hash = session.role === 'teacher' ? '#/teacher' : session.student?.is_demo ? '#/map' : '#/diagnostic';
}

export async function loginScreen(root, ctx) {
  let role = ctx.query.as === 'teacher' ? 'teacher' : 'student';
  let mode = 'login';                                   // students only: 'login' | 'register'
  const status = h('p', { class: 'form-status', role: 'status' });
  const box = h('div');

  const field = (id, label, props) => h('div', { class: 'field' }, h('label', { for: id }, label), h('input', { id, class: 'input', required: true, ...props }));

  function paint() {
    const isTeacher = role === 'teacher';
    const reg = !isTeacher && mode === 'register';
    const name = reg && field('lg-name', 'Your name', { type: 'text', maxlength: '40', autocomplete: 'name', placeholder: 'e.g. Aarav' });
    const klass = reg && field('lg-class', 'Class (optional)', { type: 'text', maxlength: '20', placeholder: 'e.g. 10-B', required: false });
    const email = field('lg-email', 'Email', { type: 'email', maxlength: '120', autocomplete: 'username', placeholder: isTeacher ? 'teacher@school.in' : 'you@example.com' });
    const pass = field('lg-pass', 'Password', { type: 'password', maxlength: '200', autocomplete: reg ? 'new-password' : 'current-password', placeholder: reg ? 'At least 8 characters' : '' });
    const submit = h('button', { class: 'btn btn-primary', type: 'submit' }, reg ? 'Create my account' : isTeacher ? 'Log in as teacher' : 'Log in');
    const form = h('form', { class: 'login-form', onSubmit: async (e) => {
      e.preventDefault(); submit.disabled = true; status.textContent = reg ? 'Creating your account…' : 'Signing in…';
      const value = (id) => form.querySelector(`#${id}`)?.value.trim() ?? '';
      try {
        const session = reg
          ? await api('/api/ps02/auth/register', { method: 'POST', body: { name: value('lg-name'), email: value('lg-email'), password: form.querySelector('#lg-pass').value, class_section: value('lg-class') } })
          : await api('/api/ps02/auth/login', { method: 'POST', body: { email: value('lg-email'), password: form.querySelector('#lg-pass').value, role } });
        finish(session);
      } catch (err) { status.textContent = err.message; submit.disabled = false; }
    } }, name, klass, email, pass, submit);

    const demo = h('button', { class: 'btn', type: 'button', onClick: async (e) => {
      e.currentTarget.disabled = true; status.textContent = 'Loading the demo…';
      try { finish(await api('/api/ps02/auth/demo', { method: 'POST', body: { role } })); }
      catch (err) { status.textContent = err.message; e.currentTarget.disabled = false; toast(err.message); }
    } }, isTeacher ? 'Try the demo teacher' : 'Try the demo student');

    const tab = (id, label) => h('button', { class: 'seg-btn', type: 'button', role: 'tab', 'aria-selected': String(role === id), 'aria-pressed': String(role === id),
      onClick: () => { role = id; mode = 'login'; status.textContent = ''; paint(); } }, label);
    box.replaceChildren(
      h('div', { class: 'seg', role: 'tablist', 'aria-label': 'Who are you?' }, tab('student', 'I am a student'), tab('teacher', 'I am a teacher')),
      h('h1', { class: 'page-title' }, isTeacher ? 'Teacher login' : reg ? 'Create your student account' : 'Student login'),
      h('p', { class: 'lede' }, isTeacher ? 'See where the whole class is stuck, and plan tomorrow’s reteaching.' : 'Your progress, your concept map and your reviews are saved to your account.'),
      form, status,
      !isTeacher && h('p', { class: 'muted small' }, reg ? 'Already have an account? ' : 'New here? ',
        h('button', { class: 'link-btn', type: 'button', onClick: () => { mode = reg ? 'login' : 'register'; status.textContent = ''; paint(); } }, reg ? 'Log in' : 'Create an account')),
      h('div', { class: 'login-demo' }, h('p', { class: 'muted small' }, 'Just looking around? No account needed:'), demo));
    form.querySelector('input')?.focus({ preventScroll: true });
  }
  paint();
  root.replaceChildren(h('section', { class: 'narrow card login-card' }, box));
}
