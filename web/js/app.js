/* ==========================================================================
   FiloTrack dashboard — vanilla JavaScript, no framework.
   Depends on: Leaflet (global `L`), i18n.js (global `I18n`).

   Data flow
     GET /api/bootstrap   routes + vehicle definitions (once)
     SSE /api/stream      full fleet snapshot ~1 Hz  → applyState()
     GET .../history      selected vehicle's trail on the map
     GET .../series       selected vehicle's speed chart
   ========================================================================== */
'use strict';

const t = I18n.t;

/* ------------------------------------------------------------------ DOM */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const els = {
  clock: $('#clock'),
  dateLabel: $('#dateLabel'),
  connBadge: $('#connBadge'),
  connText: $('#connText'),
  pauseBtn: $('#pauseBtn'),
  speedGroup: $('#speedGroup'),
  langGroup: $('#langGroup'),
  soundBtn: $('#soundBtn'),
  settingsBtn: $('#settingsBtn'),
  kpiTotal: $('#kpiTotal'),
  kpiMoving: $('#kpiMoving'),
  kpiAlarms: $('#kpiAlarms'),
  kpiAvg: $('#kpiAvg'),
  alarmKpi: $('.alarm-kpi'),
  vehicleList: $('#vehicleList'),
  fleetSub: $('#fleetSub'),
  fleetSearch: $('#fleetSearch'),
  storageInfo: $('#storageInfo'),
  mapSubtitle: $('#mapSubtitle'),
  detPlate: $('#detPlate'),
  detKind: $('#detKind'),
  detStatus: $('#detStatus'),
  detDriver: $('#detDriver'),
  detModel: $('#detModel'),
  detSpeed: $('#detSpeed'),
  detLimit: $('#detLimit'),
  speedFill: $('#speedFill'),
  detRoute: $('#detRoute'),
  detProgress: $('#detProgress'),
  detOffset: $('#detOffset'),
  detOdo: $('#detOdo'),
  progressFill: $('#progressFill'),
  historyRange: $('#historyRange'),
  chart: $('#speedChart'),
  triggerSpeed: $('#triggerSpeed'),
  triggerDev: $('#triggerDev'),
  exportBtn: $('#exportBtn'),
  alarmList: $('#alarmList'),
  alarmSub: $('#alarmSub'),
  openCount: $('#openCount'),
  ackAll: $('#ackAll'),
  alarmTabs: $$('.alarm-tabs button'),
  toasts: $('#toasts'),
  settingsModal: $('#settingsModal'),
  closeSettings: $('#closeSettings'),
  cancelSettings: $('#cancelSettings'),
  saveSettings: $('#saveSettings'),
  tolInput: $('#tolInput'),
  devInput: $('#devInput'),
  retInput: $('#retInput'),
  tolOut: $('#tolOut'),
  devOut: $('#devOut'),
  retOut: $('#retOut'),
};

/* ------------------------------------------------------------------ constants */
/* Marker / card colors per vehicle status (labels come from i18n: status.*) */
const STATUS_COLORS = {
  moving: '#22c55e',
  speed: '#f59e0b',
  deviation: '#ef4444',
  stopped: '#64748b',
};

const MARKER_STATUS_CLASSES = Object.keys(STATUS_COLORS).map((status) => `status-${status}`);

/* CSS modifier class per alarm type (labels come from i18n: alarmType.*) */
const ALARM_CLASS = { SPEED: 'speed', DEVIATION: 'deviation' };

const TOAST_LIFETIME_MS = 9000;
const MAX_TOASTS = 4;
const HISTORY_REFRESH_MS = 25000;
const SERIES_REFRESH_MS = 15000;
const RECONNECT_DELAY_MS = 3000;

const ICONS = {
  speed: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20a8 8 0 1 1 8-8"/><path d="M12 12l4-4"/></svg>',
  deviation: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 18l4-10 4 8 3-5 5 7"/><path d="M3 21h18"/></svg>',
  warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l9 16H3L12 3z"/><path d="M12 9v5M12 17h.01"/></svg>',
  pause: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5l11 7-11 7V5z"/></svg>',
  soundOn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16.5 8.5a5 5 0 0 1 0 7"/></svg>',
  soundOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M22 9l-6 6M16 9l6 6"/></svg>',
};

/* ------------------------------------------------------------------ state */
const state = {
  routes: {},
  vehiclesMeta: [],
  snapshot: null,
  online: false,
  selectedId: null,
  filter: '',
  alarmTab: 'open',
  seenAlarmIds: null,     // open alarm ids already notified (null until the first snapshot)
  sound: true,
  map: null,
  markers: {},
  routeLines: {},
  styledFor: null,        // vehicle id the route highlighting was last applied for
  corridor: null,         // wide translucent line under the selected vehicle's route
  corridorKey: null,
  historyLayer: null,
  speedSeries: [],
  alarmSignature: '',     // skips re-rendering the alarm list when nothing changed
  audioCtx: null,
};

const staticMode = new URLSearchParams(window.location.search).has('static');

/* ------------------------------------------------------------------ helpers */
function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function formatTime(ts) {
  if (!ts) return '--:--';
  return new Date(ts).toLocaleTimeString(I18n.localeTag(), { hour12: false });
}

