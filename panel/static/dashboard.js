'use strict';

const fa = value => String(value).replace(/\d/g, digit => '۰۱۲۳۴۵۶۷۸۹'[digit]);

function renderOnline(container, names) {
  container.replaceChildren();
  if (!names.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'الان کسی وصل نیست.';
    container.append(empty);
    return;
  }
  for (const name of names) {
    const person = document.createElement('span');
    person.className = 'person';
    const dot = document.createElement('span');
    dot.className = 'dot on';
    person.append(dot, document.createTextNode(name));
    container.append(person);
  }
}

async function refreshDashboard() {
  try {
    const response = await fetch('/api/status', {credentials: 'same-origin'});
    if (!response.ok) return;
    const data = await response.json();
    document.getElementById('stat-online').textContent = fa(data.online_count);
    document.getElementById('stat-cpu').textContent = `${fa(data.cpu)}٪`;
    document.getElementById('stat-ram').textContent = `${fa(data.mem_pct)}٪`;
    document.getElementById('bar-cpu').style.width = `${data.cpu}%`;
    document.getElementById('bar-ram').style.width = `${data.mem_pct}%`;
    document.getElementById('clock').textContent = data.now_fa;
    renderOnline(document.getElementById('online-list'), data.online);
  } catch (_) {
    // Keep the last successful snapshot visible during transient failures.
  }
}

window.setInterval(refreshDashboard, 5000);
