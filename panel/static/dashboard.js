'use strict';

const fa = value => String(value).replace(/\d/g, digit => '۰۱۲۳۴۵۶۷۸۹'[digit]);

function renderOnline(container, names) {
  if (!container) return;
  container.replaceChildren();
  if (!names.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state compact';
    empty.textContent = 'کسی آنلاین نیست.';
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
    document.getElementById('stat-online').textContent = fa(data.online_count);
    document.getElementById('stat-sessions').textContent = fa(data.sessions.length);
    document.getElementById('stat-cpu').textContent = `${fa(data.cpu)}٪`;
    document.getElementById('stat-ram').textContent = `${fa(data.mem_pct)}٪`;
    document.getElementById('bar-cpu').style.width = `${data.cpu}%`;
    document.getElementById('bar-ram').style.width = `${data.mem_pct}%`;
    document.getElementById('clock').textContent = data.now_fa;
    document.getElementById('net-down-speed').textContent = data.net_down_h;
    document.getElementById('net-up-speed').textContent = data.net_up_h;
    document.getElementById('net-rx-total').textContent = data.net_rx_h;
    document.getElementById('net-tx-total').textContent = data.net_tx_h;
    renderOnline(document.getElementById('online-list'), data.online);
    if (liveBadge) {
      liveBadge.classList.remove('stale');
      liveBadge.innerHTML = '<i></i> سرویس آنلاین';
      liveBadge.title = '';
    }
  } catch (_) {
    if (liveBadge) {
      liveBadge.classList.add('stale');
      liveBadge.innerHTML = '<i></i> اطلاعات قدیمی';
      liveBadge.title = 'دریافت اطلاعات تازه ناموفق بود؛ آخرین اطلاعات موفق نمایش داده می‌شود.';
    }
  }
}

refreshDashboard();
window.setInterval(refreshDashboard, 5000);