function formatRelative(ts, now = Date.now()) {
  const seconds = Math.max(0, Math.floor((now - ts) / 1000));
  if (seconds < 10) return t('time.justNow');
  if (seconds < 60) return t('time.secondsAgo', { n: seconds });
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t('time.minutesAgo', { n: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('time.hoursAgo', { n: hours });
  return new Date(ts).toLocaleDateString(I18n.localeTag());
}

function hexToRgba(hex, alpha) {
  const h = hex.replace('#', '');
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function statusOf(vehicle) {
  return STATUS_COLORS[vehicle.status] ? vehicle.status : 'moving';
}

/* Server data is language-neutral; these helpers localize it. */
function kindLabel(kind) {
  const key = `kind.${kind}`;
  const label = t(key);
  return label === key ? kind : label; // unknown kind: show the raw value
}

function routeName(vehicle) {
  const key = `route.${vehicle.route_id}.name`;
  return I18n.has(key) ? t(key) : vehicle.route_name;
}

function routeArea(vehicle) {
  const key = `route.${vehicle.route_id}.area`;
  return I18n.has(key) ? t(key) : vehicle.route_area;
}

function alarmTypeLabel(type) {
  return ALARM_CLASS[type] ? t(`alarmType.${type}`) : type;
}

/** Alarm text in the current language, built from the alarm's structured fields. */
function alarmMessage(alarm) {
  if (alarm.type === 'SPEED' && alarm.speed != null && alarm.speed_limit != null) {
    return t('alarmMessage.SPEED', {
      speed: Math.round(alarm.speed),
      limit: Math.round(alarm.speed_limit),
      over: Math.round(alarm.speed - alarm.speed_limit),
    });
  }
  if (alarm.type === 'DEVIATION' && alarm.offset_m != null && alarm.threshold_m != null) {
    return t('alarmMessage.DEVIATION', {
      offset: Math.round(alarm.offset_m),
      threshold: Math.round(alarm.threshold_m),
    });
  }
  return alarm.message; // unknown type: fall back to the server's English text
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try { message = (await res.json()).error || message; } catch (err) { /* body was not JSON */ }
    throw new Error(message);
  }
  return res.json();
}

function selectedVehicle() {
  const vehicles = state.snapshot?.vehicles;
  if (!vehicles) return null;
  return vehicles.find((v) => v.vehicle_id === state.selectedId) || null;
}

/* ------------------------------------------------------------------ map */
function initMap() {
  const map = L.map('map', {
    zoomControl: false,
    attributionControl: true,
    minZoom: 9,
    maxZoom: 18,
    preferCanvas: true,
    zoomSnap: 0.25,
  });
  state.map = map;

  L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 18,
    maxNativeZoom: 16,
    attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors',
  }).addTo(map);

  L.control.zoom({ position: 'bottomright' }).addTo(map);

  const bounds = L.latLngBounds([]);
  Object.entries(state.routes).forEach(([routeId, route]) => {
    state.routeLines[routeId] = L.polyline(route.points, {
      color: route.color,
      weight: 3,
      opacity: 0.28,
      dashArray: '2 6',
      lineCap: 'round',
      interactive: false,
    }).addTo(map);
    route.points.forEach((p) => bounds.extend(p));
  });

  state.historyLayer = L.layerGroup().addTo(map);
  if (bounds.isValid()) map.fitBounds(bounds, { padding: [26, 26] });
  else map.setView([41.03, 29.02], 12);
}

/* Highlights the selected vehicle's route and marker. */
function applySelectionStyles() {
  const selected = selectedVehicle();
  Object.entries(state.routeLines).forEach(([routeId, line]) => {
    const active = selected && selected.route_id === routeId;
    line.setStyle({
      weight: active ? 4.5 : 3,
      opacity: active ? 0.85 : 0.24,
      dashArray: active ? null : '2 6',
    });
  });

  const corridorKey = selected ? selected.route_id : null;
  if (state.corridorKey !== corridorKey) {
    state.corridorKey = corridorKey;
    if (state.corridor) {
      state.map.removeLayer(state.corridor);
      state.corridor = null;
    }
    const route = selected && state.routes[selected.route_id];
    if (route) {
      state.corridor = L.polyline(route.points, {
        color: route.color,
        weight: 20,
        opacity: 0.07,
        lineCap: 'round',
        interactive: false,
      }).addTo(state.map);
      state.corridor.bringToBack();
    }
  }

  Object.entries(state.markers).forEach(([vehicleId, marker]) => {
    const el = marker.getElement();
    if (el) el.classList.toggle('selected', vehicleId === state.selectedId);
    marker.setZIndexOffset(vehicleId === state.selectedId ? 1000 : 0);
  });
}

