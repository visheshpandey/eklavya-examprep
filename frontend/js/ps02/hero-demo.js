// The landing hero: a looping storyboard of the product's core idea:
//   wrong answer -> say why (voice) -> misconception caught -> talk it out -> resolved.
// Pure CSS animation driven by one data attribute. It pauses off-screen, when the tab is hidden, and on request (WCAG 2.2.2).
// With prefers-reduced-motion it renders as a static, readable four-step storyboard instead of looping.
import { h } from './dom.js';

const SCENES = [
  { label: 'Answer', ms: 3400 },
  { label: 'Say why', ms: 3800 },
  { label: 'Caught', ms: 3800 },
  { label: 'Talk it out', ms: 6200 },
];

const reduced = () => Boolean(globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches);

function scenes() {
  return [
    h('div', { class: 'demo-scene s-answer' },
      h('p', { class: 'demo-tag' }, 'Charge & current · Easier'),
      h('p', { class: 'demo-q' }, '2 A flows into a bulb. What does an ammeter read just after the bulb?'),
      h('div', { class: 'demo-opts' },
        h('div', { class: 'demo-opt' }, h('i', null, 'A'), '2 A'),
        h('div', { class: 'demo-opt pick-wrong' }, h('i', null, 'B'), 'Less than 2 A'),
        h('div', { class: 'demo-opt' }, h('i', null, 'C'), '0 A')),
      h('p', { class: 'demo-result' }, 'Not quite. Tell me why you picked B.')),
    h('div', { class: 'demo-scene s-say' },
      h('p', { class: 'demo-tag' }, 'Explain your thinking · any language'),
      h('div', { class: 'demo-mic' }, h('span', { class: 'demo-wave' }, Array.from({ length: 9 }, (_, i) => h('i', { style: { animationDelay: `${i * 80}ms` } }))), h('b', null, 'Listening…')),
      h('p', { class: 'demo-typed' }, h('span', null, '“bulb mein current kha jaata hai, isliye kam bachta hai”')),
      h('p', { class: 'muted small' }, 'Hindi · English · Hinglish')),
    h('div', { class: 'demo-scene s-caught' },
      h('p', { class: 'demo-tag demo-tag-bad' }, 'Misconception caught · Confidence: High'),
      h('p', { class: 'demo-big' }, 'Current gets used up'),
      h('p', { class: 'demo-quote' }, '“bulb mein current kha jaata hai”'),
      h('div', { class: 'demo-mastery' }, h('span', null, 'Charge & current'), h('b', { class: 'down' }, '42% → 35% ▼'), h('span', { class: 'demo-bar' }, h('i', null))),
      h('p', { class: 'muted small' }, 'Named from your words, not just your wrong option.')),
    h('div', { class: 'demo-scene s-talk' },
      h('p', { class: 'demo-tag' }, 'Talk it through · Eklavya won’t just tell you'),
      h('div', { class: 'demo-chat' },
        h('p', { class: 'dm tutor' }, 'If the bulb used up current, two ammeters would disagree. What would each show?'),
        h('p', { class: 'dm student' }, 'Charge toh khatam nahi hota, to dono same dikhayenge!'),
        h('p', { class: 'dm tutor' }, 'Exactly. So what does the bulb use?')),
      h('div', { class: 'demo-track' }, h('span', { class: 'demo-fill' }), h('span', { class: 'demo-marker' })),
      h('div', { class: 'demo-steps' }, h('span', null, 'Holds it'), h('span', null, 'Wavering'), h('span', null, 'Resolved')),
      h('p', { class: 'demo-win' }, '✓ Fixed by you · ', h('b', { class: 'up' }, '35% → 58% ▲'))),
  ];
}

export function heroDemo() {
  const list = scenes();
  const screen = h('div', { class: 'demo-screen' }, list);
  const dots = SCENES.map((s, i) => h('button', { class: 'demo-dot', type: 'button', 'aria-label': `Show step ${i + 1}: ${s.label}`, onClick: () => { go(i); } }, h('span', null, `${i + 1}`), s.label));
  const pauseBtn = h('button', { class: 'demo-pause', type: 'button', 'aria-pressed': 'false', 'aria-label': 'Pause the animation', onClick: () => setPaused(!paused, true) }, 'Pause');
  const root = h('figure', { class: 'demo', 'aria-label': 'Animated example of how Eklavya works' },
    h('div', { class: 'demo-top' }, h('div', { class: 'demo-dots' }, dots), pauseBtn), screen,
    h('figcaption', { class: 'visually-hidden' }, 'A student picks a wrong answer, says why by voice, Eklavya names the misconception, they talk it through, and the student fixes it themselves, raising their mastery.'));

  let index = 0, timer = null, paused = false, userPaused = false, visible = true;
  const static_ = reduced();

  function show(i) {
    index = i;
    list.forEach((el, k) => el.classList.toggle('on', k === i));
    dots.forEach((d, k) => { d.classList.toggle('active', k === i); d.setAttribute('aria-current', k === i ? 'step' : 'false'); });
  }
  function schedule() {
    clearTimeout(timer);
    if (paused || !visible || static_) return;
    timer = setTimeout(() => { show((index + 1) % SCENES.length); schedule(); }, SCENES[index].ms);
  }
  function go(i) { show(i); schedule(); }
  function setPaused(value, byUser = false) {
    paused = value; if (byUser) userPaused = value;
    pauseBtn.setAttribute('aria-pressed', String(value)); pauseBtn.textContent = value ? 'Play' : 'Pause'; pauseBtn.setAttribute('aria-label', value ? 'Play the animation' : 'Pause the animation');
    if (!value) schedule(); else clearTimeout(timer);
  }

  if (static_) {            // reduced motion: all four steps, no loop
    root.classList.add('demo-static');
    list.forEach((el) => el.classList.add('on'));
    pauseBtn.hidden = true; dots.forEach((d) => { d.hidden = true; });
  } else {
    show(0); schedule();
    if ('IntersectionObserver' in globalThis) {
      new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible && !userPaused) schedule(); else clearTimeout(timer); }, { threshold: 0.25 }).observe(root);
    }
    document.addEventListener('visibilitychange', () => { visible = !document.hidden; if (visible && !userPaused) schedule(); else clearTimeout(timer); });
  }
  return root;
}
