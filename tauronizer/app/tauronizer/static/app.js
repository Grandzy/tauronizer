'use strict';

/* ==========================================================================
   Tauronizer — frontend bez frameworków i zależności zewnętrznych.
   ========================================================================== */

const DAYS = ['Pn', 'Wt', 'Śr', 'Cz', 'Pt', 'So', 'Nd'];
const MONTHS = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru'];
const MONTHS_FULL = ['styczeń', 'luty', 'marzec', 'kwiecień', 'maj', 'czerwiec', 'lipiec', 'sierpień', 'wrzesień', 'październik', 'listopad', 'grudzień'];
const QUICK_TABS = new Set(['analysis', 'tariffs', 'history', 'sensors']);

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
  sensors: null,
  sensorDirty: false,
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
  if (tab === 'tariffs') loadKompas();
  if (tab === 'history') loadHistory();
  if (tab === 'sensors') loadSensors();
}

function renderSensorTariffs() {
  const select = $('#sensor-tariff');
  if (document.activeElement === select) return;
  const selected = state.sensorDirty ? select.value : (state.sensors?.tariff_id || '');
  select.innerHTML = '<option value="">Nie publikuj strefy i ceny</option>' + state.tariffs.map((tariff) =>
    `<option value="${escapeHtml(tariff.id)}">${escapeHtml(tariff.name)}</option>`).join('');
  if (selected && !state.tariffs.some((tariff) => tariff.id === selected)) {
    select.insertAdjacentHTML('beforeend', `<option value="${escapeHtml(selected)}">Usunięta taryfa — wybierz inną</option>`);
  }
  select.value = selected;
  if (!state.sensorDirty && document.activeElement !== $('#sensor-price-mode')) {
    $('#sensor-price-mode').value = state.sensors?.price_mode || 'gross';
  }
}

async function loadSensors() {
  try {
    const data = await api('api/sensors');
    state.sensors = data;
    renderSensorTariffs();
    $('#sensor-current').textContent = data.current_zone || '—';
    $('#sensor-published').textContent = data.published_state || '—';
    const next = data.next_change || {};
    $('#sensor-next-change').textContent = next.next_change
      ? `${formatInstant(next.next_change.at)} → ${next.next_change.zone_name}` : (next.reason || 'Brak danych');
    $('#sensor-next-mqtt').textContent = next.mqtt_error ||
      (next.mqtt_status === 'published' ? 'Opublikowano przez MQTT' : 'Oczekiwanie na publikację');
    await loadDynamicSchedule();
    const apiStatus = data.api || {};
    const apiDate = (value) => value ? new Date(value).toLocaleString('pl-PL', {timeZone: 'Europe/Warsaw'}) : '—';
    $('#sensor-api-update').textContent = apiDate(apiStatus.last_update);
    $('#sensor-api-checked').textContent = apiDate(apiStatus.last_checked);
    $('#sensor-api-connected').textContent = apiStatus.connected == null ? 'Oczekiwanie na sprawdzenie' :
      `${apiStatus.connected ? 'true — połączono' : 'false — brak połączenia'}${apiStatus.error ? ` · ${apiStatus.error}` : ''}`;
    $('#sensor-api-mqtt').textContent = apiStatus.mqtt_error ||
      (apiStatus.mqtt_status === 'published' ? 'Opublikowano przez MQTT' : 'Oczekiwanie na publikację');
    const priceLabel = (price, mode) => price == null ? '—' :
      `${formatNumber(price, 6)} zł/kWh ${mode === 'net' ? 'netto' : 'brutto'}`;
    $('#sensor-price-current').textContent = priceLabel(data.current_price, data.price_mode);
    $('#sensor-price-published').textContent = priceLabel(data.published_price, data.published_price_mode);
    const labels = { disabled: 'Publikacja strefy i ceny wyłączona', published: 'Opublikowano przez MQTT',
      missing_tariff: 'Wybrana taryfa nie istnieje', error: 'Błąd publikacji — ponawiam automatycznie' };
    $('#sensor-status').textContent = data.error || labels[data.status] || 'Oczekiwanie na publikację';
    $('#sensor-updated').textContent = data.last_published
      ? new Date(data.last_published).toLocaleString('pl-PL', {timeZone: 'Europe/Warsaw'}) : '—';
  } catch (error) {
    $('#sensor-status').textContent = `Nie udało się pobrać statusu: ${error.message}`;
  }
}