function ensureMarker(v) {
  let marker = state.markers[v.vehicle_id];
  if (marker) return marker;

  const icon = L.divIcon({
    className: 'veh-marker status-moving',
    html: '<div class="veh-pulse"></div><div class="veh-dot">' +
      '<svg class="veh-arrow" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l7 19-7-5-7 5 7-19z"/></svg>' +
      '</div><span class="veh-label"></span>',
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });

  marker = L.marker([v.lat, v.lng], { icon, riseOnHover: true }).addTo(state.map);
  marker.bindTooltip('', { direction: 'top', offset: [0, -16], opacity: 1 });
  marker.on('click', () => selectVehicle(v.vehicle_id, false));
  state.markers[v.vehicle_id] = marker;
  return marker;
}

function renderMarkers(snap) {
  snap.vehicles.forEach((v) => {
    const marker = ensureMarker(v);
    marker.setLatLng([v.lat, v.lng]);

    const el = marker.getElement();
    if (el) {
      const status = statusOf(v);
      // Toggle our classes only: Leaflet's own classes (leaflet-marker-icon, ...) provide
      // `position: absolute`; replacing className would drop them and shift the marker.
      el.classList.remove(...MARKER_STATUS_CLASSES);
      el.classList.add(`status-${status}`);
      el.classList.toggle('selected', v.vehicle_id === state.selectedId);
      el.style.setProperty('--vc', STATUS_COLORS[status]);
      el.style.setProperty('--glow', hexToRgba(STATUS_COLORS[status], 0.5));
      const arrow = el.querySelector('.veh-arrow');
      if (arrow) arrow.style.transform = `rotate(${v.heading || 0}deg)`;
      const label = el.querySelector('.veh-label');
      if (label) label.textContent = v.plate;
    }

    const offsetLine = v.offset_m > 5
      ? `<br><span class="is-alert">${escapeHtml(t('map.offset', { offset: Math.round(v.offset_m) }))}</span>`
      : '';
    marker.setTooltipContent(
      `<b>${escapeHtml(v.plate)}</b> · ${escapeHtml(v.driver)}<br>` +
      `${Math.round(v.speed)} ${escapeHtml(t('unit.speed'))} · ${escapeHtml(routeName(v))}` +
      offsetLine
    );
    marker.setZIndexOffset(v.vehicle_id === state.selectedId ? 1000 : 0);
  });
}

function focusVehicle(id) {
  const v = (state.snapshot?.vehicles || []).find((x) => x.vehicle_id === id);
  if (!v) return;
  state.map.flyTo([v.lat, v.lng], Math.max(state.map.getZoom(), 13.5), { duration: 0.9 });
}

/* ------------------------------------------------------------------ live data */
function applyState(snap, initial = false) {
  if (!snap || !Array.isArray(snap.vehicles)) return;
  state.snapshot = snap;
  setConnection(true);

  if (!state.selectedId || !snap.vehicles.some((v) => v.vehicle_id === state.selectedId)) {
    state.selectedId = snap.vehicles[0]?.vehicle_id || state.selectedId;
  }

  state.sound = !snap.settings || snap.settings.alarm_sound !== 0;
  renderAll(snap);

  // Notify (toast + sound) only for alarms that were not open in the previous snapshot
  const openIds = new Set(snap.alarms.map((a) => a.id));
  if (!initial && state.seenAlarmIds) {
    snap.alarms.forEach((a) => {
      if (!state.seenAlarmIds.has(a.id)) notifyAlarm(a);
    });
  }
  state.seenAlarmIds = openIds;

  if (state.styledFor !== state.selectedId) {
    applySelectionStyles();
    state.styledFor = state.selectedId;
  }
}

function renderAll(snap) {
  updateSoundButton();
  syncSimControls(snap);
  renderKpis(snap);
  renderVehicleList(snap);
  renderDetail(snap);
  renderAlarms(snap);
  renderMarkers(snap);
  renderFooter(snap);
}

function setConnection(online) {
  state.online = online;
  els.connBadge.classList.toggle('offline', !online);
  els.connText.textContent = t(online ? 'conn.online' : 'conn.offline');
}

function connectStream() {
  const source = new EventSource('/api/stream');
  source.onopen = () => setConnection(true);
  source.onmessage = (event) => {
    try {
      applyState(JSON.parse(event.data), false);
    } catch (err) {
      console.error('Could not read SSE message', err);
    }
  };
  source.onerror = () => {
    setConnection(false);
    // The browser retries on its own unless the stream was closed for good
    if (source.readyState === EventSource.CLOSED) setTimeout(connectStream, RECONNECT_DELAY_MS);
  };
}

/* ------------------------------------------------------------------ render: sidebar */
function renderKpis(snap) {
  const stats = snap.stats || {};
  els.kpiTotal.textContent = stats.total ?? snap.vehicles.length;
  els.kpiMoving.textContent = stats.moving ?? 0;
  els.kpiAlarms.textContent = stats.open_alarms ?? snap.alarms.length;
  els.kpiAvg.textContent = Math.round(stats.avg_speed ?? 0);
  els.alarmKpi.classList.toggle('has-alarm', (stats.open_alarms ?? 0) > 0);
}

function renderFooter(snap) {
  const stats = snap.stats || {};
  const storage = snap.storage || {};
  els.storageInfo.textContent = t('storage.info', {
    samples: I18n.formatNumber(stats.samples_today ?? 0),
    size: I18n.formatNumber(storage.db_size_mb ?? 0),
  });
  els.fleetSub.textContent = t('fleet.subtitle', {
    vehicles: snap.vehicles.length,
    routes: Object.keys(state.routes).length,
    moving: stats.moving ?? 0,
  });
  els.mapSubtitle.textContent = t('map.subtitle', { count: snap.vehicles.length });
}

