// Hands-free helpers for Practice's voice mode. Speech recognition is the browser's own (Chrome / Edge); nothing is sent to our server.
import { createDictation } from '../lib/dictation.js';
import { available as ttsAvailable } from './tts.js';

const Recognition = () => globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition;

/** Voice mode needs both a microphone recogniser and a voice to speak with. */
export const voiceSupported = () => Boolean(Recognition()) && ttsAvailable();

/** Listen for one utterance. Resolves with the transcript, or '' if nothing was heard / the mic is blocked. */
export function listenOnce({ language = 'hinglish', timeoutMs = 10000, onInterim } = {}) {
  return new Promise((resolve) => {
    let last = '', finished = false, timer = null;
    const finish = (text) => {
      if (finished) return;
      finished = true; clearTimeout(timer);
      try { dictation.stop(); } catch { /* already stopped */ }
      resolve((text || '').trim());
    };
    const dictation = createDictation({
      getLanguage: () => language,
      onText: (value, final) => { last = value; onInterim?.(value); if (final) finish(value); },
      onState: (state) => { if (state === 'idle' || state === 'error') finish(last); },
    });
    if (!dictation.available()) { resolve(''); return; }
    timer = setTimeout(() => finish(last), timeoutMs);
    dictation.start('');
  });
}

const VOICE_KEY = 'ps02.voice';
export const readVoiceMode = () => { try { return localStorage.getItem(VOICE_KEY) === '1' && voiceSupported(); } catch { return false; } };
export const writeVoiceMode = (on) => { try { localStorage.setItem(VOICE_KEY, on ? '1' : '0'); } catch { /* ignore */ } };
