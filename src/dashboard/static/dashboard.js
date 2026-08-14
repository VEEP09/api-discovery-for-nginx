/* ── 상태 ──────────────────────────────────────────── */
const state = {
  activeTab: 'overview',
  inventory: {
    sort: 'call_count', order: 'desc',
    search: '', method: '', domain: '', auth: '', status: '',
    minCalls: 0, minRtMs: 0,
    page: 1, perPage: 25,
    data: [], shadowSet: new Set(), hasSpec: false,
    selected: new Set(),         // "METHOD\u0000/path" 키
    addedSet: new Set(),         // 이번 세션에서 스펙에 추가 완료된 키
    expandedKey: null,           // Try-it-out으로 펼쳐진 행의 키 (단일 펼침)
    tryDraft: {},                // 펼쳐진 행의 폼 입력 임시 저장 (key별)
  },
  flow: {
    search: '', method: '', domain: '', auth: '', status: '',
    minCalls: 0, minRtMs: 0,
    data: [], shadowSet: new Set(), hasSpec: false,
  },
  charts: {},
};

/* ── 유틸 ─────────────────────────────────────────── */
const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];
const fmt = n => n == null ? '-' : Number(n).toLocaleString();
const fmtMs = n => n == null ? '-' : (n * 1000).toFixed(1) + ' ms';
const fmtPct = n => n == null ? '-' : n.toFixed(1) + '%';
const esc = str => String(str ?? '')
  .replace(/&/g,'&amp;')
  .replace(/</g,'&lt;')
  .replace(/>/g,'&gt;')
  .replace(/"/g,'&quot;')
  .replace(/'/g,'&#39;');

const METHOD_COLORS = { GET:'#00c04b', POST:'#63b3ed', PUT:'#f6ad55', DELETE:'#fc8181', PATCH:'#b794f4' };
const STATUS_COLORS = { '2xx':'#00c04b', '3xx':'#63b3ed', '4xx':'#f6ad55', '5xx':'#fc8181' };

// scheme별 기본 포트
const defaultPort = scheme => (scheme === 'http' ? 80 : 443);
// 기본 포트면 URL에 표기 안 함(브라우저 관례), 커스텀 포트만 :n 붙임
const portSuffix = (scheme, port) => {
  const p = parseInt(port, 10);
  return (p && p !== defaultPort(scheme)) ? `:${p}` : '';
};

/* ── help-tip 툴팁 (body 포탈 + 뷰포트 clamp) ─────────
   CSS ::after 방식은 stat-card 등 overflow:hidden 컨테이너 안에서
   잘리거나 아예 안 보였다. body에 fixed 요소로 띄워 잘림을 없앤다. */
(function initHelpTips() {
  let pop = null;
  const MARGIN = 8;

  function ensurePop() {
    if (!pop) {
      pop = document.createElement('div');
      pop.className = 'help-pop';
      document.body.appendChild(pop);
    }
    return pop;
  }

  function show(el) {
    const tip = el.getAttribute('data-tip');
    if (!tip) return;
    const p = ensurePop();
    p.textContent = tip;
    // 화면 밖에서 크기 측정 후 위치 확정 (한 프레임 깜빡임 방지)
    p.style.left = '-9999px';
    p.style.top = '0px';
    p.classList.add('show');

    const r = el.getBoundingClientRect();
    const pr = p.getBoundingClientRect();

    let left = r.left + r.width / 2 - pr.width / 2;
    left = Math.max(MARGIN, Math.min(left, window.innerWidth - pr.width - MARGIN));

    let top = r.bottom + MARGIN;                       // 기본: 배지 아래
    if (top + pr.height > window.innerHeight - MARGIN) {
      top = r.top - pr.height - MARGIN;                // 아래 공간 부족 → 위로
    }
    top = Math.max(MARGIN, top);

    p.style.left = left + 'px';
    p.style.top = top + 'px';
  }

  function hide() { if (pop) pop.classList.remove('show'); }

  function closestTip(t) { return t && t.closest ? t.closest('.help-tip') : null; }

  document.addEventListener('mouseover', e => { const el = closestTip(e.target); if (el) show(el); });
  document.addEventListener('mouseout',  e => { if (closestTip(e.target)) hide(); });
  document.addEventListener('focusin',   e => { const el = closestTip(e.target); if (el) show(el); });
  document.addEventListener('focusout',  hide);
  window.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
})();

/* ── 테마(다크/라이트) ───────────────────────────── */
function toggleTheme() {
  const root = document.documentElement;
  const next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  if (next === 'light') root.setAttribute('data-theme', 'light');
  else root.removeAttribute('data-theme');
  try { localStorage.setItem('theme', next); } catch (e) {}
}

/* ── 탭 ───────────────────────────────────────────── */
function initTabs() {
  $$('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      state.activeTab = btn.dataset.tab;
      $$('.tab-btn').forEach(b => b.classList.toggle('active', b === btn));
      $$('.tab-pane').forEach(p => {
        p.style.display = p.id === `tab-${state.activeTab}` ? '' : 'none';
        p.classList.toggle('active', p.id === `tab-${state.activeTab}`);
      });
      if (state.activeTab === 'endpoints') loadInventory();
      if (state.activeTab === 'flow') loadFlow();
      if (state.activeTab === 'anomalies') loadAnomalies();
      if (state.activeTab === 'models') renderModels();
      if (state.activeTab === 'requests') loadRequests();
      if (state.activeTab === 'users') loadUsers();
    });
  });
}


/* ── Summary ──────────────────────────────────────── */
async function loadSummary() {
  const d = await fetch('/api/summary').then(r => r.json());
  bind('stat-endpoints', fmt(d.total_endpoints));
  bind('stat-calls', fmt(d.total_calls));
  bind('stat-no-auth', fmt(d.no_auth_count));
  bind('stat-shadow', fmt(d.shadow_count));
  bind('stat-ips', fmt(d.unique_ips));
  bind('stat-model', d.model_trained ? t('model.trained') : t('model.notTrainedShort'));

  const shadowSub = $('#stat-shadow-sub');
  if (shadowSub) {
    if (d.spec_uploaded) {
      shadowSub.textContent = t('stat.shadowSub', {n: fmt(d.shadow_spec_count)});
      shadowSub.style.color = 'var(--info)';
    } else {
      shadowSub.textContent = t('js.mlDetected');
      shadowSub.style.color = '';
    }
  }
  const modelEl = $('#stat-model');
  if (modelEl) modelEl.style.color = d.model_trained ? 'var(--accent2)' : 'var(--text-muted)';

  const periodEl = $('#data-period-text');
  if (periodEl) {
    if (d.data_from && d.data_to) {
      const fmtDt = iso => {
        const dt = new Date(iso);
        const pad = n => String(n).padStart(2, '0');
        return `${dt.getFullYear()}.${pad(dt.getMonth()+1)}.${pad(dt.getDate())} ${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
      };
      periodEl.textContent = `${fmtDt(d.data_from)} ~ ${fmtDt(d.data_to)}`;
    } else {
      periodEl.textContent = t('js.noData');
    }
  }

  if (_req.fp && d.data_from && d.data_to) {
    _req.fp.set('minDate', new Date(d.data_from));
    _req.fp.set('maxDate', new Date(d.data_to));
  }
}
function bind(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

/* ── Agents ───────────────────────────────────────── */
function _agentLastSeen(iso) {
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 5)    return t('js.justNow');
  if (diff < 60)   return t('js.secAgo', {n: diff});
  if (diff < 3600) return t('js.minAgo', {n: Math.floor(diff / 60)});
  return t('js.hourAgo', {n: Math.floor(diff / 3600)});
}

function _agentStatusLabel(s) {
  return s === 'online' ? t('agent.online') : s === 'offline' ? t('agent.offline') : t('agent.unknown');
}

function _nginxStatusClass(s) {
  if (s === 'active')   return 'active';
  if (s === 'inactive' || s === 'failed') return 'inactive';
  return 'unknown';
}

function _nginxStatusLabel(s) {
  if (s === 'active')   return t('nginx.active');
  if (s === 'inactive') return t('nginx.inactive');
  if (s === 'failed')   return t('nginx.failed');
  return '—';
}

/* NGINX 종류 표기 — plus/oss/그외 */
function _nginxName(edition) {
  if (edition === 'plus') return 'NGINX Plus';
  if (edition === 'oss')  return 'NGINX OSS';
  return 'NGINX';
}

/* ── NGINX Plus Metrics ───────────────────────────────── */
function _fmtUptime(load_ts, cur_ts) {
  try {
    const secs = Math.floor((new Date(cur_ts) - new Date(load_ts)) / 1000);
    if (isNaN(secs) || secs < 0) return '—';
    const d = Math.floor(secs / 86400);
    const h = Math.floor((secs % 86400) / 3600);
    const m = Math.floor((secs % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  } catch { return '—'; }
}

function _npMetric(label, value, sub) {
  const v = value == null ? '—' : Number(value).toLocaleString();
  return `<div class="np-metric">
    <span class="np-metric-val">${v}</span>
    <span class="np-metric-label">${label}</span>
    ${sub ? `<span class="np-metric-sub">${sub}</span>` : ''}
  </div>`;
}

function renderNginxPlus(agents) {
  const section = $('#nginx-plus-section');
  if (!section) return;

  const withData = agents.filter(a => a.nginx_plus && Object.keys(a.nginx_plus).length > 0);
  if (!withData.length) { section.innerHTML = ''; return; }

  section.innerHTML = `
    <div class="np-section">
      <div class="np-section-title">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
        </svg>
        ${t('np.metricsTitle')}
      </div>
      ${withData.map(a => {
        const np   = a.nginx_plus;
        const info = np.nginx         || {};
        const conn = np.connections   || {};
        const http = np.http_requests || {};
        const ssl  = np.ssl           || {};
        const proc = np.processes     || {};

        const uptime  = _fmtUptime(info.load_timestamp, info.timestamp);
        const build   = info.build   ? `<span class="np-build">${esc(info.build)}</span>` : '';
        const version = info.version ? `v${esc(info.version)}` : '';

        const lic     = np.license || {};
        const licBadge = lic.eval != null
          ? `<span class="np-lic-badge ${lic.eval ? 'eval' : 'commercial'}">${lic.eval ? t('np.licEval') : t('np.licCommercial')}</span>`
          : '';
        const licExpiry = lic.active_till
          ? (() => {
              const d = new Date(lic.active_till * 1000);
              const pad = n => String(n).padStart(2,'0');
              const dateStr = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
              const daysLeft = Math.ceil((d - Date.now()) / 86400000);
              const dClass = daysLeft <= 30 ? 'danger' : daysLeft <= 90 ? 'warn' : 'ok';
              const dLabel = daysLeft > 0 ? `D-${daysLeft}` : `D+${Math.abs(daysLeft)} ${t('js.expired')}`;
              return `${dateStr} <span class="np-lic-days ${dClass}">${dLabel}</span>`;
            })()
          : null;
        const reportOk = lic.reporting?.healthy;
        const reportBadge = lic.reporting != null
          ? `<span class="np-report-dot ${reportOk ? 'ok' : 'fail'}"></span><span class="np-report-label">${reportOk ? t('np.reportHealthy') : t('np.reportUnhealthy')}</span>`
          : '';

        return `
        <div class="np-agent-block">
          <div class="np-agent-header">
            <div class="np-agent-title-row">
              <span class="np-agent-name">${esc(a.agent_id)}</span>
              <span class="np-agent-meta">${version} ${build} · ${t('np.uptime', {v: uptime})}</span>
            </div>
            ${(licBadge || licExpiry || reportBadge) ? `
            <div class="np-license-row">
              ${licBadge}
              ${licExpiry ? `<span class="np-lic-expiry">${t('js.expires', {date: licExpiry})}</span>` : ''}
              ${reportBadge}
            </div>` : ''}
          </div>
          <div class="np-metrics-grid">
            <div class="np-group">
              <div class="np-group-title">${t('np.connections')}</div>
              <div class="np-group-metrics">
                ${_npMetric(t('np.active'),   conn.active)}
                ${_npMetric(t('np.idle'),     conn.idle)}
                ${_npMetric(t('np.accepted'), conn.accepted)}
                ${_npMetric(t('np.dropped'),  conn.dropped)}
              </div>
            </div>
            <div class="np-group">
              <div class="np-group-title">${t('np.httpRequests')}</div>
              <div class="np-group-metrics">
                ${_npMetric(t('np.total'),     http.total)}
                ${_npMetric(t('np.inflight'), http.current)}
              </div>
            </div>
            <div class="np-group">
              <div class="np-group-title">${t('np.ssl')}</div>
              <div class="np-group-metrics">
                ${_npMetric(t('np.handshakes'), ssl.handshakes)}
                ${_npMetric(t('np.failed'),     ssl.handshakes_failed)}
                ${_npMetric(t('np.reuses'),     ssl.session_reuses)}
              </div>
            </div>
            <div class="np-group">
              <div class="np-group-title">${t('np.processes')}</div>
              <div class="np-group-metrics">
                ${_npMetric(t('np.respawned'), proc.respawned, proc.respawned > 0 ? t('js.crashes') : '')}
              </div>
            </div>
          </div>
        </div>`;
      }).join('')}
    </div>`;
}

async function refreshAgents() {
  const btn = $('#agents-refresh-btn');
  if (btn) btn.classList.add('spinning');
  await loadAgents();
  if (btn) btn.classList.remove('spinning');
}

async function loadAgents() {
  let agents = [];
  try { agents = await fetch('/api/agents').then(r => r.json()); }
  catch { /* 네트워크 오류 시 빈 배열 유지 */ }

  const section = $('#agents-section');
  const list    = $('#agent-list');
  const countEl = $('#agents-count');
  if (!section || !list) return;

  section.style.display = '';

  if (!agents.length) {
    if (countEl) countEl.textContent = t('js.noAgent');
    list.innerHTML = `
      <div class="agent-empty">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3">
          <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
        </svg>
        <span>${t('js.agentEmpty1')}</span>
        <span>${t('js.agentEmpty2')}</span>
        <span>${t('js.agentEmpty3')}</span>
      </div>`;
    return;
  }

  const online = agents.filter(a => a.status === 'online').length;
  if (countEl) countEl.textContent = t('agents.count', {online: online, total: agents.length});

  list.innerHTML = agents.map(a => `
    <div class="agent-card">
      <div class="agent-card-top">
        <div class="agent-dot ${a.status}"></div>
        <span class="agent-id">${esc(a.agent_id)}</span>
        <span class="agent-badge agent-badge--${a.status}">${_agentStatusLabel(a.status)}</span>
      </div>
      <div class="agent-card-bottom">
        <div class="agent-card-bottom-left">
          <span class="agent-ip">${esc(a.ip)}</span>
          <div class="agent-nginx-wrap">
            <span class="nginx-status-dot nginx-status-dot--${_nginxStatusClass(a.nginx_status || 'unknown')}"></span>
            <span class="nginx-status-label">${esc(_nginxName(a.nginx_edition))} <b>${_nginxStatusLabel(a.nginx_status || 'unknown')}</b></span>
          </div>
        </div>
        <div class="agent-meta">
          <span>${t('agents.rows', {n: fmt(a.total_rows)})}</span>
          <span class="agent-lastseen">${_agentLastSeen(a.last_seen)}</span>
        </div>
      </div>
    </div>
  `).join('');

  renderNginxPlus(agents);
}

/* ── 차트 ─────────────────────────────────────────── */
async function loadCharts() {
  const [top, methods, statuses] = await Promise.all([
    fetch('/api/charts/top-endpoints').then(r => r.json()),
    fetch('/api/charts/method-dist').then(r => r.json()),
    fetch('/api/charts/status-dist').then(r => r.json()),
  ]);
  renderHBar('chart-top', top, d => d.value, d => d.label, '#009639');
  renderDonut('chart-methods', methods, d => d.value, d => d.label,
    methods.map(d => METHOD_COLORS[d.label] || '#718096'));
  renderDonut('chart-status', statuses, d => d.value, d => d.label,
    statuses.map(d => STATUS_COLORS[d.label] || '#718096'));
}

function renderHBar(canvasId, data, valFn, labelFn, color) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  if (state.charts[canvasId]) state.charts[canvasId].destroy();
  state.charts[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.map(labelFn),
      datasets: [{ data: data.map(valFn), backgroundColor: color + 'cc', borderColor: color, borderWidth: 1, borderRadius: 3 }],
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ' ' + fmt(ctx.raw) } } },
      scales: {
        x: { ticks: { color: '#718096', font: { size: 10 } }, grid: { color: '#333844' } },
        y: { ticks: { color: '#a0aec0', font: { size: 10, family: 'JetBrains Mono, monospace' } }, grid: { display: false } },
      },
    },
  });
}

function renderDonut(canvasId, data, valFn, labelFn, colors) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  if (state.charts[canvasId]) state.charts[canvasId].destroy();
  state.charts[canvasId] = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: data.map(labelFn),
      datasets: [{ data: data.map(valFn), backgroundColor: colors.map(c => c + 'cc'), borderColor: '#22262f', borderWidth: 2 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '68%',
      plugins: {
        legend: { position: 'bottom', labels: { color: '#a0aec0', font: { size: 10 }, padding: 10, boxWidth: 10 } },
        tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${fmt(ctx.raw)}` } },
      },
    },
  });
}