function createVehicleCard(v) {
  const card = document.createElement('div');
  card.className = 'vehicle-card';
  card.dataset.id = v.vehicle_id;
  card.innerHTML = `
    <div class="vc-top">
      <span class="vc-plate"></span>
      <span class="vc-status"></span>
    </div>
    <div class="vc-mid">
      <span class="vc-driver"></span>
      <div class="vc-speed"><b></b><small></small></div>
    </div>
    <div class="vc-route"><i></i><span></span></div>
    <div class="vc-bar"><i></i></div>`;
  card.addEventListener('click', () => selectVehicle(v.vehicle_id, true));
  card._refs = {
    plate: card.querySelector('.vc-plate'),
    status: card.querySelector('.vc-status'),
    driver: card.querySelector('.vc-driver'),
    speed: card.querySelector('.vc-speed b'),
    unit: card.querySelector('.vc-speed small'),
    route: card.querySelector('.vc-route span'),
    bar: card.querySelector('.vc-bar i'),
  };
  return card;
}

function updateVehicleCard(card, v) {
  const refs = card._refs;
  const status = statusOf(v);
  refs.plate.textContent = v.plate;
  refs.status.textContent = t(`status.${status}`);
  refs.status.className = 'vc-status' + (status === 'moving' ? '' : ' ' + status);
  refs.driver.textContent = `${v.driver} · ${kindLabel(v.kind)}`;
  refs.speed.textContent = Math.round(v.speed);
  refs.unit.textContent = t('unit.speed');
  refs.route.textContent = routeName(v);
  const pct = Math.min(100, Math.max(0, (v.speed / (v.speed_limit || 1)) * 100));
  refs.bar.style.width = pct + '%';
  card.style.setProperty('--vc', STATUS_COLORS[status]);
  card.style.setProperty('--rc', v.route_color || '#22d3ee');
  card.classList.toggle('active', v.vehicle_id === state.selectedId);
}

/* Matches the search box against both the raw and the translated values */
function matchesFilter(v) {
  if (!state.filter) return true;
  const tag = I18n.localeTag();
  const query = state.filter.toLocaleLowerCase(tag);
  return [v.plate, v.driver, v.kind, kindLabel(v.kind), v.route_name, routeName(v), v.route_area, routeArea(v)]
    .filter(Boolean)
    .some((value) => String(value).toLocaleLowerCase(tag).includes(query));
}

function emptyState(title, hint, withIcon = false) {
  return `${withIcon ? ICONS.warning : ''}<b>${escapeHtml(title)}</b><span>${escapeHtml(hint)}</span>`;
}

function renderVehicleList(snap) {
  const vehicles = snap.vehicles.filter(matchesFilter);
  const existing = new Map(Array.from(els.vehicleList.children).map((el) => [el.dataset.id, el]));

  Array.from(els.vehicleList.children).forEach((el) => {
    if (!vehicles.some((v) => v.vehicle_id === el.dataset.id)) el.remove();
  });

  vehicles.forEach((v) => {
    const card = existing.get(v.vehicle_id) || createVehicleCard(v);
    updateVehicleCard(card, v);
    els.vehicleList.appendChild(card);
  });

  if (!vehicles.length) {
    let empty = els.vehicleList.querySelector('.empty-state');
    if (!empty) {
      empty = document.createElement('div');
      empty.className = 'empty-state';
      els.vehicleList.appendChild(empty);
    }
    empty.innerHTML = emptyState(t('fleet.emptyTitle'), t('fleet.emptyHint'));
  } else {
    els.vehicleList.querySelector('.empty-state')?.remove();
  }
}

/* ------------------------------------------------------------------ render: detail panel */
function renderDetail(snap) {
  const v = selectedVehicle();
  if (!v) return;
  const status = statusOf(v);
  const settings = snap.settings || {};

  els.detPlate.textContent = v.plate;
  els.detKind.textContent = kindLabel(v.kind);
  els.detStatus.textContent = t(`status.${status}`);
  els.detStatus.className = 'status-badge status-' + status;
  els.detDriver.textContent = v.driver;
  els.detModel.textContent = [v.model, v.phone].filter(Boolean).join(' · ');
  els.detSpeed.textContent = Math.round(v.speed);
  els.detLimit.textContent = Math.round(v.speed_limit);
  els.detRoute.textContent = routeName(v);
  els.detRoute.title = `${routeName(v)} · ${routeArea(v)}`;
  els.detProgress.textContent = t('detail.progressValue', { pct: Math.round(v.progress * 100) });
  els.detOffset.textContent = `${Math.round(v.offset_m)} m`;
  els.detOffset.classList.toggle('is-alert', v.offset_m > (settings.deviation_threshold_m || 120));
  els.detOdo.textContent = `${I18n.formatNumber(Number((v.odometer_m / 1000).toFixed(1)))} km`;
  els.progressFill.style.width = `${Math.min(100, Math.max(0, v.progress * 100))}%`;

  const pct = Math.min(100, Math.max(0, (v.speed / (v.speed_limit || 1)) * 100));
  els.speedFill.style.width = pct + '%';
  els.speedFill.classList.toggle('over', v.speed > v.speed_limit + (settings.speed_tolerance_kmh || 5));
}

