// All backend calls. Fetches never go to a third party; the backend holds the keys.
import { API_BASE } from '../lib/config.js';
import { deepMath } from './math-text.js';

/** The message in an error body. This app's handler answers {"error": "...", "code": "..."}; plain FastAPI answers {"detail": "..."}. */
export function errorText(body) {
  const v = body?.error ?? body?.detail ?? body?.message ?? '';
  return typeof v === 'string' ? v : '';
}

/** A 404 from ANY endpoint whose message is about the student ("Student not found") means the saved student no longer exists on the server
 *  (database reset): tell the app to forget it and start over. A 404 about anything else (an expired question, a missing note, a route that does not
 *  exist) is NOT that, even when the request carried the student's id. */
export function maybeStudentGone(status, message, path, body) {
  if (status !== 404) return false;
  const gone = /student/i.test(message || '');
  if (gone) globalThis.dispatchEvent?.(new CustomEvent('ps02:student-gone'));
  return gone;
}

export class ApiError extends Error {
  constructor(message, status = 0) { super(message); this.status = status; }
}

export async function api(path, { method = 'GET', body, timeout = 45000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(API_BASE + path, {
      method, signal: controller.signal,
      headers: body ? { 'content-type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let detail = '';
      try { detail = errorText(await res.json()); } catch { /* not json */ }
      maybeStudentGone(res.status, detail, path, body);
      throw new ApiError(detail || `The server answered ${res.status}.`, res.status);
    }
    return deepMath(await res.json());   // AI text may contain LaTeX: show it as plain readable maths
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err.name === 'AbortError') throw new ApiError('This is taking longer than usual. The free server may be waking up; please try again.');
    throw new ApiError('Could not reach the server. Check your connection and try again.');
  } finally {
    clearTimeout(timer);
  }
}

/** Wake the (free-tier) backend as soon as the page loads; calls onSlow() if it has not answered after `slowMs`. */
export async function warmUp(onSlow, onReady, slowMs = 2500) {
  const timer = setTimeout(onSlow, slowMs);
  try { await api('/api/health', { timeout: 90000 }); } catch { /* the first real call reports the problem */ }
  clearTimeout(timer);
  onReady();
}

/** multipart upload (notes). No JSON header: the browser sets the boundary. */
export async function apiUpload(path, formData, { timeout = 120000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(API_BASE + path, { method: 'POST', body: formData, signal: controller.signal });
    if (!res.ok) {
      let detail = '';
      try { detail = errorText(await res.json()); } catch { /* not json */ }
      maybeStudentGone(res.status, detail, path, { student_id: formData.get?.('student_id') });
      throw new ApiError(detail || `The upload failed (${res.status}).`, res.status);
    }
    return deepMath(await res.json());
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(err.name === 'AbortError' ? 'The upload took too long. Try a smaller file.' : 'Could not reach the server.');
  } finally { clearTimeout(timer); }
}

/** POST and read a newline-delimited JSON stream, calling onEvent for each event as it arrives. Throws ApiError on an {type:'error'} event. */
export async function apiStream(path, body, onEvent, { timeout = 60000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(API_BASE + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), signal: controller.signal });
    if (!res.ok) {
      let detail = '';
      try { detail = errorText(await res.json()); } catch { /* not json */ }
      maybeStudentGone(res.status, detail, path, body);
      throw new ApiError(detail || `The server answered ${res.status}.`, res.status);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const emit = (line) => { if (!line.trim()) return; const ev = deepMath(JSON.parse(line)); if (ev.type === 'error') throw new ApiError(ev.message || 'Something went wrong.'); onEvent(ev); };
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buffer.indexOf('\n')) >= 0) { emit(buffer.slice(0, nl)); buffer = buffer.slice(nl + 1); }
    }
    emit(buffer);
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(err.name === 'AbortError' ? 'This is taking longer than usual. Please try again.' : 'Could not reach the server. Check your connection and try again.');
  } finally { clearTimeout(timer); }
}

export const qs = (params) => new URLSearchParams(params).toString();