function renderLineChart(canvasId, ae, lstm) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  if (state.charts[canvasId]) state.charts[canvasId].destroy();
  const datasets = [];
  if (ae.length) datasets.push(
    { label: t('chart.aeTrain'), data: ae.map(e => ({ x: e.epoch, y: e.train_loss })), borderColor: '#00c04b', backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, tension: 0.3 },
    { label: t('chart.aeVal'),   data: ae.map(e => ({ x: e.epoch, y: e.val_loss })),   borderColor: '#68d391', backgroundColor: 'transparent', borderWidth: 1, borderDash: [4,2], pointRadius: 0, tension: 0.3 }
  );
  if (lstm.length) datasets.push(
    { label: t('chart.lstmTrain'), data: lstm.map(e => ({ x: e.epoch, y: e.train_loss })), borderColor: '#63b3ed', backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, tension: 0.3 },
    { label: t('chart.lstmVal'),   data: lstm.map(e => ({ x: e.epoch, y: e.val_loss })),   borderColor: '#90cdf4', backgroundColor: 'transparent', borderWidth: 1, borderDash: [4,2], pointRadius: 0, tension: 0.3 }
  );
  if (!datasets.length) return;
  state.charts[canvasId] = new Chart(ctx, {
    type: 'line', data: { datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#a0aec0', font: { size: 10 }, padding: 12, boxWidth: 20 } } },
      scales: {
        x: { type: 'linear', ticks: { color: '#718096', font: { size: 10 } }, grid: { color: '#333844' }, title: { display: true, text: t('chart.epoch'), color: '#718096', font: { size: 10 } } },
        y: { ticks: { color: '#718096', font: { size: 10 } }, grid: { color: '#333844' }, title: { display: true, text: t('chart.loss'), color: '#718096', font: { size: 10 } } },
      },
    },
  });
}

/* ── Inventory 테이블 ──────────────────────────────── */
async function loadInventory() {
  const s = state.inventory;
  const url = `/api/inventory?sort=${s.sort}&order=${s.order}`;
  const [data, shadow, specInfo] = await Promise.all([
    fetch(url).then(r => r.json()),
    fetch('/api/anomalies/shadow').then(r => r.json()).catch(() => []),
    fetch('/api/openapi/status').then(r => r.json()).catch(() => ({ uploaded: false })),
  ]);
  s.data = data;
  s.shadowSet = new Set(shadow.map(e => `${e.method}:${e.endpoint}`));
  s.hasSpec = !!specInfo.uploaded;
  populateDomainFilter(data);
  renderTable();
}

function populateDomainFilter(data) {
  const sel = document.getElementById('table-domain');
  if (!sel) return;
  const current = sel.value;
  const domains = new Set();
  data.forEach(e => (e.domains || []).forEach(d => domains.add(d)));
  sel.innerHTML = `<option value="">${t('filter.allDomains')}</option>` +
    [...domains].sort().map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join('');
  sel.value = current;
}

function filterInventory() {
  const s = state.inventory;
  return s.data.filter(e => {
    if (s.method && (e.method || '').toUpperCase() !== s.method.toUpperCase()) return false;
    if (s.search && !(e.endpoint || '').toLowerCase().includes(s.search.toLowerCase())) return false;
    if (s.domain && !(e.domains || []).includes(s.domain)) return false;
    if (s.auth === 'yes' && !e.has_auth) return false;
    if (s.auth === 'no'  &&  e.has_auth) return false;
    if (s.status) {
      const isShadow = s.hasSpec && s.shadowSet.has(`${e.method}:${e.endpoint}`);
      if (s.status === 'managed' && (!s.hasSpec || isShadow)) return false;
      if (s.status === 'shadow'  && (!s.hasSpec || !isShadow)) return false;
    }
    if (s.minCalls > 0 && (e.call_count || 0) < s.minCalls) return false;
    if (s.minRtMs  > 0 && ((e.avg_response_time || 0) * 1000) < s.minRtMs) return false;
    return true;
  });
}

function rowKey(e) { return `${(e.method || '').toUpperCase()} ${e.endpoint || ''}`; }

function renderTable() {
  const s = state.inventory;
  const filtered = filterInventory();
  const total = filtered.length;
  const totalPages = Math.ceil(total / s.perPage);
  s.page = Math.min(s.page, totalPages || 1);
  const slice = filtered.slice((s.page - 1) * s.perPage, s.page * s.perPage);

  const tbody = $('#inventory-tbody');
  if (!tbody) return;
  tbody.innerHTML = slice.map(e => {
    const key = rowKey(e);
    const isShadow = s.hasSpec && s.shadowSet.has(`${e.method}:${e.endpoint}`);
    const isAdded = s.addedSet.has(key);
    const isChecked = s.selected.has(key);
    const isExpanded = s.expandedKey === key;

    let statusBadge;
    if (!s.hasSpec) {
      statusBadge = '<span class="status-badge status-unknown">—</span>';
    } else if (isAdded) {
      statusBadge = `<span class="status-badge status-managed">${t('badge.managedAdded')}</span>`;
    } else if (isShadow) {
      statusBadge = `<span class="status-badge status-shadow">${t('badge.shadow')}</span>`;
    } else {
      statusBadge = `<span class="status-badge status-managed">${t('badge.managed')}</span>`;
    }

    let actionCell;
    if (isAdded) {
      actionCell = `<button class="row-add-btn added" disabled title="${t('js.alreadyAdded')}">${t('btn.added')}</button>`;
    } else if (isShadow) {
      actionCell = `<button class="row-add-btn admin-only" data-row-add="${esc(key)}" title="${t('js.addToSpec')}">${t('btn.addSpec')}</button>`;
    } else if (s.hasSpec) {
      actionCell = '<span class="row-add-na">—</span>';
    } else {
      actionCell = `<span class="row-add-na" title="${t('js.uploadFirst')}">—</span>`;
    }

    const checkable = isShadow && !isAdded;
    const checkboxCell = `<input type="checkbox" data-row-check="${esc(key)}" ${isChecked ? 'checked' : ''} ${checkable ? '' : 'disabled'} title="${checkable ? t('js.select') : (isAdded ? t('js.addedShort') : t('js.inSpec'))}">`;

    const chevron = `<button class="row-expand-btn admin-only ${isExpanded ? 'open' : ''}" data-row-expand="${esc(key)}" title="${t('js.sendRequest')}">${isExpanded ? '▼' : '▶'}</button>`;

    const detailRow = isExpanded
      ? `<tr class="row-detail" data-row-detail="${esc(key)}"><td colspan="14">${renderTryPanel(e, key)}</td></tr>`
      : '';

    return `
    <tr data-row-key="${esc(key)}" class="${isExpanded ? 'row-expanded' : ''}">
      <td class="col-check">${checkboxCell}</td>
      <td><span class="method-badge method-${e.method}">${e.method}</span></td>
      <td class="domain-cell"><div class="domain-stack">${(e.domains || []).map(d => `<span class="domain-badge">${esc(d)}</span>`).join('')}</div></td>
      <td class="endpoint-cell">${chevron}${e.api_version ? `<span class="tag">${e.api_version}</span> ` : ''}${esc(e.endpoint)}</td>
      <td class="num">${fmt(e.call_count)}</td>
      <td class="num">${fmt(e.status_2xx)}</td>
      <td class="num">${fmtMs(e.avg_response_time)}</td>
      <td class="num">${fmtMs(e.p50_response_time)}</td>
      <td class="num">${fmtMs(e.p95_response_time)}</td>
      <td class="num">${fmtMs(e.p99_response_time)}</td>
      <td class="num">${fmt(e.unique_ip_count)}</td>
      <td><span class="auth-badge ${e.has_auth ? 'auth-yes' : 'auth-no'}">${e.has_auth ? (e.auth_types?.join('/') || t('badge.auth')) : t('badge.none')}</span></td>
      <td>${statusBadge}</td>
      <td class="col-action">${actionCell}</td>
    </tr>${detailRow}`;
  }).join('');

  const info = $('#page-info');
  if (info) info.textContent = total
    ? t('page.range', {from: fmt((s.page-1)*s.perPage+1), to: fmt(Math.min(s.page*s.perPage,total)), total: fmt(total)})
    : t('page.empty');
  const prev = $('#page-prev'), next = $('#page-next');
  if (prev) prev.disabled = s.page <= 1;
  if (next) next.disabled = s.page >= totalPages;

  syncCheckAll(slice);
  updateBulkBar();
}

