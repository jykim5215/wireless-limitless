'use strict';
/* Design-preview backend: mimics window.pywebview.api with fake, in-memory
   state so style candidates can be clicked through without earbuds.
   Only inlined into design/*.html by tools/make_previews.py — never shipped. */
(() => {
  const DEFAULT_BANDS = [[30, 0, 0.7, 4], [220, -8, 1, 0], [900, -2, 1.5, 0], [2800, 4, 1, 0], [12000, 3, 0.8, 0], [5300, -3, 2, 0]];
  const PRESETS = [
    { key: 'spatial', label: '공간 음향', bands: DEFAULT_BANDS },
    { key: 'default', label: '기본', bands: DEFAULT_BANDS },
    { key: 'pop', label: '팝', bands: [[30, 0, 0.4, 4], [220, -8, 1, 0], [2800, 3.5, 1, 0], [12000, 3, 0.8, 0], [5300, -3, 2, 0], [60, -3, 0.5, 0]] },
    { key: 'bass', label: '헤비 베이스', bands: [[30, 0, 0.7, 4], [220, -8, 1, 0], [2800, 1, 1, 0], [12000, 8, 0.8, 0], [5300, -5, 2, 0], [60, 5, 0.6, 0]] },
    { key: 'rock', label: '록', bands: [[30, 0, 0.7, 4], [220, -10, 1, 0], [2800, 2, 1, 0], [12000, 3, 0.8, 0], [5300, -1, 2, 0], [60, 3, 0.6, 0]] },
    { key: 'soft', label: '소프트', bands: [[30, 0, 0.4, 4], [220, -8, 1, 0], [2800, 1, 1, 0], [12000, 1, 0.8, 0], [5300, -3, 2, 0], [60, -2, 0.5, 0]] },
    { key: 'classic', label: '클래식', bands: [[30, 0, 0.7, 4], [220, -5, 1, 0], [2800, 1, 1, 0], [12000, 1, 0.8, 0], [5300, -5, 2, 0], [60, 2, 0.6, 0]] },
  ];
  const FREQS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
  const s = {
    status: 'connected', message: null,
    device: { model: 'QCY HT08 MeloBuds Pro Plus', vendorId: 19790, address: '**:**:**:**:A1:B2', firmware: '2.0.7' },
    caps: { vendorId: 19790, model: 'QCY HT08 MeloBuds Pro Plus', eqPresets: PRESETS, eqFreqs: FREQS, eqGainLimit: 8 },
    battery: { left: 95, right: 78, case: null, leftCharging: false, rightCharging: true, caseCharging: false },
    anc: { mode: 'anc', scene: 'adaptive', level: null, vocal: false }, ancPending: false,
    eq: { preset: 'default', gains: null, bands: DEFAULT_BANDS },
    balance: 50,
    toggles: { game: false, sleep: false, ldac: true, multipoint: false },
    wear: { enabled: true, ancOnWear: true }, toneVolume: 8,
    autoOff: { minutes: null }, disconnectOff: { minutes: 5 },
    name: '', touch: { 1: 'none', 2: 'none', 3: 'play_pause', 4: 'play_pause', 5: 'voice_assistant', 6: 'next' },
    finding: false,
  };
  const push = () => setTimeout(() => window.WL.onState(JSON.parse(JSON.stringify(s))), 0);
  const ok = (fn) => async (...a) => { fn(...a); push(); return { ok: true }; };

  window.WL_PREVIEW = {
    get_app_info: async () => ({ version: '1.0.0', checkUpdatesOnStart: false, theme: document.documentElement.dataset.theme }),
    get_state: async () => JSON.parse(JSON.stringify(s)),
    refresh: async () => ({ ok: true }),
    set_anc: ok((p) => {
      s.anc = { mode: p.mode, scene: p.scene || null, level: p.level || null, vocal: !!p.vocal };
      s.ancPending = true;
      setTimeout(() => { s.ancPending = false; push(); }, 1400);
    }),
    set_eq_preset: ok((key) => { s.eq = { preset: key, gains: null, bands: PRESETS.find((p) => p.key === key).bands }; }),
    set_eq_custom: ok((g) => { s.eq = { preset: 'custom', gains: g, bands: FREQS.map((f, i) => [f, g[i], 1, 0]) }; }),
    set_balance: ok((v) => { s.balance = v; }),
    set_toggle: ok((k, v) => { s.toggles[k] = v; }),
    set_wear: ok((e, a) => { s.wear = { enabled: e, ancOnWear: a }; }),
    set_tone_volume: ok((l) => { s.toneVolume = l; }),
    set_auto_off: ok((m) => { s.autoOff = { minutes: m }; }),
    set_disconnect_off: ok((m) => { s.disconnectOff = { minutes: m }; }),
    set_touch: ok((slot, fn) => { s.touch[slot] = fn; }),
    rename: ok((n) => { s.name = n; }),
    find: ok((on) => { s.finding = on; }),
    reconnect: ok(() => {}),
    reset_default: ok(() => {}),
    factory_reset: ok(() => {}),
    check_update: async () => ({ ok: true, available: false }),
    set_auto_update_check: async () => ({ ok: true }),
    apply_update: async () => ({ ok: false, error: '미리보기에서는 업데이트할 수 없어요.' }),
  };
})();
