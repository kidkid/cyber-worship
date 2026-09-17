'use strict';

const { app, BrowserWindow, Menu, Tray, globalShortcut, ipcMain, screen, shell } = require('electron');
const path = require('path');
const fs = require('fs');

// ------------------------------------------------------------------ 单实例
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

// 版面基准尺寸：必须与 styles.css 的 :root --w / --h 一致
const BASE_W = 400;
const BASE_H = 460;

// 缩放档位。BASE * 档位必须都是整数，否则透明窗口会露出半像素缝
const ZOOM_STEPS = [0.5, 0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.2, 1.3, 1.4];
const DEFAULT_ZOOM = 0.8;   // 默认偏小一点，别太占屏幕

const CONFIG_FILE = () => path.join(app.getPath('userData'), 'window-state.json');

let mainWindow = null;
let tray = null;
let quitting = false;
let zoom = DEFAULT_ZOOM;

// ------------------------------------------------------------------ 窗口位置 / 缩放状态
function readState() {
  try {
    const s = JSON.parse(fs.readFileSync(CONFIG_FILE(), 'utf8'));
    return (s && typeof s === 'object') ? s : {};
  } catch (e) {
    return {};   // 首次运行没有配置文件
  }
}

function writeState(state) {
  try {
    fs.writeFileSync(CONFIG_FILE(), JSON.stringify(state, null, 2), 'utf8');
  } catch (e) { /* 忽略写入失败 */ }
}

function clampZoom(z) {
  const n = Number(z);
  if (!Number.isFinite(n)) return DEFAULT_ZOOM;
  const lo = ZOOM_STEPS[0], hi = ZOOM_STEPS[ZOOM_STEPS.length - 1];
  return Math.min(hi, Math.max(lo, n));
}

/** 把任意值吸附到最近的档位，保证窗口尺寸与 CSS 缩放严格同步 */
function nearestStep(z) {
  let best = ZOOM_STEPS[0];
  for (const s of ZOOM_STEPS) {
    if (Math.abs(s - z) < Math.abs(best - z)) best = s;
  }
  return best;
}

function winSize(z) {
  return { width: Math.round(BASE_W * z), height: Math.round(BASE_H * z) };
}

function defaultPosition(z = zoom) {
  const wa = screen.getPrimaryDisplay().workArea;
  const { width, height } = winSize(z);
  return { x: wa.x + wa.width - width - 24, y: wa.y + wa.height - height - 24 };
}

/**
 * 把坐标夹回可见工作区。
 * 存档里的位置可能是"上一次"的：换了分辨率、拔了外接屏、或者被拖到屏幕外之后关掉，
 * 下次启动窗口就会落在屏幕外 —— 那时候宠物既看不见也点不到，只能去删配置文件。
 */
function clampToWorkArea(x, y, w, h) {
  const d = screen.getDisplayMatching({
    x: Math.round(x), y: Math.round(y), width: w, height: h,
  });
  const wa = d.workArea;
  return {
    x: Math.round(Math.min(Math.max(x, wa.x), Math.max(wa.x, wa.x + wa.width - w))),
    y: Math.round(Math.min(Math.max(y, wa.y), Math.max(wa.y, wa.y + wa.height - h))),
  };
}