/* ── Try-it-out 패널 ──────────────────────────────── */
function pathParamKey(name, occurrence) {
  return occurrence === 1 ? name : `${name}__${occurrence}`;
}

function pathParamInstances(path) {
  const params = [];
  const counts = {};
  const re = /\{([^}]+)\}/g;
  let m;
  while ((m = re.exec(path || '')) !== null) {
    const name = m[1];
    counts[name] = (counts[name] || 0) + 1;
    const occurrence = counts[name];
    params.push({
      name,
      occurrence,
      key: pathParamKey(name, occurrence),
      label: occurrence === 1 ? name : `${name} #${occurrence}`,
    });
  }
  return params;
}

function escapeRegExp(str) {
  return String(str).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function sampleForDomain(e, domain) {
  const samples = e.sample_requests || {};
  return samples[domain] || e.sample_request || null;
}

function queryRowsFromSample(query) {
  const rows = Object.entries(query || {}).map(([k, v]) => ({
    k,
    v: Array.isArray(v) ? String(v[0] ?? '') : String(v ?? ''),
  }));
  return rows.length ? rows : [{ k: '', v: '' }];
}

function extractPathParamsFromSample(template, samplePath) {
  const params = pathParamInstances(template);
  if (!params.length || !samplePath) return {};

  let source = '^';
  let pos = 0;
  const re = /\{([^}]+)\}/g;
  let m;
  while ((m = re.exec(template || '')) !== null) {
    source += escapeRegExp(String(template).slice(pos, m.index));
    source += '([^/?#]+)';
    pos = re.lastIndex;
  }
  source += escapeRegExp(String(template || '').slice(pos)) + '$';

  const match = new RegExp(source).exec(samplePath);
  if (!match) return {};

  const values = {};
  params.forEach((param, i) => {
    try {
      values[param.key] = decodeURIComponent(match[i + 1] || '');
    } catch (_) {
      values[param.key] = match[i + 1] || '';
    }
  });
  return values;
}

function applySampleRequest(e, draft, overwrite = false) {
  const params = pathParamInstances(e.endpoint);
  const sample = sampleForDomain(e, draft.domain);
  const sampleParams = sample ? extractPathParamsFromSample(e.endpoint, sample.path) : {};

  params.forEach(param => {
    if (draft.pathParams[param.key] == null) draft.pathParams[param.key] = '';
    if (overwrite || !draft.pathParams[param.key]) {
      draft.pathParams[param.key] = sampleParams[param.key] || draft.pathParams[param.key] || '';
    }
  });

  const hasQueryInput = (draft.queryRows || []).some(r => r.k || r.v);
  if (sample && (overwrite || !hasQueryInput)) {
    draft.queryRows = queryRowsFromSample(sample.query);
  }
}

function buildConcretePath(template, pathParams) {
  const counts = {};
  return String(template || '/').replace(/\{([^}]+)\}/g, (token, name) => {
    counts[name] = (counts[name] || 0) + 1;
    const value = pathParams[pathParamKey(name, counts[name])];
    return value ? encodeURIComponent(value) : token;
  });
}

function getDraft(key) {
  const s = state.inventory;
  if (!s.tryDraft[key]) s.tryDraft[key] = {};
  return s.tryDraft[key];
}

function initDraft(e, key) {
  const draft = getDraft(key);
  if (draft._initialized) return draft;
  draft._initialized = true;
  draft.scheme = 'https';
  draft.port = defaultPort(draft.scheme);
  draft.portTouched = false;   // 사용자가 포트를 직접 바꿨는지(바꿨으면 scheme 변경 시 유지)
  draft.domain = (e.domains && e.domains[0]) || '';
  draft.timeoutMs = 10000;
  draft.pathParams = {};
  draft.queryRows = [{ k: '', v: '' }];
  applySampleRequest(e, draft, true);
  const headers = [];
  if (e.has_auth) {
    const isBearer = (e.auth_types || []).some(t => /bearer/i.test(t));
    headers.push({ k: 'Authorization', v: isBearer ? 'Bearer ' : '' });
  }
  if (['POST', 'PUT', 'PATCH'].includes((e.method || '').toUpperCase())) {
    headers.push({ k: 'Content-Type', v: 'application/json' });
  }
  if (!headers.length) headers.push({ k: '', v: '' });
  draft.headerRows = headers;
  draft.body = '';
  draft.response = null;
  draft.sending = false;
  return draft;
}

function renderTryPanel(e, key) {
  const draft = initDraft(e, key);
  const method = (e.method || 'GET').toUpperCase();
  const allowsBody = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method);
  const domains = (e.domains && e.domains.length) ? e.domains : [''];
  const params = pathParamInstances(e.endpoint);

  const domainOpts = domains.map(d =>
    `<option value="${esc(d)}" ${d === draft.domain ? 'selected' : ''}>${esc(d) || '(unknown)'}</option>`
  ).join('');
  const schemeOpts = ['https', 'http'].map(s =>
    `<option value="${s}" ${s === draft.scheme ? 'selected' : ''}>${s.toUpperCase()}</option>`
  ).join('');

  const pathParamRows = params.length ? `
    <div class="try-section">
      <div class="try-section-title">${t('try.pathParams')}</div>
      ${params.map(param => `
        <div class="try-row">
          <label class="try-key">${esc(param.label)}</label>
          <input class="try-input" data-try-path="${esc(param.key)}" value="${esc(draft.pathParams[param.key] || '')}" placeholder="${t('try.valPlaceholder')}">
        </div>`).join('')}
    </div>` : '';

  const kvRows = (rows, kind) => rows.map((r, i) => `
    <div class="try-row">
      <input class="try-input try-input-key" data-try-${kind}-k="${i}" placeholder="${t('try.keyPlaceholder')}" value="${esc(r.k)}">
      <input class="try-input try-input-val" data-try-${kind}-v="${i}" placeholder="${t('try.valPlaceholder')}" value="${esc(r.v)}">
      <button class="try-remove-btn" data-try-${kind}-remove="${i}" title="${t('js.remove')}">×</button>
    </div>`).join('');

  const bodySection = allowsBody ? `
    <div class="try-section">
      <div class="try-section-title">Body
        <span class="try-section-hint">${t('js.jsonOrText')}</span>
      </div>
      <textarea class="try-body" data-try-body placeholder='${method === 'GET' ? '' : '{"key": "value"}'}'>${esc(draft.body || '')}</textarea>
    </div>` : '';

  const previewUrl = computePreviewUrl(e, draft);

  return `
  <div class="try-panel" data-try-panel="${esc(key)}">
    <div class="try-url-bar">
      <span class="method-badge method-${method}">${method}</span>
      <select class="try-input try-scheme" data-try-scheme>${schemeOpts}</select>
      <select class="try-input try-domain" data-try-domain>${domainOpts}</select>
      <span class="try-url-colon">:</span>
      <input class="try-input try-port" data-try-port value="${esc(draft.port ?? '')}" inputmode="numeric" maxlength="5" title="${t('js.portHint')}">
      <span class="try-url-path">${esc(e.endpoint)}</span>
      <button class="try-send-btn" data-try-send ${draft.sending ? 'disabled' : ''}>
        ${draft.sending ? t('js.sending') : t('try.send')}
      </button>
    </div>
    <div class="try-preview">
      <span class="try-preview-label">${t('try.url')}</span>
      <code class="try-preview-url">${esc(previewUrl)}</code>
    </div>
    ${pathParamRows}
    <div class="try-section">
      <div class="try-section-title">${t('try.queryParams')}
        <button class="try-add-btn" data-try-add="query">${t('try.add')}</button>
      </div>
      ${kvRows(draft.queryRows, 'query')}
    </div>
    <div class="try-section">
      <div class="try-section-title">${t('try.headerSection')}
        <button class="try-add-btn" data-try-add="header">${t('try.add')}</button>
      </div>
      ${kvRows(draft.headerRows, 'header')}
    </div>
    ${bodySection}
    ${renderTryResponse(draft.response)}
  </div>`;
}

function computePreviewUrl(e, draft) {
  const path = buildConcretePath(e.endpoint, draft.pathParams || {});
  const qs = (draft.queryRows || [])
    .filter(r => r.k)
    .map(r => `${encodeURIComponent(r.k)}=${encodeURIComponent(r.v || '')}`)
    .join('&');
  return `${draft.scheme}://${draft.domain || '<domain>'}${portSuffix(draft.scheme, draft.port)}${path}${qs ? '?' + qs : ''}`;
}

function renderTryResponse(resp) {
  if (!resp) return '';
  if (resp.error) {
    return `
    <div class="try-section try-response">
      <div class="try-section-title">${t('try.response')}</div>
      <div class="try-resp-error">${esc(resp.error)}</div>
    </div>`;
  }
  const sc = resp.status_code;
  const cls = sc < 300 ? 'ok' : sc < 400 ? 'redir' : sc < 500 ? 'cliErr' : 'srvErr';
  const headersJson = JSON.stringify(resp.response_headers || {}, null, 2);
  const body = resp.response_body || '';
  let prettyBody = body;
  try {
    const parsed = JSON.parse(body);
    prettyBody = JSON.stringify(parsed, null, 2);
  } catch (_) { /* not JSON */ }
  const sizeStr = resp.content_length != null
    ? (resp.content_length < 1024 ? `${resp.content_length} B` : `${(resp.content_length / 1024).toFixed(1)} KB`)
    : '';
  return `
  <div class="try-section try-response">
    <div class="try-section-title">${t('try.response')}</div>
    <div class="try-resp-bar">
      <span class="try-status ${cls}">${sc} ${esc(resp.reason_phrase || '')}</span>
      <span class="try-meta">${resp.elapsed_ms} ms</span>
      <span class="try-meta">${esc(sizeStr)}</span>
      ${resp.body_truncated ? `<span class="try-meta warn">${t('try.truncated')}</span>` : ''}
    </div>
    <div class="try-resp-tabs">
      <button class="try-resp-tab active" data-resp-tab="body">${t('try.body')}</button>
      <button class="try-resp-tab" data-resp-tab="headers">${t('try.headers')}</button>
    </div>
    <pre class="try-resp-pane try-resp-body active" data-resp-pane="body">${esc(prettyBody)}</pre>
    <pre class="try-resp-pane try-resp-headers" data-resp-pane="headers">${esc(headersJson)}</pre>
  </div>`;
}

function rerenderTryPanel(key) {
  const e = state.inventory.data.find(en => rowKey(en) === key);
  if (!e) return;
  const cell = $(`tr.row-detail[data-row-detail="${cssEsc(key)}"] td`);
  if (!cell) return;
  cell.innerHTML = renderTryPanel(e, key);
}