/* ------------------------------------------------------------------ render: alarm center */
function renderAlarms(snap, force = false) {
  const items = state.alarmTab === 'open' ? snap.alarms : (snap.recent_alarms || []);
  const openCount = snap.alarms.length;
  const critical = snap.alarms.filter((a) => a.severity === 'critical').length;

  els.openCount.textContent = openCount;
  els.alarmSub.textContent = openCount
    ? t('alarms.summary.open', { count: openCount }) + (critical ? t('alarms.summary.critical', { count: critical }) : '')
    : t('alarms.summary.none');
  els.ackAll.disabled = openCount === 0;

  const signature = state.alarmTab + '|' + items.map((a) => `${a.id}:${a.status}:${a.resolved_ts || 0}`).join(',');
  if (!force && signature === state.alarmSignature) return;
  state.alarmSignature = signature;

  if (!items.length) {
    const isOpenTab = state.alarmTab === 'open';
    els.alarmList.innerHTML = `<div class="empty-state">${emptyState(
      t(isOpenTab ? 'alarms.emptyOpenTitle' : 'alarms.emptyAllTitle'),
      t(isOpenTab ? 'alarms.emptyOpenHint' : 'alarms.emptyAllHint'),
      true
    )}</div>`;
    return;
  }

  const fragment = document.createDocumentFragment();
  items.forEach((a) => fragment.appendChild(createAlarmItem(a)));
  els.alarmList.replaceChildren(fragment);
}

function createAlarmItem(a) {
  const resolved = !!a.resolved_ts;
  const typeClass = ALARM_CLASS[a.type] || 'speed';
  const item = document.createElement('div');
  item.className = ['alarm-item', typeClass, a.severity === 'critical' && 'critical', resolved && 'resolved']
    .filter(Boolean).join(' ');

  const badges = [
    a.status === 'acked' && !resolved ? `<span class="acked">${escapeHtml(t('alarms.acked'))}</span>` : '',
    resolved ? `<span>${escapeHtml(t('alarms.resolved'))}</span>` : '',
  ].join('');
  const action = resolved
    ? '<span class="alarm-status-label">—</span>'
    : `<button class="ack-btn" type="button">${escapeHtml(t('alarms.ack'))}</button>`;

  item.innerHTML = `
    <div class="alarm-icon">${a.type === 'DEVIATION' ? ICONS.deviation : ICONS.speed}</div>
    <div class="alarm-body">
      <div class="alarm-title">${escapeHtml(a.plate || a.vehicle_id)} <span class="tag">${escapeHtml(alarmTypeLabel(a.type))}</span></div>
      <div class="alarm-msg">${escapeHtml(alarmMessage(a))}</div>
      <div class="alarm-meta">
        <span>${formatTime(a.ts)}</span><span>${escapeHtml(formatRelative(a.ts))}</span>${badges}
      </div>
    </div>
    ${action}`;

  item.addEventListener('click', () => selectVehicle(a.vehicle_id, true));
  item.querySelector('.ack-btn')?.addEventListener('click', (ev) => {
    ev.stopPropagation(); // do not also select the vehicle
    acknowledge(a.id);
  });
  return item;
}

/* ------------------------------------------------------------------ selection and history */
function selectVehicle(id, fly = true) {
  if (state.selectedId === id) {
    if (fly) focusVehicle(id);
    return;
  }
  state.selectedId = id;
  state.speedSeries = [];
  drawSpeedChart();
  if (state.snapshot) {
    renderVehicleList(state.snapshot);
    renderDetail(state.snapshot);
    renderAlarms(state.snapshot, true);
  }
  applySelectionStyles();
  state.styledFor = state.selectedId;
  if (fly) focusVehicle(id);
  loadHistory();
  loadSeries();
}

function historyMinutes() {
  return Number(els.historyRange.value) || 60;
}

async function loadHistory() {
  const v = selectedVehicle();
  if (!v) return;
  const id = v.vehicle_id;
  try {
    const data = await api(`/api/vehicles/${id}/history?minutes=${historyMinutes()}`);
    if (state.selectedId === id) drawHistory(data.points || []);
  } catch (err) {
    console.warn('Could not load history:', err.message);
  }
}

