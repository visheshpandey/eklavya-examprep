// Text-to-speech (the browser's own voices) shared by the Socratic dialogue, Ask a doubt and Practice voice mode.
// Hindi voice for Hinglish/Hindi, Indian English otherwise. One mute switch for everything.
const MUTE_KEY = 'ps02.mute';

export const isMuted = () => { try { return localStorage.getItem(MUTE_KEY) === '1'; } catch { return false; } };
export function setMuted(value) {
  try { localStorage.setItem(MUTE_KEY, value ? '1' : '0'); } catch { /* ignore */ }
  if (value) stop();
}

export const available = () => Boolean(globalThis.speechSynthesis);

export function stop() { try { globalThis.speechSynthesis?.cancel(); } catch { /* ignore */ } }

/** Speak `text`. Resolves when it finishes (or straight away if muted/unsupported), so callers can chain "then listen". */
export function speak(text, language = 'hinglish', { force = false, rate = 0.95 } = {}) {
  return new Promise((resolve) => {
    const synth = globalThis.speechSynthesis;
    if (!synth || !text || (!force && isMuted())) { resolve(); return; }
    synth.cancel();
    const u = new SpeechSynthesisUtterance(String(text).replace(/\s+/g, ' ').trim());
    u.lang = language === 'english' ? 'en-IN' : 'hi-IN';
    u.rate = rate;
    const done = () => resolve();
    u.onend = done; u.onerror = done;
    // a safety net: some browsers never fire onend for long text
    setTimeout(done, Math.min(60000, 1500 + text.length * 90));
    synth.speak(u);
  });
}