function cssEsc(v) {
  if (window.CSS && CSS.escape) return CSS.escape(v);
  return String(v).replace(/"/g, '\\"');
}

async function sendTryRequest(key) {
  const e = state.inventory.data.find(en => rowKey(en) === key);
  if (!e) return;
  const draft = getDraft(key);

  if (!draft.domain) {
    draft.response = { error: t('js.noDomain') };
    rerenderTryPanel(key);
    return;
  }
  const missingParams = pathParamInstances(e.endpoint)
    .filter(param => !String(draft.pathParams?.[param.key] || '').trim());
  if (missingParams.length) {
    draft.response = { error: t('js.missingParams', {list: missingParams.map(p => p.label).join(', ')}) };
    rerenderTryPanel(key);
    return;
  }

  draft.sending = true;
  draft.response = null;
  rerenderTryPanel(key);

  const path = buildConcretePath(e.endpoint, draft.pathParams || {});
  const query = {};
  (draft.queryRows || []).forEach(r => { if (r.k) query[r.k] = r.v || ''; });
  const headers = {};
  (draft.headerRows || []).forEach(r => { if (r.k) headers[r.k] = r.v || ''; });

  const contentTypeKey = Object.keys(headers).find(k => k.toLowerCase() === 'content-type');
  const contentType = contentTypeKey ? headers[contentTypeKey] : '';
  let body = draft.body;
  if (body && String(contentType).toLowerCase().includes('application/json')) {
    try { body = JSON.parse(body); } catch (_) { /* leave as raw text */ }
  }

  try {
    const res = await fetch('/api/test/request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        method: e.method,
        scheme: draft.scheme,
        domain: draft.domain,
        port: draft.port,
        endpoint: e.endpoint,
        path,
        query,
        headers,
        body,
        timeout_ms: draft.timeoutMs,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      draft.response = { error: data.detail || `HTTP ${res.status}` };
    } else if (data.ok === false) {
      draft.response = { error: data.error || t('js.requestFailed') };
    } else {
      draft.response = data;
    }
  } catch (err) {
    draft.response = { error: t('js.networkError', {msg: err.message}) };
  } finally {
    draft.sending = false;
    rerenderTryPanel(key);
  }
}

function tryPanelKey(target) {
  const panel = target.closest('.try-panel');
  return panel ? panel.getAttribute('data-try-panel') : null;
}

function updateTryPreview(key) {
  const e = state.inventory.data.find(en => rowKey(en) === key);
  const panel = $(`.try-panel[data-try-panel="${cssEsc(key)}"]`);
  if (!e || !panel) return;
  const el = $('.try-preview-url', panel);
  if (el) el.textContent = computePreviewUrl(e, getDraft(key));
}

function blankKvRow(rows) {
  if (!rows.length) rows.push({ k: '', v: '' });
}

function handleTryPanelClick(e) {
  const sendBtn = e.target.closest('button[data-try-send]');
  if (sendBtn) {
    const key = tryPanelKey(sendBtn);
    if (key) sendTryRequest(key);
    return;
  }

  const addBtn = e.target.closest('button[data-try-add]');
  if (addBtn) {
    const key = tryPanelKey(addBtn);
    if (!key) return;
    const draft = getDraft(key);
    const kind = addBtn.getAttribute('data-try-add');
    const rows = kind === 'header' ? draft.headerRows : draft.queryRows;
    rows.push({ k: '', v: '' });
    rerenderTryPanel(key);
    return;
  }

  const queryRemove = e.target.closest('button[data-try-query-remove]');
  if (queryRemove) {
    const key = tryPanelKey(queryRemove);
    if (!key) return;
    const rows = getDraft(key).queryRows;
    rows.splice(Number(queryRemove.getAttribute('data-try-query-remove')), 1);
    blankKvRow(rows);
    rerenderTryPanel(key);
    return;
  }

  const headerRemove = e.target.closest('button[data-try-header-remove]');
  if (headerRemove) {
    const key = tryPanelKey(headerRemove);
    if (!key) return;
    const rows = getDraft(key).headerRows;
    rows.splice(Number(headerRemove.getAttribute('data-try-header-remove')), 1);
    blankKvRow(rows);
    rerenderTryPanel(key);
    return;
  }

  const tabBtn = e.target.closest('button[data-resp-tab]');
  if (tabBtn) {
    const response = tabBtn.closest('.try-response');
    const name = tabBtn.getAttribute('data-resp-tab');
    if (!response || !name) return;
    $$('[data-resp-tab]', response).forEach(btn => btn.classList.toggle('active', btn === tabBtn));
    $$('[data-resp-pane]', response).forEach(pane => {
      pane.classList.toggle('active', pane.getAttribute('data-resp-pane') === name);
    });
  }
}

function handleTryPanelInput(e) {
  const target = e.target;
  const key = tryPanelKey(target);
  if (!key) return;
  const draft = getDraft(key);

  if (target.hasAttribute('data-try-scheme')) {
    draft.scheme = target.value;
    if (!draft.portTouched) draft.port = defaultPort(draft.scheme);  // 직접 안 바꿨으면 기본 포트로
    rerenderTryPanel(key);   // 포트 입력값 갱신 위해 재렌더
    return;
  }
  if (target.hasAttribute('data-try-port')) {
    draft.port = target.value.trim();
    draft.portTouched = true;
    updateTryPreview(key);
    return;
  }
  if (target.hasAttribute('data-try-domain')) {
    draft.domain = target.value;
    const e = state.inventory.data.find(en => rowKey(en) === key);
    if (e) applySampleRequest(e, draft, true);
    rerenderTryPanel(key);
    return;
  }
  if (target.hasAttribute('data-try-body')) {
    draft.body = target.value;
    return;
  }

  const pathName = target.getAttribute('data-try-path');
  if (pathName != null) {
    draft.pathParams[pathName] = target.value;
    updateTryPreview(key);
    return;
  }

  const updateKv = (rows, attrPrefix) => {
    const keyIndex = target.getAttribute(`data-try-${attrPrefix}-k`);
    const valueIndex = target.getAttribute(`data-try-${attrPrefix}-v`);
    if (keyIndex != null) {
      rows[Number(keyIndex)].k = target.value;
      return true;
    }
    if (valueIndex != null) {
      rows[Number(valueIndex)].v = target.value;
      return true;
    }
    return false;
  };

  if (updateKv(draft.queryRows, 'query')) {
    updateTryPreview(key);
    return;
  }
  updateKv(draft.headerRows, 'header');
}

function syncCheckAll(slice) {
  const s = state.inventory;
  const all = $('#check-all');
  if (!all) return;
  const eligible = slice.filter(e => s.hasSpec && s.shadowSet.has(`${e.method}:${e.endpoint}`) && !s.addedSet.has(rowKey(e)));
  if (!eligible.length) { all.checked = false; all.indeterminate = false; all.disabled = true; return; }
  all.disabled = false;
  const checkedCount = eligible.filter(e => s.selected.has(rowKey(e))).length;
  all.checked = checkedCount === eligible.length;
  all.indeterminate = checkedCount > 0 && checkedCount < eligible.length;
}

function updateBulkBar() {
  const s = state.inventory;
  const info = $('#bulk-selected-info');
  const hint = $('#bulk-bar-hint');
  const btn  = $('#bulk-add-btn');
  const cnt  = $('#bulk-add-count');
  const n = s.selected.size;
  if (info) {
    info.textContent = n ? t('js.nSelected', {n: fmt(n)}) : t('shadow.noSelection');
    info.classList.toggle('has-sel', n > 0);
  }
  if (hint) hint.textContent = s.hasSpec
    ? t('js.bulkHint')
    : t('js.bulkNeedSpec', {tab: t('tab.anomalies')});
  if (cnt) cnt.textContent = fmt(n);
  if (btn) btn.disabled = !s.hasSpec || n === 0;
}

function initTableControls() {
  const bindFilter = (id, key, transform = v => v) => {
    const el = document.getElementById(id);
    if (!el) return;
    const evt = el.tagName === 'SELECT' ? 'change' : 'input';
    el.addEventListener(evt, e => {
      state.inventory[key] = transform(e.target.value);
      state.inventory.page = 1;
      renderTable();
    });
  };
  bindFilter('table-search', 'search');
  bindFilter('table-method', 'method');
  bindFilter('table-domain', 'domain');
  bindFilter('table-auth', 'auth');
  bindFilter('table-status', 'status');
  bindFilter('table-min-calls', 'minCalls', v => Number(v) || 0);
  bindFilter('table-min-rt', 'minRtMs', v => Number(v) || 0);

  const resetBtn = document.getElementById('table-reset');
  if (resetBtn) resetBtn.addEventListener('click', () => {
    Object.assign(state.inventory, {
      search: '', method: '', domain: '', auth: '', status: '',
      minCalls: 0, minRtMs: 0, page: 1,
    });
    ['table-search', 'table-method', 'table-domain', 'table-auth',
     'table-status', 'table-min-calls', 'table-min-rt']
      .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    renderTable();
  });

  $$('.number-input').forEach(wrap => {
    const input = wrap.querySelector('input');
    const up = wrap.querySelector('.spin-up');
    const down = wrap.querySelector('.spin-down');
    if (!input || !up || !down) return;
    const step = Number(input.step) || 1;
    const min = input.min !== '' ? Number(input.min) : -Infinity;
    const bump = (delta) => {
      const cur = Number(input.value) || 0;
      const next = Math.max(min, Math.round((cur + delta) * 10) / 10);
      input.value = next;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    };
    up.addEventListener('click', () => bump(step));
    down.addEventListener('click', () => bump(-step));
  });

  $$('thead th[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (state.inventory.sort === col) state.inventory.order = state.inventory.order === 'desc' ? 'asc' : 'desc';
      else { state.inventory.sort = col; state.inventory.order = 'desc'; }
      $$('thead th').forEach(t => t.classList.remove('sort-asc', 'sort-desc'));
      th.classList.add(state.inventory.order === 'asc' ? 'sort-asc' : 'sort-desc');
      loadInventory();
    });
  });

  const prev = $('#page-prev'), next = $('#page-next');
  if (prev) prev.addEventListener('click', () => { state.inventory.page--; renderTable(); });
  if (next) next.addEventListener('click', () => { state.inventory.page++; renderTable(); });

  // 체크박스 / + Spec 버튼 / Try-it-out (이벤트 위임)
  const tbody = $('#inventory-tbody');
  if (tbody) {
    tbody.addEventListener('change', e => {
      const cb = e.target.closest('input[type="checkbox"][data-row-check]');
      if (!cb) {
        handleTryPanelInput(e);
        return;
      }
      const key = cb.getAttribute('data-row-check');
      if (cb.checked) state.inventory.selected.add(key);
      else state.inventory.selected.delete(key);
      const slice = currentPageSlice();
      syncCheckAll(slice);
      updateBulkBar();
    });
    tbody.addEventListener('click', e => {
      const addBtn = e.target.closest('button[data-row-add]');
      if (addBtn) {
        addSingleEndpointToSpec(addBtn.getAttribute('data-row-add'), addBtn);
        return;
      }
      if (e.target.closest('.try-panel')) {
        handleTryPanelClick(e);
        return;
      }
      if (e.target.closest('.col-check') || e.target.closest('.col-action')) return;
      const tr = e.target.closest('tr[data-row-key]');
      if (tr) {
        const key = tr.getAttribute('data-row-key');
        state.inventory.expandedKey = state.inventory.expandedKey === key ? null : key;
        renderTable();
        return;
      }
      handleTryPanelClick(e);
    });
    tbody.addEventListener('input', handleTryPanelInput);
  }

  const checkAll = $('#check-all');
  if (checkAll) checkAll.addEventListener('change', e => {
    const s = state.inventory;
    const slice = currentPageSlice();
    const eligible = slice.filter(en => s.hasSpec && s.shadowSet.has(`${en.method}:${en.endpoint}`) && !s.addedSet.has(rowKey(en)));
    if (e.target.checked) eligible.forEach(en => s.selected.add(rowKey(en)));
    else                  eligible.forEach(en => s.selected.delete(rowKey(en)));
    renderTable();
  });

  const selShadowBtn = $('#bulk-select-shadow');
  if (selShadowBtn) selShadowBtn.addEventListener('click', () => {
    const s = state.inventory;
    if (!s.hasSpec) { showBulkMsg(t('js.noSpecUploaded'), 'err'); return; }
    const slice = currentPageSlice();
    slice.forEach(en => {
      if (s.shadowSet.has(`${en.method}:${en.endpoint}`) && !s.addedSet.has(rowKey(en))) {
        s.selected.add(rowKey(en));
      }
    });
    renderTable();
  });

  const clearBtn = $('#bulk-clear');
  if (clearBtn) clearBtn.addEventListener('click', () => {
    state.inventory.selected.clear();
    renderTable();
  });

  const bulkAdd = $('#bulk-add-btn');
  if (bulkAdd) bulkAdd.addEventListener('click', addSelectedEndpointsToSpec);
}

function currentPageSlice() {
  const s = state.inventory;
  const filtered = filterInventory();
  return filtered.slice((s.page - 1) * s.perPage, s.page * s.perPage);
}