function drawHistory(points) {
  if (!state.historyLayer) return;
  state.historyLayer.clearLayers();
  if (points.length < 2) return;

  const latlngs = points.map((p) => [p.lat, p.lng]);
  const color = selectedVehicle()?.route_color || '#22d3ee';

  // Wide colored glow + thin bright core
  L.polyline(latlngs, { color, weight: 5, opacity: 0.25, lineCap: 'round', interactive: false })
    .addTo(state.historyLayer);
  L.polyline(latlngs, { color: '#e8f7ff', weight: 1.6, opacity: 0.55, lineCap: 'round', interactive: false })
    .addTo(state.historyLayer);

  const start = points[0];
  const end = points[points.length - 1];
  L.circleMarker([start.lat, start.lng], {
    radius: 4, color: '#22c55e', weight: 2, fillColor: '#0b1727', fillOpacity: 1, interactive: false,
  }).addTo(state.historyLayer).bindTooltip(t('map.trailStart'), { direction: 'top' });
  L.circleMarker([end.lat, end.lng], {
    radius: 4, color: '#22d3ee', weight: 2, fillColor: '#22d3ee', fillOpacity: 0.8, interactive: false,
  }).addTo(state.historyLayer);
}

async function loadSeries() {
  const v = selectedVehicle();
  if (!v) return;
  const id = v.vehicle_id;
  const minutes = historyMinutes();
  const bucket = minutes <= 15 ? 10 : minutes <= 60 ? 20 : 60; // seconds per chart point
  try {
    const data = await api(`/api/vehicles/${id}/series?minutes=${minutes}&bucket=${bucket}`);
    if (state.selectedId !== id) return;
    state.speedSeries = data.series || [];
    drawSpeedChart();
  } catch (err) {
    console.warn('Could not load speed series:', err.message);
  }
}

/* ------------------------------------------------------------------ speed chart (canvas) */
function drawSpeedChart() {
  const canvas = els.chart;
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  if (rect.width < 10) return;

  const dpr = window.devicePixelRatio || 1;
  const height = 96;
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(height * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, height);

  const limit = selectedVehicle()?.speed_limit || 50;
  const data = state.speedSeries;
  const maxVal = Math.max(limit * 1.4, ...data.map((d) => d.max || 0), 20);
  const padTop = 10;
  const padBottom = 14;
  const plotH = height - padTop - padBottom;

  // Horizontal grid lines
  ctx.strokeStyle = 'rgba(148,178,214,0.08)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 2; i++) {
    const y = padTop + (plotH / 2) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(rect.width, y);
    ctx.stroke();
  }

  if (data.length < 2) {
    ctx.fillStyle = 'rgba(139,163,192,0.6)';
    ctx.font = '10px "Segoe UI", sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(t('chart.collecting'), rect.width / 2, height / 2);
    return;
  }

  const firstTs = data[0].ts;
  const lastTs = data[data.length - 1].ts;
  const span = Math.max(1000, lastTs - firstTs);
  const xOf = (ts) => ((ts - firstTs) / span) * (rect.width - 6) + 3;
  const yOf = (val) => padTop + plotH - Math.min(1, val / maxVal) * plotH;
  const tracePath = () => {
    ctx.beginPath();
    data.forEach((d, i) => (i === 0 ? ctx.moveTo(xOf(d.ts), yOf(d.avg)) : ctx.lineTo(xOf(d.ts), yOf(d.avg))));
  };

  // Speed limit (dashed)
  const limitY = yOf(limit);
  ctx.setLineDash([3, 4]);
  ctx.strokeStyle = 'rgba(245,158,11,0.45)';
  ctx.beginPath();
  ctx.moveTo(0, limitY);
  ctx.lineTo(rect.width, limitY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Filled area under the average speed
  const gradient = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
  gradient.addColorStop(0, 'rgba(34,211,238,0.22)');
  gradient.addColorStop(1, 'rgba(34,211,238,0)');
  tracePath();
  ctx.lineTo(rect.width, padTop + plotH);
  ctx.lineTo(0, padTop + plotH);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  // Average speed line
  tracePath();
  ctx.strokeStyle = '#22d3ee';
  ctx.lineWidth = 1.6;
  ctx.lineJoin = 'round';
  ctx.stroke();

  // Latest point
  const last = data[data.length - 1];
  ctx.beginPath();
  ctx.arc(xOf(last.ts), yOf(last.avg), 2.6, 0, Math.PI * 2);
  ctx.fillStyle = '#7dd3fc';
  ctx.fill();

  // Labels
  ctx.font = '8px "Segoe UI", sans-serif';
  ctx.fillStyle = 'rgba(139,163,192,0.65)';
  ctx.textAlign = 'left';
  ctx.fillText(t('chart.max', { value: Math.round(Math.max(...data.map((d) => d.max || 0))) }), 0, 8);
  ctx.textAlign = 'right';
  ctx.fillStyle = 'rgba(245,158,11,0.75)';
  ctx.fillText(t('chart.limit', { value: Math.round(limit) }), rect.width, 8);
  ctx.textAlign = 'left';
  ctx.fillStyle = 'rgba(95,120,153,0.75)';
  ctx.fillText(formatTime(firstTs), 0, height - 2);
  ctx.textAlign = 'right';
  ctx.fillText(formatTime(lastTs), rect.width, height - 2);
}

/* ------------------------------------------------------------------ alarms: actions, toasts, sound */
async function acknowledge(id) {
  try {
    await api(`/api/alarms/${id}/ack`, { method: 'POST', body: '{}' });
  } catch (err) {
    toast(t('toast.error'), err.message, 'critical');
  }
}

