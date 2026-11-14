'use strict';

/* ==========================================================================
   Tauronizer — frontend bez frameworków i zależności zewnętrznych.
   ========================================================================== */

const DAYS = ['Pn', 'Wt', 'Śr', 'Cz', 'Pt', 'So', 'Nd'];
const MONTHS = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru'];
const MONTHS_FULL = ['styczeń', 'luty', 'marzec', 'kwiecień', 'maj', 'czerwiec', 'lipiec', 'sierpień', 'wrzesień', 'październik', 'listopad', 'grudzień'];
const QUICK_TABS = new Set(['analysis', 'tariffs', 'history']);

const state = {
  config: null,
  entities: [],
  tariffs: [],
  analysis: null,
  analyses: [],
  selectedTariffs: new Set(),
  knownTariffIds: new Set(),
  selectionInitialized: false,
  busy: false,
  editingTariff: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const plnFormatter = new Intl.NumberFormat('pl-PL', {
  style: 'currency',
  currency: 'PLN',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const numberFormatter = new Intl.NumberFormat('pl-PL', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[character]));
}

function formatPLN(value) {
  const number = Number(value);
  return Number.isFinite(number) ? plnFormatter.format(number) : '—';
}

function formatNumber(value, digits = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return new Intl.NumberFormat('pl-PL', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(number);
}

function plural(count, one, few, many) {
  const absolute = Math.abs(Number(count)) || 0;
  const lastTwo = absolute % 100;
  const last = absolute % 10;
  if (absolute === 1) return one;
  if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) return few;
  return many;
}

function formatDate(isoDate) {
  if (!isoDate) return '—';
  const parts = String(isoDate).slice(0, 10).split('-');
  if (parts.length !== 3) return isoDate;
  return `${parts[2]}.${parts[1]}.${parts[0]}`;
}

function toISODate(dateObject) {
  const year = dateObject.getFullYear();
  const month = String(dateObject.getMonth() + 1).padStart(2, '0');
  const day = String(dateObject.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function parseISODate(isoDate) {
  const [year, month, day] = isoDate.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function addDays(dateObject, days) {
  const copy = new Date(dateObject);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function today() {
  const parts = new Intl.DateTimeFormat('pl-PL', {
    timeZone: 'Europe/Warsaw',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const value = (type) => Number(parts.find((part) => part.type === type)?.value);
  return new Date(value('year'), value('month') - 1, value('day'));
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

/* ---------------------------------------------------------------- network */

function normalizeBasePath() {
  let path = window.location.pathname;
  if (path.endsWith('/index.html')) path = path.slice(0, -'index.html'.length);
  if (!path.endsWith('/')) path += '/';
  if (path !== window.location.pathname) {
    window.history.replaceState(null, '', path + window.location.search + window.location.hash);
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (error) {
      data = { detail: text };
    }
  }
  if (!response.ok) {
    let message = data && data.detail;
    if (Array.isArray(message)) {
      message = message
        .map((item) => {
          const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join('.') : '';
          return `${field ? field + ': ' : ''}${item.msg || 'nieprawidłowa wartość'}`;
        })
        .join('; ');
    }
    if (!message) message = `Błąd HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return data;
}

/* ------------------------------------------------------------------ toast */

function toast(message, type = 'info', duration = 5000) {
  const root = $('#toast-root');
  if (!root) return;
  while (root.children.length >= 4) root.firstElementChild.remove();
  const element = document.createElement('div');
  element.className = `toast ${type}`;
  element.textContent = message;
  root.appendChild(element);
  window.setTimeout(() => {
    element.classList.add('is-leaving');
    window.setTimeout(() => element.remove(), 220);
  }, duration);
}

/* ------------------------------------------------------------------ tabs */

function switchTab(tab) {
  if (!QUICK_TABS.has(tab)) tab = 'analysis';
  $$('.tab-button').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.tab === tab);
  });
  $$('.tab-panel').forEach((panel) => {
    panel.hidden = panel.id !== `tab-${tab}`;
  });
  const hash = tab === 'analysis' ? '' : `#${tab}`;
  const target = window.location.pathname + window.location.search + hash;
  if (window.location.pathname + window.location.search + window.location.hash !== target) {
    window.history.replaceState(null, '', target);
  }
  if (tab === 'history') loadHistory();
}

/* ------------------------------------------------------------------ theme */

function bindTheme() {
  const button = $('#theme-toggle');
  if (!button) return;
  const syncLabel = () => {
    const dark = document.documentElement.dataset.theme === 'dark';
    button.setAttribute('aria-pressed', String(dark));
    button.setAttribute('title', dark ? 'Włącz jasny motyw' : 'Włącz ciemny motyw');
  };
  syncLabel();
  button.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem('tauronizer-theme', next);
    } catch (error) {
      /* storage may be disabled */
    }
    syncLabel();
  });
}

/* ------------------------------------------------------------- date ranges */

function setDateRange(start, end, activeButton = null) {
  $('#date-start').value = toISODate(start);
  $('#date-end').value = toISODate(end);
  $$('#quick-ranges button').forEach((button) => button.classList.toggle('is-active', button === activeButton));
}

function bindDateControls() {
  const startInput = $('#date-start');
  const endInput = $('#date-end');
  [startInput, endInput].forEach((input) => {
    input.addEventListener('change', () => {
      $$('#quick-ranges button').forEach((button) => button.classList.remove('is-active'));
    });
  });

  $('#quick-ranges').addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button) return;
    const end = today();
    if (button.dataset.days) {
      setDateRange(addDays(end, -(Number(button.dataset.days) - 1)), end, button);
      return;
    }
    if (button.dataset.range === 'year') {
      setDateRange(new Date(end.getFullYear(), 0, 1), end, button);
      return;
    }
    if (button.dataset.range === 'prev-year') {
      const year = end.getFullYear() - 1;
      setDateRange(new Date(year, 0, 1), new Date(year, 11, 31), button);
    }
  });
}

/* ------------------------------------------------------------------- data */

async function loadConfig() {
  try {
    const config = await api('api/config');
    state.config = config;
    const badge = $('#mode-badge');
    badge.textContent = config.mode === 'supervisor' ? 'Home Assistant' : 'Tryb samodzielny';
    badge.title = config.mode === 'supervisor'
      ? 'Połączono przez Supervisor — encje i statystyki z Home Assistant.'
      : 'Tryb samodzielny (HA_URL / HA_TOKEN).';
    $('#app-version').textContent = `v${config.version}`;
    $('#tariff-disclaimer').innerHTML = `
      <span><strong>Zanim porównasz:</strong> ${escapeHtml(config.disclaimer)}
      Wbudowane taryfy (G11, G12, G12w, G13) są edytowalne — możesz też skopiować preset
      i dopasować go do własnej umowy.</span>`;
  } catch (error) {
    toast(`Nie udało się wczytać konfiguracji: ${error.message}`, 'error', 8000);
  }
}

async function loadEntities() {
  const select = $('#entity-select');
  const hint = $('#entity-hint');
  try {
    const data = await api('api/entities');
    state.entities = data.entities || [];
    const saved = localStorage.getItem('tauronizer-entity');

    select.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = state.entities.length
      ? 'Wybierz encję zużycia energii…'
      : 'Brak sensorów energii';
    select.appendChild(placeholder);

    state.entities.forEach((entity) => {
      const option = document.createElement('option');
      option.value = entity.entity_id;
      option.textContent = `${entity.name} — ${entity.entity_id}`;
      select.appendChild(option);
    });

    if (saved && state.entities.some((entity) => entity.entity_id === saved)) {
      select.value = saved;
    } else if (state.entities.length === 1) {
      select.value = state.entities[0].entity_id;
    }

    updateEntityHint();
    if (!state.entities.length) {
      hint.textContent = 'Nie znaleziono sensorów energii. Sprawdź, czy encja ma device_class: energy lub state_class: total_increasing.';
    }
  } catch (error) {
    select.innerHTML = '<option value="">Brak dostępu do encji</option>';
    hint.textContent = error.message;
    toast(`Nie udało się pobrać encji: ${error.message}`, 'error', 9000);
  }
}

function updateEntityHint() {
  const select = $('#entity-select');
  const hint = $('#entity-hint');
  const entity = state.entities.find((item) => item.entity_id === select.value);
  if (entity) {
    hint.textContent = `${entity.entity_id} · jednostka: ${entity.unit || 'kWh'} · stan: ${entity.state ?? '—'}`;
  } else if (state.entities.length) {
    hint.textContent = `${state.entities.length} ${plural(state.entities.length, 'sensor', 'sensory', 'sensorów')} energii. Wybierz ten, który mierzy całkowite zużycie domu.`;
  }
}

async function loadTariffs() {
  try {
    const data = await api('api/tariffs');
    state.tariffs = data.tariffs || [];
    const ids = new Set(state.tariffs.map((tariff) => tariff.id));

    if (!state.selectionInitialized) {
      state.selectedTariffs = new Set(ids);
      state.selectionInitialized = true;
    } else {
      state.tariffs.forEach((tariff) => {
        if (!state.knownTariffIds.has(tariff.id)) state.selectedTariffs.add(tariff.id);
      });
      Array.from(state.selectedTariffs).forEach((id) => {
        if (!ids.has(id)) state.selectedTariffs.delete(id);
      });
    }
    state.knownTariffIds = ids;

    renderTariffChips();
    renderTariffGrid();
    updateToggleLabel();
  } catch (error) {
    $('#tariff-chips').innerHTML = '<span class="muted small">Nie udało się wczytać taryf.</span>';
    $('#tariff-grid').innerHTML = `<div class="empty-state card"><p class="muted">${escapeHtml(error.message)}</p></div>`;
    toast(`Nie udało się pobrać taryf: ${error.message}`, 'error', 8000);
  }
}

async function loadHistory() {
  const container = $('#history-list');
  try {
    const data = await api('api/analyses');
    state.analyses = data.analyses || [];
    renderHistory();
  } catch (error) {
    container.innerHTML = `<div class="empty-state card"><p class="muted">${escapeHtml(error.message)}</p></div>`;
  }
}

/* ------------------------------------------------------------------ chips */

function renderTariffChips() {
  const container = $('#tariff-chips');
  if (!state.tariffs.length) {
    container.innerHTML = '<span class="muted small">Brak taryf. Dodaj taryfę w zakładce „Taryfy”.</span>';
    return;
  }
  container.innerHTML = state.tariffs.map((tariff) => {
    const active = state.selectedTariffs.has(tariff.id);
    return `
      <label class="chip ${active ? 'is-active' : ''}">
        <input type="checkbox" value="${escapeHtml(tariff.id)}" ${active ? 'checked' : ''}>
        <span>${escapeHtml(tariff.name)}</span>
      </label>`;
  }).join('');
}

function updateToggleLabel() {
  const button = $('#toggle-tariffs');
  if (!button) return;
  const allSelected = state.tariffs.length > 0
    && state.tariffs.every((tariff) => state.selectedTariffs.has(tariff.id));
  button.textContent = allSelected ? 'Odznacz wszystkie' : 'Zaznacz wszystkie';
}

function bindTariffChips() {
  $('#tariff-chips').addEventListener('change', (event) => {
    const input = event.target.closest('input[type="checkbox"]');
    if (!input) return;
    if (input.checked) state.selectedTariffs.add(input.value);
    else state.selectedTariffs.delete(input.value);
    input.closest('.chip')?.classList.toggle('is-active', input.checked);
    updateToggleLabel();
  });

  $('#toggle-tariffs').addEventListener('click', () => {
    const allSelected = state.tariffs.length > 0
      && state.tariffs.every((tariff) => state.selectedTariffs.has(tariff.id));
    state.selectedTariffs = allSelected ? new Set() : new Set(state.tariffs.map((tariff) => tariff.id));
    $$('#tariff-chips input[type="checkbox"]').forEach((input) => {
      input.checked = !allSelected;
      input.closest('.chip')?.classList.toggle('is-active', !allSelected);
    });
    updateToggleLabel();
  });
}

/* --------------------------------------------------------------- analysis */

function setAnalyzing(busy) {
  state.busy = busy;
  const button = $('#analyze-button');
  button.disabled = busy;
  button.innerHTML = busy
    ? '<span class="spinner"></span> Analizuję…'
    : `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z"></path></svg> Analizuj zużycie`;
}

async function handleAnalyze(event) {
  event.preventDefault();
  if (state.busy) return;

  const entityId = $('#entity-select').value;
  const start = $('#date-start').value;
  const end = $('#date-end').value;
  const tariffIds = Array.from(state.selectedTariffs);

  if (!entityId) return toast('Wybierz encję zużycia energii.', 'error');
  if (!start || !end) return toast('Uzupełnij zakres dat.', 'error');
  if (start > end) return toast('Data początkowa jest późniejsza niż końcowa.', 'error');
  if (!tariffIds.length) return toast('Zaznacz co najmniej jedną taryfę.', 'error');

  setAnalyzing(true);
  const status = $('#analyze-status');
  const startedAt = Date.now();
  status.textContent = 'Pobieram statystyki z Home Assistant…';
  const ticker = window.setInterval(() => {
    status.textContent = `Analizuję… ${Math.round((Date.now() - startedAt) / 1000)} s`;
  }, 1000);

  try {
    const result = await api('api/analyze', {
      method: 'POST',
      body: JSON.stringify({ entity_id: entityId, start, end, tariff_ids: tariffIds }),
    });
    state.analysis = result;
    try {
      localStorage.setItem('tauronizer-entity', entityId);
    } catch (error) {
      /* ignore */
    }
    renderAnalysis(result);
    status.textContent = `Gotowe w ${((Date.now() - startedAt) / 1000).toFixed(1)} s`;
    loadHistory();
    window.setTimeout(() => {
      $('#analysis-results')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 80);
  } catch (error) {
    status.textContent = '';
    toast(error.message, 'error', 9000);
  } finally {
    window.clearInterval(ticker);
    setAnalyzing(false);
  }
}

function renderAnalysis(result) {
  const container = $('#analysis-results');
  const allTariffs = result.tariffs || [];
  const valid = allTariffs.filter((tariff) => !tariff.error);
  const failed = allTariffs.filter((tariff) => tariff.error);

  if (!valid.length) {
    container.innerHTML = `<div class="empty-state card">
      <div class="empty-icon">⚠️</div>
      <h3>Nie udało się policzyć żadnej taryfy</h3>
      <p class="muted">${escapeHtml(failed[0]?.error || 'Brak danych do obliczeń.')}</p>
    </div>`;
    return;
  }

  const cheapest = valid[0];
  const runnerUp = valid[1];
  const maxTotal = Math.max(...valid.map((tariff) => Number(tariff.total_pln) || 0), 0.01);
  const isTie = Boolean(result.is_tie) && runnerUp;
  const warnings = Array.isArray(result.warnings) ? result.warnings : [];

  const warningBlock = (warnings.length || failed.length) ? `
    <div class="warn-list">
      <strong>Uwagi do danych</strong>
      <ul>
        ${warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join('')}
        ${failed.map((tariff) => `<li>Nie policzono „${escapeHtml(tariff.name)}”: ${escapeHtml(tariff.error)}</li>`).join('')}
      </ul>
    </div>` : '';

  const heroSaving = valid.length > 1
    ? `<div class="hero-saving">
         <span>${isTie ? 'Różnica do drugiej opcji' : 'Oszczędność wobec najdroższej'}</span>
         <strong>${formatPLN(isTie ? runnerUp.total_pln - cheapest.total_pln : result.max_savings_pln)}</strong>
         <span>${isTie ? 'praktycznie remis' : 'w analizowanym okresie'}</span>
       </div>`
    : `<div class="hero-saving">
         <span>Porównanie</span>
         <strong>—</strong>
         <span>zaznacz więcej taryf</span>
       </div>`;

  const bars = valid.map((tariff) => {
    const width = Math.max(2, (Number(tariff.total_pln) / maxTotal) * 100);
    const delta = tariff.rank === 1
      ? 'najtaniej'
      : `+${formatPLN(tariff.extra_cost_pln)}`;
    return `
      <div class="bar-row ${tariff.rank === 1 ? 'is-best' : ''}">
        <div class="bar-label"><span class="rank">${tariff.rank}.</span> ${escapeHtml(tariff.name)}
          ${tariff.is_preset ? '<span class="badge subtle">preset</span>' : ''}
        </div>
        <div class="bar-track"><div class="bar-fill" style="width:${width.toFixed(2)}%"></div></div>
        <div class="bar-value">${formatPLN(tariff.total_pln)}</div>
        <div class="bar-delta">${delta}</div>
      </div>`;
  }).join('');

  const breakdownLabels = [
    ['Energia czynna netto (bez akcyzy)', 'energy_pln'],
    ['Dystrybucja netto', 'distribution_pln'],
    ['Opłaty zmienne netto', 'variable_fees_pln'],
    ['Akcyza', 'excise_pln'],
    ['Opłaty stałe netto', 'fixed_pln'],
    ['Opłata mocowa netto', 'capacity_fee_pln'],
    ['Netto', 'net_pln'],
    ['VAT', 'vat_pln'],
    ['Razem brutto', 'total_pln'],
  ];

  const details = valid.map((tariff) => {
    const breakdown = tariff.breakdown || {};
    const breakdownRows = breakdownLabels.map(([label, key]) => {
      const isTotal = key === 'total_pln';
      return `<div class="${isTotal ? 'total' : ''}"><dt>${label}</dt><dd>${formatPLN(breakdown[key] ?? 0)}</dd></div>`;
    }).join('');

    const zoneRows = (tariff.zones || []).map((zone) => `
      <tr>
        <td>${escapeHtml(zone.name)}</td>
        <td>${formatNumber(zone.kwh, 2)}</td>
        <td>${formatNumber(zone.share_percent, 1)}%</td>
        <td>${formatPLN(zone.energy_pln)}</td>
        <td>${formatPLN(zone.distribution_pln)}</td>
      </tr>`).join('');

    return `
      <details class="details" ${tariff.rank === 1 ? 'open' : ''}>
        <summary>
          <span>${tariff.rank}. ${escapeHtml(tariff.name)}</span>
          ${tariff.is_preset ? '<span class="badge subtle">preset</span>' : ''}
          ${tariff.extra_cost_pln > 0 ? `<span class="muted small">+${formatPLN(tariff.extra_cost_pln)}</span>` : ''}
          <span class="summary-cost">${formatPLN(tariff.total_pln)}</span>
        </summary>
        <div class="details-body">
          <div class="details-columns">
            <div>
              <h4>Zużycie według stref</h4>
              <div class="table-wrap">
                <table class="data-table">
                  <thead><tr><th>Strefa</th><th>kWh</th><th>Udział</th><th>Energia netto</th><th>Dystrybucja netto</th></tr></thead>
                  <tbody>${zoneRows || '<tr><td colspan="5">Brak zużycia w okresie.</td></tr>'}</tbody>
                </table>
              </div>
            </div>
            <div>
              <h4>Składniki rachunku</h4>
              <dl class="breakdown">${breakdownRows}</dl>
              ${tariff.capacity_fee ? `<p class="muted small">Opłata mocowa: ${formatPLN(tariff.capacity_fee.net_monthly)}/mies. netto.
                Podstawa: ${formatNumber(tariff.capacity_fee.annual_kwh, 1)} kWh
                (${tariff.capacity_fee.estimated ? 'szacunek roczny z wybranego okresu' : 'pobór wpisany w konfiguracji'}).</p>` : ''}
              <p class="muted small" style="margin-top:10px">Szacunek w skali roku: <strong>${formatPLN(tariff.annual_pln)}</strong></p>
            </div>
          </div>
        </div>
      </details>`;
  }).join('');

  const profile = result.profile || {};
  const profileValues = Array.isArray(profile.weekday_hour_kwh) ? profile.weekday_hour_kwh : [];
  const profileMax = Number(profile.max_cell_kwh) || 0;

  let heatmap = '';
  if (profileValues.length === 7) {
    let cells = '<div></div>';
    for (let hour = 0; hour < 24; hour += 1) {
      cells += `<div class="heatmap-hour">${hour % 3 === 0 ? hour : ''}</div>`;
    }
    profileValues.forEach((row, dayIndex) => {
      cells += `<div class="heatmap-day">${DAYS[dayIndex]}</div>`;
      row.forEach((value, hour) => {
        const numeric = Number(value) || 0;
        const ratio = profileMax > 0 ? numeric / profileMax : 0;
        const alpha = numeric > 0 ? Math.min(0.92, 0.12 + ratio * 0.8) : 0;
        const style = alpha > 0 ? ` style="background:rgba(232,147,12,${alpha.toFixed(3)})"` : '';
        const label = `${DAYS[dayIndex]} ${String(hour).padStart(2, '0')}:00 — ${formatNumber(numeric, 2)} kWh`;
        cells += `<div class="heatmap-cell"${style} title="${escapeHtml(label)}"></div>`;
      });
    });
    heatmap = `
      <div class="heatmap">
        <div class="heatmap-grid">${cells}</div>
        <div class="legend">
          <span>0 kWh</span>
          <span class="legend-gradient"></span>
          <span>${formatNumber(profileMax, 2)} kWh</span>
        </div>
      </div>`;
  }

  const monthly = Array.isArray(result.monthly_kwh) ? result.monthly_kwh : [];
  let monthlyChart = '';
  if (monthly.length > 1) {
    const monthlyMax = Math.max(...monthly.map((item) => Number(item.kwh) || 0), 0.01);
    const barsHtml = monthly.map((item) => {
      const [year, month] = String(item.month).split('-').map(Number);
      const label = new Date(year, month - 1, 1).toLocaleDateString('pl-PL', { month: 'short', year: '2-digit' });
      const height = Math.max(3, ((Number(item.kwh) || 0) / monthlyMax) * 100);
      return `<div class="month-bar" title="${escapeHtml(item.month)}: ${formatNumber(item.kwh, 1)} kWh">
        <div class="month-bar-track"><div class="month-bar-fill" style="height:${height.toFixed(1)}%"></div></div>
        <span>${escapeHtml(label)}</span>
      </div>`;
    }).join('');
    monthlyChart = `
      <div class="card-head" style="margin-top:22px;margin-bottom:0">
        <h3>Zużycie miesięczne</h3>
        <span class="muted small">kWh</span>
      </div>
      <div class="month-bars">${barsHtml}</div>`;
  }

  container.innerHTML = `
    <div class="result-meta">
      <span><strong>${escapeHtml(result.entity_name || result.entity_id)}</strong>
        <span class="muted">(${escapeHtml(result.entity_id)})</span></span>
      <span>${formatDate(result.start)} – ${formatDate(result.end)} · ${result.days} dni</span>
      <span><strong>${formatNumber(result.total_kwh, 2)} kWh</strong></span>
      <span>${valid.length} ${plural(valid.length, 'taryfa', 'taryfy', 'taryf')} w porównaniu</span>
    </div>

    ${warningBlock}

    <div class="result-hero">
      <div class="hero-main">
        <span class="eyebrow">${isTie ? 'Remis na szczycie' : 'Najtańsza taryfa'}</span>
        <h2>${escapeHtml(cheapest.name)}
          ${cheapest.is_preset ? '<span class="badge">preset</span>' : ''}
        </h2>
        <p class="muted">${escapeHtml(cheapest.description || 'Taryfa własna.')}</p>
        <div class="hero-metrics">
          <div><span>Koszt w okresie</span><strong>${formatPLN(cheapest.total_pln)}</strong></div>
          <div><span>Szacunek roczny</span><strong>${formatPLN(cheapest.annual_pln)}</strong></div>
          <div><span>Średnia cena</span><strong>${formatNumber(cheapest.per_kwh_pln, 3)} zł/kWh</strong></div>
        </div>
      </div>
      ${heroSaving}
    </div>

    <section class="card">
      <div class="card-head">
        <h3>Porównanie kosztów</h3>
        <span class="muted small">pełny rachunek z opłatami stałymi i VAT</span>
      </div>
      <div class="bars">${bars}</div>
    </section>

    <section class="card">
      <div class="card-head">
        <h3>Szczegóły rachunku</h3>
        <span class="muted small">kliknij taryfę, aby rozwinąć</span>
      </div>
      <div class="tariff-details">${details}</div>
    </section>

    <section class="card">
      <div class="card-head">
        <h3>Profil zużycia</h3>
        <span class="muted small">średnie zużycie w podziale na dzień tygodnia i godzinę</span>
      </div>
      ${heatmap || '<p class="muted small">Brak danych profilu.</p>'}
      ${monthlyChart}
    </section>

    <p class="methodology">${escapeHtml(result.methodology || '')}</p>
  `;
}

/* ----------------------------------------------------------------- taryfy */

function tariffPriceRange(tariff) {
  const config = tariff.config || {};
  const extras = (config.variable_fees || []).reduce((sum, fee) => sum + (Number(fee.net_per_kwh) || 0), 0)
    + (Number(config.excise_net_per_kwh) || 0);
  const vatMultiplier = 1 + (Number(config.vat_percent ?? 23) || 0) / 100;
  const prices = (config.zones || [])
    .map((zone) => (Number(zone.energy_net) + Number(zone.distribution_net) + extras) * vatMultiplier)
    .filter((value) => Number.isFinite(value));
  if (!prices.length) return null;
  return { min: Math.min(...prices), max: Math.max(...prices) };
}

function monthsLabel(months) {
  if (!Array.isArray(months) || !months.length || months.length >= 12) return '';
  const sorted = [...new Set(months)].filter((month) => month >= 1 && month <= 12).sort((a, b) => a - b);
  if (sorted.length >= 12) return '';
  const parts = [];
  let start = sorted[0];
  let prev = sorted[0];
  for (let index = 1; index <= sorted.length; index += 1) {
    const current = sorted[index];
    if (current === prev + 1) {
      prev = current;
      continue;
    }
    parts.push(start === prev ? MONTHS[start - 1] : `${MONTHS[start - 1]}–${MONTHS[prev - 1]}`);
    start = current;
    prev = current;
  }
  return parts.join(', ');
}

function zoneSchedule(zone) {
  const days = (zone.days || []).map((day) => DAYS[day]).join(', ');
  const intervals = (zone.intervals || []).join(', ');
  const months = monthsLabel(zone.months);
  return `${days} · ${intervals}${months ? ` · mies.: ${months}` : ''}`;
}

function renderTariffGrid() {
  const grid = $('#tariff-grid');
  if (!state.tariffs.length) {
    grid.innerHTML = `<div class="empty-state card">
      <div class="empty-icon">🧾</div>
      <h3>Brak zdefiniowanych taryf</h3>
      <p class="muted">Dodaj własną taryfę albo przywróć presety Tauron.</p>
      <button class="button primary" type="button" id="empty-new-tariff">+ Nowa taryfa</button>
    </div>`;
    $('#empty-new-tariff')?.addEventListener('click', () => openTariffEditor(null));
    return;
  }

  grid.innerHTML = state.tariffs.map((tariff) => {
    const config = tariff.config || {};
    const range = tariffPriceRange(tariff);
    const fixed = (config.fixed_fees || []).reduce((sum, fee) => sum + (Number(fee.net_monthly) || 0), 0);
    const zones = config.zones || [];
    const pills = zones.slice(0, 5).map((zone) => `
      <span class="zone-pill" title="${escapeHtml(zoneSchedule(zone))}">
        ${escapeHtml(zone.name)}
        <b>${formatNumber((Number(zone.energy_net) || 0) + (Number(zone.distribution_net) || 0), 2)}</b>
      </span>`).join('');

    return `
      <article class="tariff-card ${tariff.is_preset ? 'is-preset' : ''}">
        <div class="tariff-head">
          <h3>${escapeHtml(tariff.name)}</h3>
          ${tariff.is_preset ? '<span class="badge">preset</span>' : ''}
        </div>
        <p class="muted">${escapeHtml(tariff.description || 'Taryfa własna.')}</p>
        <p class="muted small">Strefy: energia + sieć, netto zł/kWh, bez akcyzy i opłat dodatkowych.</p>
        <div class="zone-pills">${pills || '<span class="muted small">Brak stref</span>'}</div>
        <div class="tariff-meta">
          <span>${range ? `zmienne brutto: <b>${formatNumber(range.min, 2)}${range.max - range.min > 0.001 ? `–${formatNumber(range.max, 2)}` : ''} zł/kWh</b>` : 'brak cen'}</span>
          <span>stałe: <b>${formatPLN(fixed)}</b>/mies. netto${config.capacity_fee ? " + mocowa według progu zużycia" : ""}</span>
        </div>
        <div class="tariff-actions">
          <button type="button" data-action="edit" data-id="${escapeHtml(tariff.id)}">Edytuj</button>
          <button type="button" data-action="duplicate" data-id="${escapeHtml(tariff.id)}">Duplikuj</button>
          <button type="button" class="danger" data-action="delete" data-id="${escapeHtml(tariff.id)}">Usuń</button>
        </div>
      </article>`;
  }).join('');
}

async function handleTariffAction(event) {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const tariff = state.tariffs.find((item) => item.id === button.dataset.id);
  if (!tariff) return;

  if (button.dataset.action === 'edit') {
    openTariffEditor(tariff);
    return;
  }

  if (button.dataset.action === 'duplicate') {
    button.disabled = true;
    try {
      await api(`api/tariffs/${encodeURIComponent(tariff.id)}/duplicate`, { method: 'POST' });
      toast(`Skopiowano taryfę „${tariff.name}”.`, 'success');
      await loadTariffs();
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      button.disabled = false;
    }
    return;
  }

  if (button.dataset.action === 'delete') {
    if (!window.confirm(`Usunąć taryfę „${tariff.name}”? Tej operacji nie można cofnąć.`)) return;
    button.disabled = true;
    try {
      await api(`api/tariffs/${encodeURIComponent(tariff.id)}`, { method: 'DELETE' });
      toast('Taryfa została usunięta.', 'success');
      await loadTariffs();
    } catch (error) {
      toast(error.message, 'error');
      button.disabled = false;
    }
  }
}

/* ------------------------------------------------------------------ modal */

function openModal(html) {
  const root = $('#modal-root');
  root.innerHTML = `<div class="modal-backdrop" data-close></div>${html}`;
  root.hidden = false;
  document.body.classList.add('modal-open');
  window.setTimeout(() => {
    const first = root.querySelector('.modal-body input, .modal-body select, .modal-body textarea')
      || root.querySelector('button, input, select, textarea');
    first?.focus();
  }, 40);
}

function closeModal() {
  const root = $('#modal-root');
  root.hidden = true;
  root.innerHTML = '';
  document.body.classList.remove('modal-open');
  state.editingTariff = null;
}

function newZoneId() {
  return `zone_${Math.random().toString(36).slice(2, 9)}`;
}

function zoneEditorHtml(zone = {}) {
  const id = zone.id || newZoneId();
  const days = new Set(Array.isArray(zone.days) ? zone.days : [0, 1, 2, 3, 4, 5, 6]);
  const monthSet = new Set(Array.isArray(zone.months) ? zone.months.map(Number) : []);
  const dayChecks = DAYS.map((label, index) => `
    <label class="day-check">
      <input type="checkbox" class="day-input" value="${index}" ${days.has(index) ? 'checked' : ''}>
      ${label}
    </label>`).join('');
  const monthChecks = MONTHS.map((label, index) => `
    <label class="day-check" title="${MONTHS_FULL[index]}">
      <input type="checkbox" class="month-input" value="${index + 1}" ${monthSet.has(index + 1) ? 'checked' : ''}>
      ${label}
    </label>`).join('');
  return `
    <div class="zone-editor" data-zone-id="${escapeHtml(id)}">
      <div class="zone-editor-head">
        <input class="input zone-name" value="${escapeHtml(zone.name || '')}" maxlength="80" placeholder="Nazwa strefy, np. Szczyt">
        <button type="button" class="icon-button small" data-remove-zone title="Usuń strefę" aria-label="Usuń strefę">✕</button>
      </div>
      <div class="form-grid">
        <label class="field">
          <span class="field-label">Dni tygodnia</span>
          <div class="days-row">${dayChecks}</div>
        </label>
        <label class="field">
          <span class="field-label">Godziny</span>
          <input class="input zone-intervals" value="${escapeHtml((zone.intervals || []).join(', '))}"
                 placeholder="06:00-13:00, 15:00-22:00">
          <span class="field-hint">Pełne godziny, oddziel przecinkami. Doba to 00:00-24:00.</span>
        </label>
        <label class="field field-wide">
          <span class="field-label">Miesiące (opcjonalnie)</span>
          <div class="days-row">${monthChecks}</div>
          <span class="field-hint">Zaznacz, jeśli strefa obowiązuje tylko w części roku. Brak zaznaczeń = cały rok.</span>
        </label>
        <label class="field">
          <span class="field-label">Energia netto bez akcyzy (zł/kWh)</span>
          <input class="input zone-energy" type="number" min="0" max="10" step="0.0001"
                 value="${Number(zone.energy_net ?? 0)}">
        </label>
        <label class="field">
          <span class="field-label">Dystrybucja netto (zł/kWh)</span>
          <input class="input zone-distribution" type="number" min="0" max="10" step="0.0001"
                 value="${Number(zone.distribution_net ?? 0)}">
        </label>
      </div>
      <label class="check-row">
        <input type="checkbox" class="zone-holidays" ${zone.exclude_holidays ? 'checked' : ''}>
        Święta traktuj jak pozaszczyt (np. G12w, G13)
      </label>
    </div>`;
}

function feeRowHtml(fee, kind) {
  const isFixed = kind === 'fixed';
  const value = Number(isFixed ? (fee.net_monthly ?? 0) : (fee.net_per_kwh ?? 0));
  return `
    <div class="fee-row">
      <input class="input fee-name" value="${escapeHtml(fee.name || '')}" maxlength="80"
             placeholder="${isFixed ? 'np. opłata stała sieciowa' : 'np. opłata OZE'}">
      <input class="input fee-value" type="number" min="0" step="0.0001" value="${value}">
      <button type="button" class="icon-button small" data-remove-fee title="Usuń opłatę" aria-label="Usuń opłatę">✕</button>
    </div>`;
}

function defaultTariffConfig() {
  const g11 = state.tariffs.find((tariff) => tariff.preset_id === 'g11');
  if (g11) return clone(g11.config);
  return {
    zones: [{
      id: 'cala_doba',
      name: 'Cała doba',
      days: [0, 1, 2, 3, 4, 5, 6],
      intervals: ['00:00-24:00'],
      energy_net: 0.5,
      distribution_net: 0.3,
      exclude_holidays: false,
    }],
    fixed_fees: [],
    variable_fees: [],
    excise_net_per_kwh: 0.005,
    vat_percent: 23,
  };
}

function openTariffEditor(tariff) {
  state.editingTariff = tariff;
  const config = tariff ? clone(tariff.config) : defaultTariffConfig();
  const zones = Array.isArray(config.zones) ? config.zones : [];
  const fixedFees = Array.isArray(config.fixed_fees) ? config.fixed_fees : [];
  const variableFees = Array.isArray(config.variable_fees) ? config.variable_fees : [];

  openModal(`
    <div class="modal-dialog wide" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div class="modal-header">
        <div>
          <h2 id="modal-title">${tariff ? 'Edytuj taryfę' : 'Nowa taryfa'}</h2>
          <p>${tariff && tariff.is_preset
            ? 'Edytujesz wbudowany preset. W każdej chwili możesz przywrócić domyślne wartości.'
            : 'Stawki podawaj netto, energię bez akcyzy. Akcyza jest dodawana osobno, VAT na końcu.'}</p>
        </div>
        <button class="icon-button" type="button" data-close aria-label="Zamknij">✕</button>
      </div>
      <form id="tariff-form" novalidate>
        <div class="modal-body">
          <div class="form-stack">
            <label class="field">
              <span class="field-label">Nazwa taryfy</span>
              <input class="input" id="tariff-name" maxlength="80" required
                     value="${escapeHtml(tariff?.name || '')}" placeholder="np. Tauron G12w — moja umowa">
            </label>
            <label class="field">
              <span class="field-label">Opis</span>
              <input class="input" id="tariff-description" maxlength="600"
                     value="${escapeHtml(tariff?.description || '')}"
                     placeholder="Krótki opis, np. szczyt w dni robocze 6–13 i 15–22">
            </label>

            <div>
              <div class="group-head">
                <div>
                  <h3>Strefy czasowe</h3>
                  <p class="muted small">Kolejność ma znaczenie: pierwsza pasująca strefa wygrywa. Ostatnia powinna pokrywać całą dobę.</p>
                </div>
                <button type="button" class="button ghost" data-add-zone>+ Dodaj strefę</button>
              </div>
              <div id="zone-list">${zones.map(zoneEditorHtml).join('')}</div>
            </div>

            <div class="form-row">
              <div>
                <div class="group-head">
                  <h3>Opłaty stałe</h3>
                  <button type="button" class="link-button" data-add-fee="fixed">+ Dodaj</button>
                </div>
                <div id="fixed-fees">${fixedFees.map((fee) => feeRowHtml(fee, 'fixed')).join('')}</div>
                <p class="field-hint">Miesięczne, netto; proporcjonalnie do okresu. Sieciowa: 1 faza 7,38 zł; 3 fazy 10,86 zł. Abonament dla cyklu 1/2/6/12 mies.: 4,56/2,28/0,76/0,38 zł miesięcznie. Opłatę handlową wpisz z umowy.</p>
              </div>
              <div>
                <div class="group-head">
                  <h3>Opłaty zmienne</h3>
                  <button type="button" class="link-button" data-add-fee="variable">+ Dodaj</button>
                </div>
                <div id="variable-fees">${variableFees.map((fee) => feeRowHtml(fee, 'variable')).join('')}</div>
                <p class="field-hint">Za każdą kWh, netto: jakościowa, OZE, kogeneracyjna. Opłatę mocową ustaw poniżej.</p>
              </div>
            </div>

            <div>
              <h3>Opłata mocowa — gospodarstwo domowe</h3>
              <label class="field"><span><input id="capacity-enabled" type="checkbox" ${config.capacity_fee ? 'checked' : ''}> Naliczaj miesięcznie według progu zużycia</span></label>
              <label class="field">
                <span class="field-label">Pobór energii do ustalenia progu (kWh)</span>
                <input class="input" id="capacity-annual" type="number" min="0" step="any"
                  value="${config.capacity_fee?.annual_kwh ?? ''}" placeholder="Puste: szacunek roczny z analizy">
              </label>
              <p class="field-hint">Wpisz pobór z sieci z ostatnich 12 miesięcy według odczytu Taurona. Dla nowego odbiorcy wpisz pobór do ostatniego odczytu (0 przed pierwszym). Puste pole oznacza szacunek: zużycie z analizy × 365,25 / liczba dni. Krótki lub niepełny okres może wskazać inny próg niż faktura.</p>
              <div class="form-row">
                ${['poniżej 500 kWh', '500–1200 kWh', 'powyżej 1200 do 2800 kWh', 'powyżej 2800 kWh'].map((label, index) => `
                  <label class="field">
                    <span class="field-label">${label} (zł/mies. netto)</span>
                    <input class="input capacity-rate" type="number" min="0" max="10000" step="0.01"
                      value="${config.capacity_fee?.net_monthly_rates?.[index] ?? [4.29, 10.31, 17.18, 24.05][index]}">
                  </label>`).join('')}
              </div>
              <p class="field-hint">Usuń opłatę mocową z pozostałych opłat, jeśli była tam wpisana — aby nie naliczać jej dwa razy.</p>
            </div>

            <div class="form-row">
              <label class="field">
                <span class="field-label">Akcyza netto (zł/kWh)</span>
                <input class="input" id="tariff-excise" type="number" min="0" max="1" step="0.0001"
                       value="${Number(config.excise_net_per_kwh ?? 0.005)}">
              </label>
              <label class="field">
                <span class="field-label">VAT (%)</span>
                <input class="input" id="tariff-vat" type="number" min="0" max="100" step="0.1"
                       value="${Number(config.vat_percent ?? 23)}">
              </label>
            </div>

            <div class="form-error" id="tariff-form-error" role="alert"></div>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="button ghost" data-close>Anuluj</button>
          <button type="submit" class="button primary" id="save-tariff">Zapisz taryfę</button>
        </div>
      </form>
    </div>`);
}

function showFormError(message) {
  const box = $('#tariff-form-error');
  if (!box) return;
  box.textContent = message;
  box.classList.add('is-visible');
  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function readFees(form, containerId, key) {
  const rows = $$(`#${containerId} .fee-row`, form);
  const fees = [];
  for (const row of rows) {
    const name = $('.fee-name', row).value.trim();
    const value = Number($('.fee-value', row).value);
    if (!name && (!Number.isFinite(value) || value === 0)) continue;
    if (!name) throw new Error('Opłata bez nazwy — uzupełnij nazwę lub usuń wiersz.');
    if (!Number.isFinite(value) || value < 0) throw new Error(`Nieprawidłowa kwota opłaty „${name}”.`);
    fees.push({ name, [key]: value });
  }
  return fees;
}

async function saveTariffForm(form) {
  const errorBox = $('#tariff-form-error');
  errorBox?.classList.remove('is-visible');

  try {
    const name = $('#tariff-name').value.trim();
    if (!name) throw new Error('Podaj nazwę taryfy.');
    const description = $('#tariff-description').value.trim();

    const zones = $$('.zone-editor', form).map((element) => {
      const zoneName = $('.zone-name', element).value.trim();
      const days = $$('.day-input:checked', element).map((input) => Number(input.value));
      const months = $$('.month-input:checked', element).map((input) => Number(input.value));
      const intervals = $('.zone-intervals', element).value
        .split(/[,;\n]+/)
        .map((value) => value.trim())
        .filter(Boolean);
      const energy = Number($('.zone-energy', element).value);
      const distribution = Number($('.zone-distribution', element).value);

      if (!zoneName) throw new Error('Każda strefa musi mieć nazwę.');
      if (!days.length) throw new Error(`Strefa „${zoneName}” nie ma wybranych dni.`);
      if (!intervals.length) throw new Error(`Strefa „${zoneName}” nie ma przedziałów godzinowych.`);
      if (!Number.isFinite(energy) || energy < 0 || energy > 10) throw new Error(`Strefa „${zoneName}”: nieprawidłowa cena energii.`);
      if (!Number.isFinite(distribution) || distribution < 0 || distribution > 10) throw new Error(`Strefa „${zoneName}”: nieprawidłowa cena dystrybucji.`);

      return {
        id: element.dataset.zoneId || newZoneId(),
        name: zoneName,
        days,
        intervals,
        ...(months.length && months.length < 12 ? { months } : {}),
        energy_net: energy,
        distribution_net: distribution,
        exclude_holidays: $('.zone-holidays', element).checked,
      };
    });

    if (!zones.length) throw new Error('Dodaj co najmniej jedną strefę.');

    const excise = Number($('#tariff-excise').value);
    const vat = Number($('#tariff-vat').value);
    if (!Number.isFinite(excise) || excise < 0 || excise > 1) throw new Error('Akcyza musi być w zakresie 0–1 zł/kWh.');
    if (!Number.isFinite(vat) || vat < 0 || vat > 100) throw new Error('VAT musi być w zakresie 0–100%.');

    let capacityFee = null;
    if ($('#capacity-enabled').checked) {
      const annualText = $('#capacity-annual').value.trim();
      const annualKwh = annualText === '' ? null : Number(annualText);
      const rates = $$('.capacity-rate', form).map((input) => Number(input.value));
      if (annualKwh !== null && (!Number.isFinite(annualKwh) || annualKwh < 0)) throw new Error('Pobór energii musi być nieujemną liczbą.');
      if (rates.some((rate) => !Number.isFinite(rate) || rate < 0 || rate > 10000)) throw new Error('Stawki opłaty mocowej muszą być w zakresie 0–10000 zł.');
      capacityFee = { annual_kwh: annualKwh, net_monthly_rates: rates };
    }

    const payload = {
      name,
      description,
      config: {
        zones,
        fixed_fees: readFees(form, 'fixed-fees', 'net_monthly'),
        variable_fees: readFees(form, 'variable-fees', 'net_per_kwh'),
        capacity_fee: capacityFee,
        excise_net_per_kwh: excise,
        vat_percent: vat,
      },
    };

    const saveButton = $('#save-tariff');
    saveButton.disabled = true;
    saveButton.innerHTML = '<span class="spinner"></span> Zapisywanie…';

    if (state.editingTariff) {
      await api(`api/tariffs/${encodeURIComponent(state.editingTariff.id)}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      toast('Taryfa została zapisana.', 'success');
    } else {
      await api('api/tariffs', { method: 'POST', body: JSON.stringify(payload) });
      toast('Dodano nową taryfę.', 'success');
    }

    closeModal();
    await loadTariffs();
  } catch (error) {
    showFormError(error.message);
    const saveButton = $('#save-tariff');
    if (saveButton) {
      saveButton.disabled = false;
      saveButton.textContent = 'Zapisz taryfę';
    }
  }
}

function bindModalEvents() {
  const root = $('#modal-root');

  root.addEventListener('click', (event) => {
    if (event.target.closest('[data-close]')) {
      closeModal();
      return;
    }

    const addZone = event.target.closest('[data-add-zone]');
    if (addZone) {
      $('#zone-list').insertAdjacentHTML('beforeend', zoneEditorHtml({}));
      $('#zone-list .zone-editor:last-child .zone-name')?.focus();
      return;
    }

    const removeZone = event.target.closest('[data-remove-zone]');
    if (removeZone) {
      if ($$('.zone-editor').length <= 1) {
        toast('Taryfa musi mieć co najmniej jedną strefę.', 'error');
        return;
      }
      removeZone.closest('.zone-editor')?.remove();
      return;
    }

    const addFee = event.target.closest('[data-add-fee]');
    if (addFee) {
      const kind = addFee.dataset.addFee;
      const container = kind === 'fixed' ? $('#fixed-fees') : $('#variable-fees');
      container.insertAdjacentHTML('beforeend', feeRowHtml({}, kind));
      container.querySelector('.fee-row:last-child .fee-name')?.focus();
      return;
    }

    const removeFee = event.target.closest('[data-remove-fee]');
    if (removeFee) {
      removeFee.closest('.fee-row')?.remove();
    }
  });

  root.addEventListener('submit', (event) => {
    if (event.target.id !== 'tariff-form') return;
    event.preventDefault();
    saveTariffForm(event.target);
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !root.hidden) closeModal();
  });
}

/* ---------------------------------------------------------------- historia */

function renderHistory() {
  const container = $('#history-list');
  if (!state.analyses.length) {
    container.innerHTML = `<div class="empty-state card">
      <div class="empty-icon">🕘</div>
      <h3>Historia jest pusta</h3>
      <p class="muted">Każda wykonana analiza zapisuje się tutaj automatycznie.</p>
    </div>`;
    return;
  }

  container.innerHTML = state.analyses.map((item) => `
    <article class="history-item">
      <div class="history-main">
        <div class="history-title">
          ${escapeHtml(item.cheapest_name || 'Brak danych')}
          ${item.cheapest_name ? '<span class="badge">najtańsza</span>' : ''}
        </div>
        <div class="muted small">
          ${escapeHtml(item.entity_name)} · ${formatDate(item.start)}–${formatDate(item.end)} · ${formatNumber(item.total_kwh, 1)} kWh
        </div>
      </div>
      <div class="history-cost">
        <strong>${formatPLN(item.cheapest_total_pln)}</strong>
        <span>oszczędność ${formatPLN(item.max_savings_pln)}</span>
      </div>
      <div class="history-actions">
        <button type="button" data-open="${escapeHtml(item.id)}">Podgląd</button>
        <button type="button" class="danger" data-delete="${escapeHtml(item.id)}">Usuń</button>
      </div>
    </article>`).join('');
}

function ensureEntityOption(entityId, name) {
  const select = $('#entity-select');
  if (Array.from(select.options).some((option) => option.value === entityId)) return;
  const option = document.createElement('option');
  option.value = entityId;
  option.textContent = `${name || entityId} — ${entityId}`;
  select.appendChild(option);
}

async function handleHistoryAction(event) {
  const openButton = event.target.closest('button[data-open]');
  const deleteButton = event.target.closest('button[data-delete]');

  if (openButton) {
    openButton.disabled = true;
    try {
      const record = await api(`api/analyses/${encodeURIComponent(openButton.dataset.open)}`);
      if (!record.result) throw new Error('Zapisana analiza jest uszkodzona.');
      const result = record.result;
      result.id = record.id;
      result.created_at = record.created_at;
      state.analysis = result;

      ensureEntityOption(result.entity_id, result.entity_name);
      $('#entity-select').value = result.entity_id;
      $('#date-start').value = result.start;
      $('#date-end').value = result.end;
      $$('#quick-ranges button').forEach((button) => button.classList.remove('is-active'));
      updateEntityHint();

      renderAnalysis(result);
      switchTab('analysis');
      window.setTimeout(() => {
        $('#analysis-results')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 80);
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      openButton.disabled = false;
    }
    return;
  }

  if (deleteButton) {
    if (!window.confirm('Usunąć tę analizę z historii?')) return;
    deleteButton.disabled = true;
    try {
      await api(`api/analyses/${encodeURIComponent(deleteButton.dataset.delete)}`, { method: 'DELETE' });
      toast('Analiza została usunięta.', 'success');
      await loadHistory();
    } catch (error) {
      toast(error.message, 'error');
      deleteButton.disabled = false;
    }
  }
}

/* ------------------------------------------------------------------- init */

function bindEvents() {
  $$('.tab-button').forEach((button) => {
    button.addEventListener('click', () => switchTab(button.dataset.tab));
  });

  $('#analysis-form').addEventListener('submit', handleAnalyze);
  $('#entity-select').addEventListener('change', updateEntityHint);
  bindDateControls();
  bindTariffChips();
  bindModalEvents();

  $('#tariff-grid').addEventListener('click', handleTariffAction);
  $('#history-list').addEventListener('click', handleHistoryAction);
  $('#refresh-history').addEventListener('click', loadHistory);

  $('#new-tariff').addEventListener('click', () => openTariffEditor(null));
  $('#restore-presets').addEventListener('click', async () => {
    if (!window.confirm('Przywrócić domyślne presety Tauron? Zmiany w presetach zostaną nadpisane.')) return;
    try {
      const result = await api('api/tariffs/restore-presets', { method: 'POST' });
      toast(`Przywrócono ${result.restored} ${plural(result.restored, 'preset', 'presety', 'presetów')}.`, 'success');
      await loadTariffs();
    } catch (error) {
      toast(error.message, 'error');
    }
  });

  window.addEventListener('hashchange', () => {
    switchTab(window.location.hash.replace('#', '') || 'analysis');
  });
}

async function init() {
  normalizeBasePath();
  bindTheme();
  bindEvents();
  setDateRange(addDays(today(), -29), today());

  await loadConfig();
  await Promise.allSettled([loadEntities(), loadTariffs()]);
  await loadHistory();

  const hash = window.location.hash.replace('#', '');
  if (QUICK_TABS.has(hash)) switchTab(hash);
}

document.addEventListener('DOMContentLoaded', init);