function showBulkMsg(msg, type) {
  // bulk bar의 hint 영역에 일시 표시
  const hint = $('#bulk-bar-hint');
  if (!hint) return;
  const prev = hint.textContent;
  hint.textContent = msg;
  hint.style.color = type === 'err' ? '#f08080' : type === 'ok' ? 'var(--accent2)' : '';
  setTimeout(() => { hint.style.color = ''; updateBulkBar(); }, 4000);
}

function parseRowKey(key) {
  const i = key.indexOf(' ');
  return { method: key.slice(0, i), endpoint: key.slice(i + 1) };
}

async function postMergeShadow(items) {
  const res = await fetch('/api/openapi/merge-shadow', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoints: items }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = typeof data.detail === 'string' ? data.detail : t('js.failedHttp', {status: res.status});
    throw new Error(msg);
  }
  return data;
}

async function addSingleEndpointToSpec(key, btn) {
  if (btn) { btn.disabled = true; btn.classList.add('running'); btn.textContent = t('js.adding'); }
  try {
    const { method, endpoint } = parseRowKey(key);
    const data = await postMergeShadow([{ method, endpoint }]);
    state.inventory.addedSet.add(key);
    state.inventory.selected.delete(key);
    showBulkMsg(t('js.addedOne', {method: method, endpoint: endpoint, total: fmt(data.endpoint_count || 0)}), 'ok');
    await refreshAfterMerge();
  } catch (e) {
    if (btn) { btn.disabled = false; btn.classList.remove('running'); btn.textContent = t('btn.addSpec'); }
    showBulkMsg(t('js.addFailed', {msg: e.message}), 'err');
  }
}

async function addSelectedEndpointsToSpec() {
  const s = state.inventory;
  if (!s.selected.size) return;
  const btn = $('#bulk-add-btn');
  if (btn) { btn.disabled = true; btn.classList.add('running'); }
  const items = [...s.selected].map(parseRowKey);
  try {
    const data = await postMergeShadow(items);
    items.forEach(it => s.addedSet.add(`${it.method} ${it.endpoint}`));
    s.selected.clear();
    const skipped = (data.skipped || []).length;
    showBulkMsg(
      t('js.bulkAdded', {n: fmt(data.added), skipped: skipped ? t('js.bulkSkipped', {n: skipped}) : '', total: fmt(data.endpoint_count || 0)}),
      'ok',
    );
    await refreshAfterMerge();
  } catch (e) {
    showBulkMsg(t('js.bulkAddFailed', {msg: e.message}), 'err');
    if (btn) { btn.disabled = false; btn.classList.remove('running'); }
  }
}

async function refreshAfterMerge() {
  await Promise.all([loadSpecStatus(), loadSummary()]);
  // shadow 결과를 다시 받아 shadowSet 갱신
  const shadow = await fetch('/api/anomalies/shadow').then(r => r.json()).catch(() => []);
  state.inventory.shadowSet = new Set(shadow.map(e => `${e.method}:${e.endpoint}`));
  renderTable();
  // Anomalies 탭이 열려있으면 거기도 갱신
  if (state.activeTab === 'anomalies') loadAnomalies();
}

/* ── Anomalies ────────────────────────────────────── */
async function loadAnomalies() {
  const [shadow, unused, noAuth, mlEp, susIps, timeAn, slow] = await Promise.all([
    fetch('/api/anomalies/shadow').then(r => r.json()),
    fetch('/api/anomalies/unused-spec').then(r => r.json()),
    fetch('/api/anomalies/no-auth').then(r => r.json()),
    fetch('/api/anomalies/ml-endpoints').then(r => r.json()),
    fetch('/api/anomalies/suspicious-ips').then(r => r.json()),
    fetch('/api/anomalies/time-anomaly').then(r => r.json()),
    fetch('/api/anomalies/slow').then(r => r.json()),
  ]);
  renderShadowList(shadow);
  renderUnusedList(unused);
  renderAnomalyList('no-auth-list', noAuth, e => t('meta.callsAvg', {calls: fmt(e.call_count), ms: fmtMs(e.avg_response_time)}));
  renderAnomalyList('slow-list', slow, e => t('meta.p95p99', {p95: fmtMs(e.p95_response_time), p99: fmtMs(e.p99_response_time), calls: fmt(e.call_count)}));
  renderMLEndpoints(mlEp);
  renderSuspiciousIPs(susIps);
  renderTimeAnomalies(timeAn);

  bind('shadow-count', shadow.length);
  bind('unused-count', unused.length);
  bind('noauth-count', noAuth.length);
  bind('slow-count', slow.length);
  bind('ml-ep-count', mlEp.length);
  bind('sus-ip-count', susIps.length);
  bind('offhour-count', timeAn.length);
}

function renderMLEndpoints(items) {
  const el = document.getElementById('ml-endpoints-list');
  if (!el) return;
  if (!items.length) { el.innerHTML = `<div class="empty-state">${t('js.noMlEndpoints')}</div>`; return; }
  el.innerHTML = items.map(e => `
    <div class="anomaly-item">
      <span class="ep">
        <span class="method-badge method-${e.method}">${e.method}</span>
        <span class="domain-stack">${(e.domains || []).map(d => `<span class="domain-badge">${esc(d)}</span>`).join('')}</span>
        ${esc(e.endpoint)}
      </span>
      <span class="meta">${t('js.metaAnomalous', {pct: fmtPct(e.anomaly_ratio), a: fmt(e.anomalous_requests), b: fmt(e.total_requests)})} · max score ${e.max_score}</span>
    </div>`).join('');
}

function renderSuspiciousIPs(items) {
  const el = document.getElementById('suspicious-ips-list');
  if (!el) return;
  if (!items.length) { el.innerHTML = `<div class="empty-state">${t('js.noSuspiciousIp')}</div>`; return; }
  el.innerHTML = items.map(e => `
    <div class="anomaly-item">
      <span class="ep"><span class="ip-badge">${esc(e.ip)}</span></span>
      <span class="meta">${t('js.metaSequences', {pct: fmtPct(e.anomaly_ratio)})} · ${fmt(e.anomalous_sequences)}/${fmt(e.total_sequences)} · last: ${esc(e.last_seen || '-')}</span>
    </div>`).join('');
}

function renderTimeAnomalies(items) {
  const el = document.getElementById('time-anomaly-list');
  if (!el) return;
  if (!items.length) { el.innerHTML = `<div class="empty-state">${t('js.noOffHour')}</div>`; return; }
  const fmtHrs = hrs => hrs.map(h => String(h).padStart(2, '0') + ':00').join(', ') || '—';
  el.innerHTML = items.map(e => `
    <div class="anomaly-item">
      <span class="ep">
        <span class="method-badge method-${e.method}">${e.method}</span>
        <span class="domain-stack">${(e.domains || []).map(d => `<span class="domain-badge">${esc(d)}</span>`).join('')}</span>
        ${esc(e.endpoint)}
      </span>
      <span class="meta">
        Core: <span class="hour-core">${fmtHrs(e.core_hours)}</span> ·
        Off-hour: <span class="hour-rare">${fmtHrs(e.rare_hours)}</span> ·
        ${t('js.offHourCount', {n: fmt(e.off_hour_requests), pct: fmtPct(e.off_hour_ratio)})}
      </span>
    </div>`).join('');
}

function renderShadowList(items) {
  const el = document.getElementById('shadow-list');
  if (!el) return;
  if (!items.length) { el.innerHTML = `<div class="empty-state">${t('js.noShadow')}</div>`; return; }
  el.innerHTML = items.map(e => `
    <div class="anomaly-item">
      <span class="ep">
        <span class="method-badge method-${e.method}">${e.method}</span>
        <span class="domain-stack">${(e.domains || []).map(d => `<span class="domain-badge">${esc(d)}</span>`).join('')}</span>
        ${esc(e.endpoint)}
      </span>
      <span class="meta">${t('js.metaCalls', {calls: fmt(e.call_count), rate: fmtPct(e.error_rate), ips: fmt(e.unique_ip_count)})}</span>
    </div>`).join('');
}

function renderUnusedList(items) {
  const el = document.getElementById('unused-spec-list');
  if (!el) return;
  if (!items.length) {
    el.innerHTML = `<div class="empty-state">${t('js.allSpecUsed')}</div>`;
    return;
  }
  el.innerHTML = items.map(e => `
    <div class="unused-item">
      <span class="ep">
        <span class="method-badge method-${e.method}">${e.method}</span>
        ${esc(e.path)}
      </span>
      <span class="meta">
        ${e.summary ? esc(e.summary) + ' · ' : ''}
        ${e.operation_id ? `<span class="op-id">${esc(e.operation_id)}</span>` : ''}
        ${e.tags?.length ? e.tags.map(t => `<span class="tag">${esc(t)}</span>`).join(' ') : ''}
      </span>
    </div>`).join('');
}

function renderAnomalyList(id, items, metaFn) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!items.length) { el.innerHTML = `<div class="empty-state">${t('anomaly.noItems')}</div>`; return; }
  el.innerHTML = items.map(e => `
    <div class="anomaly-item">
      <span class="ep">
        <span class="method-badge method-${e.method}">${e.method}</span>
        <span class="domain-stack">${(e.domains || []).map(d => `<span class="domain-badge">${esc(d)}</span>`).join('')}</span>
        ${esc(e.endpoint)}
      </span>
      <span class="meta">${metaFn(e)}</span>
    </div>`).join('');
}

/* ── OpenAPI 업로드 ────────────────────────────────── */
async function loadSpecStatus() {
  const info = await fetch('/api/openapi/status').then(r => r.json());
  updateSpecUI(info);
}

function updateSpecUI(info) {
  const badge = $('#spec-status-badge');
  const uploadZone = $('#upload-zone');
  const specInfo = $('#spec-info');
  if (!badge) return;

  if (info.uploaded) {
    badge.innerHTML = `<span class="spec-badge ok">✓ ${esc(info.file_name)}</span>`;
    if (uploadZone) uploadZone.style.display = 'none';
    if (specInfo) {
      specInfo.style.display = 'flex';
      bind('spec-title', info.title);
      bind('spec-version', info.version || '-');
      bind('spec-oas-version', info.openapi_version);
      bind('spec-ep-count', fmt(info.endpoint_count));
      bind('spec-filename', info.file_name);
    }
  } else {
    badge.innerHTML = `<span class="spec-badge none">${t('js.specNotUploaded')}</span>`;
    if (uploadZone) uploadZone.style.display = '';
    if (specInfo) specInfo.style.display = 'none';
  }
}

function showUploadError(msg) {
  const el = $('#upload-error');
  if (!el) return;
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 5000);
}

async function uploadSpec(file) {
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch('/api/openapi/upload', { method: 'POST', body: fd });
    let data;
    try { data = await res.json(); } catch {
      showUploadError(t('js.serverError', {status: res.status}));
      return;
    }
    if (!res.ok) {
      const msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      showUploadError(msg || t('js.uploadFailed'));
      return;
    }
    updateSpecUI({ uploaded: true, ...data });
    await loadAnomalies();
    await loadSummary();
  } catch (e) {
    showUploadError(t('js.networkError', {msg: e.message}));
  }
}

function initUpload() {
  const zone = $('#upload-zone');
  const input = $('#spec-file-input');
  const browseBtn = $('#upload-browse-btn');
  const removeBtn = $('#spec-remove-btn');

  if (browseBtn) browseBtn.addEventListener('click', e => { e.stopPropagation(); input?.click(); });
  if (zone) zone.addEventListener('click', () => input?.click());
  if (input) input.addEventListener('change', e => { if (e.target.files[0]) uploadSpec(e.target.files[0]); });

  if (zone) {
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e => {
      e.preventDefault(); zone.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file) uploadSpec(file);
    });
  }

  if (removeBtn) {
    removeBtn.addEventListener('click', async () => {
      await fetch('/api/openapi/spec', { method: 'DELETE' });
      updateSpecUI({ uploaded: false });
      await loadAnomalies();
      await loadSummary();
    });
  }

  const exportBtn = $('#export-all-btn');
  if (exportBtn) exportBtn.addEventListener('click', exportAllAsOpenAPI);
}

/* ── OpenAPI Action 버튼 ───────────────────────────── */
function showOasMsg(type, msg) {
  const el = $('#oas-action-msg');
  if (!el) return;
  el.className = 'oas-action-msg ' + (type || '');
  el.textContent = msg || '';
  if (msg) setTimeout(() => { if (el.textContent === msg) { el.textContent = ''; el.className = 'oas-action-msg'; } }, 5000);
}

