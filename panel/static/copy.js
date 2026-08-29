'use strict';

function copyValue(el) {
  const value = 'value' in el && el.tagName === 'INPUT' ? el.value : el.textContent.trim();
  const done = () => flashCopied(el);
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(value).then(done).catch(() => fallbackCopy(el, value, done));
  } else {
    fallbackCopy(el, value, done);
  }
}

function fallbackCopy(el, value, done) {
  const ta = document.createElement('textarea');
  ta.value = value;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.append(ta);
  ta.select();
  try {
    document.execCommand('copy');
  } catch (_) {
    // Nothing more we can do without clipboard access.
  }
  ta.remove();
  done();
}

function flashCopied(el) {
  el.classList.add('copied-flash');
  setTimeout(() => el.classList.remove('copied-flash'), 500);
  const rect = el.getBoundingClientRect();
  const badge = document.createElement('span');
  badge.className = 'copied-badge';
  badge.textContent = 'کپی شد ✓';
  document.body.append(badge);
  badge.style.left = Math.round(rect.left + rect.width / 2) + 'px';
  badge.style.top = Math.round(rect.top) + 'px';
  requestAnimationFrame(() => badge.classList.add('show'));
  setTimeout(() => {
    badge.classList.remove('show');
    setTimeout(() => badge.remove(), 200);
  }, 1100);
}

document.addEventListener('click', event => {
  const el = event.target.closest('.copyable');
  if (!el) return;
  event.preventDefault();
  if (el.tagName === 'INPUT') el.select();
  copyValue(el);
});
