// The chosen student and language live in localStorage (wrapped: it can throw in private windows).
const KEY = 'ps02.student';
const LANG = 'ps02.lang';

function read(key) { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; } }
function write(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* ignore */ } }

let memory = read(KEY);
export const getStudent = () => memory;
export function setStudent(student) { memory = student; write(KEY, student); }
export function clearStudent() { memory = null; try { localStorage.removeItem(KEY); } catch { /* ignore */ } }

/** 'hinglish' | 'english' | 'hindi': feedback text (Hindi shows Hinglish) and the microphone language. */
export const getLang = () => read(LANG) || 'hinglish';
export const setLang = (lang) => write(LANG, lang);
