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
      liveBadge.replaceChildren();
      const mark = document.createElement('i');
      liveBadge.append(mark, document.createTextNode(' ' + (document.body.getAttribute('data-live') || 'online')));
      liveBadge.title = '';
    }
  } catch (_) {
    if (liveBadge) {
      liveBadge.classList.add('stale');
      liveBadge.replaceChildren();
      const mark = document.createElement('i');
      liveBadge.append(mark, document.createTextNode(' ' + (document.body.getAttribute('data-stale') || 'stale')));
      liveBadge.title = '';
    }
  }
}

refreshDashboard();
window.setInterval(refreshDashboard, 5000);



function csrfFrom(form) {
  const input = form && form.querySelector('input[name="csrf_token"]');
  return input ? input.value : '';
}

function fillSpeedLine(data) {
  const line = document.getElementById('speed-line');
  if (!line) return;
  const fail = line.getAttribute('data-fail') || 'failed';
  const mbps = line.getAttribute('data-mbps') || 'Mbps';
  const startL = line.getAttribute('data-start') || 'start';
  const endL = line.getAttribute('data-end') || 'end';
  if (!data || !data.ok) {
    line.textContent = fail;
    return;
  }
  const down = data.down_mbps == null ? '—' : data.down_mbps;
  const up = data.up_mbps == null ? '—' : data.up_mbps;
  const started = data.started || data.at || '—';
  const ended = data.ended || data.at || '—';
  line.textContent = '↓ ' + down + ' ' + mbps + ' · ↑ ' + up + ' ' + mbps + ' · ' + startL + ' ' + started + ' → ' + endL + ' ' + ended;
}

const speedForm = document.getElementById('speed-form');
if (speedForm) {
  speedForm.addEventListener('submit', async event => {
    event.preventDefault();
    const btn = document.getElementById('speed-run');
    const line = document.getElementById('speed-line');
    const running = (line && line.getAttribute('data-running')) || 'Testing…';
    if (btn) btn.disabled = true;
    if (line) line.textContent = running;
    try {
      const body = new URLSearchParams();
      body.set('csrf_token', csrfFrom(speedForm));
      const response = await fetch('/api/speedtest', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': csrfFrom(speedForm),
        },
        body,
      });
      const data = await response.json().catch(() => ({}));
      fillSpeedLine(data);
    } catch (_) {
      fillSpeedLine(null);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = speedForm.getAttribute('data-run') || btn.textContent;
      }
    }
  });
}
