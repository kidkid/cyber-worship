'use strict';

/* ============================================================
   赛博朝拜 · 渲染层
   - 磕头帧动画 / 疯狂磕头 / 过热机制
   - 总功德累计（localStorage）
   - 金币与功德文字特效、合成音效
   - 透明区域鼠标穿透（按 alpha 掩码判定）
   - 宠物大小调节（Ctrl+滚轮 / 菜单 / 托盘；窗口与页面缩放由主进程同步）
   ============================================================ */

// ---------------------------------------------------------------- 场景配置

const SCENES = {
  wealth: {
    name: '财运',
    label: '财运 · 财神爷',
    god: 'god_caishen', godW: 150,
    altar: 'altar_wealth', altarW: 206,
    accent: '#f2c75c',
    meritTexts: ['财运 +1', '功德 +1', '暴富 +1', '进宝 +1'],
    smoke: { x: 0.470, y: 0.296 },
  },
  stock: {
    name: '涨停',
    label: '涨停 · 暴富牛神',
    god: 'god_bull', godW: 212,
    altar: 'altar_stock', altarW: 214,
    accent: '#e2453c',
    meritTexts: ['涨停 +1', '红盘 +1', '放量 +1', '满仓 +1'],
    smoke: { x: 0.156, y: 0.280 },
  },
  health: {
    name: '健康',
    label: '健康 · 长寿星',
    god: 'god_shouxing', godW: 146,
    altar: 'altar_health', altarW: 216,
    accent: '#46c08a',
    meritTexts: ['寿命 +1', '安康 +1', '无病 +1', '元气 +1'],
    smoke: { x: 0.710, y: 0.308 },
  },
  study: {
    name: '考研',
    label: '考研 · 文昌帝君',
    god: 'god_wenchang', godW: 134,
    altar: 'altar_study', altarW: 198,
    accent: '#5aa9f2',
    meritTexts: ['功名 +1', '上岸 +1', '开智 +1', '上岸 +1'],
    smoke: { x: 0.381, y: 0.316 },
  },
};

const SCENE_KEYS = Object.keys(SCENES);

/** 境界：按累计功德解锁，纯属图个乐 */
const RANKS = [
  [0, '凡人'], [50, '香客'], [200, '善信'], [500, '居士'],
  [1200, '护法'], [3000, '真人'], [8000, '半仙'], [20000, '大罗金仙'],
];

// 版面常量（与 styles.css / main.js / tools/layout_mock.py 保持一致）
const GOD_BOTTOM_Y = 190;    // 神像底边（水平中心由 CSS --god-cx 决定）
const ALTAR_BOTTOM_Y = 420;  // 香案底边（水平中心由 CSS --altar-cx 决定）
const SMOKE_W = 78, SMOKE_H = 150;
const KOWTOW_SEQ = [1, 2, 3, 2];
const KOWTOW_ASPECT = 450 / 436;   // 帧画布高宽比（assets/images/kowtow_*.png 实测 436x450）

// ---------------------------------------------------------------- 状态

const store = {
  get(k, d) {
    try { const v = localStorage.getItem('cw.' + k); return v === null ? d : JSON.parse(v); }
    catch (e) { return d; }
  },
  set(k, v) { try { localStorage.setItem('cw.' + k, JSON.stringify(v)); } catch (e) {} },
};

let merit = store.get('merit', 0);
let sceneKey = store.get('scene', 'wealth');
if (!SCENES[sceneKey]) sceneKey = 'wealth';
let muted = store.get('muted', false);
let tapCount = store.get('tapCount', 0);

let zoom = 1;                // 由主进程给定，这里只用于显示与触发切换

let seqIdx = 0;
let animTimer = null;
let autoInterval = 200;      // 自动磕头帧间隔，越小越"疯狂"
let curInterval = autoInterval;
let frenzyUntil = 0;
let dizzyUntil = 0;
let bowCount = 0;            // 完整叩拜次数，用来给自动音效降频

// ---------------------------------------------------------------- DOM

