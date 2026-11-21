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

export const qs = (params) => new URLSearchParams(params).toString();