async function exportAllAsOpenAPI() {
  const btn = $('#export-all-btn');
  if (!btn || btn.disabled) return;
  btn.disabled = true; btn.classList.add('running');
  showOasMsg('', t('js.generating'));
  try {
    const res = await fetch('/api/openapi/export-all');
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      showOasMsg('err', data.detail || t('js.failedHttp', {status: res.status}));
      return;
    }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="?([^"]+)"?/);
    const fname = m ? m[1] : `api-discovery-${Date.now()}.json`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = fname; document.body.appendChild(a); a.click();
    a.remove(); URL.revokeObjectURL(url);
    showOasMsg('ok', t('js.downloaded', {file: fname}));
  } catch (e) {
    showOasMsg('err', t('js.networkError', {msg: e.message}));
  } finally {
    btn.disabled = false; btn.classList.remove('running');
  }
}

/* ── Models 탭 ────────────────────────────────────── */
async function renderModels() {
  const [hist, summary] = await Promise.all([
    fetch('/api/charts/training-history').then(r => r.json()),
    fetch('/api/summary').then(r => r.json()),
  ]);
  renderLineChart('chart-training', hist.autoencoder || [], hist.lstm || []);

  const aeInfo = document.getElementById('ae-info');
  if (aeInfo) {
    aeInfo.innerHTML = hist.autoencoder?.length ? `
      <div class="model-row"><span class="k">${t('model.epochs')}</span><span class="v">${hist.autoencoder.length}</span></div>
      <div class="model-row"><span class="k">${t('model.finalTrain')}</span><span class="v">${hist.autoencoder.at(-1)?.train_loss?.toFixed(6)}</span></div>
      <div class="model-row"><span class="k">${t('model.finalVal')}</span><span class="v">${hist.autoencoder.at(-1)?.val_loss?.toFixed(6)}</span></div>
      <div class="model-row"><span class="k">${t('model.threshold')}</span><span class="v">${summary.ae_threshold?.toFixed(6) ?? '-'}</span></div>
    ` : `<div class="no-model">${t('model.notTrained')}</div>`;
  }
  const lstmInfo = document.getElementById('lstm-info');
  if (lstmInfo) {
    lstmInfo.innerHTML = hist.lstm?.length ? `
      <div class="model-row"><span class="k">${t('model.epochs')}</span><span class="v">${hist.lstm.length}</span></div>
      <div class="model-row"><span class="k">${t('model.finalTrain')}</span><span class="v">${hist.lstm.at(-1)?.train_loss?.toFixed(6)}</span></div>
      <div class="model-row"><span class="k">${t('model.finalVal')}</span><span class="v">${hist.lstm.at(-1)?.val_loss?.toFixed(6)}</span></div>
      <div class="model-row"><span class="k">${t('model.threshold')}</span><span class="v">${summary.lstm_threshold?.toFixed(6) ?? '-'}</span></div>
    ` : `<div class="no-model">${t('model.notTrained')}</div>`;
  }
}

/* ── Flow (Sunburst) ──────────────────────────────── */
const METHOD_FILL = { GET:'#00c04b', POST:'#63b3ed', PUT:'#f6ad55', DELETE:'#fc8181', PATCH:'#b794f4', HEAD:'#a0aec0', OPTIONS:'#a0aec0' };
const DOMAIN_PALETTE = ['#3182ce', '#38a169', '#805ad5', '#d69e2e', '#e53e3e', '#319795', '#d53f8c', '#4299e1'];
const FLOW_EXPAND_NODE_LIMIT = 420;

async function loadFlow() {
  const [data, shadow, specInfo] = await Promise.all([
    fetch('/api/inventory').then(r => r.json()),
    fetch('/api/anomalies/shadow').then(r => r.json()).catch(() => []),
    fetch('/api/openapi/status').then(r => r.json()).catch(() => ({ uploaded: false })),
  ]);
  // 정적 리소스는 백엔드 /api/inventory 에서 이미 제외됨 (API만 내려옴)
  state.flow.data = data;
  state.flow.shadowSet = new Set(shadow.map(e => `${e.method}:${e.endpoint}`));
  state.flow.hasSpec = !!specInfo.uploaded;
  populateFlowDomainFilter(data);
  renderCurrentFlow();
}

function initFlowControls() {
  const bindFilter = (id, key, transform = v => v) => {
    const el = document.getElementById(id);
    if (!el) return;
    const evt = el.tagName === 'SELECT' ? 'change' : 'input';
    el.addEventListener(evt, e => {
      state.flow[key] = transform(e.target.value);
      renderCurrentFlow();
    });
  };
  bindFilter('flow-search', 'search');
  bindFilter('flow-method', 'method');
  bindFilter('flow-domain', 'domain');
  bindFilter('flow-auth', 'auth');
  bindFilter('flow-status', 'status');
  bindFilter('flow-min-calls', 'minCalls', v => Number(v) || 0);
  bindFilter('flow-min-rt', 'minRtMs', v => Number(v) || 0);

  const resetBtn = document.getElementById('flow-reset');
  if (resetBtn) resetBtn.addEventListener('click', () => {
    Object.assign(state.flow, {
      search: '', method: '', domain: '', auth: '', status: '',
      minCalls: 0, minRtMs: 0,
    });
    ['flow-search', 'flow-method', 'flow-domain', 'flow-auth',
     'flow-status', 'flow-min-calls', 'flow-min-rt']
      .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    renderCurrentFlow();
  });
}

function populateFlowDomainFilter(data) {
  const sel = document.getElementById('flow-domain');
  if (!sel) return;
  const current = sel.value;
  const domains = new Set();
  data.forEach(e => (e.domains || []).forEach(d => domains.add(d)));
  sel.innerHTML = `<option value="">${t('filter.allDomains')}</option>` +
    [...domains].sort().map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join('');
  sel.value = [...domains].includes(current) ? current : '';
  state.flow.domain = sel.value;
}

function renderCurrentFlow() {
  const prepared = prepareFlowHighlight(state.flow.data);
  updateFlowStats(prepared);
  const tree = buildFlowHierarchy(state.flow.data, prepared.highlightKeys);
  renderFlowTree(tree, prepared);
}

function flowEndpointKey(domain, e) {
  return `${domain}\u0000${e.method || ''}\u0000${e.endpoint || ''}`;
}

function hasActiveEndpointFilters() {
  const s = state.flow;
  return !!(s.search || s.method || s.domain || s.auth || s.status || s.minCalls > 0 || s.minRtMs > 0);
}

function matchesEndpointFilters(e, domain) {
  const s = state.flow;
  if (s.method && (e.method || '').toUpperCase() !== s.method.toUpperCase()) return false;
  if (s.search && !(e.endpoint || '').toLowerCase().includes(s.search.toLowerCase())) return false;
  if (s.domain && domain !== s.domain) return false;
  if (s.auth === 'yes' && !e.has_auth) return false;
  if (s.auth === 'no'  &&  e.has_auth) return false;
  if (s.status) {
    const isShadow = state.flow.hasSpec && state.flow.shadowSet.has(`${e.method}:${e.endpoint}`);
    if (s.status === 'managed' && (!state.flow.hasSpec || isShadow)) return false;
    if (s.status === 'shadow'  && (!state.flow.hasSpec || !isShadow)) return false;
  }
  if (s.minCalls > 0 && (e.call_count || 0) < s.minCalls) return false;
  if (s.minRtMs  > 0 && ((e.avg_response_time || 0) * 1000) < s.minRtMs) return false;
  return true;
}

function prepareFlowHighlight(inventory) {
  const highlightKeys = new Set();
  const active = hasActiveEndpointFilters();
  let matchedCount = 0;
  let matchedCalls = 0;

  if (active) {
    inventory.forEach(e => {
      const domains = e.domains?.length ? e.domains : ['(unknown)'];
      domains.forEach(domain => {
        if (!matchesEndpointFilters(e, domain)) return;
        highlightKeys.add(flowEndpointKey(domain, e));
        matchedCount++;
        matchedCalls += e.call_count || 0;
      });
    });
  }

  return {
    highlightKeys,
    filterActive: active,
    matchedCount,
    matchedCalls,
    totalCount: inventory.length,
  };
}

function updateFlowStats(meta) {
  const el = document.getElementById('flow-stats');
  if (!el) return;
  const totalCalls = state.flow.data.reduce((s, e) => s + (e.call_count || 0), 0);
  const parts = [
    `<span class="flow-stat-pill">${t('flow.totalEndpoints', {n: fmt(meta.totalCount)})}</span>`,
    `<span class="flow-stat-pill">${t('flow.totalCalls', {n: fmt(totalCalls)})}</span>`,
  ];
  if (meta.filterActive) {
    parts.push(`<span class="flow-stat-pill highlight">${t('flow.filterMatched', {nodes: fmt(meta.matchedCount), calls: fmt(meta.matchedCalls)})}</span>`);
  } else {
    parts.push(`<span class="flow-stat-pill">${t('flow.filterHint')}</span>`);
  }
  if (meta.note) {
    parts.push(`<span class="flow-stat-pill warn">${esc(meta.note)}</span>`);
  }
  el.innerHTML = parts.join('');
}

function buildFlowHierarchy(inventory, highlightKeys = new Set()) {
  const root = { name: 'API', _children: {}, methods: {}, endpointKeys: [] };

  const ensure = (parent, name) => {
    if (!parent._children[name])
      parent._children[name] = { name, _children: {}, methods: {}, endpointKeys: [] };
    return parent._children[name];
  };

  for (const e of inventory) {
    const domains = e.domains?.length ? e.domains : ['(unknown)'];
    const segments = (e.endpoint || '/').split('/').filter(s => s);
    for (const domain of domains) {
      let node = ensure(root, domain);
      node.isDomain = true;
      for (const seg of segments) node = ensure(node, seg);
      const m = e.method || 'GET';
      node.methods[m] = (node.methods[m] || 0) + (e.call_count || 0);
      node.endpointKeys.push(flowEndpointKey(domain, e));
    }
  }

  const toD3 = (n) => {
    const children = Object.values(n._children).map(toD3);
    const ownMethods = Object.entries(n.methods || {})
      .map(([m, c]) => ({ method: m, count: c }))
      .sort((a, b) => b.count - a.count);
    const rollup = {};
    ownMethods.forEach(m => { rollup[m.method] = (rollup[m.method] || 0) + m.count; });
    children.forEach(c => (c.methods || []).forEach(m => {
      rollup[m.method] = (rollup[m.method] || 0) + m.count;
    }));
    const methods = Object.entries(rollup)
      .map(([m, c]) => ({ method: m, count: c }))
      .sort((a, b) => b.count - a.count);
    const leafCalls = ownMethods.reduce((s, m) => s + m.count, 0);
    const highlight = (n.endpointKeys || []).some(k => highlightKeys.has(k));
    const highlightDescendant = highlight || children.some(c => c.highlightDescendant);
    const out = { name: n.name, methods, leafCalls, isDomain: !!n.isDomain, highlight, highlightDescendant };
    if (children.length) out.children = children;
    return out;
  };
  return toD3(root);
}