const $ = (s) => document.querySelector(s);
const stage = $('#stage');
const godEl = $('#god');
const altarEl = $('#altar');
const personEl = $('#person');
const smokeLayer = $('#smokeLayer');
const fx = $('#fx');
const meritEl = $('#merit');
const badgeEl = $('#badge');
const barEl = $('#bar');
const toolsEl = $('#tools');
const chipsEl = $('#chips');
const menuEl = $('#menu');
const toastEl = $('#toast');
const rankNameEl = $('#rankName');
const zoomValEl = $('#zoomVal');

// ---------------------------------------------------------------- 音效（纯 Web Audio 合成，不依赖音频文件）

let actx = null;
function ac() {
  if (!actx) {
    const C = window.AudioContext || window.webkitAudioContext;
    actx = new C();
  }
  if (actx.state === 'suspended') actx.resume();
  return actx;
}

/** 磕头"咚"：低频下坠 + 短噪声敲击，音量可控 */
function sfxThud(vol = 0.5) {
  if (muted) return;
  const c = ac(), t = c.currentTime;

  const osc = c.createOscillator();
  const og = c.createGain();
  osc.type = 'sine';
  osc.frequency.setValueAtTime(200, t);
  osc.frequency.exponentialRampToValueAtTime(56, t + 0.17);
  og.gain.setValueAtTime(0.0001, t);
  og.gain.exponentialRampToValueAtTime(vol, t + 0.008);
  og.gain.exponentialRampToValueAtTime(0.0001, t + 0.24);
  osc.connect(og).connect(c.destination);
  osc.start(t); osc.stop(t + 0.27);

  const len = 2048;
  const buf = c.createBuffer(1, len, c.sampleRate);
  const ch = buf.getChannelData(0);
  for (let i = 0; i < len; i++) ch[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 7);
  const src = c.createBufferSource(); src.buffer = buf;
  const bp = c.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 820; bp.Q.value = 0.8;
  const ng = c.createGain(); ng.gain.value = vol * 0.42;
  src.connect(bp).connect(ng).connect(c.destination);
  src.start(t);
}

/** 金币"叮" */
function sfxCoin(vol = 0.32) {
  if (muted) return;
  const c = ac(), t = c.currentTime;
  [1568, 2352].forEach((f, i) => {
    const o = c.createOscillator(), g = c.createGain();
    o.type = 'triangle';
    o.frequency.value = f;
    const v = vol * (i ? 0.4 : 1);
    g.gain.setValueAtTime(0.0001, t + i * 0.045);
    g.gain.exponentialRampToValueAtTime(v, t + i * 0.045 + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, t + i * 0.045 + 0.34);
    o.connect(g).connect(c.destination);
    o.start(t + i * 0.045); o.stop(t + i * 0.045 + 0.36);
  });
}

/** 过热"嗡" */
function sfxDizzy() {
  if (muted) return;
  const c = ac(), t = c.currentTime;
  const o = c.createOscillator(), g = c.createGain();
  o.type = 'sawtooth';
  o.frequency.setValueAtTime(120, t);
  o.frequency.linearRampToValueAtTime(72, t + 0.7);
  const lp = c.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 520;
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(0.16, t + 0.06);
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.8);
  o.connect(lp).connect(g).connect(c.destination);
  o.start(t); o.stop(t + 0.85);
}

// ---------------------------------------------------------------- 排版

/** 元素在 stage 局部坐标系里的位置（页面缩放不影响这套坐标，都是 CSS px） */
function localRect(el) {
  const r = el.getBoundingClientRect();
  const s = stage.getBoundingClientRect();
  return { x: r.left - s.left, y: r.top - s.top, w: r.width, h: r.height };
}

