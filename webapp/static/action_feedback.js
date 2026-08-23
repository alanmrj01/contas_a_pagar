(() => {
  'use strict';

  const NEXT_MESSAGE_KEY = 'contas-a-pagar-action-feedback';
  const TYPES = new Set(['info', 'progress', 'success', 'error', 'neutral']);

  function create() {
    const region = document.createElement('div');
    region.className = 'actionFeedbackRegion';
    region.setAttribute('aria-live', 'polite');
    region.setAttribute('aria-atomic', 'false');
    document.body.appendChild(region);
    const active = new Map();
    let sequence = 0;

    function remove(key, item) {
      if (active.get(key) !== item) return;
      active.delete(key);
      item.node.classList.remove('isVisible');
      window.setTimeout(() => item.node.remove(), 180);
    }

    function notify(message, type = 'info', key = '', duration = null) {
      const text = String(message || '').trim();
      if (!text) return;
      const safeType = TYPES.has(type) ? type : 'info';
      const safeKey = key || `message-${++sequence}`;
      let item = active.get(safeKey);
      if (!item) {
        const node = document.createElement('div');
        const icon = document.createElement('span');
        const content = document.createElement('span');
        icon.className = 'actionFeedbackIcon';
        icon.setAttribute('aria-hidden', 'true');
        content.className = 'actionFeedbackText';
        node.append(icon, content);
        region.appendChild(node);
        item = {node, icon, content, timer: 0};
        active.set(safeKey, item);
        window.requestAnimationFrame(() => node.classList.add('isVisible'));
      }
      if (item.timer) window.clearTimeout(item.timer);
      item.node.className = `actionFeedback actionFeedback--${safeType} isVisible`;
      item.node.setAttribute('role', safeType === 'error' ? 'alert' : 'status');
      item.content.textContent = text;
      item.icon.textContent = safeType === 'success' ? '✓' : safeType === 'error' ? '!' : safeType === 'neutral' ? '–' : 'i';
      const timeout = duration === null
        ? (safeType === 'progress' ? 0 : safeType === 'error' ? 7000 : 4200)
        : Math.max(0, Number(duration) || 0);
      if (timeout) item.timer = window.setTimeout(() => remove(safeKey, item), timeout);
    }

    function next(message, type = 'success') {
      try {
        sessionStorage.setItem(NEXT_MESSAGE_KEY, JSON.stringify({message:String(message || ''), type:TYPES.has(type) ? type : 'success'}));
      } catch (_) {}
    }

    try {
      const stored = JSON.parse(sessionStorage.getItem(NEXT_MESSAGE_KEY) || 'null');
      sessionStorage.removeItem(NEXT_MESSAGE_KEY);
      if (stored && stored.message) notify(stored.message, stored.type, 'previous-action');
    } catch (_) {
      try { sessionStorage.removeItem(NEXT_MESSAGE_KEY); } catch (_error) {}
    }

    return Object.freeze({
      info: (message, key = '') => notify(message, 'info', key),
      started: (message, key = '') => notify(message, 'progress', key, 0),
      success: (message, key = '') => notify(message, 'success', key),
      error: (message, key = '') => notify(message, 'error', key),
      noChange: (message, key = '') => notify(message, 'neutral', key),
      next,
    });
  }

  window.ActionFeedback = Object.freeze({create});
})();