function renderFlowTree(data, meta = {}) {
  const containerEl = document.getElementById('flow-chart');
  const tooltip = document.getElementById('flow-tooltip');
  if (!containerEl) return;
  containerEl.innerHTML = '';
  if (!data.children?.length) {
    containerEl.innerHTML = `<div class="empty-state">${t('js.noApiData')}</div>`;
    return;
  }

  const NW = 190, NH = 36, NH_HALF = NH / 2;
  const V_MIN = NH + 14;
  const H_GAP = 280;
  const viewportW = containerEl.clientWidth || 1100;
  const viewportH = containerEl.clientHeight || 720;
  const svgW = viewportW;
  const svgH = viewportH;
  let uid = 0;

  const root = d3.hierarchy(data)
    .sum(d => d.leafCalls || 0);

  root.descendants().forEach(d => {
    if (d.depth >= 3 && d.children) { d._children = d.children; d.children = null; }
  });

  containerEl.style.position = 'relative';
  const svg = d3.select(containerEl).append('svg')
    .attr('width', svgW).attr('height', svgH).style('display', 'block');

  const defs = svg.append('defs');
  const glowF = defs.append('filter').attr('id','fn-glow').attr('x','-30%').attr('y','-30%').attr('width','160%').attr('height','160%');
  glowF.append('feGaussianBlur').attr('in','SourceGraphic').attr('stdDeviation','3').attr('result','blur');
  const feMerge = glowF.append('feMerge');
  feMerge.append('feMergeNode').attr('in','blur');
  feMerge.append('feMergeNode').attr('in','SourceGraphic');

  const gZoom = svg.append('g');
  const zb = d3.zoom().scaleExtent([0.05, 4])
    .on('zoom', e => gZoom.attr('transform', e.transform));
  svg.call(zb);

  const overlay = d3.select(containerEl).append('div').attr('class', 'flow-overlay-actions');
  overlay.append('button').attr('id', 'flow-expand-btn').attr('class', 'flow-action-btn').text(t('flow.expandAll'));
  overlay.append('button').attr('id', 'flow-collapse-btn').attr('class', 'flow-action-btn').text(t('flow.collapseAll'));
  overlay.append('button').attr('class', 'flow-action-btn').text(t('flow.fitView'))
    .on('click', fitView);

  const gLink = gZoom.append('g');
  const gNode = gZoom.append('g');

  function fitView() {
    const ns = root.descendants();
    if (!ns.length) return;
    let x0=Infinity, x1=-Infinity, y0=Infinity, y1=-Infinity;
    ns.forEach(d => {
      x0=Math.min(x0,(d.sx||0)-NH_HALF); x1=Math.max(x1,(d.sx||0)+NH_HALF);
      y0=Math.min(y0,d.y-NW/2);          y1=Math.max(y1,d.y+NW/2);
    });
    const PAD=70;
    const sc=Math.min(1,Math.min(viewportW/(y1-y0+PAD*2),viewportH/(x1-x0+PAD*2)));
    const readableScale = Math.max(0.55, sc);
    const tx = sc < 0.55 ? PAD - readableScale * y0 : viewportW/2-readableScale*((y0+y1)/2);
    const ty = sc < 0.55 ? PAD - readableScale * x0 : viewportH/2-readableScale*((x0+x1)/2);
    svg.transition().duration(520).call(zb.transform, d3.zoomIdentity.translate(tx, ty).scale(readableScale));
  }

  function update(src) {
    const nodes = root.descendants();
    nodes.forEach(d => { if (!d._uid) d._uid = ++uid; });
    const visCount = nodes.length;
    // V_MIN = 노드 높이+여백 → 겹침 원천 차단
    const vSpacing = Math.max(V_MIN, Math.min(82, (svgH - 120) / Math.max(2, visCount)));
    d3.tree().nodeSize([vSpacing, H_GAP])(root);
    const xs = nodes.map(d => d.x);
    const mid = (Math.min(...xs) + Math.max(...xs)) / 2;
    nodes.forEach(d => d.sx = d.x - mid + svgH/2);

    /* Links */
    gLink.selectAll('path').data(root.links(), d => d.target._uid)
      .join(
        e => e.append('path').attr('fill','none').attr('d', () => curve(src,src)),
        u => u,
        ex => ex.transition().duration(360).attr('opacity',0).remove()
      )
      .transition().duration(400)
      .attr('opacity', 1)
      .attr('stroke', d => {
        if (d.target.data.highlight) return '#f6ad55';
        if (d.target.data.highlightDescendant) return '#f6ad5588';
        const ms = d.target.data.methods;
        return (ms?.length === 1) ? `${METHOD_FILL[ms[0].method] || '#718096'}55` : '#2d3448';
      })
      .attr('stroke-width', d => {
        if (d.target.data.highlight) return 4;
        if (d.target.data.highlightDescendant) return 2.5;
        const v = d.target.value || 1;
        return Math.max(1.5, Math.min(5, v/500));
      })
      .attr('d', d => curve(d.source, d.target));

    /* Nodes */
    const nSel = gNode.selectAll('g.fn').data(nodes, d => d._uid);

    const enter = nSel.enter().append('g').attr('class', 'fn')
      .attr('transform', d => `translate(${src.y||0},${src.sx||svgH/2})`)
      .on('click', (_, d) => {
        if (!d.children && !d._children) return;
        if (d.children) { d._children = d.children; d.children = null; }
        else             { d.children = d._children; d._children = null; }
        update(d);
      })
      .on('mouseover', (e, d) => {
        const path = d.ancestors().reverse().slice(1).map(n => n.data.name).join(' › ');
        const ms = (d.data.methods||[]).map(m =>
          `<span style="color:${METHOD_FILL[m.method]};font-weight:700">${m.method}</span>&nbsp;${m.count.toLocaleString()}`
        ).join('&nbsp;&nbsp;');
        tooltip.innerHTML = `<div style="font-family:'JetBrains Mono',monospace;color:#63b3ed;margin-bottom:4px">${esc(path)}</div>${ms?ms+'<br>':''}<span style="color:#718096">${(d.value||0).toLocaleString()} calls total</span>`;
        tooltip.style.display = 'block';
      })
      .on('mousemove', e => { tooltip.style.left=(e.pageX+14)+'px'; tooltip.style.top=(e.pageY+14)+'px'; })
      .on('mouseout', () => tooltip.style.display='none')
      .style('cursor', d => (d.children||d._children)?'pointer':'default');

    enter.append('rect').attr('class','n-bg').attr('rx',6);
    enter.append('rect').attr('class','n-bar').attr('x',-NW/2).attr('y',-NH_HALF+5).attr('width',3).attr('height',NH-10).attr('rx',1.5);
    enter.append('text').attr('class','n-exp').attr('x',-NW/2+16).attr('dy','0.35em').attr('text-anchor','middle').attr('font-size',9).attr('pointer-events','none');
    enter.append('text').attr('class','n-lbl').attr('dy','0.35em').attr('text-anchor','middle').attr('font-size',11).attr('font-family','"JetBrains Mono",monospace').attr('pointer-events','none');
    enter.append('text').attr('class','n-cnt').attr('dy','0.35em').attr('text-anchor','end').attr('font-size',9).attr('font-family','"JetBrains Mono",monospace').attr('fill','#4a5568').attr('pointer-events','none');
    enter.append('g').attr('class','n-dots');

    const merged = nSel.merge(enter);
    merged.transition().duration(420).attr('transform', d => `translate(${d.y},${d.sx})`);

    merged.select('.n-bg')
      .attr('x',-NW/2).attr('y',-NH_HALF).attr('width',NW).attr('height',NH)
      .attr('fill', d => {
        if (d.data.highlight) return '#2b2114';
        if (d.data.highlightDescendant) return d.data.isDomain ? '#112334' : '#171b22';
        return d.data.name==='API'?'#0d0f14':d.data.isDomain?'#0b1d30':'#121620';
      })
      .attr('stroke', d => {
        if (d.data.highlight) return '#f6ad55';
        if (d.data.highlightDescendant) return '#dd6b20';
        if (d.data.isDomain) return '#3182ce';
        const ms = d.data.methods;
        if (ms?.length===1) return METHOD_FILL[ms[0].method]+'80';
        if (ms?.length>1)   return '#2d3a52';
        return d._children ? '#3a4460' : '#1e2535';
      })
      .attr('stroke-width', d => d.data.highlight ? 2.5 : d.data.highlightDescendant ? 2 : 1.5);

    merged.select('.n-bar')
      .attr('fill', d => {
        if (d.data.isDomain) return '#3b82f6';
        const ms = d.data.methods;
        if (ms?.length===1) return METHOD_FILL[ms[0].method];
        if (ms?.length>1)   return '#64748b';
        return '#2d3a52';
      });

    merged.select('.n-exp')
      .text(d => d._children?'▶':d.children?'▼':'')
      .attr('fill', d => d._children?'#00c04b':'#718096');

    merged.select('.n-lbl')
      .text(d => { const n=d.data.name; return n==='API'?t('flow.rootAll'):n.length>18?n.slice(0,16)+'…':n; })
      .attr('fill', d => d.data.highlight ? '#fed7aa' : d.data.isDomain?'#63b3ed':'#e2e8f0')
      .attr('font-weight', d => d.data.highlight ? 700 : d.data.isDomain?600:400);

    merged.select('.n-cnt')
      .attr('x', d => { const ms=d.data.methods||[]; return NW/2 - (ms.length?ms.length*13+8:6); })
      .text(d => d.depth>0&&d.value>0?d.value.toLocaleString():'');

    merged.each(function(d) {
      const ms = d.data.methods||[];
      const g  = d3.select(this).select('.n-dots');
      g.selectAll('*').remove();
      if (!ms.length) return;
      const R=4, GAP=13;
      let cx = NW/2 - ms.length*GAP + 2;
      ms.forEach(m => {
        g.append('circle').attr('cx',cx).attr('cy',0).attr('r',R)
          .attr('fill', METHOD_FILL[m.method]||'#718096').attr('opacity',0.9);
        cx += GAP;
      });
    });

    nSel.exit().transition().duration(320)
      .attr('opacity',0).attr('transform',`translate(${src.y||0},${src.sx||0})`).remove();
  }

  function curve(s, t) {
    const x1=s.y+NW/2, y1=s.sx??svgH/2, x2=t.y-NW/2, y2=t.sx??svgH/2;
    const mx=(x1+x2)/2;
    return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
  }

  function countPotentialNodes(node) {
    const kids = [...(node.children || []), ...(node._children || [])];
    return 1 + kids.reduce((sum, child) => sum + countPotentialNodes(child), 0);
  }

  function expandAll(node) {
    if (node._children) { node.children = node._children; node._children = null; }
    (node.children || []).forEach(expandAll);
  }

  function expandToDepth(node, maxDepth) {
    if (node.depth >= maxDepth) return;
    if (node._children) { node.children = node._children; node._children = null; }
    (node.children || []).forEach(child => expandToDepth(child, maxDepth));
  }

  function collapseAll(node) {
    (node.children || []).forEach(collapseAll);
    if (node.depth > 0 && node.children) { node._children = node.children; node.children = null; }
  }

  const expandBtn  = document.getElementById('flow-expand-btn');
  const collapseBtn = document.getElementById('flow-collapse-btn');
  if (expandBtn) {
    expandBtn.onclick = () => {
      const potential = countPotentialNodes(root);
      if (potential > FLOW_EXPAND_NODE_LIMIT) {
        expandToDepth(root, 4);
        updateFlowStats({ ...meta, note: `${fmt(potential)} nodes detected; expanded to depth 4 to keep labels readable.` });
      } else {
        expandAll(root);
      }
      update(root);
      setTimeout(fitView, 440);
    };
  }
  if (collapseBtn) collapseBtn.onclick = () => {
    collapseAll(root);
    update(root);
    setTimeout(fitView, 440);
  };

  update(root);
  setTimeout(fitView, 130);
}

/* ── Pipeline Run ─────────────────────────────────── */
let _pipelinePollTimer = null;

async function runPipeline() {
  const btn = document.getElementById('run-btn');
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.classList.add('running');
  btn.innerHTML = '<span class="spin" style="width:12px;height:12px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;display:inline-block;animation:spin .7s linear infinite"></span> ' + t('btn.running');

  try {
    const res = await fetch('/api/pipeline/run', { method: 'POST' }).then(r => r.json());
    if (!res.ok) {
      showPipelineStatus('warn', res.message || t('js.alreadyRunning'));
    }
  } catch (e) {
    showPipelineStatus('err', t('js.reqFailedShort'));
    resetRunBtn();
    return;
  }
  _pipelinePollTimer = setInterval(pollPipelineStatus, 1500);
}

async function pollPipelineStatus() {
  try {
    const s = await fetch('/api/pipeline/status').then(r => r.json());
    if (!s.running) {
      clearInterval(_pipelinePollTimer);
      _pipelinePollTimer = null;
      resetRunBtn();
      if (s.last_run_ok === true) {
        showPipelineStatus('ok', t('js.doneAt', {at: s.last_run_at}));
        await Promise.all([loadSummary(), loadCharts(), loadSpecStatus()]);
        await loadInventory();
      } else if (s.last_run_ok === false) {
        showPipelineStatus('err', t('js.failedAt', {at: s.last_run_at}));
      }
    }
  } catch (e) {
    clearInterval(_pipelinePollTimer);
    _pipelinePollTimer = null;
    resetRunBtn();
  }
}

function resetRunBtn() {
  const btn = document.getElementById('run-btn');
  if (!btn) return;
  btn.disabled = false;
  btn.classList.remove('running');
  btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg> ' + t('topbar.runNow');
}

