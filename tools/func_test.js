'use strict';
/**
 * 功能测试：在真实 Electron 环境里驱动界面，验证核心玩法
 *   1. 点小人 -> 功德 +1 累加，并写入 localStorage
 *   2. 3 秒内连点 > 20 次 -> 触发"过热"眩晕，期间点击不计功德
 *   3. 【真实鼠标事件】移到场景按钮上 -> 面板浮出 -> 点击 -> 场景真的切换了
 *      （这是回归测试：早先命中判定与"悬停才显示"互锁，导致场景按钮点不动）
 *   4. 四套场景的版面（底边对齐、香烟落点）
 *   5. 空格键磕头 / 上香 +10 / 右键菜单归零
 *   6. 宠物大小：按钮与 Ctrl+滚轮（主进程档位）
 * 用法： node_modules/.bin/electron tools/func_test.js
 */
const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const os = require('os');
const fs = require('fs');

const ROOT = path.join(__dirname, '..');
const W = 400, H = 460;
const errs = [];
const fails = [];

// 用临时 userData，别污染真实存档
const tmp = path.join(os.tmpdir(), 'cw-func-test-' + Date.now());
fs.mkdirSync(tmp, { recursive: true });
app.setPath('userData', tmp);

// --- 模拟主进程的缩放入口（真实运行时由 main.js 提供）---
const ZOOM_STEPS = [0.5, 0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.2, 1.3, 1.4];
let fakeZoom = 1;
ipcMain.handle('zoom:get', () => fakeZoom);
ipcMain.handle('zoom:set', (_e, z) => { fakeZoom = z; return fakeZoom; });
ipcMain.handle('zoom:step', (_e, dir) => {
  let i = ZOOM_STEPS.indexOf(fakeZoom);
  i = Math.min(ZOOM_STEPS.length - 1, Math.max(0, i + (dir > 0 ? 1 : -1)));
  fakeZoom = ZOOM_STEPS[i];
  return fakeZoom;
});