function layout() {
  const s = SCENES[sceneKey];

  // 神像：统一底边，高度按真实比例推出来
  const gAspect = (godEl.naturalHeight && godEl.naturalWidth)
    ? godEl.naturalHeight / godEl.naturalWidth : 0.68;
  const godH = Math.round(s.godW * gAspect);
  godEl.style.width = s.godW + 'px';
  godEl.style.top = Math.max(4, GOD_BOTTOM_Y - godH) + 'px';
  document.documentElement.style.setProperty('--god-bottom', GOD_BOTTOM_Y + 'px');

  // 香案：同样统一底边
  const aAspect = (altarEl.naturalHeight && altarEl.naturalWidth)
    ? altarEl.naturalHeight / altarEl.naturalWidth : 0.68;
  const altarH = Math.round(s.altarW * aAspect);
  altarEl.style.width = s.altarW + 'px';
  altarEl.style.top = Math.max(60, ALTAR_BOTTOM_Y - altarH) + 'px';

  // 人物：尺寸由 styles.css 的 --person-w 决定，这里只同步一下宽高比保险
  const pw = parseFloat(getComputedStyle(personEl).width) || 194;
  personEl.style.height = Math.round(pw * KOWTOW_ASPECT) + 'px';
  personEl.style.top = Math.round(ALTAR_BOTTOM_Y - pw * KOWTOW_ASPECT) + 'px';

  // 香烟从香炉口往上飘（s.smoke 是香炉在香案图里的相对位置，已按素材实测标定）
  const a = localRect(altarEl);
  const bx = a.x + a.w * s.smoke.x;
  const by = a.y + a.h * s.smoke.y;
  smokeLayer.style.left = (bx - SMOKE_W / 2) + 'px';
  smokeLayer.style.top = (by - SMOKE_H) + 'px';

  document.documentElement.style.setProperty('--accent', s.accent);

  pushCoverage();   // 版面变了，命中网格要跟着重算
}

function applyScene(key, silent) {
  if (!SCENES[key]) return;
  sceneKey = key;
  const s = SCENES[key];

  godEl.src = 'assets/images/' + s.god + '.png';
  godEl.dataset.hit = s.god;
  altarEl.src = 'assets/images/' + s.altar + '.png';
  altarEl.dataset.hit = s.altar;

  const once = () => { layout(); };
  if (godEl.complete && altarEl.complete) once();
  else {
    godEl.addEventListener('load', once, { once: true });
    altarEl.addEventListener('load', once, { once: true });
  }

  [...chipsEl.children].forEach((c) => c.classList.toggle('on', c.dataset.key === key));

  store.set('scene', key);
  if (window.pet) window.pet.notifyScene(key);
  if (!silent) toast(s.label);
}

function setFrame(n) {
  const file = 'kowtow_' + n;
  if (personEl.dataset.frame === file) return;
  personEl.dataset.frame = file;
  personEl.src = 'assets/images/' + file + '.png';
  personEl.dataset.hit = file;
}

// ---------------------------------------------------------------- 宠物大小

function renderZoom() {
  if (zoomValEl) zoomValEl.textContent = Math.round(zoom * 100) + '%';
}

function applyZoomValue(z) {
  const n = Number(z);
  if (Number.isFinite(n) && n > 0) zoom = n;
  renderZoom();
  layout();
}

/** 让主进程沿着档位调整大小，再把结果同步到界面 */
async function changeZoom(dir) {
  if (!window.pet || !window.pet.stepZoom) return;
  const z = await window.pet.stepZoom(dir);
  applyZoomValue(z);
  toast('宠物大小 ' + Math.round(zoom * 100) + '%');
}

function setZoomAbsolute(z) {
  if (!window.pet || !window.pet.setZoom) return;
  window.pet.setZoom(z).then(applyZoomValue);
}

// ---------------------------------------------------------------- 磕头循环

function tick() {
  const now = Date.now();
  if (now < dizzyUntil) {
    curInterval = 900;
  } else if (now < frenzyUntil) {
    curInterval = 95;
  } else {
    curInterval = autoInterval;
  }

  seqIdx = (seqIdx + 1) % KOWTOW_SEQ.length;
  const n = KOWTOW_SEQ[seqIdx];
  setFrame(n);

  // 每完成几次完整叩拜轻轻响一声，避免持续噪音
  if (n === 3 && Date.now() >= dizzyUntil) {
    bowCount += 1;
    if (bowCount % 3 === 0) sfxThud(0.14);
  }

  animTimer = setTimeout(tick, curInterval);
}

// ---------------------------------------------------------------- 特效

