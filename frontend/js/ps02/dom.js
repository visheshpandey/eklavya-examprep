// Tiny DOM helpers. Everything is built with textContent / createElement, never innerHTML, so API text can't inject markup.
const SVG_NS = 'http://www.w3.org/2000/svg';

function apply(node, props) {
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') node.setAttribute('class', value);
    else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'text') node.textContent = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
}

function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** h('button', {class: 'btn', onClick}, 'Label', childNode) */
export function h(tag, props, ...children) {
  return append((() => { const n = document.createElement(tag); apply(n, props); return n; })(), children);
}

export function s(tag, props, ...children) {
  const n = document.createElementNS(SVG_NS, tag);
  apply(n, props);
  return append(n, children);
}

export const clear = (node) => node.replaceChildren();

// Screens write `cond && h(...)`. The native replaceChildren would print "false" for a falsy child, so drop those (and flatten arrays).
const nativeReplace = Element.prototype.replaceChildren;
Element.prototype.replaceChildren = function replaceChildren(...kids) {
  return nativeReplace.apply(this, kids.flat(Infinity).filter((k) => k != null && k !== false));
};
