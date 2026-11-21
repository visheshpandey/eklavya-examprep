// The chosen student and language live in localStorage (wrapped: it can throw in private windows).
const KEY = 'ps02.student';
const LANG = 'ps02.lang';

function read(key) { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; } }
function write(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* ignore */ } }

let memory = read(KEY);
export const getStudent = () => memory;
export function setStudent(student) { memory = student; write(KEY, student); }
const TOKEN = 'ps02.token';
const ROLE = 'ps02.role';
let token = read(TOKEN), role = read(ROLE);
export const getToken = () => token;
export const getRole = () => role;   // 'student' | 'teacher' | null
/** After a login: keep the token and role, and the student's profile when it is a student. */
export function setSession({ token: t, role: r, student }) {
  token = t; role = r; write(TOKEN, t); write(ROLE, r);
  if (student) setStudent({ id: student.id, name: student.name, demo: Boolean(student.is_demo) }); else clearStudent();
}
export function clearSession() {
  token = null; role = null;
  try { localStorage.removeItem(TOKEN); localStorage.removeItem(ROLE); } catch { /* ignore */ }
  clearStudent();
}
export function clearStudent() { memory = null; try { localStorage.removeItem(KEY); } catch { /* ignore */ } }

/** 'hinglish' | 'english' | 'hindi': feedback text (Hindi shows Hinglish) and the microphone language. */
export const getLang = () => read(LANG) || 'hinglish';
export const setLang = (lang) => { write(LANG, lang); globalThis.dispatchEvent?.(new CustomEvent('ps02:lang', { detail: lang })); };