async function acknowledgeAll() {
  try {
    const res = await api('/api/alarms/ack-all', { method: 'POST', body: '{}' });
    if (res.acknowledged) {
      toast(t('toast.ackedTitle'), t('toast.ackedBody', { count: res.acknowledged }), 'info');
    }
  } catch (err) {
    toast(t('toast.error'), err.message, 'critical');
  }
}

function notifyAlarm(a) {
  const critical = a.severity === 'critical';
  toast(`${a.plate || a.vehicle_id} · ${alarmTypeLabel(a.type)}`, alarmMessage(a), critical ? 'critical' : 'warning', a.ts);
  if (state.sound) beep(critical);
}

function toast(title, message, kind = 'info', ts = Date.now()) {
  const critical = kind === 'critical';
  const el = document.createElement('div');
  el.className = 'toast' + (critical ? ' critical' : '');
  el.innerHTML = `
    <div class="toast-icon">${critical ? ICONS.warning : ICONS.speed}</div>
    <div class="toast-body">
      <b>${escapeHtml(title)}</b>
      <p>${escapeHtml(message)}</p>
      <small>${formatTime(ts)}</small>
    </div>`;
  els.toasts.appendChild(el);
  setTimeout(() => {
    el.classList.add('is-leaving');
    setTimeout(() => el.remove(), 260);
  }, TOAST_LIFETIME_MS);
  while (els.toasts.children.length > MAX_TOASTS) els.toasts.firstElementChild.remove();
}

/* Short WebAudio beep; two tones for critical alarms. Browsers may block audio
   until the user has interacted with the page. */
function beep(critical = false) {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    state.audioCtx = state.audioCtx || new AudioCtx();
    const ctx = state.audioCtx;
    if (ctx.state === 'suspended') ctx.resume();
    const play = (freq, at, duration) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + at);
      gain.gain.exponentialRampToValueAtTime(0.14, ctx.currentTime + at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + duration);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + at);
      osc.stop(ctx.currentTime + at + duration + 0.02);
    };
    play(critical ? 660 : 880, 0, 0.18);
    if (critical) play(520, 0.2, 0.25);
  } catch (err) { /* audio not supported */ }
}

function updateSoundButton() {
  els.soundBtn.innerHTML = state.sound ? ICONS.soundOn : ICONS.soundOff;
  els.soundBtn.classList.toggle('muted', !state.sound);
  els.soundBtn.title = t(state.sound ? 'sound.on' : 'sound.off');
  els.soundBtn.setAttribute('aria-pressed', String(state.sound));
}

/* ------------------------------------------------------------------ simulation controls */
function syncSimControls(snap) {
  const sim = snap.simulation || {};
  const running = sim.running !== false;
  els.pauseBtn.innerHTML = (running ? ICONS.pause : ICONS.play) +
    `<span>${escapeHtml(t(running ? 'sim.pause' : 'sim.resume'))}</span>`;
  els.pauseBtn.title = t(running ? 'sim.pauseTitle' : 'sim.resumeTitle');
  const speed = Number(sim.speed || 1);
  $$('#speedGroup button').forEach((btn) => {
    btn.classList.toggle('active', Math.abs(Number(btn.dataset.speed) - speed) < 0.01);
  });
}

async function postSimulation(body) {
  try {
    await api('/api/simulation', { method: 'POST', body: JSON.stringify(body) });
  } catch (err) {
    toast(t('toast.error'), err.message, 'critical');
  }
}

function toggleSimulation() {
  const running = state.snapshot?.simulation?.running !== false;
  return postSimulation({ action: running ? 'pause' : 'resume' });
}

function setSimSpeed(value) {
  return postSimulation({ action: 'speed', value: Number(value) });
}

async function setSound(enabled) {
  state.sound = enabled;
  updateSoundButton();
  try {
    await api('/api/settings', { method: 'POST', body: JSON.stringify({ alarm_sound: enabled ? 1 : 0 }) });
  } catch (err) {
    console.warn('Could not save the sound setting:', err.message);
  }
  if (enabled) beep(false);
}

async function triggerScenario(kind) {
  const v = selectedVehicle();
  if (!v) return;
  try {
    await api(`/api/vehicles/${v.vehicle_id}/trigger`, { method: 'POST', body: JSON.stringify({ type: kind }) });
    const type = alarmTypeLabel(kind === 'speed' ? 'SPEED' : 'DEVIATION');
    toast(t('toast.scenarioTitle', { plate: v.plate }), t('toast.scenarioBody', { type }), 'warning');
  } catch (err) {
    toast(t('toast.error'), err.message, 'critical');
  }
}

/* ------------------------------------------------------------------ settings dialog */
function openSettings() {
  const settings = state.snapshot?.settings || {};
  const fields = [
    [els.tolInput, els.tolOut, settings.speed_tolerance_kmh ?? 5],
    [els.devInput, els.devOut, settings.deviation_threshold_m ?? 120],
    [els.retInput, els.retOut, settings.retention_hours ?? 24],
  ];
  fields.forEach(([input, output, value]) => {
    input.value = Math.round(value);
    output.textContent = input.value;
  });
  els.settingsModal.hidden = false;
  els.tolInput.focus();
}

function closeSettings() {
  els.settingsModal.hidden = true;
}

