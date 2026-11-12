/* ==========================================================================
   Internationalization (i18n)

   Usage
     I18n.t('alarms.title')                       -> "Alarm Center"
     I18n.t('fleet.subtitle', { vehicles: 8 })    -> "{vehicles}" is replaced
     I18n.t('alarms.summary.open', { count: 2 })  -> plural form via Intl.PluralRules
     I18n.setLocale('tr')                          -> re-translates the DOM, notifies listeners

   Static markup is translated through data attributes:
     data-i18n="key"               element text
     data-i18n-title="key"         title attribute (tooltip)
     data-i18n-placeholder="key"   placeholder attribute
     data-i18n-aria-label="key"    aria-label attribute

   Adding a language: add an entry to MESSAGES and LOCALE_TAGS; missing keys
   fall back to English.
   ========================================================================== */
'use strict';

const I18n = (() => {
  const STORAGE_KEY = 'filotrack.locale';
  const DEFAULT_LOCALE = 'en';

  /* BCP 47 tags used for number / date formatting and plural rules */
  const LOCALE_TAGS = { en: 'en-GB', tr: 'tr-TR' };

  const MESSAGES = {
    en: {
      'app.title': 'FiloTrack · Live Fleet Monitoring',
      'brand.subtitle': 'Live Fleet Monitoring Center',
      'brand.simChip': 'SIMULATION',

      'lang.title': 'Language',

      'conn.connecting': 'Connecting…',
      'conn.online': 'Live connection',
      'conn.offline': 'Disconnected',

      'sim.pause': 'Pause',
      'sim.resume': 'Resume',
      'sim.pauseTitle': 'Pause the simulation',
      'sim.resumeTitle': 'Resume the simulation',
      'sim.speedTitle': 'Simulation speed',

      'sound.on': 'Alarm sound on',
      'sound.off': 'Alarm sound off',

      'unit.speed': 'km/h',
      'unit.hours': 'hours',

      'kpi.total': 'Active vehicles',
      'kpi.moving': 'Moving',
      'kpi.alarms': 'Open alarms',
      'kpi.avgSpeed': 'Avg. speed · km/h',

      'fleet.title': 'Fleet',
      'fleet.subtitle': '{vehicles} vehicles · {routes} routes · {moving} moving',
      'fleet.live': 'Live',
      'fleet.search': 'Search plate, driver or route…',
      'fleet.emptyTitle': 'No vehicle found',
      'fleet.emptyHint': 'Try changing the search filter.',

      'storage.loading': 'Preparing time series…',
      'storage.info': '{samples} samples today · {size} MB time series',

      'map.title': 'Live map',
      'map.subtitleIdle': 'Istanbul · Route simulation',
      'map.subtitle': 'Istanbul · tracking {count} vehicles live',
      'map.offset': 'Offset: {offset} m',
      'map.trailStart': 'Trail start',

      'legend.normal': 'Normal driving',
      'legend.speed': 'Speeding',
      'legend.deviation': 'Off route',
      'legend.hint': 'Click a marker or a list item to follow a vehicle.',

      'status.moving': 'Moving',
      'status.speed': 'Speeding',
      'status.deviation': 'Off route',
      'status.stopped': 'Stopped',

      'detail.exportTitle': 'Download the selected time range as CSV',
      'detail.speedLimit': 'Speed limit',
      'detail.route': 'Route',
      'detail.progress': 'Progress',
      'detail.progressValue': '{pct}%',
      'detail.offset': 'Route offset',
      'detail.odometer': 'Odometer',

      'chart.title': 'Speed history',
      'chart.range15': 'Last 15 min',
      'chart.range60': 'Last 1 hour',
      'chart.range360': 'Last 6 hours',
      'chart.collecting': 'Collecting speed data…',
      'chart.max': 'max {value} km/h',
      'chart.limit': 'limit {value}',

      'trigger.speed': 'Speeding test',
      'trigger.deviation': 'Off-route test',

      'alarms.title': 'Alarm Center',
      'alarms.ackAll': 'Acknowledge all',
      'alarms.tabOpen': 'Active',
      'alarms.tabAll': 'All',
      'alarms.summary.none': 'No open alarms · system normal',
      'alarms.summary.open': { one: '{count} open alarm', other: '{count} open alarms' },
      'alarms.summary.critical': ' · {count} critical',
      'alarms.emptyOpenTitle': 'All quiet',
      'alarms.emptyOpenHint': 'Speeding or off-route events will appear here.',
      'alarms.emptyAllTitle': 'No recorded alarms',
      'alarms.emptyAllHint': 'Past alarms are listed in this tab.',
      'alarms.acked': 'Acknowledged',
      'alarms.resolved': 'Resolved',
      'alarms.ack': 'Acknowledge',

      'alarmType.SPEED': 'Speeding',
      'alarmType.DEVIATION': 'Off route',
      'alarmMessage.SPEED': 'Speeding: {speed} km/h (limit {limit} km/h, +{over} km/h)',
      'alarmMessage.DEVIATION': 'Off route: {offset} m from the route centerline (threshold {threshold} m)',

      'time.justNow': 'just now',
      'time.secondsAgo': '{n}s ago',
      'time.minutesAgo': '{n} min ago',
      'time.hoursAgo': '{n} h ago',

      'toast.error': 'Error',
      'toast.ackedTitle': 'Alarms acknowledged',
      'toast.ackedBody': { one: '{count} alarm acknowledged.', other: '{count} alarms acknowledged.' },
      'toast.scenarioTitle': '{plate} · test scenario',
      'toast.scenarioBody': '{type} scenario started. The alarm will appear in the alarm center within a few seconds.',
      'toast.settingsTitle': 'Settings updated',
      'toast.settingsBody': 'New alarm thresholds apply to the next measurements.',
      'toast.connTitle': 'Connection error',
      'toast.connBody': 'Could not reach the server. Retrying shortly.',

      'settings.open': 'Alarm settings',
      'settings.title': 'Alarm Settings',
      'settings.subtitle': 'Thresholds apply to new measurements.',
      'settings.close': 'Close',
      'settings.tolerance': 'Speed tolerance',
      'settings.toleranceHelp': 'Speeds this far above the limit count as a violation.',
      'settings.deviation': 'Off-route threshold',
      'settings.deviationHelp': 'Moving further than this from the route centerline raises an alarm.',
      'settings.retention': 'Data retention',
      'settings.retentionHelp': 'Time-series records older than this are deleted automatically.',
      'settings.note': 'Alarms are confirmed over consecutive measurements; single-sample GPS noise does not raise an alarm.',
      'settings.cancel': 'Cancel',
      'settings.save': 'Save',

      'kind.delivery': 'Delivery',
      'kind.logistics': 'Logistics',
      'kind.field_service': 'Field service',
      'kind.heavy_haul': 'Heavy haulage',
      'kind.staff_shuttle': 'Staff shuttle',
      'kind.courier': 'Courier',
      'kind.cold_chain': 'Cold chain',
      'kind.management': 'Management',
      /* Route names / areas come from the server in English (backend/routes.py) */
    },

    tr: {
      'app.title': 'FiloTrack · Canlı Filo İzleme',
      'brand.subtitle': 'Canlı Filo İzleme Merkezi',
      'brand.simChip': 'SİMÜLASYON',

      'lang.title': 'Dil',

      'conn.connecting': 'Bağlanıyor…',
      'conn.online': 'Canlı bağlantı',
      'conn.offline': 'Bağlantı yok',

      'sim.pause': 'Duraklat',
      'sim.resume': 'Devam',
      'sim.pauseTitle': 'Simülasyonu duraklat',
      'sim.resumeTitle': 'Simülasyonu sürdür',
      'sim.speedTitle': 'Simülasyon hızı',

      'sound.on': 'Alarm sesi açık',
      'sound.off': 'Alarm sesi kapalı',

      'unit.speed': 'km/sa',
      'unit.hours': 'saat',

      'kpi.total': 'Aktif araç',
      'kpi.moving': 'Hareketli',
      'kpi.alarms': 'Açık alarm',
      'kpi.avgSpeed': 'Ort. hız · km/sa',

      'fleet.title': 'Filo',
      'fleet.subtitle': '{vehicles} araç · {routes} güzergâh · {moving} hareketli',
      'fleet.live': 'Canlı',
      'fleet.search': 'Plaka, sürücü veya rota ara…',
      'fleet.emptyTitle': 'Araç bulunamadı',
      'fleet.emptyHint': 'Arama filtresini değiştirmeyi deneyin.',

      'storage.loading': 'Zaman serisi hazırlanıyor…',
      'storage.info': 'Bugün {samples} ölçüm · {size} MB zaman serisi',

      'map.title': 'Canlı harita',
      'map.subtitleIdle': 'İstanbul · Güzergâh simülasyonu',
      'map.subtitle': 'İstanbul · {count} araç canlı izleniyor',
      'map.offset': 'Sapma: {offset} m',
      'map.trailStart': 'İz başlangıcı',

      'legend.normal': 'Normal seyir',
      'legend.speed': 'Hız ihlali',
      'legend.deviation': 'Rota dışı',
      'legend.hint': 'İşaretçiye veya listeye tıklayarak aracı takip edin.',

      'status.moving': 'Hareketli',
      'status.speed': 'Hız ihlali',
      'status.deviation': 'Rota dışı',
      'status.stopped': 'Duruyor',

      'detail.exportTitle': 'Seçili zaman aralığının konum verisini CSV olarak indir',
      'detail.speedLimit': 'Hız limiti',
      'detail.route': 'Güzergâh',
      'detail.progress': 'İlerleme',
      'detail.progressValue': '%{pct}',
      'detail.offset': 'Merkez sapma',
      'detail.odometer': 'Kilometre',

      'chart.title': 'Hız geçmişi',
      'chart.range15': 'Son 15 dk',
      'chart.range60': 'Son 1 saat',
      'chart.range360': 'Son 6 saat',
      'chart.collecting': 'Hız verisi toplanıyor…',
      'chart.max': 'maks {value} km/sa',
      'chart.limit': 'limit {value}',

      'trigger.speed': 'Hız ihlali testi',
      'trigger.deviation': 'Rota dışı testi',

      'alarms.title': 'Alarm Merkezi',
      'alarms.ackAll': 'Tümünü onayla',
      'alarms.tabOpen': 'Aktif',
      'alarms.tabAll': 'Tümü',
      'alarms.summary.none': 'Açık alarm yok · sistem normal',
      'alarms.summary.open': '{count} açık alarm',
      'alarms.summary.critical': ' · {count} kritik',
      'alarms.emptyOpenTitle': 'Sistem sakin',
      'alarms.emptyOpenHint': 'Hız veya rota ihlali algılandığında burada görünür.',
      'alarms.emptyAllTitle': 'Kayıtlı alarm yok',
      'alarms.emptyAllHint': 'Geçmiş alarmlar bu sekmede listelenir.',
      'alarms.acked': 'Onaylandı',
      'alarms.resolved': 'Çözüldü',
      'alarms.ack': 'Onayla',

      'alarmType.SPEED': 'Hız ihlali',
      'alarmType.DEVIATION': 'Rota dışı',
      'alarmMessage.SPEED': 'Hız ihlali: {speed} km/sa (limit {limit} km/sa, +{over} km/sa)',
      'alarmMessage.DEVIATION': 'Rota dışına çıkış: merkez hattan {offset} m sapma (eşik {threshold} m)',

      'time.justNow': 'şimdi',
      'time.secondsAgo': '{n} sn önce',
      'time.minutesAgo': '{n} dk önce',
      'time.hoursAgo': '{n} sa önce',

      'toast.error': 'Hata',
      'toast.ackedTitle': 'Alarmlar onaylandı',
      'toast.ackedBody': '{count} alarm onaylandı.',
      'toast.scenarioTitle': '{plate} · test senaryosu',
      'toast.scenarioBody': '{type} senaryosu başlatıldı. Alarm birkaç saniye içinde alarm merkezinde görünecek.',
      'toast.settingsTitle': 'Ayarlar güncellendi',
      'toast.settingsBody': 'Alarm eşikleri yeni ölçümlerde geçerli olacak.',
      'toast.connTitle': 'Bağlantı hatası',
      'toast.connBody': 'Sunucuya ulaşılamadı. Kısa süre içinde yeniden denenecek.',

      'settings.open': 'Alarm ayarları',
      'settings.title': 'Alarm Ayarları',
      'settings.subtitle': 'Eşikler yeni ölçümlerde devreye girer.',
      'settings.close': 'Kapat',
      'settings.tolerance': 'Hız toleransı',
      'settings.toleranceHelp': 'Limitin bu kadar üzerindeki hızlar ihlal sayılır.',
      'settings.deviation': 'Rota sapma eşiği',
      'settings.deviationHelp': 'Merkez hattan bu mesafeden fazla uzaklaşma alarm üretir.',
      'settings.retention': 'Veri saklama',
      'settings.retentionHelp': 'Zaman serisi kayıtları bu süreden sonra otomatik silinir.',
      'settings.note': 'Alarmlar ardışık ölçümlerle doğrulanır; tek ölçümlük GPS gürültüsü alarm üretmez.',
      'settings.cancel': 'Vazgeç',
      'settings.save': 'Kaydet',

      'kind.delivery': 'Dağıtım',
      'kind.logistics': 'Lojistik',
      'kind.field_service': 'Saha ekibi',
      'kind.heavy_haul': 'Ağır nakliye',
      'kind.staff_shuttle': 'Personel servisi',
      'kind.courier': 'Kurye',
      'kind.cold_chain': 'Soğuk zincir',
      'kind.management': 'Yönetim',

      'route.bagdat.name': 'Bağdat Caddesi',
      'route.tem.name': 'TEM Otoyolu',
      'route.sahil.name': 'Sahil Yolu',
      'route.tarihi.name': 'Tarihi Yarımada',
      'route.kadikoy.area': 'Kadıköy şehir içi',
      'route.kuzey.name': 'Büyükdere Caddesi',
      'route.bogaz.name': 'Boğaziçi Geçişi',
      'route.bogaz.area': 'Beşiktaş → 15 Temmuz Şehitler Köprüsü',
    },
  };

  const SUPPORTED = Object.keys(MESSAGES);
  const listeners = [];
  let locale = detectLocale();
  let pluralRules = new Intl.PluralRules(LOCALE_TAGS[locale]);

  /* Saved choice → browser language → English.
     localStorage can throw (private mode, blocked storage), so every access is guarded. */
  function detectLocale() {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (SUPPORTED.includes(saved)) return saved;
    } catch (err) { /* storage unavailable */ }
    const preferred = (navigator.languages || [navigator.language || ''])
      .map((tag) => String(tag).slice(0, 2).toLowerCase())
      .find((code) => SUPPORTED.includes(code));
    return preferred || DEFAULT_LOCALE;
  }

  function lookup(key) {
    const own = MESSAGES[locale][key];
    return own != null ? own : MESSAGES[DEFAULT_LOCALE][key];
  }

  /** Translated text for `key`, with `{name}` placeholders replaced from `params`. */
  function t(key, params = {}) {
    let message = lookup(key);
    if (message == null) return key;
    if (typeof message === 'object') {
      message = message[pluralRules.select(Number(params.count) || 0)] || message.other;
    }
    return message.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
  }

  /** True when the *current* locale defines `key` (no English fallback). */
  function has(key) {
    return MESSAGES[locale][key] != null;
  }

  function translateDom(root = document) {
    root.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll('[data-i18n-title]').forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    root.querySelectorAll('[data-i18n-placeholder]').forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    root.querySelectorAll('[data-i18n-aria-label]').forEach((el) => {
      el.setAttribute('aria-label', t(el.dataset.i18nAriaLabel));
    });
    document.documentElement.lang = locale;
  }

  function setLocale(next) {
    if (!SUPPORTED.includes(next) || next === locale) return;
    locale = next;
    pluralRules = new Intl.PluralRules(LOCALE_TAGS[locale]);
    try { window.localStorage.setItem(STORAGE_KEY, locale); } catch (err) { /* not persisted */ }
    translateDom();
    listeners.forEach((callback) => callback(locale));
  }

  return {
    SUPPORTED,
    t,
    has,
    setLocale,
    translateDom,
    getLocale: () => locale,
    /** BCP 47 tag for Intl / toLocale*String APIs */
    localeTag: () => LOCALE_TAGS[locale],
    formatNumber: (value) => new Intl.NumberFormat(LOCALE_TAGS[locale]).format(value),
    onChange: (callback) => listeners.push(callback),
  };
})();