// ------------------------------------------------------------------ 主窗口
function createWindow() {
  const state = readState();
  zoom = nearestStep(clampZoom(state.zoom === undefined ? DEFAULT_ZOOM : state.zoom));
  coverage = null;
  hovering = null;
  coverageDeadline = Date.now() + 3000;

  const { width, height } = winSize(zoom);
  const fallback = defaultPosition(zoom);
  // 存档位置一律夹回可见区域：否则窗口可能落在屏幕外，宠物就"消失"了
  const pos = clampToWorkArea(
    Number.isFinite(state.x) ? state.x : fallback.x,
    Number.isFinite(state.y) ? state.y : fallback.y,
    width, height,
  );

  mainWindow = new BrowserWindow({
    width,
    height,
    x: Math.round(pos.x),
    y: Math.round(pos.y),
    transparent: true,        // 关键：窗口透明
    frame: false,             // 关键：无标题栏无边框
    alwaysOnTop: true,        // 关键：始终置顶在桌面
    resizable: false,
    maximizable: false,
    minimizable: true,
    fullscreenable: false,
    hasShadow: false,
    skipTaskbar: false,
    show: false,
    // 透明窗口下有实测拿不到 ready-to-show 的情况，所以下面用三重兜底把宠物显示出来
    paintWhenInitiallyHidden: true,
    backgroundColor: '#00000000',
    title: '赛博朝拜',
    icon: path.join(__dirname, 'assets', 'icon.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      backgroundThrottling: false,
      // 缩放用 Chromium 的页面缩放：渲染层的坐标系始终是 BASE_W x BASE_H 的
      // CSS px，所有坐标/命中判定都不用换算，拖拽区也不会错位；
      // 窗口物理尺寸由 setBounds 同步改小，视觉上就是"宠物变小了"。
      zoomFactor: zoom,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'index.html'));

  // 显示宠物：ready-to-show -> did-finish-load -> 定时兜底，谁先到用谁，只执行一次
  let shown = false;
  const showPet = () => {
    if (shown || !mainWindow || mainWindow.isDestroyed()) return;
    shown = true;
    // 置顶级别：让宠物浮在普通窗口之上，但不要盖住全屏游戏
    mainWindow.setAlwaysOnTop(true, 'screen-saver');
    mainWindow.show();
    mainWindow.setAlwaysOnTop(true, 'screen-saver');
  };
  mainWindow.once('ready-to-show', showPet);
  mainWindow.webContents.once('did-finish-load', () => setTimeout(showPet, 120));
  mainWindow.webContents.once('did-fail-load', (_e, code, desc) => {
    console.error('[赛博朝拜] 界面加载失败:', code, desc);
    showPet();   // 出错了也要让用户看到窗口，方便排查
  });
  setTimeout(showPet, 2500);

  // 记住位置（带上缩放，否则会把它冲掉）
  const saveBounds = () => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    const b = mainWindow.getBounds();
    writeState({ x: b.x, y: b.y, zoom });
  };
  let moveTimer = null;
  mainWindow.on('move', () => {
    clearTimeout(moveTimer);
    moveTimer = setTimeout(saveBounds, 400);
  });

  // 窗口内的外链一律用系统浏览器打开，避免在宠物窗口里跳走
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ------------------------------------------------------------------ 缩放
/**
 * 切换宠物大小。
 * 窗口锚定「右下角」缩放：缩小后宠物仍然贴着原来的屏幕角落，不会往屏幕中间跑。
 */
function applyZoom(next, broadcast) {
  zoom = nearestStep(clampZoom(next));

  const { width, height } = winSize(zoom);
  const state = readState();

  if (mainWindow && !mainWindow.isDestroyed()) {
    const b = mainWindow.getBounds();
    const wa = screen.getDisplayMatching(b).workArea;
    let x = b.x + b.width - width;
    let y = b.y + b.height - height;
    x = Math.min(Math.max(x, wa.x), Math.max(wa.x, wa.x + wa.width - width));
    y = Math.min(Math.max(y, wa.y), Math.max(wa.y, wa.y + wa.height - height));

    // resizable:false 的窗口在部分平台上 setBounds 不生效，临时放开一下
    const wasResizable = mainWindow.isResizable();
    if (!wasResizable) mainWindow.setResizable(true);
    mainWindow.setBounds({ x: Math.round(x), y: Math.round(y), width, height });
    // 页面缩放：渲染层坐标系保持 BASE_W x BASE_H 不变，视觉上整体放大/缩小
    mainWindow.webContents.setZoomFactor(zoom);
    if (!wasResizable) mainWindow.setResizable(false);

    writeState({ ...state, x: Math.round(x), y: Math.round(y), zoom });
  } else {
    writeState({ ...state, zoom });
  }

  if (broadcast !== false) sendToRenderer('zoom:changed', zoom);
  refreshTray();
  return zoom;
}

function stepZoom(dir, broadcast) {
  let i = ZOOM_STEPS.indexOf(nearestStep(zoom));
  i = Math.min(ZOOM_STEPS.length - 1, Math.max(0, i + (dir > 0 ? 1 : -1)));
  return applyZoom(ZOOM_STEPS[i], broadcast);
}

// ------------------------------------------------------------------ 系统托盘
const SCENES = [
  { key: 'wealth', label: '财运 · 财神爷' },
  { key: 'stock', label: '涨停 · 暴富牛神' },
  { key: 'health', label: '健康 · 长寿星' },
  { key: 'study', label: '考研 · 文昌帝君' },
];

let currentScene = 'wealth';

function sendToRenderer(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

function buildTrayMenu() {
  return Menu.buildFromTemplate([
    {
      label: mainWindow && mainWindow.isVisible() ? '隐藏宠物' : '显示宠物',
      click: () => toggleVisible(),
    },
    { type: 'separator' },
    {
      label: '切换朝拜对象',
      submenu: SCENES.map((s) => ({
        label: s.label,
        type: 'radio',
        checked: currentScene === s.key,
        click: () => {
          currentScene = s.key;
          sendToRenderer('scene:set', s.key);
          refreshTray();
        },
      })),
    },
    {
      label: '宠物大小（' + Math.round(zoom * 100) + '%）',
      submenu: ZOOM_STEPS.map((z) => ({
        label: Math.round(z * 100) + '%' + (z === DEFAULT_ZOOM ? '（默认）' : ''),
        type: 'radio',
        checked: Math.abs(z - zoom) < 1e-6,
        click: () => applyZoom(z),
      })),
    },
    {
      label: '一键上香（加功德）',
      click: () => sendToRenderer('action:offer', null),
    },
    {
      label: '清零总功德',
      click: () => sendToRenderer('action:reset', null),
    },
    { type: 'separator' },
    { label: '老板键：Ctrl + Alt + H', enabled: false },
    { label: '退出赛博朝拜', click: () => quitApp() },
  ]);
}

function refreshTray() {
  if (!tray) return;
  tray.setContextMenu(buildTrayMenu());
  tray.setToolTip('赛博朝拜 · 电子磕头');
}

function toggleVisible() {
  if (!mainWindow) return;
  if (mainWindow.isVisible()) mainWindow.hide();
  else {
    mainWindow.show();
    mainWindow.setAlwaysOnTop(true, 'screen-saver');
  }
  refreshTray();
}

function createTray() {
  tray = new Tray(path.join(__dirname, 'assets', 'icon.ico'));
  refreshTray();
  tray.on('click', () => toggleVisible());
  tray.on('double-click', () => toggleVisible());
}

function quitApp() {
  quitting = true;
  if (mainWindow && !mainWindow.isDestroyed()) {
    const b = mainWindow.getBounds();
    writeState({ x: b.x, y: b.y, zoom });
  }
  app.quit();
}

// ------------------------------------------------------------------ 生命周期
app.whenReady().then(() => {
  app.setAppUserModelId('com.cyber.worship');
  createWindow();
  createTray();

  // 光标轮询：40ms 一次，足够跟手，开销可以忽略（就是一次 GetCursorPos）
  pollTimer = setInterval(pollCursor, 40);

  // 老板键：Ctrl + Alt + H 快速隐藏 / 显示
  globalShortcut.register('CommandOrControl+Alt+H', () => toggleVisible());

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
    else if (mainWindow) mainWindow.show();
  });
});