async function saveSettings() {
  try {
    await api('/api/settings', {
      method: 'POST',
      body: JSON.stringify({
        speed_tolerance_kmh: Number(els.tolInput.value),
        deviation_threshold_m: Number(els.devInput.value),
        retention_hours: Number(els.retInput.value),
      }),
    });
    closeSettings();
    toast(t('toast.settingsTitle'), t('toast.settingsBody'), 'info');
  } catch (err) {
    toast(t('toast.error'), err.message, 'critical');
  }
}

/* ------------------------------------------------------------------ language */
function syncLanguageButtons() {
  const current = I18n.getLocale();
  els.langGroup.querySelectorAll('button[data-lang]').forEach((btn) => {
    const active = btn.dataset.lang === current;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', String(active));
  });
}

/* Static text is re-translated by I18n itself; everything rendered from data is redrawn here. */
function onLocaleChange() {
  syncLanguageButtons();
  updateClock();
  setConnection(state.online);
  if (state.snapshot) {
    renderAll(state.snapshot);
    renderAlarms(state.snapshot, true);
  }
  drawSpeedChart();
  loadHistory(); // re-binds the localized "trail start" tooltip
}

/* ------------------------------------------------------------------ events */
function bindUI() {
  els.pauseBtn.addEventListener('click', toggleSimulation);
  els.speedGroup.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-speed]');
    if (btn) setSimSpeed(btn.dataset.speed);
  });
  els.langGroup.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-lang]');
    if (btn) I18n.setLocale(btn.dataset.lang);
  });
  I18n.onChange(onLocaleChange);

  els.soundBtn.addEventListener('click', () => setSound(!state.sound));
  els.settingsBtn.addEventListener('click', openSettings);
  els.closeSettings.addEventListener('click', closeSettings);
  els.cancelSettings.addEventListener('click', closeSettings);
  els.saveSettings.addEventListener('click', saveSettings);
  els.settingsModal.addEventListener('click', (ev) => {
    if (ev.target === els.settingsModal) closeSettings(); // click on the backdrop
  });
  [[els.tolInput, els.tolOut], [els.devInput, els.devOut], [els.retInput, els.retOut]].forEach(([input, output]) => {
    input.addEventListener('input', () => { output.textContent = input.value; });
  });

  els.fleetSearch.addEventListener('input', () => {
    state.filter = els.fleetSearch.value.trim();
    if (state.snapshot) renderVehicleList(state.snapshot);
  });

  els.historyRange.addEventListener('change', () => {
    loadHistory();
    loadSeries();
  });

  els.alarmTabs.forEach((btn) => {
    btn.addEventListener('click', () => {
      state.alarmTab = btn.dataset.tab;
      els.alarmTabs.forEach((b) => b.classList.toggle('active', b === btn));
      if (state.snapshot) renderAlarms(state.snapshot, true);
    });
  });

  els.ackAll.addEventListener('click', acknowledgeAll);
  els.triggerSpeed.addEventListener('click', () => triggerScenario('speed'));
  els.triggerDev.addEventListener('click', () => triggerScenario('deviation'));

  els.exportBtn.addEventListener('click', () => {
    const v = selectedVehicle();
    if (!v) return;
    window.location.href = `/api/vehicles/${encodeURIComponent(v.vehicle_id)}/export.csv?minutes=${historyMinutes()}`;
  });

  window.addEventListener('resize', () => drawSpeedChart());
  window.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') closeSettings();
    if (ev.key === ' ' && ev.target === document.body) { // space bar: pause / resume
      ev.preventDefault();
      toggleSimulation();
    }
  });
}

function updateClock() {
  const now = new Date();
  els.clock.textContent = now.toLocaleTimeString(I18n.localeTag(), { hour12: false });
  els.dateLabel.textContent = now.toLocaleDateString(I18n.localeTag(), {
    day: '2-digit', month: 'short', year: 'numeric',
  });
}

/* ------------------------------------------------------------------ start */
async function init() {
  I18n.translateDom();
  syncLanguageButtons();
  updateClock();
  setInterval(updateClock, 1000);
  bindUI();

  try {
    const boot = await api('/api/bootstrap');
    state.routes = boot.routes || {};
    state.vehiclesMeta = boot.vehicles || [];
    state.selectedId = boot.state?.vehicles?.[0]?.vehicle_id || state.vehiclesMeta[0]?.id || null;
  } catch (err) {
    toast(t('toast.connTitle'), t('toast.connBody'), 'critical');
    setTimeout(() => window.location.reload(), 4000);
    return;
  }

  initMap();
  updateSoundButton();
  if (!staticMode) connectStream(); // ?static=1 renders one snapshot (used for screenshots)

  setInterval(loadHistory, HISTORY_REFRESH_MS);
  setInterval(loadSeries, SERIES_REFRESH_MS);

  // Render immediately instead of waiting for the first SSE message
  try {
    const snap = await api('/api/state');
    if (snap && snap.vehicles) {
      applyState(snap, true);
      loadHistory();
      loadSeries();
    }
  } catch (err) {
    console.warn('Could not load the initial state:', err.message);
  }
}

init();