function showPipelineStatus(type, msg) {
  const el = document.getElementById('pipeline-status');
  if (!el) return;
  el.className = 'pipeline-status ' + (type === 'ok' ? 'ok' : type === 'err' ? 'err' : '');
  el.textContent = msg;
}

/* ── Requests 탭 ──────────────────────────────────── */
const _req = { page: 1, perPage: 100, sort: 'time', order: 'desc', method: '', uri: '', dateFrom: '', dateTo: '', total: 0, timer: null, fp: null };

function initRequests() {
  const methodSel = $('#req-method');
  const uriInput  = $('#req-uri');
  const trigger   = $('#req-date-trigger');
  const resetBtn  = $('#req-date-reset');
  const displayEl = $('#req-date-display');
  const prevBtn   = $('#req-prev');
  const nextBtn   = $('#req-next');

  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const reset = () => { _req.page = 1; loadRequests(); };

  const fmtDt = d => {
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}.${p(d.getMonth()+1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  };

  const fp = flatpickr('#req-date-picker', {
    mode: 'range',
    enableTime: true,
    time_24hr: true,
    minuteIncrement: 1,
    disableMobile: true,
    positionElement: trigger,
    onChange(dates) {
      if (dates.length === 2) {
        const pad = n => String(n).padStart(2, '0');
        const fmt = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
        _req.dateFrom = fmt(dates[0]) + ':00';
        _req.dateTo   = fmt(dates[1]) + ':59+09:00';
        if (displayEl) displayEl.textContent = `${fmtDt(dates[0])} ~ ${fmtDt(dates[1])}`;
        if (trigger) trigger.classList.add('has-value');
        _req.page = 1;
        loadRequests();
      } else if (dates.length < 2) {
        if (displayEl) displayEl.textContent = dates.length === 1
          ? `${fmtDt(dates[0])} ~`
          : t('js.selectRange');
      }
    },
    onClose(dates) {
      if (dates.length === 1) {
        fp.clear();
        _req.dateFrom = ''; _req.dateTo = '';
        if (displayEl) displayEl.textContent = t('js.selectRange');
        if (trigger) trigger.classList.remove('has-value');
      }
    },
  });
  _req.fp = fp;

  if (trigger) trigger.addEventListener('click', e => {
    if (!e.target.closest('#req-date-reset')) fp.open();
  });

  if (resetBtn) resetBtn.addEventListener('click', () => {
    fp.clear();
    _req.dateFrom = ''; _req.dateTo = '';
    if (displayEl) displayEl.textContent = t('js.selectRange');
    if (trigger) trigger.classList.remove('has-value');
    reset();
  });

  if (methodSel) methodSel.addEventListener('change', () => { _req.method = methodSel.value; reset(); });
  if (uriInput)  uriInput.addEventListener('input', debounce(() => { _req.uri = uriInput.value.trim(); reset(); }, 300));
  if (prevBtn) prevBtn.addEventListener('click', () => { if (_req.page > 1) { _req.page--; loadRequests(); } });
  if (nextBtn) nextBtn.addEventListener('click', () => { const maxPage = Math.ceil(_req.total / _req.perPage); if (_req.page < maxPage) { _req.page++; loadRequests(); } });

  $$('.page-size-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _req.perPage = parseInt(btn.dataset.size, 10);
      _req.page = 1;
      $$('.page-size-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      loadRequests();
    });
  });

  $$('[data-rsort]').forEach(th => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
      const col = th.dataset.rsort;
      if (_req.sort === col) { _req.order = _req.order === 'desc' ? 'asc' : 'desc'; }
      else { _req.sort = col; _req.order = 'desc'; }
      _req.page = 1;
      loadRequests();
    });
  });
}

function updateReqSortIndicators() {
  $$('[data-rsort]').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.rsort === _req.sort) {
      th.classList.add(_req.order === 'asc' ? 'sort-asc' : 'sort-desc');
    }
  });
}

async function loadRequests() {
  const params = new URLSearchParams({
    page: _req.page, per_page: _req.perPage,
    sort: _req.sort, order: _req.order,
    method: _req.method, uri: _req.uri,
  });
  if (_req.dateFrom) params.set('date_from', _req.dateFrom);
  if (_req.dateTo)   params.set('date_to',   _req.dateTo);
  updateReqSortIndicators();
  const data = await fetch(`/api/logs?${params}`).then(r => r.json()).catch(() => null);
  if (!data) return;

  _req.total = data.total;

  const totalLabel = $('#req-total-label');
  if (totalLabel) totalLabel.textContent = t('js.totalCount', {n: fmt(data.total)});

  const pageLabel = $('#req-page-label');
  if (pageLabel) {
    const maxPage = Math.max(1, Math.ceil(data.total / _req.perPage));
    pageLabel.textContent = `${_req.page} / ${maxPage}`;
  }
  const prevBtn = $('#req-prev');
  const nextBtn = $('#req-next');
  if (prevBtn) prevBtn.disabled = _req.page <= 1;
  if (nextBtn) nextBtn.disabled = _req.page >= Math.ceil(data.total / _req.perPage);

  const tbody = $('#req-tbody');
  if (!tbody) return;

  const fmtTime = iso => {
    if (!iso) return '—';
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}.${pad(d.getMonth()+1)}.${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  };

  const statusClass = s => s >= 500 ? 'red' : s >= 400 ? 'warn' : s >= 300 ? 'blue' : 'green';
  const methodColor = { GET:'#4a9eff', POST:'#f59e0b', PUT:'#8b5cf6', DELETE:'#ef4444', PATCH:'#10b981' };

  tbody.innerHTML = data.rows.map(r => {
    const rt = r.request_time != null ? Math.round(r.request_time * 1000) : '—';
    const domain = r.host || '—';
    const auth = r.has_auth ? `<span class="badge-auth">${t('badge.auth')}</span>` : '';
    const color = methodColor[r.method] || '#888';
    return `<tr>
      <td class="mono">${fmtTime(r.time)}</td>
      <td><span class="method-badge" style="background:${color}22;color:${color}">${esc(r.method)}</span></td>
      <td class="uri-cell" title="${esc(r.uri)}">${esc(r.normalized_uri || r.uri)}</td>
      <td><span class="status-badge ${statusClass(r.status)}">${r.status}</span></td>
      <td class="mono">${esc(r.remote_addr)}</td>
      <td class="mono">${rt}</td>
      <td class="domain-cell">${esc(domain)}</td>
      <td>${auth}</td>
    </tr>`;
  }).join('');
}

/* ── Users (계정 관리, admin 전용) ────────────────── */
async function loadUsers() {
  let list = [];
  try { list = await fetch('/api/users').then(r => r.ok ? r.json() : []); }
  catch (e) { list = []; }
  renderUsersTable(list);
}

function renderUsersTable(list) {
  const tbody = $('#users-tbody');
  if (!tbody) return;
  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="3" class="users-empty">${t('js.noAccounts')}</td></tr>`;
    return;
  }
  tbody.innerHTML = list.map(u => `
    <tr>
      <td class="mono">${esc(u.username)}</td>
      <td><span class="role-badge role-${u.role === 'admin' ? 'admin' : 'viewer'}">${esc(u.role)}</span></td>
      <td class="users-actions">
        <button class="users-mini" data-user-pw="${esc(u.username)}">${t('js.changePw')}</button>
        <button class="users-mini danger" data-user-del="${esc(u.username)}">${t('js.delete')}</button>
      </td>
    </tr>`).join('');
}

function showUsersMsg(msg, kind) {
  const el = $('#users-msg');
  if (!el) return;
  el.textContent = msg || '';
  el.className = 'users-msg ' + (kind || '');
  if (msg) setTimeout(() => {
    if (el.textContent === msg) { el.textContent = ''; el.className = 'users-msg'; }
  }, 4000);
}

async function createUser() {
  const name = ($('#new-user-name').value || '').trim();
  const role = $('#new-user-role').value;
  const pw = $('#new-user-pw').value || '';
  if (!name || !pw) { showUsersMsg(t('js.needCredentials'), 'err'); return; }
  try {
    const res = await fetch('/api/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: name, role, password: pw }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { showUsersMsg(data.detail || t('js.addFailed', {msg: ''}), 'err'); return; }
    showUsersMsg(t('js.accountAdded', {name: name}), 'ok');
    $('#new-user-name').value = '';
    $('#new-user-pw').value = '';
    loadUsers();
  } catch (e) { showUsersMsg(t('js.networkError', {msg: e.message}), 'err'); }
}

async function deleteUser(name) {
  if (!confirm(t('js.confirmDelete', {name: name}))) return;
  try {
    const res = await fetch(`/api/users/${encodeURIComponent(name)}`, { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { showUsersMsg(data.detail || t('js.deleteFailed'), 'err'); return; }
    showUsersMsg(t('js.accountDeleted', {name: name}), 'ok');
    loadUsers();
  } catch (e) { showUsersMsg(t('js.networkError', {msg: e.message}), 'err'); }
}

async function changeUserPassword(name) {
  const pw = prompt(t('js.promptNewPw', {name: name}));
  if (pw == null) return;
  if (pw.length < 8) { showUsersMsg(t('js.pwTooShort'), 'err'); return; }
  try {
    const res = await fetch(`/api/users/${encodeURIComponent(name)}/password`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { showUsersMsg(data.detail || t('js.changeFailed'), 'err'); return; }
    showUsersMsg(t('js.pwChanged', {name: name}), 'ok');
  } catch (e) { showUsersMsg(t('js.networkError', {msg: e.message}), 'err'); }
}

function initUsers() {
  const addBtn = $('#user-add-btn');
  if (addBtn) addBtn.addEventListener('click', createUser);
  const pw = $('#new-user-pw');
  if (pw) pw.addEventListener('keydown', e => { if (e.key === 'Enter') createUser(); });
  const tbody = $('#users-tbody');
  if (tbody) tbody.addEventListener('click', e => {
    const del = e.target.closest('[data-user-del]');
    if (del) return deleteUser(del.getAttribute('data-user-del'));
    const cpw = e.target.closest('[data-user-pw]');
    if (cpw) return changeUserPassword(cpw.getAttribute('data-user-pw'));
  });
}

/* ── 인증/역할 ────────────────────────────────────── */
async function loadMe() {
  let me = null;
  try { me = await fetch('/api/me').then(r => r.ok ? r.json() : null); }
  catch (e) { me = null; }
  if (!me) return;
  // admin이면 admin-only 컨트롤 노출 (로컬 모드는 role=admin으로 전권)
  document.body.classList.toggle('is-admin', me.role === 'admin');
  const box = document.getElementById('user-box');
  if (me.auth_enabled && box) {
    const chip = document.getElementById('user-chip');
    if (chip) chip.textContent = `${me.username} · ${me.role}`;
    box.hidden = false;
  }
}

/* ── 초기화 ───────────────────────────────────────── */
async function init() {
  await I18n.init();          // 카탈로그를 먼저 올려야 첫 렌더가 올바른 언어로 나온다
  await loadMe();
  initTabs();
  initTableControls();
  initFlowControls();
  initUpload();
  initRequests();
  initUsers();
  await Promise.all([loadSummary(), loadCharts(), loadSpecStatus(), loadAgents()]);
  await loadInventory();

  setInterval(loadAgents, 30000);

  const clock = document.getElementById('clock');
  if (clock) { const tick = () => { clock.textContent = new Date().toLocaleTimeString(); }; tick(); setInterval(tick, 1000); }

  /* data-i18n 이 붙은 정적 요소는 I18n.apply() 가 처리하지만, 표·카드처럼
     JS 가 그려낸 내용은 다시 렌더해야 언어가 바뀐다. */
  window.addEventListener('languagechange', () => {
    loadSummary();
    loadSpecStatus();
    loadAgents();
    renderTable();
    if (typeof loadAnomalies === 'function') loadAnomalies();

    /* 도메인 필터는 JS 가 채우므로 첫 옵션 문구만 바꾼다. 통째로 다시 채우면
       사용자가 고른 도메인이 초기화된다. */
    ['table-domain', 'flow-domain'].forEach(id => {
      const opt = document.getElementById(id)?.querySelector('option[value=""]');
      if (opt) opt.textContent = t('filter.allDomains');
    });

    /* Flow 는 d3 로 그려져 data-i18n 이 닿지 않는다. 탭이 이미 그려져 있을 때만 다시 그린다. */
    if (state.flow?.data && document.querySelector('#flow-tree svg')) loadFlow();
  });
}

document.addEventListener('DOMContentLoaded', init);
