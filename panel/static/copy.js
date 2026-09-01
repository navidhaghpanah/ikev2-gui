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


function closeDialog(dialog) {
  if (dialog && dialog.open) dialog.close();
}

document.addEventListener('click', event => {
  const closeButton = event.target.closest('[data-dialog-close]');
  if (closeButton) closeDialog(closeButton.closest('dialog'));

  const toggle = event.target.closest('.password-toggle');
  if (toggle) {
    const input = toggle.parentElement.querySelector('input');
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    toggle.textContent = show ? 'پنهان' : 'نمایش';
    toggle.setAttribute('aria-label', show ? 'پنهان کردن رمز' : 'نمایش رمز');
  }

  const editButton = event.target.closest('.edit-user-button');
  if (editButton) {
    const dialog = document.getElementById('edit-user-dialog');
    document.getElementById('edit-user-name').value = editButton.dataset.user;
    document.getElementById('edit-user-label').textContent = editButton.dataset.user;
    document.getElementById('edit-user-expires').value = editButton.dataset.expires;
    document.getElementById('edit-user-quota').value = editButton.dataset.quota;
    document.getElementById('edit-user-ss').checked = editButton.dataset.ss === '1';
    document.getElementById('edit-user-hy').checked = editButton.dataset.hy === '1';
    document.getElementById('edit-user-vless').checked = editButton.dataset.vless === '1';
    const vmess = document.getElementById('edit-user-vmess');
    const http = document.getElementById('edit-user-http');
    const mtg = document.getElementById('edit-user-mtg');
    if (vmess) vmess.checked = editButton.dataset.vmess === '1';
    if (http) http.checked = editButton.dataset.http === '1';
    if (mtg) mtg.checked = editButton.dataset.mtg === '1';
    dialog.showModal();
  }
});

document.querySelectorAll('dialog').forEach(dialog => {
  dialog.addEventListener('click', event => {
    if (event.target === dialog) closeDialog(dialog);
  });
});

document.addEventListener('submit', event => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;

  if (form.dataset.confirm && form.dataset.confirmed !== 'true') {
    event.preventDefault();
    const dialog = document.getElementById('confirm-dialog');
    document.getElementById('confirm-title').textContent = form.dataset.confirmTitle || 'تأیید عملیات';
    document.getElementById('confirm-message').textContent = form.dataset.confirm;
    dialog.returnValue = '';
    dialog.showModal();
    dialog.addEventListener('close', () => {
      if (dialog.returnValue === 'confirm') {
        form.dataset.confirmed = 'true';
        form.requestSubmit();
      }
    }, {once: true});
    return;
  }

  const submitter = event.submitter || form.querySelector('[type="submit"]');
  if (!submitter) return;
  submitter.disabled = true;
  submitter.classList.add('is-loading');
  submitter.dataset.originalText = submitter.textContent;
  submitter.textContent = 'در حال انجام…';
  form.setAttribute('aria-busy', 'true');
});

window.addEventListener('pageshow', () => {
  document.querySelectorAll('form[aria-busy="true"]').forEach(form => {
    form.removeAttribute('aria-busy');
    const button = form.querySelector('.is-loading');
    if (button) {
      button.disabled = false;
      button.classList.remove('is-loading');
      button.textContent = button.dataset.originalText || button.textContent;
    }
  });
});