app.on('second-instance', () => {
  if (mainWindow) {
    mainWindow.show();
    mainWindow.focus();
  }
});

app.on('window-all-closed', () => {
  // 桌面宠物：关掉窗口不退出，留在托盘里
  if (quitting) app.quit();
});

app.on('will-quit', () => {
  if (pollTimer) clearInterval(pollTimer);
  globalShortcut.unregisterAll();
});

// ------------------------------------------------------------------ 鼠标穿透
//
// 渲染层把「命中网格」（哪些格子会挡住桌面点击）算好推过来，
// 这里定时读系统光标位置自己判定穿透与否。
//
// 为什么不用 setIgnoreMouseEvents(true, {forward:true}) + 监听渲染层 mousemove 来恢复？
// 实测（tools/drag_test.py）窗口一旦进入穿透状态，即便鼠标移到完全不透明的
// 神像像素上也不会恢复，整个宠物就永远点不动了 —— 那正是"切不了场景"的根因。
// 轮询方案不依赖任何事件转发，行为完全确定。
let coverage = null;
let hovering = null;
let pollTimer = null;
let coverageDeadline = 0;      // 超过这个时刻还没收到命中网格，就先当作"可交互"

ipcMain.on('coverage:update', (_e, c) => {
  if (c && typeof c.grid === 'string' && c.cols > 0 && c.rows > 0 && c.cell > 0) {
    if (!coverage) coverageDeadline = Date.now() + 3000;   // 首帧之后才开始计时兜底
    coverage = c;
    hovering = null;          // 网格变了，强制下一次重新判定
  }
});

function cursorHitsPet() {
  if (!mainWindow || mainWindow.isDestroyed()) return false;
  if (!coverage) {
    // 渲染层还没把命中网格送上来：短暂过渡期按"穿透"处理（别挡桌面），
    // 但如果迟迟收不到，就退回"可交互" —— 宁可挡一点，也不能让宠物变成永远点不动。
    return coverageDeadline > 0 && Date.now() > coverageDeadline;
  }
  const p = screen.getCursorScreenPoint();
  const b = mainWindow.getBounds();
  // 屏幕/窗口都是 DIP，页面缩放只影响一个系数，除掉就回到基准 CSS 坐标
  const x = (p.x - b.x) / zoom;
  const y = (p.y - b.y) / zoom;
  if (x < 0 || y < 0) return false;
  const cx = Math.floor(x / coverage.cell);
  const cy = Math.floor(y / coverage.cell);
  if (cx >= coverage.cols || cy >= coverage.rows) return false;
  return coverage.grid[cy * coverage.cols + cx] === '1';
}

function pollCursor() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (!mainWindow.isVisible()) { hovering = null; return; }
  const hit = cursorHitsPet();
  if (hit === hovering) return;
  hovering = hit;
  mainWindow.setIgnoreMouseEvents(!hit);
  sendToRenderer('hover:changed', hit);
}

// ------------------------------------------------------------------ IPC
ipcMain.on('scene:changed', (_e, key) => {
  currentScene = key;
  refreshTray();
});

ipcMain.on('app:quit', () => quitApp());
ipcMain.on('app:hide', () => toggleVisible());

ipcMain.handle('win:bounds', () => {
  if (!mainWindow || mainWindow.isDestroyed()) return null;
  return mainWindow.getBounds();
});

ipcMain.on('win:resetPosition', () => {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const p = defaultPosition();
  const { width, height } = winSize();
  mainWindow.setBounds({ x: Math.round(p.x), y: Math.round(p.y), width, height });
  writeState({ ...readState(), x: Math.round(p.x), y: Math.round(p.y), zoom });
});

ipcMain.handle('zoom:get', () => zoom);
ipcMain.handle('zoom:set', (_e, z) => applyZoom(z, false));
ipcMain.handle('zoom:step', (_e, dir) => stepZoom(dir, false));
