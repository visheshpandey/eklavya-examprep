// All backend calls. Fetches never go to a third party; the backend holds the keys.
import { API_BASE } from '../lib/config.js';

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
      try { const j = await res.json(); detail = j.detail || j.message || ''; } catch { /* not json */ }
      if (res.status === 404 && /student not found/i.test(String(detail))) globalThis.dispatchEvent(new CustomEvent('ps02:student-gone'));   // a stale saved student: start over
      throw new ApiError(typeof detail === 'string' && detail ? detail : `The server answered ${res.status}.`, res.status);
    }
    return await res.json();
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
      try { const j = await res.json(); detail = j.detail || j.error || j.message || ''; } catch { /* not json */ }
      throw new ApiError(typeof detail === 'string' && detail ? detail : `The upload failed (${res.status}).`, res.status);
    }
    return await res.json();
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
      try { const j = await res.json(); detail = j.detail || j.message || ''; } catch { /* not json */ }
      if (res.status === 404 && /student not found/i.test(String(detail))) globalThis.dispatchEvent(new CustomEvent('ps02:student-gone'));
      throw new ApiError(typeof detail === 'string' && detail ? detail : `The server answered ${res.status}.`, res.status);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const emit = (line) => { if (!line.trim()) return; const ev = JSON.parse(line); if (ev.type === 'error') throw new ApiError(ev.message || 'Something went wrong.'); onEvent(ev); };
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