function formatInstant(value) {
  return new Date(value).toLocaleString('pl-PL', {timeZone: 'Europe/Warsaw', timeZoneName: 'short',
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'});
}

async function loadDynamicSchedule() {
  const container = $('#dynamic-schedule');
  try {
    const plan = await api('api/kompas/schedule');
    const time = (value, end = false) => {
      const label = new Date(value).toLocaleTimeString('pl-PL', {
        timeZone: 'Europe/Warsaw', hour: '2-digit', minute: '2-digit', timeZoneName: 'short'});
      return end ? label.replace(/^00:00/, '24:00') : label;
    };
    container.innerHTML = `<p class="muted small">${escapeHtml(plan.tariff_name || 'Brak taryfy G14dynamic')}
      ${plan.is_current_tariff ? '· Twoja obecna taryfa' : '· podgląd; sensor następnej zmiany korzysta z taryfy wybranej w Sensorach'}</p>
      <div class="schedule-days">${(plan.days || []).map((day) => `<section class="schedule-day">
        <h4>${formatDate(day.date)}</h4><p class="muted small">${day.available_hours}/${day.expected_hours} opublikowanych godzin${day.complete ? '' : ' · niepełne dane'}</p>
        <ol class="schedule-segments">${day.segments.map((segment) => `<li class="schedule-segment zone-level-${segment.level ?? 'missing'}">
          <span class="schedule-time">${escapeHtml(time(segment.start))} – ${escapeHtml(time(segment.end, true))}</span>
          <strong>${escapeHtml(segment.zone_name || 'Brak opublikowanych danych')}</strong>
          ${segment.price_gross == null ? '' : `<span class="muted small">${formatNumber(segment.price_gross, 4)} zł/kWh brutto</span>`}</li>`).join('')}</ol></section>`).join('')}</div>`;
  } catch (error) {
    container.textContent = `Nie udało się pobrać harmonogramu: ${error.message}`;
  }
}

async function loadKompas() {
  try {
    const data = await api('api/kompas');
    const labels = {waiting: 'Oczekiwanie na import', updating: 'Aktualizacja ostatnich dni', importing: 'Import historii w tle', ready: 'Baza uzupełniona', error: 'Import przerwany — ponawiam'};
    $('#kompas-status').textContent = `${labels[data.status] || data.status}. ${data.hours} godzin w bazie` +
      (data.first_day ? ` (${formatDate(data.first_day)} – ${formatDate(data.last_day)})` : '') +
      (data.last_sync ? ` · ostatnia synchronizacja: ${new Date(data.last_sync).toLocaleString('pl-PL')}` : '') +
      (data.missing_archive_hours ? ` · brakujące godziny w archiwum: ${data.missing_archive_hours} (będą uzupełniane)` : '') +
      (data.error ? `. ${data.error}` : '');
  } catch (error) { $('#kompas-status').textContent = error.message; }
}

function bindSensorEvents() {
  $('#refresh-kompas').addEventListener('click', async () => {
    try { await api('api/kompas/refresh', {method: 'POST'}); toast('Zlecono uzupełnienie danych Kompasu PSE.', 'success'); await loadKompas(); }
    catch (error) { toast(error.message, 'error'); }
  });
  window.setInterval(() => { if (!document.hidden && !$('#tab-tariffs').hidden) loadKompas(); }, 10000);
  $('#sensor-tariff').addEventListener('change', () => { state.sensorDirty = true; });
  $('#sensor-price-mode').addEventListener('change', () => { state.sensorDirty = true; });
  $('#sensor-settings').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = $('#sensor-save');
    button.disabled = true;
    try {
      const data = await api('api/sensors', {method: 'PUT', body: JSON.stringify({tariff_id: $('#sensor-tariff').value || null, price_mode: $('#sensor-price-mode').value})});
      state.sensorDirty = false;
      state.sensors = data;
      await loadSensors();
      toast(data.error ? 'Zapisano taryfę. Sprawdź status publikacji MQTT.' : 'Zapisano ustawienia sensora.', data.error ? 'error' : 'success');
    } catch (error) { toast(error.message, 'error'); }
    finally { button.disabled = false; }
  });
  window.setInterval(() => {
    if (!document.hidden && !$('#tab-sensors').hidden && !$('#sensor-save').disabled) loadSensors();
  }, 5000);
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
      Wbudowane taryfy (G11, G12, G12w, G13, G14dynamic) są edytowalne — możesz też skopiować preset
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
    hint.textContent = `${state.entities.length} ${plural(state.entities.length, 'sensor', 'sensory', 'sensorów')} energii. Dla prosumenta wybierz licznik poboru z sieci.`;
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
    loadKompas();
    renderSensorTariffs();
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

function syncProsumerFields() {
  const mode = $('#prosumer-mode').value;
  $('#prosumer-options').hidden = mode === 'off';
  $('#prosumer-export-field').hidden = mode === 'off';
  $('#prosumer-ratio-field').hidden = mode !== 'net_metering';
  $('#prosumer-balance-unit').textContent = mode === 'net_metering' ? 'kWh do odebrania' : 'zł depozytu';
  $('#prosumer-mode-help').textContent = mode === 'net_metering'
    ? 'Najpierw rozliczamy te same strefy, potem strefy z najdroższą dystrybucją. Opłaty stałe pozostają. Niewykorzystane opusty wygasają.'
    : 'Depozyt pokrywa energię z akcyzą i VAT; dystrybucję i opłaty stałe płacisz osobno. Nowy depozyt jest dostępny w kolejnym miesiącu. Wybierz system zgodny z umową. RCE z danych godzinowych jest przybliżeniem.';
  $$('.prosumer-balance-zone').forEach(el => { el.hidden = mode !== 'net_metering'; });
  $$('.prosumer-export-value').forEach(el => { el.hidden = mode === 'net_metering'; });
  $$('.prosumer-balance-amount-label').forEach(el => { el.textContent = mode === 'net_metering' ? 'Pozostałe kWh' : 'Pozostałe zł'; });
  $('#prosumer-save-status').textContent = '';
}

function addProsumerBalance(balance = {}) {
  const row = document.createElement('div');
  row.className = 'prosumer-balance-row';
  row.innerHTML = `<label class="field"><span class="field-label">Miesiąc</span><input class="input" type="month" data-balance="month" value="${escapeHtml(balance.month || '')}"></label>
    <label class="field"><span class="field-label prosumer-balance-amount-label">Pozostałe saldo</span><input class="input" type="number" min="0.001" step="any" data-balance="amount" value="${escapeHtml(balance.amount ?? '')}"></label>
    <label class="field prosumer-balance-zone"><span class="field-label">Strefa salda</span><select class="input" data-balance="zone_id"><option value="">Wspólna pula (szacunek)</option>${Array.from(new Map(state.tariffs.flatMap(t => t.config.zones.map(z => [z.id,z.name])))).map(([id,name]) => `<option value="${escapeHtml(id)}" ${balance.zone_id === id ? 'selected' : ''}>${escapeHtml(name)} (${escapeHtml(id)})</option>`).join('')}</select></label>
    <label class="field prosumer-export-value"><span class="field-label">Wartość eksportu przed ×1,23 (zł, opcjonalnie)</span><input class="input" type="number" min="0" step="any" data-balance="export_value_pln" value="${escapeHtml(balance.export_value_pln ?? '')}"></label>
    <button type="button" class="button ghost" data-remove-balance aria-label="Usuń miesiąc salda">Usuń</button>`;
  $('#prosumer-balances').appendChild(row);
  syncProsumerFields();
}

function readProsumerSettings() {
  const mode = $('#prosumer-mode').value;
  const settings = {mode, export_entity_id: $('#prosumer-export').value || null,
    ratio: Number($('#prosumer-ratio').value), opening_balances: []};
  if (mode === 'off') return settings;
  if (!settings.export_entity_id) throw new Error('Wybierz encję eksportu do sieci.');
  if (settings.export_entity_id === $('#entity-select').value) throw new Error('Pobór i eksport muszą pochodzić z dwóch różnych encji.');
  settings.opening_balances = $$('.prosumer-balance-row').map(row => {
    const month = $('[data-balance="month"]', row).value;
    const amount = Number($('[data-balance="amount"]', row).value);
    const value = $('[data-balance="export_value_pln"]', row).value;
    if (!month || !Number.isFinite(amount) || amount <= 0) throw new Error('Uzupełnij miesiąc i dodatnią wartość każdego salda.');
    return {month, amount, zone_id: mode === 'net_metering' ? $('[data-balance="zone_id"]', row).value || null : null, export_value_pln: mode === 'net_metering' || value === '' ? null : Number(value)};
  });
  return settings;
}

function applyProsumerSettings(settings = {}) {
  $('#prosumer-mode').value = settings.mode || 'off';
  const select = $('#prosumer-export');
  select.innerHTML = '<option value="">Wybierz encję eksportu…</option>' + state.entities.map(e => `<option value="${escapeHtml(e.entity_id)}">${escapeHtml(e.name)} — ${escapeHtml(e.entity_id)}</option>`).join('');
  if (settings.export_entity_id && !state.entities.some(e => e.entity_id === settings.export_entity_id)) {
    const option = new Option(settings.export_entity_id, settings.export_entity_id);
    select.add(option);
  }
  select.value = settings.export_entity_id || '';
  $('#prosumer-ratio').value = String(settings.ratio || 0.8);
  $('#prosumer-balances').innerHTML = '';
  (settings.opening_balances || []).forEach(addProsumerBalance);
  syncProsumerFields();
}

async function loadProsumer() {
  try {
    const data = await api('api/prosumer');
    applyProsumerSettings(data.settings);
    const prices = data.prices;
    $('#prosumer-price-status').textContent = `Ceny PSE: ${prices.last_update ? formatInstant(prices.last_update) : 'oczekiwanie na pobranie'}${prices.error ? ` · ${prices.error}` : ''}. ` +
      (prices.series || []).map(s => `${s.kind.toUpperCase()}: ${s.count} cen`).join(' · ');
  } catch (error) { toast(`Ustawienia prosumenta: ${error.message}`, 'error'); }
}

function bindProsumerEvents() {
  $('#prosumer-mode').addEventListener('change', syncProsumerFields);
  $('#prosumer-add-balance').addEventListener('click', () => addProsumerBalance());
  $('#prosumer-balances').addEventListener('click', event => event.target.closest('[data-remove-balance]')?.closest('.prosumer-balance-row').remove());
  $('#prosumer-save').addEventListener('click', async () => {
    try {
      await api('api/prosumer', {method:'PUT', body:JSON.stringify(readProsumerSettings())});
      $('#prosumer-save-status').textContent = 'Zapisano. Ustawienia zostaną użyte w kolejnej analizie.';
    } catch (error) { toast(error.message, 'error'); }
  });
  $('#prosumer-refresh-prices').addEventListener('click', async () => {
    try {
      await api('api/prosumer/prices/refresh', {method:'POST'});
      $('#prosumer-price-status').textContent = 'Zlecono odświeżenie cen w tle. Ponownie otwórz aplikację, aby zobaczyć stan bazy.';
    } catch (error) { toast(error.message, 'error'); }
  });
}

function renderProsumerLedger(tariff) {
  const p = tariff.prosumer;
  if (!p) return '';
  const metering = p.mode === 'net_metering';
  const quantity = value => `${formatNumber(value, metering ? 3 : 2)} ${p.unit}`;
  return `<div class="prosumer-ledger"><h4>Rozliczenie prosumenta</h4>
    <p class="muted small">Rachunek przed rozliczeniem: <strong>${formatPLN(p.purchase_gross_pln)}</strong> · Pomniejszenie rachunku: <strong>${formatPLN(p.credit_used_pln)}</strong> · Do zapłaty: <strong>${formatPLN(tariff.total_pln)}</strong></p>
    <p class="muted small">Saldo końcowe: <strong>${quantity(p.closing_balance)}</strong> · Wygasło: ${quantity(p.expired)}${!metering ? ` · Potencjalny zwrot po wygaśnięciu: ${formatPLN(p.refundable_pln)} (nie odjęto od rachunku)` : ''}</p>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Miesiąc</th><th>Pobór kWh</th><th>Eksport kWh</th><th>${metering ? 'Nowy opust' : 'Nowy depozyt'}</th><th>Wykorzystano</th><th>Wygasło</th><th>Saldo</th><th>Do zapłaty</th></tr></thead><tbody>
    ${p.months.map(m => `<tr><td>${escapeHtml(m.month)}</td><td>${formatNumber(m.import_kwh,2)}</td><td>${formatNumber(m.export_kwh,2)}</td><td>${quantity(m.credit_created)}</td><td>${quantity(m.credit_used)}</td><td>${quantity(m.expired)}</td><td>${quantity(m.balance)}</td><td>${formatPLN(m.due_pln)}</td></tr>`).join('')}
    </tbody></table></div><p class="muted small">${metering ? 'Tabela stref i pączek pokazują opłaty pozostałe po opuście. Opusty między strefami są symulowane dla każdej taryfy osobno.' : 'Tabela składników i pączek pokazują rachunek przed zapłatą z depozytu. Saldo obejmuje też nowy depozyt dostępny od następnego miesiąca. Zwrot jest szacunkiem limitu 20% (RCEm) / 30% (RCE), bez zwiększenia ×1,23.'}
    ${p.months.some(m => m.refund_unknown) ? 'Nie wyliczono części zwrotu: brak pierwotnej wartości eksportu dla salda początkowego.' : ''}</p></div>`;
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

  let prosumer;
  try { prosumer = readProsumerSettings(); } catch (error) { return toast(error.message, 'error'); }
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
      body: JSON.stringify({ entity_id: entityId, start, end, tariff_ids: tariffIds, prosumer }),
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

function renderDataQuality(quality, label = 'Kompletność danych') {
  if (!quality) return '<p class="muted small">Ta zapisana analiza nie ma informacji o kompletności. Wykonaj ją ponownie.</p>';
  const months = (quality.months || []).map((row) => `<tr>
    <td>${escapeHtml(row.month)}${row.partial_month ? ' · fragment miesiąca' : ''}</td>
    <td>${row.received_hours}/${row.expected_hours}</td><td>${row.percent == null ? '—' : `${formatNumber(row.percent, 2)}%`}</td>
    <td>${row.missing_hours ? `<strong class="coverage-warning">Brak ${row.missing_hours} godz.</strong>` : row.expected_hours ? 'Kompletne' : 'Oczekiwanie'}${row.pending_hours ? ` · ${row.pending_hours} godz. jeszcze niezakończonych` : ''}</td></tr>`).join('');
  const gaps = (quality.gaps || []).map((gap) => `<li>${escapeHtml(formatInstant(gap.start))} – ${escapeHtml(formatInstant(gap.end))} · ${gap.hours} godz.</li>`).join('');
  return `<section class="card data-quality"><div class="card-head"><h3>${escapeHtml(label)}</h3>
      <strong class="${quality.missing_hours ? 'coverage-warning' : ''}">${quality.percent == null ? 'Oczekiwanie na zakończone godziny' : `${formatNumber(quality.percent, 2)}% godzin`}</strong></div>
    <p>${quality.received_hours} z ${quality.expected_hours} zakończonych godzin ma prawidłowe statystyki zużycia.
      ${quality.missing_hours ? `<strong class="coverage-warning">Brakuje ${quality.missing_hours} godzin. Koszty i ranking mogą się zmienić po uzupełnieniu danych.</strong>` : ''}</p>
    <p class="muted small">Czas Europe/Warsaw, z uwzględnieniem dni 23- i 25-godzinnych. Zerowe odczyty liczą się jako dane.
      ${quality.pending_hours ? `${quality.pending_hours} trwających lub przyszłych godzin nie zaliczono do braków.` : ''}
      ${quality.invalid_samples ? `${quality.invalid_samples} nieprawidłowych odczytów nie potwierdza kompletności.` : ''}
      Brakujących godzin nie uzupełniamy szacunkiem.</p>
    <details class="coverage-details"><summary>Kompletność miesięcy i brakujące przedziały (${quality.gap_count})</summary>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>Miesiąc</th><th>Godziny</th><th>Kompletność</th><th>Status</th></tr></thead><tbody>${months}</tbody></table></div>
      ${gaps ? `<p class="muted small">Brakujące przedziały; godzina końcowa jest wyłączona z przedziału.</p><ul>${gaps}</ul>` : ''}
      ${quality.gaps_truncated ? '<p class="muted small">Pokazano pierwsze 200 przedziałów. Podsumowanie uwzględnia wszystkie braki.</p>' : ''}
    </details></section>`;
}

function bindChartTooltips() {
  const tooltip = $('#chart-tooltip');
  const tooltipValue = $('#chart-tooltip-value');
  let anchor = null;
  const hide = () => {
    tooltip.hidden = true;
    if (anchor) {
      anchor.classList.remove('is-chart-active');
      const describedBy = (anchor.getAttribute('aria-describedby') || '').split(' ').filter((id) => id && id !== tooltip.id);
      if (describedBy.length) anchor.setAttribute('aria-describedby', describedBy.join(' '));
      else anchor.removeAttribute('aria-describedby');
    }
    anchor = null;
  };
  const find = (target) => target instanceof Element ? target.closest('[data-chart-tooltip]') : null;
  const show = (target, x, y) => {
    if (!target || !target.dataset.chartTooltip) return hide();
    if (anchor !== target) hide();
    anchor = target;
    tooltipValue.textContent = target.dataset.chartTooltip;
    tooltip.style.setProperty('--tooltip-dot', target.dataset.chartColor === 'accent' ? 'var(--accent)' : 'var(--teal)');
    target.classList.add('is-chart-active');
    const describedBy = new Set((target.getAttribute('aria-describedby') || '').split(' ').filter(Boolean));
    describedBy.add(tooltip.id);
    target.setAttribute('aria-describedby', [...describedBy].join(' '));
    tooltip.hidden = false;
    const rect = tooltip.getBoundingClientRect();
    const left = Math.max(8, Math.min(x + 12, window.innerWidth - rect.width - 8));
    const top = y + rect.height + 20 > window.innerHeight ? Math.max(8, y - rect.height - 12) : y + 12;
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  };
  document.addEventListener('pointerover', (event) => {
    const target = find(event.target);
    if (target) show(target, event.clientX, event.clientY);
  });
  document.addEventListener('pointermove', (event) => {
    const target = find(event.target);
    if (target) show(target, event.clientX, event.clientY);
    else hide();
  });
  document.addEventListener('pointerout', (event) => {
    const target = find(event.target);
    if (target && !target.contains(event.relatedTarget)) hide();
  });
  document.addEventListener('focusin', (event) => {
    const target = find(event.target);
    if (target) {
      const rect = target.getBoundingClientRect();
      show(target, rect.left + rect.width / 2, rect.bottom);
    } else hide();
  });
  document.addEventListener('focusout', hide);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') hide(); });
  window.addEventListener('scroll', () => {
    if (anchor && document.activeElement === anchor) {
      const rect = anchor.getBoundingClientRect();
      if (rect.bottom > 0 && rect.top < window.innerHeight) show(anchor, rect.left + rect.width / 2, rect.bottom);
      else hide();
    } else hide();
  }, true);
  window.addEventListener('resize', hide);
}

function bindInvoiceLegendHover() {
  const findSegment = (target) => target instanceof Element ? target.closest('.invoice-donut-segment') : null;
  const highlight = (segment, active) => {
    const chart = segment.closest('.invoice-chart');
    chart.querySelectorAll('.invoice-legend-item').forEach((row) => {
      row.classList.toggle('is-highlighted', active && row.dataset.invoiceItem === segment.dataset.invoiceItem);
    });
  };
  for (const eventName of ['pointerover', 'focusin']) {
    document.addEventListener(eventName, (event) => {
      const segment = findSegment(event.target);
      if (segment) highlight(segment, true);
    });
  }
  for (const eventName of ['pointerout', 'focusout']) {
    document.addEventListener(eventName, (event) => {
      const segment = findSegment(event.target);
      if (segment && !segment.contains(event.relatedTarget)) highlight(segment, false);
    });
  }
}

function renderInvoiceDonut(tariff) {
  const breakdown = tariff.breakdown || {};
  const detailed = Array.isArray(breakdown.invoice_items);
  const fallback = [
    ['Energia czynna netto (bez akcyzy)', 'energy_pln'], ['Dystrybucja netto', 'distribution_pln'],
    ['Opłaty zmienne netto', 'variable_fees_pln'], ['Akcyza', 'excise_pln'],
    ['Opłaty stałe netto', 'fixed_pln'], ['Opłata mocowa netto', 'capacity_fee_pln'], ['VAT', 'vat_pln'],
  ].map(([name, key]) => ({name, amount_pln: breakdown[key] ?? 0}));
  const items = (detailed ? breakdown.invoice_items : fallback).map((item) => ({
    name: String(item.name || 'Składnik rachunku'), amount: Math.max(0, Number(item.amount_pln) || 0),
  }));
  const sum = items.reduce((total, item) => total + item.amount, 0);
  const colors = ['#eab43d', '#63c7b2', '#7da7ed', '#b891de', '#e38670', '#a2bd68', '#d68fb4',
    '#68b7cf', '#d7c783', '#8e9be0', '#e3a468', '#80c69b', '#c5a2cd', '#93b7c3', '#b5ad7b', '#ba8b76'];
  const circumference = 2 * Math.PI * 82;
  let offset = 0;
  const arcs = items.map((item, index) => {
    if (!item.amount || !sum) return '';
    const length = item.amount / sum * circumference;
    const title = `${item.name}: ${formatPLN(item.amount)} · ${formatNumber(item.amount / sum * 100, 2)}%`;
    const arc = `<circle class="invoice-donut-segment" data-invoice-item="${index}" tabindex="0" aria-label="${escapeHtml(title)}" cx="110" cy="110" r="82" fill="none" stroke="${colors[index % colors.length]}"
      stroke-width="30" stroke-dasharray="${length.toFixed(6)} ${circumference.toFixed(6)}" stroke-dashoffset="${(-offset).toFixed(6)}"
      transform="rotate(-90 110 110)"><title>${escapeHtml(title)}</title></circle>`;
    offset += length;
    return arc;
  }).join('');
  const legend = items.map((item, index) => `<li class="invoice-legend-item${item.amount ? '' : ' is-zero'}" data-invoice-item="${index}" style="--invoice-color:${colors[index % colors.length]}">
    <span class="invoice-swatch" style="background:${colors[index % colors.length]}"></span>
    <span class="invoice-item-name">${escapeHtml(item.name)}</span>
    <strong>${formatPLN(item.amount)}</strong><span class="muted">${formatNumber(sum ? item.amount / sum * 100 : 0, 2)}%</span></li>`).join('');
  return `<section class="invoice-chart"><h4>Struktura potencjalnej faktury</h4>
    <div class="invoice-chart-layout"><div class="invoice-donut">
      <svg viewBox="0 0 220 220" role="img" aria-label="${escapeHtml(`Składniki rachunku dla ${tariff.name}, razem ${formatPLN(breakdown.total_pln ?? tariff.total_pln)} brutto. Kwoty i udziały w legendzie.`)}">
        <circle cx="110" cy="110" r="82" fill="none" stroke="var(--surface-3)" stroke-width="30"></circle>${arcs}</svg>
      <div class="invoice-donut-center"><span>Razem brutto</span><strong>${formatPLN(breakdown.total_pln ?? tariff.total_pln)}</strong></div></div>
      <ul class="invoice-legend" aria-label="Składniki faktury, kwoty i udziały">${legend}</ul></div>
    <p class="muted small">${sum ? 'Składniki netto i akcyza, VAT jako osobna pozycja. Kwoty zaokrąglone do groszy.' + (tariff.prosumer && tariff.prosumer.mode !== 'net_metering' ? ' Przed pokryciem części rachunku z depozytu.' : '') : 'Brak kosztów do przedstawienia na wykresie.'}
      ${detailed ? '' : 'Ta zapisana analiza ma opłaty zmienne i stałe zgrupowane. Wykonaj ją ponownie, aby zobaczyć poszczególne opłaty.'}</p>
    </section>`;
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
    </div>${renderDataQuality(result.data_quality)}`;
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
      <div class="bar-row ${tariff.rank === 1 ? 'is-best' : ''}" data-chart-tooltip="${escapeHtml(formatPLN(tariff.total_pln))}" data-chart-color="${tariff.rank === 1 ? 'accent' : 'teal'}" aria-label="${escapeHtml(`${tariff.name}: ${formatPLN(tariff.total_pln)} brutto · ${delta}`)}" tabindex="0">
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
              <p class="muted small" style="margin-top:10px">${result.prosumer ? 'Przeliczenie na rok' : 'Szacunek w skali roku'}: <strong>${formatPLN(tariff.annual_pln)}</strong></p>
            </div>
          </div>
          ${renderProsumerLedger(tariff)}
          ${renderInvoiceDonut(tariff)}
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
        const style = ` style="--heatmap-color:rgba(232,147,12,${alpha.toFixed(3)});--heatmap-base:var(${alpha > 0 ? '--surface' : '--surface-3'});"`;
        const label = `${DAYS[dayIndex]} ${String(hour).padStart(2, '0')}:00 — ${formatNumber(numeric, 2)} kWh`;
        cells += `<div class="heatmap-cell profile-hour-cell" data-hour="${hour}"${style} aria-label="${escapeHtml(label)}" tabindex="0">
          <span class="profile-cell-value" aria-hidden="true"><strong>${formatNumber(numeric, 2)}</strong></span></div>`;
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

  const monthLabel = (month) => {
    const [year, number] = String(month).split('-').map(Number);
    return new Date(year, number - 1, 1).toLocaleDateString('pl-PL', { month: 'short', year: 'numeric' });
  };
  const monthProfile = Array.isArray(result.month_weekday_profile) ? result.month_weekday_profile : [];
  let monthHeatmap = '';
  if (monthProfile.length) {
    const maximum = Math.max(...monthProfile.flatMap((row) => row.weekday_kwh), 0);
    let cells = '<div></div>' + DAYS.map((day) => `<div class="heatmap-hour">${day}</div>`).join('');
    monthProfile.forEach((row) => {
      cells += `<div class="heatmap-day">${escapeHtml(monthLabel(row.month))}</div>`;
      row.weekday_kwh.forEach((value, index) => {
        const hasData = (row.weekday_sample_count?.[index] ?? 1) > 0;
        const alpha = value > 0 && maximum > 0 ? Math.min(0.92, 0.12 + value / maximum * 0.8) : 0;
        const style = ` style="--heatmap-color:rgba(232,147,12,${alpha.toFixed(3)});--heatmap-base:var(${alpha > 0 ? '--surface' : '--surface-3'});"`;
        const label = `${monthLabel(row.month)}, ${DAYS[index]} — ${hasData ? `${formatNumber(value, 2)} kWh` : 'brak statystyk'}`;
        cells += `<div class="heatmap-cell month-heatmap-cell${hasData ? '' : ' no-data'}"${style} title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}" tabindex="0">${hasData ? formatNumber(value, 1) : '—'}</div>`;
      });
    });
    monthHeatmap = `<div class="card-head chart-heading"><h3>Zużycie według miesięcy i dni tygodnia</h3>
        <span class="muted small">suma kWh dla każdego dnia tygodnia w miesiącu</span></div>
      <div class="heatmap"><div class="heatmap-grid month-heatmap-grid">${cells}</div>
        <div class="legend"><span>0 kWh</span><span class="legend-gradient"></span><span>${formatNumber(maximum, 2)} kWh</span><span>· — brak statystyk</span></div></div>`;
  }

  const qualityByMonth = new Map((result.data_quality?.months || []).map((row) => [row.month, row]));
  const missingLabel = (month) => qualityByMonth.get(month)?.missing_hours
    ? ` · niepełne dane: brak ${qualityByMonth.get(month).missing_hours} godz.` : '';
  const monthWarning = (month) => missingLabel(month) ? `<span class="coverage-warning" title="${escapeHtml(missingLabel(month))}"> ⚠</span>` : '';
  const monthly = Array.isArray(result.monthly_kwh) ? result.monthly_kwh : [];
  let monthlyChart = '';
  if (monthly.length) {
    const monthlyMax = Math.max(...monthly.map((item) => Number(item.kwh) || 0), 0.01);
    const barsHtml = monthly.map((item) => {
      const [year, month] = String(item.month).split('-').map(Number);
      const label = new Date(year, month - 1, 1).toLocaleDateString('pl-PL', { month: 'short', year: '2-digit' });
      const height = Math.max(3, ((Number(item.kwh) || 0) / monthlyMax) * 100);
      const tooltip = escapeHtml(`${monthLabel(item.month)} — ${formatNumber(item.kwh, 2)} kWh${missingLabel(item.month)}`);
      return `<div class="month-bar" data-chart-tooltip="${escapeHtml(`${formatNumber(item.kwh, 2)} kWh`)}" data-chart-color="teal" aria-label="${tooltip}" tabindex="0">
        <div class="month-bar-track"><div class="month-bar-fill" style="height:${height.toFixed(1)}%"></div></div>
        <span>${escapeHtml(label)}${monthWarning(item.month)}</span>
      </div>`;
    }).join('');
    monthlyChart = `
      <div class="card-head" style="margin-top:22px;margin-bottom:0">
        <h3>Zużycie miesięczne</h3>
        <span class="muted small">kWh</span>
      </div>
      <div class="month-bars">${barsHtml}</div>`;
  }

  const monthlyCosts = Array.isArray(result.monthly_costs) ? result.monthly_costs : [];
  let monthlyCostChart = '';
  if (monthlyCosts.length && result.current_tariff_id && result.monthly_costs_basis === 'analysis') {
    const maxCost = Math.max(...monthlyCosts.flatMap((row) => [row.current, row.recommended])
      .filter((cost) => cost && cost.total_pln !== null).map((cost) => Number(cost.total_pln)), 0.01);
    const costBars = monthlyCosts.map((row) => {
      const bar = (cost, kind, label) => {
        const available = cost && cost.total_pln !== null && !cost.error;
        const title = available ? `${monthLabel(row.month)} — ${label}: ${cost.name}, ${formatPLN(cost.total_pln)} brutto${missingLabel(row.month)}` : `${monthLabel(row.month)} — ${label}: ${cost?.error || 'brak dostępnej taryfy'}`;
        const height = available ? Math.max(0, Number(cost.total_pln) / maxCost * 100) : 0;
        return `<div class="cost-bar-column" data-chart-tooltip="${available ? escapeHtml(formatPLN(cost.total_pln)) : '— zł'}" data-chart-color="${kind === 'current' ? 'accent' : 'teal'}" aria-label="${escapeHtml(title)}" tabindex="0">
          <div class="cost-bar-track"><div class="cost-bar-fill ${kind}" style="height:${height.toFixed(3)}%"></div></div>
          <span class="cost-bar-value">${available ? formatNumber(cost.total_pln, 2) : '—'}</span></div>`;
      };
      return `<div class="cost-month"><div class="cost-pair">${bar(row.current, 'current', 'Moja taryfa')}${bar(row.recommended, 'cheapest', 'Najtańsza taryfa')}</div>
        <span class="cost-month-label">${escapeHtml(monthLabel(row.month))}${monthWarning(row.month)}</span></div>`;
    }).join('');
    const unavailable = monthlyCosts.filter((row) => row.unavailable_tariffs?.length).map((row) =>
      `<li><strong>${escapeHtml(monthLabel(row.month))}</strong>: ${row.unavailable_tariffs.map((cost) => `${escapeHtml(cost.name)} — ${escapeHtml(cost.error)}`).join('; ')}</li>`).join('');
    monthlyCostChart = `<div class="card-head chart-heading"><h3>Koszty miesięczne</h3><span class="muted small">${result.prosumer ? 'do zapłaty po rozliczeniu · zł' : 'pełny rachunek brutto · zł'}</span></div>
      <div class="cost-legend"><span><i class="current"></i>Moja taryfa: ${escapeHtml(result.current_tariff_name)}</span>
        <span><i class="cheapest"></i>Najtańsza w całej analizie: ${escapeHtml(result.cheapest_tariff_name)}</span></div>
      <div class="cost-months">${costBars}</div>
      <p class="muted small">Ta sama taryfa, najtańsza w całym okresie analizy, jest porównywana z Twoją obecną taryfą w każdym miesiącu. Opłaty stałe proporcjonalnie do dni w zakresie; próg mocowej z całej analizy.</p>
      ${unavailable ? `<details class="monthly-cost-errors"><summary>Niepełne dane — porównanie obejmuje dostępne wyniki</summary><ul>${unavailable}</ul></details>` : ''}`;
  } else if (monthlyCosts.length && result.monthly_costs_basis !== 'analysis') {
    monthlyCostChart = '<p class="muted small chart-heading">Wykonaj analizę ponownie, aby porównać wszystkie miesiące z jedną taryfą, najtańszą w całym okresie.</p>';
  } else if (monthlyCosts.length) {
    monthlyCostChart = '<div class="card-head chart-heading"><h3>Koszty miesięczne</h3></div><p class="muted small">Wybierz obecną taryfę w zakładce Sensory i wykonaj nową analizę, aby porównać miesięczne koszty.</p>';
  } else {
    monthlyCostChart = '<p class="muted small chart-heading">Ta zapisana analiza nie zawiera nowych wykresów. Wykonaj ją ponownie, aby zobaczyć miesięczny profil i porównanie kosztów.</p>';
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
    ${result.prosumer ? `<div class="notice prosumer-summary"><strong>Symulacja prosumenta — ${escapeHtml(result.prosumer.settings.mode === 'net_metering' ? 'net-metering' : result.prosumer.settings.mode.toUpperCase())}</strong><p>Ranking i koszty miesięczne pokazują kwotę do zapłaty po rozliczeniu. Saldo końcowe pozostaje osobno. Eksport po bilansowaniu godzinowym: ${formatNumber(result.prosumer.export_kwh,2)} kWh.</p><p>Kompletność wspólnych godzin poboru i eksportu: ${formatNumber(result.prosumer.paired_quality.percent,1)}%${result.prosumer.incomplete ? ' — wynik niepełny' : ''}.</p></div>${renderDataQuality(result.prosumer.export_quality, 'Kompletność danych eksportu')}` : ''}
    ${renderDataQuality(result.data_quality, result.prosumer ? 'Kompletność danych poboru' : 'Kompletność danych')}

    <div class="result-hero">
      <div class="hero-main">
        <span class="eyebrow">${isTie ? 'Remis na szczycie' : 'Najtańsza taryfa'}</span>
        <h2>${escapeHtml(cheapest.name)}
          ${cheapest.is_preset ? '<span class="badge">preset</span>' : ''}
        </h2>
        <p class="muted">${escapeHtml(cheapest.description || 'Taryfa własna.')}</p>
        <div class="hero-metrics">
          <div><span>${result.prosumer ? 'Do zapłaty w okresie' : 'Koszt w okresie'}</span><strong>${formatPLN(cheapest.total_pln)}</strong></div>
          <div><span>${result.prosumer ? 'Przeliczenie na rok' : 'Szacunek roczny'}</span><strong>${formatPLN(cheapest.annual_pln)}</strong></div>
          <div><span>Średnia cena</span><strong>${formatNumber(cheapest.per_kwh_pln, 3)} zł/kWh</strong></div>
        </div>
      </div>
      ${heroSaving}
    </div>

    <section class="card">
      <div class="card-head">
        <h3>Porównanie kosztów</h3>
        <span class="muted small">${result.prosumer ? 'do zapłaty po rozliczeniu prosumenta' : 'pełny rachunek z opłatami stałymi i VAT'}</span>
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
        <span class="muted small">suma zużycia w podziale na dzień tygodnia i godzinę</span>
      </div>
      ${heatmap || '<p class="muted small">Brak danych profilu.</p>'}
      ${monthHeatmap}
      ${monthlyChart}
      ${monthlyCostChart}
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

function isDefaultZone(zone) {
  if (zone.kompas_level != null) return false;
  return Boolean(zone.is_default) || (
    (zone.days || []).length === 7 && !(zone.months || []).length &&
    (zone.intervals || []).length === 1 && zone.intervals[0] === '00:00-24:00' &&
    !zone.exclude_holidays
  );
}

function zoneSchedule(zone) {
  if (zone.kompas_level != null) return `Strefa S${Number(zone.kompas_level) + 1} — godziny z Kompasu PSE`;
  if (isDefaultZone(zone)) return 'Pozostałe godziny — strefa domyślna';
  const days = (zone.days || []).map((day) => DAYS[day]).join(', ');
  const intervals = (zone.intervals || []).join(', ');
  const months = monthsLabel(zone.months);
  return `${days} · ${intervals}${months ? ` · mies.: ${months}` : ''}`;
}

function zoneDescription(zone) {
  return zone.description || (zone.kompas_level != null
    ? state.config?.kompas_zone_descriptions?.[zone.kompas_level] || '' : '');
}

function tariffZoneHelp(config) {
  if (config.zone_source !== 'pse_kompas') return '';
  return `<details class="tariff-zone-help">
    <summary>Co oznaczają strefy S1–S4?</summary>
    <p>Kompas PSE wskazuje, kiedy systemowi energetycznemu sprzyja większe lub mniejsze zużycie energii, m.in. w zależności od produkcji OZE i zapotrzebowania.</p>
    <dl>${(config.zones || []).map(zone => `<dt>${escapeHtml(zone.name)}</dt><dd>${escapeHtml(zoneDescription(zone))}</dd>`).join('')}</dl>
    <p>Godziny stref zmieniają się z dnia na dzień — nie są stałym harmonogramem. S1–S4 zmieniają cenę dystrybucji; cena samej energii pozostaje stała według cennika. Do dystrybucji dochodzą energia i pozostałe opłaty.</p>
  </details>`;
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
    const zones = (config.zones || []).slice().sort((a, b) => Number(isDefaultZone(a)) - Number(isDefaultZone(b)));
    const pills = zones.slice(0, 5).map((zone) => `
      <span class="zone-pill" title="${escapeHtml(zoneSchedule(zone))}">
        ${escapeHtml(isDefaultZone(zone) && zone.name === 'Pozaszczyt' ? 'Pozostałe godziny — strefa domyślna' : zone.name)}
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
        ${tariffZoneHelp(config)}
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
  const isDefault = isDefaultZone(zone);
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
    <div class="zone-editor" data-zone-id="${escapeHtml(id)}" ${zone.kompas_level != null ? `data-kompas-level="${Number(zone.kompas_level)}"` : ''}>
      <div class="zone-editor-head">
        <input class="input zone-name" value="${escapeHtml(isDefault && zone.name === 'Pozaszczyt' ? 'Pozostałe godziny — strefa domyślna' : (zone.name || ''))}" maxlength="80" placeholder="Nazwa strefy, np. Szczyt">
        <button type="button" class="icon-button small" data-remove-zone title="Usuń strefę" aria-label="Usuń strefę">✕</button>
      </div>
      ${zoneDescription(zone) ? `<p class="muted small" data-zone-description>${escapeHtml(zoneDescription(zone))}</p>` : ''}
      <label class="check-row">
        <input type="checkbox" class="zone-default" ${isDefault ? 'checked' : ''}>
        Pozostałe godziny — strefa domyślna
      </label>
      <p class="field-hint">Strefa domyślna jest zawsze sprawdzana na końcu. Obejmuje czas poza pozostałymi strefami, także w święta.</p>
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
  const zones = Array.isArray(config.zones) ? config.zones.slice().sort((a, b) => Number(isDefaultZone(a)) - Number(isDefaultZone(b))) : [];
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
                  <p class="muted small">Pierwsza pasująca strefa wygrywa. Strefa domyślna jest automatycznie ustawiana i sprawdzana na końcu.</p>
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
                <p class="field-hint">Miesięczne, netto; proporcjonalnie do okresu. Sieciowa: 1 faza 7,38 zł; 3 fazy 10,86 zł. Abonament od 01.10.2026 nie jest naliczany (0 zł). Opłatę handlową wpisz z umowy.</p>
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
  $$('.zone-editor', $('#zone-list')).forEach(syncDefaultZoneEditor);
  if (config.zone_source === 'pse_kompas') {
    $('[data-add-zone]', $('#tariff-form')).hidden = true;
    $$('.zone-default', $('#zone-list')).forEach(input => { input.closest('label').hidden = true; });
    $('#zone-list').previousElementSibling.querySelector('p').textContent = 'Strefy S1–S4 wybiera Kompas PSE. Możesz edytować nazwy i stawki; godzin nie ustawia się ręcznie.';
  }
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

function syncDefaultZoneEditor(row) {
  const dynamic = row.dataset.kompasLevel != null;
  const enabled = $('.zone-default', row).checked;
  $('.zone-default', row).disabled = dynamic;
  $('[data-remove-zone]', row).disabled = dynamic;
  if (dynamic) {
    $('.zone-default', row).closest('label').hidden = true;
    $('.zone-default', row).closest('label').nextElementSibling.textContent = `Strefa S${Number(row.dataset.kompasLevel) + 1} — godziny pobierane z Kompasu PSE.`;
    $$('.day-input, .month-input, .zone-intervals', row).forEach(input => { input.closest('.field').hidden = true; });
    $('.zone-holidays', row).closest('label').hidden = true;
  }
  $$('.day-input, .month-input, .zone-intervals, .zone-holidays', row).forEach((input) => {
    input.disabled = enabled || dynamic;
  });
  if (enabled) {
    $$('.day-input', row).forEach((input) => { input.checked = true; });
    $$('.month-input', row).forEach((input) => { input.checked = false; });
    $('.zone-intervals', row).value = '00:00-24:00';
    $('.zone-holidays', row).checked = false;
  }
}

async function saveTariffForm(form) {
  const errorBox = $('#tariff-form-error');
  errorBox?.classList.remove('is-visible');

  try {
    const name = $('#tariff-name').value.trim();
    if (!name) throw new Error('Podaj nazwę taryfy.');
    const description = $('#tariff-description').value.trim();

    const zones = $$('.zone-editor', form).map((element) => {
      const isDefault = $('.zone-default', element).checked;
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
      if (!isDefault && !days.length) throw new Error(`Strefa „${zoneName}” nie ma wybranych dni.`);
      if (!isDefault && !intervals.length) throw new Error(`Strefa „${zoneName}” nie ma przedziałów godzinowych.`);
      if (!Number.isFinite(energy) || energy < 0 || energy > 10) throw new Error(`Strefa „${zoneName}”: nieprawidłowa cena energii.`);
      if (!Number.isFinite(distribution) || distribution < 0 || distribution > 10) throw new Error(`Strefa „${zoneName}”: nieprawidłowa cena dystrybucji.`);

      return {
        id: element.dataset.zoneId || newZoneId(),
        name: zoneName,
        is_default: isDefault,
        description: $('[data-zone-description]', element)?.textContent || '',
        ...(element.dataset.kompasLevel != null ? {kompas_level: Number(element.dataset.kompasLevel)} : {}),
        days: isDefault ? [0, 1, 2, 3, 4, 5, 6] : days,
        intervals: isDefault ? ['00:00-24:00'] : intervals,
        ...(!isDefault && months.length && months.length < 12 ? { months } : {}),
        energy_net: energy,
        distribution_net: distribution,
        exclude_holidays: !isDefault && $('.zone-holidays', element).checked,
      };
    });

    if (!zones.length) throw new Error('Dodaj co najmniej jedną strefę.');
    if (zones.filter(isDefaultZone).length > 1) throw new Error('Taryfa może mieć tylko jedną strefę domyślną. Zmień godziny lub dni drugiej strefy całodobowej.');
    zones.sort((a, b) => Number(isDefaultZone(a)) - Number(isDefaultZone(b)));

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
        zone_source: state.editingTariff?.config.zone_source || 'schedule',
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

  root.addEventListener('change', (event) => {
    if (!event.target.matches('.zone-default')) return;
    const row = event.target.closest('.zone-editor');
    if (event.target.checked) {
      if ($$('.zone-default:checked', root).length > 1) {
        event.target.checked = false;
        toast('Najpierw wyłącz oznaczenie dotychczasowej strefy domyślnej.', 'error');
        return;
      }
      $('#zone-list').append(row);
    }
    syncDefaultZoneEditor(row);
  });

  root.addEventListener('click', (event) => {
    if (event.target.closest('[data-close]')) {
      closeModal();
      return;
    }

    const addZone = event.target.closest('[data-add-zone]');
    if (addZone) {
      const fallback = $('#zone-list .zone-default:checked')?.closest('.zone-editor');
      if (fallback) fallback.insertAdjacentHTML('beforebegin', zoneEditorHtml({}));
      else $('#zone-list').insertAdjacentHTML('beforeend', zoneEditorHtml({}));
      const rows = $$('.zone-editor', $('#zone-list'));
      rows.findLast((row) => !$('.zone-default', row).checked)?.querySelector('.zone-name')?.focus();
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
      applyProsumerSettings(result.prosumer?.settings || {mode:'off'});

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
  bindSensorEvents();
  bindProsumerEvents();
  bindChartTooltips();
  bindInvoiceLegendHover();
  setDateRange(addDays(today(), -29), today());

  await loadConfig();
  await Promise.allSettled([loadEntities(), loadTariffs()]);
  await loadProsumer();
  await loadHistory();

  const hash = window.location.hash.replace('#', '');
  if (QUICK_TABS.has(hash)) switchTab(hash);
}

document.addEventListener('DOMContentLoaded', init);
