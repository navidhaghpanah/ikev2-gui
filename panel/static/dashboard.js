'use strict';

const LANG = document.documentElement.lang || 'fa';
const faDigits = value => String(value).replace(/\d/g, digit => '۰۱۲۳۴۵۶۷۸۹'[digit]);
const fmt = value => (LANG === 'fa' ? faDigits(value) : String(value));
const pct = value => (LANG === 'fa' ? `${fmt(value)}٪` : `${fmt(value)}%`);

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderOnline(container, names) {
  if (!container) return;
  container.replaceChildren();
  if (!names.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state compact';
    empty.textContent = document.body.getAttribute('data-nobody') || (LANG === 'fa' ? 'کسی آنلاین نیست.' : 'Nobody is online.');
    container.append(empty);
    return;
  }
  for (const name of names) {
    const person = document.createElement('span');
    person.className = 'online-user';
    const dot = document.createElement('span');
    dot.className = 'online-dot';
    person.append(dot, document.createTextNode(name));
    container.append(person);
  }
}

async function refreshDashboard() {
  const liveBadge = document.querySelector('.topbar .live-badge');
  try {
    const response = await fetch('/api/status', {credentials: 'same-origin'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    setText('stat-online', fmt(data.online_count));
    setText('stat-sessions', fmt(data.sessions.length));
    setText('stat-cpu', pct(data.cpu));
    setText('stat-ram', pct(data.mem_pct));
    setText('top-cpu', pct(data.cpu));
    setText('top-ram', pct(data.mem_pct));
    const barCpu = document.getElementById('bar-cpu');
    const barRam = document.getElementById('bar-ram');
    if (barCpu) barCpu.style.width = `${data.cpu}%`;
    if (barRam) barRam.style.width = `${data.mem_pct}%`;
    setText('clock', LANG === 'fa' ? data.now_fa : (data.now || data.now_fa));
    setText('net-down-speed', data.net_down_h);
    setText('net-up-speed', data.net_up_h);
    setText('net-rx-total', data.net_rx_h);
    setText('net-tx-total', data.net_tx_h);
    renderOnline(document.getElementById('online-list'), data.online);
    if (liveBadge) {
      liveBadge.classList.remove('stale');
      liveBadge.innerHTML = '<i></i> ' + (document.body.getAttribute('data-live') || 'online');
      liveBadge.title = '';
    }
  } catch (_) {
    if (liveBadge) {
      liveBadge.classList.add('stale');
      liveBadge.innerHTML = '<i></i> ' + (document.body.getAttribute('data-stale') || 'stale');
      liveBadge.title = '';
    }
  }
}

refreshDashboard();
window.setInterval(refreshDashboard, 5000);