const ok = (cond, label, extra) => {
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${label}${extra !== undefined ? '  -> ' + JSON.stringify(extra) : ''}`);
  if (!cond) fails.push(label);
};

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: W, height: H, show: false, transparent: true, frame: false,
    webPreferences: {
      preload: path.join(ROOT, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: false,
      backgroundThrottling: false,
    },
  });
  win.webContents.on('console-message', (...a) => {
    const d = a[1];
    const msg = d && typeof d === 'object' ? d.message : a[2];
    const lv = d && typeof d === 'object' ? d.level : a[1];
    if (lv === 'error' || lv === 3) errs.push(String(msg));
  });
  win.webContents.on('render-process-gone', () => errs.push('render-process-gone'));

  const js = (s) => win.webContents.executeJavaScript(s);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  /** 真实鼠标事件：走 Chromium 的输入管线，等价于用户手点 */
  const moveMouse = (x, y) => win.webContents.sendInputEvent({ type: 'mouseMove', x, y });
  const clickMouse = async (x, y) => {
    win.webContents.sendInputEvent({ type: 'mouseMove', x, y });
    await wait(120);
    win.webContents.sendInputEvent({ type: 'mouseDown', x, y, button: 'left', clickCount: 1 });
    await wait(60);
    win.webContents.sendInputEvent({ type: 'mouseUp', x, y, button: 'left', clickCount: 1 });
    await wait(120);
  };

  await win.loadFile(path.join(ROOT, 'index.html'));
  await wait(900);

  // ---- 1. 点击小人累加功德
  await js(`(() => { const p = document.querySelector('#person');
    for (let i = 0; i < 5; i++) p.dispatchEvent(new MouseEvent('click', {bubbles: true})); })()`);
  await wait(120);
  let s = await js(`({ merit: document.querySelector('#merit').textContent,
                       stored: localStorage.getItem('cw.merit'),
                       rank: document.querySelector('#rankName').textContent })`);
  ok(s.merit === '5', '点击小人 5 次 -> 功德 5', s);
  ok(s.stored === '5', '功德已写入 localStorage', s.stored);

  // ---- 2. 连点触发过热
  await js(`(() => { const p = document.querySelector('#person');
    for (let i = 0; i < 30; i++) p.dispatchEvent(new MouseEvent('click', {bubbles: true})); })()`);
  await wait(120);
  s = await js(`({ merit: document.querySelector('#merit').textContent,
                   dizzy: document.querySelector('#person').classList.contains('dizzy'),
                   toast: document.querySelector('#toast').textContent })`);
  ok(s.dizzy === true, '3 秒内连点 30 次 -> 触发过热眩晕', s.dizzy);
  ok(/头晕/.test(s.toast), '过热提示文案正确', s.toast);
  const before = parseInt(s.merit, 10);
  await js(`document.querySelector('#person').dispatchEvent(new MouseEvent('click', {bubbles: true}))`);
  await wait(80);
  s = await js(`document.querySelector('#merit').textContent`);
  ok(parseInt(s, 10) === before, '眩晕期间点击不再增加功德', { before, after: s });

  // ---- 3. 真实鼠标：悬停 -> 面板浮出 -> 点场景按钮
  const rectOf = (sel) => js(`(() => { const r = document.querySelector('${sel}').getBoundingClientRect();
      return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }; })()`);

  const barRect = await rectOf('#bar');
  const chipRect = await rectOf('.chip[data-key="stock"]');
  const chipCx = chipRect.x + Math.round(chipRect.w / 2);
  const chipCy = chipRect.y + Math.round(chipRect.h / 2);

  // 注：隐藏窗口下 Chromium 不派发"合成"的 mousemove，所以这里只断言应用层的命中判定；
  // 真实鼠标的"移入 -> 面板浮出 -> 点中"全链路由 tools/hover_test.js 用可见窗口覆盖。
  s = await js(`({ hitChip: hitTest(${chipCx}, ${chipCy}),
                   hitGod: hitTest(248, 120),
                   hitEmpty: hitTest(4, ${H - 4}),
                   hitBadge: hitTest(${W - 30}, ${H - 26}) })`);
  ok(s.hitChip === true, '命中判定：悬停隐藏状态下的场景按钮也算命中（这是"点不动场景"的根因）', s.hitChip);
  ok(s.hitEmpty === false, '命中判定：空白处不拦截鼠标', s.hitEmpty);
  ok(s.hitGod === true && s.hitBadge === true, '命中判定：神像 / 功德牌可点', s);

  // 真点一下
  const sceneBefore = await js(`document.querySelector('#god').getAttribute('src')`);
  await clickMouse(chipCx, chipCy);
  await wait(400);
  const sceneAfter = await js(`({ god: document.querySelector('#god').getAttribute('src'),
                                 altar: document.querySelector('#altar').getAttribute('src'),
                                 toast: document.querySelector('#toast').textContent,
                                 stored: localStorage.getItem('cw.scene') })`);
  ok(sceneBefore !== sceneAfter.god && /god_bull/.test(sceneAfter.god),
    '真实鼠标点击"涨停"标签 -> 神像切换为牛神', { before: sceneBefore, after: sceneAfter.god });
  ok(/altar_stock/.test(sceneAfter.altar), '香案同步切换', sceneAfter.altar);
  ok(sceneAfter.stored === '"stock"', '场景已写入 localStorage', sceneAfter.stored);

  // 再点"考研"，确认可以连续切换（不是只能切一次）
  const chip2 = await rectOf('.chip[data-key="study"]');
  await clickMouse(chip2.x + Math.round(chip2.w / 2), chip2.y + Math.round(chip2.h / 2));
  await wait(400);
  s = await js(`document.querySelector('#god').getAttribute('src')`);
  ok(/god_wenchang/.test(s), '再次点击"考研"标签 -> 继续切换', s);

  console.log('  场景条盒模型:', JSON.stringify(barRect));

  // ---- 4. 四套场景的版面
  // 注意：窗口是隐藏的，Chromium 不会推进 CSS transition，所以 rect 宽度会停在旧值。
  // 这里断言 layout() 写进去的 inline 样式 + 不参与过渡的 top，二者才是真正的版面结果。
  const probeScene = `(() => { const g = document.querySelector('#god'), a = document.querySelector('#altar'),
      s = document.querySelector('#smokeLayer');
    const ar = a.getBoundingClientRect();
    return { god: g.getAttribute('src'), altar: a.getAttribute('src'),
             godW: parseFloat(g.style.width), godTop: Math.round(g.getBoundingClientRect().top),
             altarW: parseFloat(a.style.width), altarTop: Math.round(ar.top),
             altarX: Math.round(ar.left),
             natGod: [g.naturalWidth, g.naturalHeight], natAltar: [a.naturalWidth, a.naturalHeight],
             accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
             smokeX: Math.round(parseFloat(s.style.left) + 39),
             smokeY: Math.round(parseFloat(s.style.top) + 150) }; })()`;
  const seen = {};
  for (let i = 0; i < 4; i++) {
    const label = ['财运', '涨停', '健康', '考研'][i];
    await js(`[...document.querySelectorAll('.chip')].find(c => c.textContent === '${label}').click()`);
    await wait(500);
    seen[label] = await js(probeScene);
  }
  ok(new Set(Object.values(seen).map((v) => v.god)).size === 4, '四个场景神像各不相同');
  ok(new Set(Object.values(seen).map((v) => v.altar)).size === 4, '四个场景香案各不相同');
  ok(new Set(Object.values(seen).map((v) => v.accent)).size === 4, '四个场景强调色各不相同');

  // 香案底边必须统一落在 ALTAR_BOTTOM_Y=420
  const ALTAR_BOTTOM_Y = 420;
  const altarBottomErr = {};
  for (const [k, v] of Object.entries(seen)) {
    const h = Math.round(v.altarW * v.natAltar[1] / v.natAltar[0]);
    altarBottomErr[k] = v.altarTop + h - ALTAR_BOTTOM_Y;
  }
  ok(Object.values(altarBottomErr).every((e) => Math.abs(e) <= 1), '四套香案底边统一在 y=420', altarBottomErr);

  // 神像底边统一落在 GOD_BOTTOM_Y=190（允许 ±9 的浮动动画偏移）
  const GOD_BOTTOM_Y = 190;
  const godBottomErr = {};
  for (const [k, v] of Object.entries(seen)) {
    const h = Math.round(v.godW * v.natGod[1] / v.natGod[0]);
    godBottomErr[k] = v.godTop + h - GOD_BOTTOM_Y;
  }
  ok(Object.values(godBottomErr).every((e) => Math.abs(e) <= 9), '四尊神像底边统一在 y=190', godBottomErr);

  // 香烟落点必须落在香案横向范围内，且在香案上半部（香炉位置）
  const smokeOut = {};
  for (const [k, v] of Object.entries(seen)) {
    if (v.smokeX < v.altarX || v.smokeX > v.altarX + v.altarW) smokeOut[k] = v.smokeX;
  }
  ok(Object.keys(smokeOut).length === 0, '香烟落点都在香案横向范围内',
    Object.fromEntries(Object.entries(seen).map(([k, v]) => [k, v.smokeX])));
  console.log('  各场景排版:', JSON.stringify(seen, null, 1));

  // ---- 5. 空格磕头 / 上香 / 右键菜单归零
  await wait(5300);   // 等眩晕结束
  const m0 = parseInt(await js(`document.querySelector('#merit').textContent`), 10);
  await js(`document.dispatchEvent(new KeyboardEvent('keydown', {code: 'Space', key: ' ', bubbles: true}))`);
  await wait(120);
  const m1 = parseInt(await js(`document.querySelector('#merit').textContent`), 10);
  ok(m1 === m0 + 1, '空格键磕头 -> 功德 +1', { m0, m1 });

  await js(`document.querySelector('#btnOffer').click()`);
  await wait(120);
  const m2 = parseInt(await js(`document.querySelector('#merit').textContent`), 10);
  ok(m2 === m1 + 10, '上香 -> 功德 +10', { m1, m2 });

  // 归零现在只在右键菜单里：用真实右键唤出菜单，再点菜单项
  await clickMouse(248, 300);            // 先移到香案上，让命中判定通过
  win.webContents.sendInputEvent({ type: 'mouseDown', x: 248, y: 300, button: 'right', clickCount: 1 });
  win.webContents.sendInputEvent({ type: 'mouseUp', x: 248, y: 300, button: 'right', clickCount: 1 });
  await wait(250);
  const menuShown = await js(`document.querySelector('#menu').classList.contains('show')`);
  ok(menuShown === true, '在香案上右键 -> 唤出菜单', menuShown);
  await js(`document.querySelector('#menu .mi[data-act="reset"]').click()`);
  await wait(150);
  const m3 = await js(`document.querySelector('#merit').textContent`);
  ok(m3 === '0', '菜单里"清零总功德"生效', m3);
  ok(!(await js(`document.querySelector('#menu').classList.contains('show')`)), '点完菜单项菜单自动收起');

  // ---- 6. 宠物大小
  const z0 = await js(`document.querySelector('#zoomVal').textContent`);
  await js(`document.querySelector('#btnZoomIn').click()`);
  await wait(250);
  const z1 = await js(`document.querySelector('#zoomVal').textContent`);
  await js(`document.querySelector('#btnZoomIn').click()`);
  await wait(250);
  const z2 = await js(`document.querySelector('#zoomVal').textContent`);
  await js(`document.querySelector('#btnZoomOut').click()`);
  await wait(250);
  const z3 = await js(`document.querySelector('#zoomVal').textContent`);
  ok(z0 === '100%' && z1 === '110%' && z2 === '120%' && z3 === '110%',
    '放大/缩小按钮按档位生效', { z0, z1, z2, z3 });

  // Ctrl + 滚轮：交给主进程档位
  await js(`document.dispatchEvent(new WheelEvent('wheel', {deltaY: -120, ctrlKey: true, bubbles: true, cancelable: true}))`);
  await wait(250);
  const z4 = await js(`document.querySelector('#zoomVal').textContent`);
  ok(z4 === '120%', 'Ctrl+滚轮上 -> 放大到 120%', z4);
  await js(`document.dispatchEvent(new WheelEvent('wheel', {deltaY: 120, ctrlKey: true, bubbles: true, cancelable: true}))`);
  await js(`document.dispatchEvent(new WheelEvent('wheel', {deltaY: 120, ctrlKey: true, bubbles: true, cancelable: true}))`);
  await wait(300);
  const z5 = await js(`document.querySelector('#zoomVal').textContent`);
  ok(z5 === '100%', 'Ctrl+滚轮下 -> 缩小回 100%', z5);

  // ---- 7. 窗口尺寸改变了，版面要跟着重算
  const smokeBefore = await js(`document.querySelector('#smokeLayer').style.left`);
  win.setBounds({ x: 40, y: 40, width: Math.round(W * 0.8), height: Math.round(H * 0.8) });
  win.webContents.setZoomFactor(0.8);
  await wait(500);
  const after = await js(`(() => { const a = document.querySelector('#altar').getBoundingClientRect();
      const s = document.querySelector('#smokeLayer');
      const ar = a.getBoundingClientRect ? a : null;
      return { altarLeft: Math.round(a.left), altarWidth: Math.round(a.width),
               smokeLeft: s.style.left, innerW: window.innerWidth, innerH: window.innerHeight,
               dpr: window.devicePixelRatio, zoomFactor: 0.8 }; })()`);
  ok(after.smokeLeft === smokeBefore, '窗口缩放后香烟落点不变（CSS px 坐标系未被缩放影响）',
    { before: smokeBefore, after: after.smokeLeft });
  ok(after.innerW >= W - 3 && after.innerW <= W, '页面缩放后 CSS 视口宽度仍约等于基准宽度',
    { innerW: after.innerW, expect: W });
  console.log('  缩放后:', JSON.stringify(after));

  // ---- 8. 自动磕头动画在跑
  const f3 = await js(`document.querySelector('#person').dataset.frame`);
  ok(f3 && /kowtow_[123]/.test(f3), '自动磕头帧动画在推进', f3);

  ok(errs.length === 0, '无渲染进程错误', errs);
  console.log('FAILS=' + fails.length);
  console.log(fails.length ? 'FAILED: ' + fails.join(' | ') : 'ALL PASS');
  app.exit(fails.length ? 1 : 0);
});
