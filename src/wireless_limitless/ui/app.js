'use strict';
/* Wireless Limitless UI. Renders the backend state (pushed by Python through
   window.WL.onState) and calls window.pywebview.api.* for every change.
   Device-provided strings are always inserted with textContent. */
(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const STATUS = {
    idle: ['준비 중', ''],
    searching: ['이어버드 찾는 중', ''],
    connecting: ['연결 중', ''],
    syncing: ['설정 불러오는 중', ''],
    connected: ['연결됨', ''],
    offline: ['연결 안 됨', ''],
    unsupported: ['지원되지 않는 모델', ''],
    bt_off: ['블루투스 꺼짐', ''],
  };
  const SCENES = [
    ['adaptive', '적응형', '소음에 맞춰 자동 조절'],
    ['indoor', '실내', '사무실·카페'],
    ['commute', '출퇴근', '버스·지하철'],
    ['noisy', '시끄러운 곳', '비행기·공사장'],
    ['wind', '바람 소음', '야외 바람 소리 줄이기'],
  ];
  const LEVELED = new Set(['indoor', 'commute', 'noisy']);
  const TOUCH_FUNCS = [
    ['none', '없음'], ['play_pause', '재생 / 일시정지'], ['previous', '이전 곡'], ['next', '다음 곡'],
    ['voice_assistant', '음성 비서'], ['volume_up', '볼륨 크게'], ['volume_down', '볼륨 작게'],
    ['game_mode', '게임 모드 켜기/끄기'], ['anc', '소음 제어 전환'],
  ];
  const TONE_LEVELS = [[4, '낮음'], [6, '보통'], [8, '높음'], [10, '최대']];
  const FREQ_LABEL = (f) => (f >= 1000 ? `${f / 1000}k` : `${f}`);

  let S = null;          // latest backend state
  let api = null;        // pywebview api (or the preview mock)
  let caps = null;       // model capabilities currently rendered
  const memo = { anc: { scene: 'adaptive', level: 2 }, trans: { vocal: false, level: 4 }, gains: new Array(10).fill(0) };
  const drag = { eq: false, balance: false, ambient: false };
  let appInfo = null;
  let pendingUpdate = null;

  // ------------------------------------------------------------ plumbing
  async function call(method, ...args) {
    if (!api || typeof api[method] !== 'function') {
      toast('앱이 아직 준비되지 않았어요.', 'error');
      return { ok: false };
    }
    try {
      const res = (await api[method](...args)) || { ok: true };
      if (res.ok === false && res.error) toast(res.error, 'error');
      return res;
    } catch (err) {
      toast('요청을 처리하지 못했어요.', 'error');
      return { ok: false };
    }
  }

  function toast(text, kind = 'ok') {
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.innerHTML = `<svg><use href="#i-${kind === 'error' ? 'warn' : 'check'}"/></svg><span></span>`;
    el.querySelector('span').textContent = text;
    $('#toasts').append(el);
    setTimeout(() => el.remove(), kind === 'error' ? 6000 : 3200);
  }

  function debounce(fn, ms) {
    let t = 0;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }

  // -------------------------------------------------------- static build
  function buildStatic() {
    const scenes = $('#ancScenes');
    for (const [key, label, tip] of SCENES) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'chip'; b.dataset.scene = key; b.setAttribute('role', 'radio');
      b.textContent = label;
      b.title = tip;
      scenes.append(b);
    }
    for (const sel of $$('#touchGrid select')) {
      for (const [key, label] of TOUCH_FUNCS) sel.add(new Option(label, key));
    }
    const tone = $('#toneSeg');
    for (const [level, label] of TONE_LEVELS) {
      const b = document.createElement('button');
      b.type = 'button'; b.dataset.level = level; b.setAttribute('role', 'radio'); b.textContent = label;
      tone.append(b);
    }
  }

  function buildForCaps(c) {
    caps = c;
    const presets = $('#eqPresets');
    presets.replaceChildren();
    for (const p of [...c.eqPresets, { key: 'custom', label: '사용자 지정' }]) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'chip'; b.dataset.preset = p.key; b.setAttribute('role', 'radio');
      b.textContent = p.label;
      presets.append(b);
    }
    const bands = $('#eqBands');
    bands.replaceChildren();
    c.eqFreqs.forEach((f, i) => {
      const band = document.createElement('div');
      band.className = 'eq-band';
      band.innerHTML = `<output>0</output><input type="range" class="range" min="-${c.eqGainLimit}" max="${c.eqGainLimit}" step="1" value="0"><label></label>`;
      band.querySelector('label').textContent = FREQ_LABEL(f);
      const input = band.querySelector('input');
      input.dataset.band = i;
      input.setAttribute('aria-label', `${FREQ_LABEL(f)}Hz`);
      bands.append(band);
    });
    buildGrid();
  }

  // --------------------------------------------------------------- render
  function render() {
    if (!S) return;
    if (S.caps && (!caps || caps.vendorId !== S.caps.vendorId)) buildForCaps(S.caps);
    const live = S.status === 'connected';
    $('#app').classList.toggle('offline', !live);
    renderDevice(live);
    renderBanner(live);
    renderAnc();
    renderEq();
    renderBalance();
    setCheck('#gameToggle', S.toggles.game);
    renderTouch();
    renderSettings();
  }

  function setCheck(sel, value) {
    const el = $(sel);
    if (value !== null && value !== undefined) el.checked = !!value;
  }

  function renderDevice() {
    const name = (S.name && S.name.trim()) || (S.device && S.device.model) || '이어버드';
    $('#deviceName').textContent = name;
    const firmware = S.device && S.device.firmware ? `펌웨어 ${S.device.firmware}` : '\u00a0';
    $('#deviceModel').textContent = S.name && S.device ? S.device.model : firmware;
    const st = $('#deviceStatus');
    st.className = `device-status s-${S.status}`;
    $('#statusText').textContent = STATUS[S.status] ? STATUS[S.status][0] : S.status;
    const b = S.battery || {};
    for (const side of ['left', 'right', 'case']) {
      const row = $(`.battery[data-side="${side}"]`);
      const level = b[side];
      if (side === 'case') row.hidden = level == null;
      row.style.setProperty('--pct', `${level || 0}%`);
      row.querySelector('.bat-bar i').style.width = `${level || 0}%`;
      row.querySelector('.bat-val').textContent = level == null ? '--' : `${level}%`;
      row.classList.toggle('low', level != null && level <= 20);
      row.classList.toggle('charging', !!b[`${side}Charging`]);
    }
    $('#findModal').classList.toggle('finding', !!S.finding);
    $('#findToggle').textContent = S.finding ? '소리 멈추기' : '소리 울리기';
  }

  function renderBanner(live) {
    const banner = $('#statusBanner');
    if (live) { banner.hidden = true; return; }
    const [title, fallback] = STATUS[S.status] || [S.status, ''];
    const working = ['searching', 'connecting', 'syncing', 'idle'].includes(S.status);
    banner.hidden = false;
    banner.classList.toggle('error', !working);
    $('#bannerTitle').textContent = title;
    $('#bannerMsg').textContent = S.message || fallback;
  }

  function renderAnc() {
    const anc = S.anc;
    $('#ancPending').hidden = !S.ancPending;
    for (const tile of $$('#ancModes .mode-tile')) {
      const on = !!anc && tile.dataset.mode === anc.mode;
      tile.classList.toggle('active', on);
      tile.setAttribute('aria-checked', on);
    }
    for (const d of $$('.anc-detail')) d.classList.toggle('active', !!anc && d.dataset.for === anc.mode);
    if (!anc) return;
    if (anc.mode === 'anc') {
      memo.anc.scene = anc.scene;
      if (anc.level) memo.anc.level = anc.level;
    } else if (anc.mode === 'transparency') {
      memo.trans.vocal = anc.vocal;
      if (anc.level) memo.trans.level = anc.level;
    }
    const scene = anc.mode === 'anc' ? anc.scene : memo.anc.scene;
    for (const chip of $$('#ancScenes .chip')) {
      chip.classList.toggle('active', chip.dataset.scene === scene);
      chip.setAttribute('aria-checked', chip.dataset.scene === scene);
    }
    $('#ancLevelRow').hidden = !LEVELED.has(scene);
    const level = anc.mode === 'anc' ? anc.level : memo.anc.level;
    for (const b of $$('#ancLevels button')) b.classList.toggle('active', Number(b.dataset.level) === level);

    const vocal = anc.mode === 'transparency' ? anc.vocal : memo.trans.vocal;
    $('#vocalToggle').checked = !!vocal;
    $('#ambientBlock').classList.toggle('disabled', !!vocal);
    const range = $('#ambientRange');
    range.disabled = !!vocal;
    if (!drag.ambient) {
      range.value = memo.trans.level;
      paintRange(range);
      $('#ambientOut').textContent = memo.trans.level;
    }
  }

  function renderEq() {
    const eq = S.eq;
    const active = eq ? eq.preset : null;
    for (const chip of $$('#eqPresets .chip')) {
      chip.classList.toggle('active', chip.dataset.preset === active);
      chip.setAttribute('aria-checked', chip.dataset.preset === active);
    }
    const custom = active === 'custom';
    $('#eqEditor').hidden = !custom;
    if (custom && eq.gains && !drag.eq) {
      memo.gains = eq.gains.slice();
      setBandInputs(memo.gains);
    }
    drawCurve(eq ? (custom && drag.eq ? bandsFromGains(memo.gains) : eq.bands) : []);
  }

  function setBandInputs(gains) {
    $$('#eqBands .range').forEach((input, i) => {
      input.value = gains[i];
      paintVertical(input);
      input.closest('.eq-band').querySelector('output').textContent = fmtDb(gains[i]);
    });
  }

  const fmtDb = (g) => (g > 0 ? `+${g}` : `${g}`);
  const bandsFromGains = (gains) => (caps ? caps.eqFreqs.map((f, i) => [f, gains[i], 1.0, 0]) : []);

  function renderBalance() {
    if (S.balance == null || drag.balance) return;
    const r = $('#balanceRange');
    r.value = S.balance;
    paintCenter(r);
    $('#balanceOut').textContent = balanceLabel(S.balance);
  }

  const balanceLabel = (v) => (v === 50 ? '가운데' : v < 50 ? `왼쪽 +${50 - v}` : `오른쪽 +${v - 50}`);

  function renderTouch() {
    if (!S.touch) return;
    for (const sel of $$('#touchGrid select')) {
      const value = S.touch[sel.dataset.slot];
      if (value == null) continue;
      if (![...sel.options].some((o) => o.value === value)) sel.add(new Option(`알 수 없음 (${value})`, value));
      if (document.activeElement !== sel) sel.value = value;
    }
  }

  function renderSettings() {
    const wear = S.wear;
    if (wear) {
      $('#wearToggle').checked = wear.enabled;
      $('#ancOnWearToggle').checked = wear.ancOnWear;
      $('#ancOnWearRow').hidden = !wear.enabled;
    }
    setCheck('#sleepToggle', S.toggles.sleep);
    setCheck('#ldacToggle', S.toggles.ldac);
    setCheck('#multiToggle', S.toggles.multipoint);
    for (const b of $$('#toneSeg button')) b.classList.toggle('active', Number(b.dataset.level) === S.toneVolume);

    const autoSel = $('#autoOffSel');
    if (S.autoOff && document.activeElement !== autoSel) {
      const m = S.autoOff.minutes;
      const preset = m == null ? 'off' : String(m);
      const known = [...autoSel.options].some((o) => o.value === preset);
      autoSel.value = known ? preset : 'custom';
      $('#autoOffCustomRow').hidden = known;
      if (!known && document.activeElement !== $('#autoOffCustom')) $('#autoOffCustom').value = m;
    }
    const discSel = $('#discOffSel');
    if (S.disconnectOff && document.activeElement !== discSel) {
      const m = S.disconnectOff.minutes;
      discSel.value = m == null ? 'off' : String(m);
    }
    const nameInput = $('#nameInput');
    if (document.activeElement !== nameInput && S.name != null) nameInput.value = S.name;
    nameInput.placeholder = S.device ? S.device.model : '';
    $('#factModel').textContent = S.device ? S.device.model : '-';
    $('#factFirmware').textContent = S.device && S.device.firmware ? S.device.firmware : '-';
    $('#factAddress').textContent = S.device ? S.device.address : '-';
  }

  // ------------------------------------------------------ range painting
  function pct(input) {
    const min = Number(input.min), max = Number(input.max);
    return ((Number(input.value) - min) / (max - min)) * 100;
  }
  function paintRange(input) { input.style.setProperty('--fill', `${pct(input)}%`); }
  function paintCenter(input) {
    const p = pct(input);
    input.style.setProperty('--lo', `${Math.min(p, 50)}%`);
    input.style.setProperty('--hi', `${Math.max(p, 50)}%`);
  }
  const paintVertical = paintCenter;

  // --------------------------------------------------------- EQ curve SVG
  const FS = 48000, W = 600, H = 160, DB_RANGE = 12;

  function biquadDb(f, [f0, gain, q, kind]) {
    const w0 = (2 * Math.PI * f0) / FS;
    const alpha = Math.sin(w0) / (2 * Math.max(q, 0.1));
    const cos = Math.cos(w0);
    let b0, b1, b2, a0, a1, a2;
    if (kind === 4) {
      b0 = (1 + cos) / 2; b1 = -(1 + cos); b2 = (1 + cos) / 2; a0 = 1 + alpha; a1 = -2 * cos; a2 = 1 - alpha;
    } else {
      if (!gain) return 0;
      const A = Math.pow(10, gain / 40);
      b0 = 1 + alpha * A; b1 = -2 * cos; b2 = 1 - alpha * A; a0 = 1 + alpha / A; a1 = -2 * cos; a2 = 1 - alpha / A;
    }
    const w = (2 * Math.PI * f) / FS;
    const c1 = Math.cos(w), s1 = Math.sin(w), c2 = Math.cos(2 * w), s2 = Math.sin(2 * w);
    const nr = b0 + b1 * c1 + b2 * c2, ni = -(b1 * s1 + b2 * s2);
    const dr = a0 + a1 * c1 + a2 * c2, di = -(a1 * s1 + a2 * s2);
    return 10 * Math.log10((nr * nr + ni * ni) / (dr * dr + di * di));
  }
  const xOf = (f) => (Math.log10(f / 20) / Math.log10(1000)) * W;
  const yOf = (db) => H / 2 - (Math.max(-DB_RANGE, Math.min(DB_RANGE, db)) / DB_RANGE) * (H / 2 - 12);

  function buildGrid() {
    const g = $('#eqCurve .eq-grid');
    const lines = [];
    for (const f of [50, 100, 200, 500, 1000, 2000, 5000, 10000]) lines.push(`<line x1="${xOf(f)}" x2="${xOf(f)}" y1="0" y2="${H}"/>`);
    for (const db of [-6, 6]) lines.push(`<line x1="0" x2="${W}" y1="${yOf(db)}" y2="${yOf(db)}"/>`);
    lines.push(`<line class="zero" x1="0" x2="${W}" y1="${yOf(0)}" y2="${yOf(0)}"/>`);
    g.innerHTML = lines.join('');
  }

  function drawCurve(bands) {
    const pts = [];
    for (let i = 0; i <= 140; i++) {
      const f = 20 * Math.pow(1000, i / 140);
      const db = bands.reduce((sum, b) => sum + biquadDb(f, b), 0);
      pts.push(`${xOf(f).toFixed(1)},${yOf(db).toFixed(1)}`);
    }
    const line = `M${pts.join(' L')}`;
    $('#eqCurve .eq-line').setAttribute('d', line);
    $('#eqCurve .eq-fill').setAttribute('d', `${line} L${W},${H} L0,${H} Z`);
  }

  // --------------------------------------------------------------- events
  function ancPayload(mode) {
    if (mode === 'anc') return { mode, scene: memo.anc.scene, level: LEVELED.has(memo.anc.scene) ? memo.anc.level : null };
    if (mode === 'transparency') return { mode, vocal: memo.trans.vocal, level: memo.trans.vocal ? null : memo.trans.level };
    return { mode: 'normal' };
  }

  function bind() {
    for (const item of $$('.nav-item')) item.addEventListener('click', () => showPage(item.dataset.page));

    $('#ancModes').addEventListener('click', (e) => {
      const tile = e.target.closest('.mode-tile');
      if (tile) call('set_anc', ancPayload(tile.dataset.mode));
    });
    $('#ancScenes').addEventListener('click', (e) => {
      const chip = e.target.closest('.chip');
      if (!chip) return;
      memo.anc.scene = chip.dataset.scene;
      call('set_anc', ancPayload('anc'));
    });
    $('#ancLevels').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      memo.anc.level = Number(b.dataset.level);
      call('set_anc', ancPayload('anc'));
    });
    $('#vocalToggle').addEventListener('change', (e) => {
      memo.trans.vocal = e.target.checked;
      call('set_anc', ancPayload('transparency'));
    });
    const ambient = $('#ambientRange');
    ambient.addEventListener('input', () => { drag.ambient = true; paintRange(ambient); $('#ambientOut').textContent = ambient.value; });
    ambient.addEventListener('change', () => {
      drag.ambient = false;
      memo.trans.level = Number(ambient.value);
      memo.trans.vocal = false;
      call('set_anc', ancPayload('transparency'));
    });

    $('#eqPresets').addEventListener('click', (e) => {
      const chip = e.target.closest('.chip');
      if (!chip) return;
      if (chip.dataset.preset === 'custom') call('set_eq_custom', memo.gains.slice());
      else call('set_eq_preset', chip.dataset.preset);
    });
    const sendGains = debounce(() => { call('set_eq_custom', memo.gains.slice()); drag.eq = false; }, 220);
    $('#eqBands').addEventListener('input', (e) => {
      const input = e.target.closest('.range');
      if (!input) return;
      drag.eq = true;
      memo.gains[Number(input.dataset.band)] = Number(input.value);
      paintVertical(input);
      input.closest('.eq-band').querySelector('output').textContent = fmtDb(Number(input.value));
      drawCurve(bandsFromGains(memo.gains));
      sendGains();
    });
    $('#eqFlat').addEventListener('click', () => {
      memo.gains = new Array(10).fill(0);
      setBandInputs(memo.gains);
      call('set_eq_custom', memo.gains.slice());
    });

    const bal = $('#balanceRange');
    const sendBalance = debounce(() => { call('set_balance', Number(bal.value)); drag.balance = false; }, 180);
    bal.addEventListener('input', () => {
      drag.balance = true;
      if (Math.abs(Number(bal.value) - 50) <= 2) bal.value = 50;  // gentle snap to centre
      paintCenter(bal);
      $('#balanceOut').textContent = balanceLabel(Number(bal.value));
      sendBalance();
    });
    bal.addEventListener('dblclick', () => { bal.value = 50; bal.dispatchEvent(new Event('input')); });

    $('#gameToggle').addEventListener('change', (e) => call('set_toggle', 'game', e.target.checked));
    $('#sleepToggle').addEventListener('change', (e) => call('set_toggle', 'sleep', e.target.checked));
    for (const [id, key, label] of [['#ldacToggle', 'ldac', 'LDAC 고음질'], ['#multiToggle', 'multipoint', '듀얼 기기 연결']]) {
      $(id).addEventListener('change', async (e) => {
        const want = e.target.checked;
        e.target.checked = !want;  // keep the device state until confirmed
        const ok = await confirmBox({
          title: `${label} ${want ? '켜기' : '끄기'}`,
          text: '이어버드가 잠깐 다시 시작될 수 있어요.',
          okText: want ? '켜기' : '끄기',
        });
        if (ok) call('set_toggle', key, want);
      });
    }
    const sendWear = () => call('set_wear', $('#wearToggle').checked, $('#ancOnWearToggle').checked);
    $('#wearToggle').addEventListener('change', sendWear);
    $('#ancOnWearToggle').addEventListener('change', sendWear);
    $('#toneSeg').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (b) call('set_tone_volume', Number(b.dataset.level));
    });
    $('#autoOffSel').addEventListener('change', (e) => {
      const v = e.target.value;
      $('#autoOffCustomRow').hidden = v !== 'custom';
      if (v === 'custom') { $('#autoOffCustom').focus(); return; }
      call('set_auto_off', v === 'off' ? null : Number(v));
    });
    $('#autoOffApply').addEventListener('click', () => {
      const m = Math.round(Number($('#autoOffCustom').value));
      if (!(m >= 1 && m <= 1440)) { toast('1~1440분 사이로 입력해 주세요.', 'error'); return; }
      call('set_auto_off', m);
    });
    $('#discOffSel').addEventListener('change', (e) => {
      const v = e.target.value;
      call('set_disconnect_off', v === 'off' ? null : Number(v));
    });
    $('#touchGrid').addEventListener('change', (e) => {
      const sel = e.target.closest('select');
      if (sel) call('set_touch', Number(sel.dataset.slot), sel.value);
    });

    $('#nameSave').addEventListener('click', async () => {
      const name = $('#nameInput').value.trim();
      if (!name) { toast('이름을 입력해 주세요.', 'error'); return; }
      if (new TextEncoder().encode(name).length > 31) { toast('이름이 너무 길어요. (한글 10자까지)', 'error'); return; }
      const res = await call('rename', name);
      if (res.ok) toast('이름을 바꿨어요. 다시 연결하면 반영돼요.');
    });
    $('#nameInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#nameSave').click(); });

    $('#btnReconnect').addEventListener('click', () => call('reconnect'));
    $('#btnFind').addEventListener('click', () => openModal('#findModal'));
    $('#findToggle').addEventListener('click', () => call('find', !(S && S.finding)));

    $('#btnResetDefault').addEventListener('click', async () => {
      const ok = await confirmBox({
        title: '기본값 복원',
        text: '이어버드 설정을 출고 상태로 되돌려요. 페어링은 유지돼요.',
        okText: '복원',
      });
      if (ok && (await call('reset_default')).ok) toast('기본값으로 복원했어요.');
    });
    $('#btnFactoryReset').addEventListener('click', async () => {
      const ok = await confirmBox({
        title: '공장 초기화',
        text: '모든 설정과 페어링 기록이 지워져요. 모든 기기에서 다시 페어링해야 해요.',
        ack: '페어링이 모두 지워지는 것을 이해했어요.',
        okText: '공장 초기화',
        danger: true,
      });
      if (ok) call('factory_reset');
    });

    $('#btnCheckUpdate').addEventListener('click', () => checkUpdate(true));
    $('#autoUpdateToggle').addEventListener('change', (e) => call('set_auto_update_check', e.target.checked));
    $('#btnUpdateBanner').addEventListener('click', () => openUpdateModal());
    $('#btnUpdateDismiss').addEventListener('click', () => { $('#updateBanner').hidden = true; });
    $('#updateApply').addEventListener('click', applyUpdate);

    for (const modal of $$('.modal')) {
      modal.addEventListener('click', (e) => { if (e.target === modal || e.target.closest('[data-close]')) closeModal(modal); });
    }
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') $$('.modal').filter((m) => !m.hidden).forEach(closeModal);
    });
    window.addEventListener('focus', () => { if (S && S.status === 'connected' && api && api.refresh) api.refresh(); });
  }

  function showPage(page) {
    for (const item of $$('.nav-item')) item.classList.toggle('active', item.dataset.page === page);
    for (const p of $$('.page')) p.classList.toggle('active', p.id === `page-${page}`);
    $('#main').scrollTop = 0;
  }

  // --------------------------------------------------------------- modals
  function openModal(sel) { $(sel).hidden = false; }
  function closeModal(modal) {
    modal.hidden = true;
    if (modal.id === 'findModal' && S && S.finding) call('find', false);
    if (modal._resolve) { modal._resolve(false); modal._resolve = null; }
  }

  function confirmBox({ title, text, okText = '확인', ack = null, danger = false }) {
    const modal = $('#confirmModal');
    $('#confirmTitle').textContent = title;
    $('#confirmText').textContent = text;
    const ok = $('#confirmOk');
    ok.textContent = okText;
    ok.className = `btn ${danger ? 'danger' : 'primary'}`;
    $('#confirmAckRow').hidden = !ack;
    $('#confirmAck').checked = false;
    ok.disabled = !!ack;
    if (ack) $('#confirmAckText').textContent = ack;
    $('#confirmAck').onchange = (e) => { ok.disabled = !e.target.checked; };
    modal.hidden = false;
    return new Promise((resolve) => {
      modal._resolve = resolve;
      ok.onclick = () => { modal._resolve = null; modal.hidden = true; resolve(true); };
    });
  }

  // -------------------------------------------------------------- updates
  async function checkUpdate(manual) {
    const status = $('#updateStatus');
    if (manual) status.textContent = '확인하는 중…';
    const res = await call('check_update');
    if (!res || res.ok === false) {
      status.textContent = '확인하지 못했어요';
      return;
    }
    if (!res.available) {
      status.textContent = '최신 버전이에요';
      if (manual) toast('이미 최신 버전이에요.');
      return;
    }
    pendingUpdate = res;
    status.textContent = `새 버전 ${res.version}`;
    $('#navUpdateBadge').hidden = false;
    $('#updateBannerTitle').textContent = `새 버전 ${res.version}이 있어요`;
    $('#updateBanner').hidden = false;
    if (manual) openUpdateModal();
  }

  function openUpdateModal() {
    if (!pendingUpdate) return;
    $('#updateTitle').textContent = `v${pendingUpdate.version} 업데이트`;
    $('#updateLead').textContent = pendingUpdate.canApply
      ? '앱이 잠시 닫혔다가 새 버전으로 다시 열려요.'
      : '소스로 실행 중이라 자동 교체는 할 수 없어요.';
    $('#updateChangelog').textContent = pendingUpdate.changelog || '(변경 사항 없음)';
    $('#updateApply').hidden = !pendingUpdate.canApply;
    $('#updateProgress').hidden = true;
    openModal('#updateModal');
  }

  async function applyUpdate() {
    const btn = $('#updateApply');
    btn.disabled = true;
    btn.textContent = '내려받는 중…';
    $('#updateProgress').hidden = false;
    const res = await call('apply_update');
    if (!res.ok) { btn.disabled = false; btn.textContent = '다시 시도'; }
    else btn.textContent = '다시 시작하는 중…';
  }

  // ---------------------------------------------------------------- start
  window.WL = {
    onState(state) { S = state; render(); },
    onUpdateProgress(p) { $('#updateProgress i').style.setProperty('--pct', `${Math.round(p * 100)}%`); $('#updateProgress i').style.width = `${Math.round(p * 100)}%`; },
  };

  async function attach(backend) {
    if (api || !backend || typeof backend.get_state !== 'function') return;
    api = backend;
    appInfo = await call('get_app_info');
    if (appInfo && appInfo.version) {
      $('#appVersion').textContent = `v${appInfo.version}`;
      $('#appVersionFoot').textContent = `v${appInfo.version}`;
      $('#autoUpdateToggle').checked = !!appInfo.checkUpdatesOnStart;
    }
    const state = await call('get_state');
    if (state && state.status) WL.onState(state);
    if (appInfo && appInfo.checkUpdatesOnStart) setTimeout(() => checkUpdate(false), 4000);
  }

  document.addEventListener('DOMContentLoaded', () => {
    buildStatic();
    bind();
    const start = location.hash.replace('#', '');
    if (['touch', 'settings'].includes(start)) showPage(start);
    if (window.pywebview && window.pywebview.api) attach(window.pywebview.api);
    else if (window.WL_PREVIEW) attach(window.WL_PREVIEW);
  });
  window.addEventListener('pywebviewready', () => attach(window.pywebview.api));
})();