function floatText(text, x, y) {
  const el = document.createElement('div');
  el.className = 'float-txt';
  el.textContent = text;
  el.style.left = x + 'px';
  el.style.top = y + 'px';
  fx.appendChild(el);
  const dx = (Math.random() - 0.5) * 46;
  el.animate(
    [
      { transform: 'translate(-50%, 0) scale(0.7)', opacity: 0 },
      { transform: `translate(calc(-50% + ${dx * 0.3}px), -16px) scale(1.08)`, opacity: 1, offset: 0.2 },
      { transform: `translate(calc(-50% + ${dx}px), -74px) scale(1)`, opacity: 0 },
    ],
    { duration: 1150, easing: 'cubic-bezier(.22,.7,.3,1)' }
  ).onfinish = () => el.remove();
}

function coinBurst(cx, cy, n) {
  for (let i = 0; i < n; i++) {
    const el = document.createElement('img');
    el.className = 'coin-fly';
    el.src = 'assets/images/coin.png';
    el.style.left = cx + 'px';
    el.style.top = cy + 'px';
    fx.appendChild(el);
    const ang = (-Math.PI / 2) + (Math.random() - 0.5) * 2.0;
    const dist = 40 + Math.random() * 70;
    const dx = Math.cos(ang) * dist;
    const dy = Math.sin(ang) * dist;
    const rot = (Math.random() - 0.5) * 540;
    const sc = 0.6 + Math.random() * 0.7;
    el.animate(
      [
        { transform: `translate(-50%,-50%) scale(0.3) rotate(0deg)`, opacity: 0 },
        { transform: `translate(calc(-50% + ${dx * 0.5}px), calc(-50% + ${dy * 0.9}px)) scale(${sc}) rotate(${rot * 0.55}deg)`,
          opacity: 1, offset: 0.28 },
        { transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy + 120}px)) scale(${sc * 0.7}) rotate(${rot}deg)`,
          opacity: 0 },
      ],
      { duration: 900 + Math.random() * 350, easing: 'cubic-bezier(.25,.6,.4,1)' }
    ).onfinish = () => el.remove();
  }
}

function ripple(cx, cy) {
  const el = document.createElement('div');
  el.className = 'ripple';
  el.style.left = cx + 'px';
  el.style.top = cy + 'px';
  fx.appendChild(el);
  setTimeout(() => el.remove(), 520);
}

let toastTimer = null;
function toast(text) {
  toastEl.textContent = text;
  toastEl.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove('show'), 1500);
}

function rankOf(n) {
  let name = RANKS[0][1];
  for (const [need, label] of RANKS) if (n >= need) name = label;
  return name;
}

function renderMerit(bump) {
  meritEl.textContent = merit.toLocaleString('en-US');
  rankNameEl.textContent = rankOf(merit);
  if (bump) {
    badgeEl.classList.remove('bump');
    void badgeEl.offsetWidth;
    badgeEl.classList.add('bump');
  }
  pushCoverage();   // 数字变长会让功德牌变宽，命中区跟着变
}

// ---------------------------------------------------------------- 交互

/** 一次磕头：+1 功德 + 特效 */
function kowtowOnce(isUser) {
  const now = Date.now();
  if (now < dizzyUntil) {
    toast('头晕目眩… 休息一下');
    return;
  }

  merit += 1;
  tapCount += 1;
  store.set('merit', merit);
  store.set('tapCount', tapCount);
  renderMerit(isUser);

  const s = SCENES[sceneKey];
  const pr = localRect(personEl);
  const hx = pr.x + pr.w * 0.5 + (Math.random() - 0.5) * 26;
  const hy = pr.y + pr.h * 0.24;

  floatText(s.meritTexts[Math.floor(Math.random() * s.meritTexts.length)], hx, hy);
  coinBurst(hx, hy + 20, 3 + Math.floor(Math.random() * 3));

  if (isUser) {
    ripple(pr.x + pr.w * 0.5, pr.y + pr.h * 0.55);
    sfxThud(0.46);
    sfxCoin(0.3);
    // 疯狂磕头：连点后短暂提速
    seqIdx = 0; setFrame(1);
    frenzyUntil = now + 900;
    personEl.classList.add('frenzy');
    setTimeout(() => personEl.classList.remove('frenzy'), 900);
    checkOverheat();
  }
}

function checkOverheat() {
  const now = Date.now();
  recentTaps = recentTaps.filter((t) => now - t < 3000);
  recentTaps.push(now);
  if (recentTaps.length > 20) {
    dizzyUntil = now + 5000;
    recentTaps = [];
    personEl.classList.add('dizzy');
    sfxDizzy();
    toast('头晕目眩，休息 5 秒');
    setTimeout(() => {
      personEl.classList.remove('dizzy');
      toast('缓过来了，继续拜');
    }, 5000);
  }
}
let recentTaps = [];

/** 上香：一次 +10 */
function offerIncense() {
  const now = Date.now();
  if (now < dizzyUntil) { toast('头晕目眩… 休息一下'); return; }
  merit += 10;
  store.set('merit', merit);
  renderMerit(true);

  const a = localRect(altarEl);
  floatText('上香 +10', a.x + a.w * 0.5, a.y + a.h * 0.08);
  coinBurst(a.x + a.w * 0.5, a.y + a.h * 0.3, 8);
  sfxCoin(0.5);
  smokeLayer.animate(
    [{ filter: 'brightness(1)' }, { filter: 'brightness(2.2)' }, { filter: 'brightness(1)' }],
    { duration: 700 }
  );
}

// ---------------------------------------------------------------- 透明区域鼠标穿透
//
// 血泪教训：不要依赖 Chromium 的"转发鼠标事件"来恢复可交互。
// 实测（tools/drag_test.py）窗口一旦被设成穿透（WS_EX_TRANSPARENT），
// 即使鼠标移到神像这种完全不透明的像素上也不会恢复 —— 于是整个宠物点不动、
// 场景自然也就切不了。
//
// 现在改成完全确定的方案：
//   渲染层算出一张「命中网格」（哪些格子会挡住桌面点击）交给主进程；
//   主进程定时读系统光标位置，自己决定穿透与否，再反过来通知渲染层要不要浮出面板。

const CELL = 4;                       // 命中网格精度（CSS px）
const BASE_W = 400, BASE_H = 460;     // 必须与 main.js BASE_W / BASE_H 一致

/** 人物三帧的掩码取并集：磕头时姿势不同、轮廓会变，取并集才不漏 */
let personUnion = null;
function personUnionMask() {
  if (personUnion) return personUnion;
  const hs = ['kowtow_1', 'kowtow_2', 'kowtow_3']
    .map((k) => window.HITMAPS && window.HITMAPS[k]).filter(Boolean);
  if (!hs.length) return null;
  const w = hs[0].w, h = hs[0].h;
  const rows = [];
  for (let y = 0; y < h; y++) {
    let row = '';
    for (let x = 0; x < w; x++) {
      let v = '0';
      for (const hm of hs) {
        if (hm.w === w && hm.h === h && hm.rows[y][x] === '1') { v = '1'; break; }
      }
      row += v;
    }
    rows.push(row);
  }
  personUnion = { w, h, rows };
  return personUnion;
}

/** 一次性收齐各元素的矩形与掩码，避免在网格里反复调 getBoundingClientRect */
function collectHitRects() {
  const s = stage.getBoundingClientRect();
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return { l: r.left - s.left, t: r.top - s.top, r: r.right - s.left, b: r.bottom - s.top,
             w: r.width, h: r.height };
  };

  // 面板（场景条 / 工具列 / 功德牌 / 展开的菜单）按矩形算，且永远算命中
  const panels = [barEl, toolsEl, badgeEl].map(box);
  if (menuEl.classList.contains('show')) panels.push(box(menuEl));

  // 画面元素按 alpha 掩码算，透明像素放行
  const images = [godEl, altarEl, personEl].map((el) => {
    const b = box(el);
    b.mask = (el === personEl) ? personUnionMask()
                               : (window.HITMAPS && window.HITMAPS[el.dataset.hit]);
    return b;
  });

  return { panels, images };
}

function hitAtRects(pre, x, y) {
  for (const p of pre.panels) {
    if (x >= p.l && x <= p.r && y >= p.t && y <= p.b) return true;
  }
  for (const im of pre.images) {
    if (x < im.l || x > im.r || y < im.t || y > im.b) continue;
    const m = im.mask;
    if (!m) return true;        // 没掩码就退回矩形：宁可挡住，也别点不着
    const cx = Math.min(m.w - 1, Math.max(0, Math.floor((x - im.l) / im.w * m.w)));
    const cy = Math.min(m.h - 1, Math.max(0, Math.floor((y - im.t) / im.h * m.h)));
    if (m.rows[cy][cx] === '1') return true;
  }
  return false;
}

/** 单点命中判定（右键菜单、自动化测试用） */
function hitTest(x, y) {
  return hitAtRects(collectHitRects(), x, y);
}

let covTimer = null;
/** 把命中网格推给主进程；同一帧内多次触发只算一次 */
function pushCoverage() {
  if (!window.pet || !window.pet.updateCoverage) return;
  clearTimeout(covTimer);
  covTimer = setTimeout(() => {
    const pre = collectHitRects();
    const cols = Math.ceil(BASE_W / CELL), rows = Math.ceil(BASE_H / CELL);
    const out = [];
    for (let cy = 0; cy < rows; cy++) {
      const y = cy * CELL + CELL / 2;
      for (let cx = 0; cx < cols; cx++) {
        out.push(hitAtRects(pre, cx * CELL + CELL / 2, y) ? '1' : '0');
      }
    }
    window.pet.updateCoverage({ cell: CELL, cols, rows, grid: out.join('') });
  }, 0);
}

/** 主进程判定光标是否落在宠物身上，决定浮出/收起面板 */
function setHover(on) {
  const v = !!on;
  if (v === stage.classList.contains('hover-ui')) return;
  stage.classList.toggle('hover-ui', v);
  if (!v) hideMenu();
}

// ---------------------------------------------------------------- 右键菜单

function buildMenu() {
  const scenes = SCENE_KEYS
    .map((k) => `<div class="mi ${k === sceneKey ? 'on' : ''}" data-act="scene" data-key="${k}">${SCENES[k].label}</div>`)
    .join('');
  menuEl.innerHTML =
    scenes +
    '<div class="mi sep"></div>' +
    '<div class="mi" data-act="zoom-out">缩小宠物　－</div>' +
    `<div class="mi dim">当前大小　${Math.round(zoom * 100)}%（Ctrl + 滚轮）</div>` +
    '<div class="mi" data-act="zoom-in">放大宠物　＋</div>' +
    '<div class="mi sep"></div>' +
    `<div class="mi ${muted ? 'on' : ''}" data-act="mute">音效静音</div>` +
    '<div class="mi" data-act="offer">上香（+10）</div>' +
    '<div class="mi" data-act="reset">清零总功德</div>' +
    '<div class="mi sep"></div>' +
    '<div class="mi" data-act="pos">宠物归位</div>' +
    '<div class="mi" data-act="hide">隐藏（Ctrl+Alt+H）</div>' +
    '<div class="mi" data-act="quit">退出</div>';
}

function showMenu(x, y) {
  buildMenu();
  menuEl.classList.add('show');
  const r = menuEl.getBoundingClientRect();
  const sr = stage.getBoundingClientRect();
  let left = x - sr.left, top = y - sr.top;
  if (left + r.width > sr.width - 6) left = sr.width - r.width - 6;
  if (top + r.height > sr.height - 6) top = Math.max(6, sr.height - r.height - 6);
  menuEl.style.left = left + 'px';
  menuEl.style.top = top + 'px';
  pushCoverage();          // 菜单展开后要多挡住它自己这块，否则菜单项点不到
}

function hideMenu() {
  if (!menuEl.classList.contains('show')) return;
  menuEl.classList.remove('show');
  pushCoverage();
}

menuEl.addEventListener('click', (e) => {
  const mi = e.target.closest('.mi');
  if (!mi || !mi.dataset.act) return;
  const act = mi.dataset.act;
  hideMenu();
  if (act === 'scene') applyScene(mi.dataset.key);
  else if (act === 'zoom-in') changeZoom(1);
  else if (act === 'zoom-out') changeZoom(-1);
  else if (act === 'mute') { muted = !muted; store.set('muted', muted); toast(muted ? '已静音' : '已开启音效'); }
  else if (act === 'offer') offerIncense();
  else if (act === 'reset') resetMerit();
  else if (act === 'pos') window.pet && window.pet.resetPosition();
  else if (act === 'hide') window.pet && window.pet.hide();
  else if (act === 'quit') window.pet && window.pet.quit();
});

function resetMerit() {
  merit = 0; tapCount = 0;
  store.set('merit', 0); store.set('tapCount', 0);
  renderMerit(true);
  toast('总功德已清零');
}

// ---------------------------------------------------------------- 事件绑定

function bindUI() {
  // 场景按钮
  SCENE_KEYS.forEach((k) => {
    const b = document.createElement('button');
    b.className = 'chip';
    b.dataset.key = k;
    b.textContent = SCENES[k].name;
    b.addEventListener('click', (e) => { e.stopPropagation(); applyScene(k); });
    chipsEl.appendChild(b);
  });

  personEl.addEventListener('click', (e) => { e.stopPropagation(); kowtowOnce(true); });

  document.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    if (hitTest(e.clientX, e.clientY)) showMenu(e.clientX, e.clientY);
    else hideMenu();
  });

  document.addEventListener('click', (e) => {
    if (!menuEl.contains(e.target)) hideMenu();
  });

  document.addEventListener('mousemove', () => {
    // 鼠标能进来就说明主进程已经判定为"命中"，把面板浮出来（轮询的兜底/提速）
    setHover(true);
  });
  // 注意：不要在这里监听 mouseleave 去收面板。
  // 穿透状态切换时 Chromium 会补发 enter/leave，容易和主进程的判定打架，
  // 反而出现"光标还在宠物上、面板却缩回去"的抖动。收面板交给主进程的 hover:changed。

  document.addEventListener('keydown', (e) => {
    if (e.code === 'Space') {
      e.preventDefault();
      if (e.repeat) return;
      kowtowOnce(true);
    } else if (e.key === 'Escape') {
      hideMenu();
    } else if (e.ctrlKey && (e.key === '=' || e.key === '+' || e.code === 'Equal' || e.code === 'NumpadAdd')) {
      // 接管 Ctrl+加减号，避免 Chromium 自带的页面缩放把窗口尺寸搞乱
      e.preventDefault();
      changeZoom(1);
    } else if (e.ctrlKey && (e.key === '-' || e.key === '_' || e.code === 'Minus' || e.code === 'NumpadSubtract')) {
      e.preventDefault();
      changeZoom(-1);
    }
  });

  // Ctrl + 滚轮缩放。非 Ctrl 的滚轮放行，不影响桌面
  document.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    changeZoom(e.deltaY < 0 ? 1 : -1);
  }, { passive: false });

  $('#btnOffer').addEventListener('click', (e) => { e.stopPropagation(); offerIncense(); });
  $('#btnZoomIn').addEventListener('click', (e) => { e.stopPropagation(); changeZoom(1); });
  $('#btnZoomOut').addEventListener('click', (e) => { e.stopPropagation(); changeZoom(-1); });
  $('#btnHide').addEventListener('click', (e) => { e.stopPropagation(); window.pet && window.pet.hide(); });
  $('#btnQuit').addEventListener('click', (e) => { e.stopPropagation(); window.pet && window.pet.quit(); });

  window.addEventListener('resize', layout);
}

// ---------------------------------------------------------------- 启动

function boot() {
  bindUI();
  applyScene(sceneKey, true);
  renderMerit(false);
  renderZoom();
  setFrame(1);
  // 等图片解码完再排版，避免用不到真实尺寸
  Promise.all([
    godEl.decode().catch(() => {}),
    altarEl.decode().catch(() => {}),
  ]).then(layout);

  tick();

  // 托盘 / 主进程指令
  if (window.pet) {
    window.pet.onSceneSet((k) => applyScene(k));
    window.pet.onOffer(() => offerIncense());
    window.pet.onReset(() => resetMerit());
    window.pet.onZoomChanged((z) => applyZoomValue(z));
    // 主进程按光标位置判定"是否落在宠物身上"，穿透与否也由它决定
    window.pet.onHoverChanged((on) => setHover(on));
    window.pet.getZoom().then(applyZoomValue).catch(() => {});
    pushCoverage();
  }

  setTimeout(() => {
    toast('点小人磕头 · 功德 +1');
    layout();
  }, 600);
}

if (document.readyState === 'complete') boot();
else window.addEventListener('load', boot);
