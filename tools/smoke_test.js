'use strict';
/**
 * 冒烟测试：在真实的 Electron 渲染环境里加载界面，检查
 *   - 所有图片是否加载成功
 *   - 四个场景图片的热区掩码（hitmaps.js）是否被渲染层读到
 *   - 神像/香案/人物/香烟/UI 的实际盒模型是否符合预期版面
 *   - 命中判定的覆盖率（窗口里有多少面积会挡住桌面点击）
 *   - 有无渲染进程控制台报错
 * 用法： node_modules/.bin/electron tools/smoke_test.js
 */
const { app, BrowserWindow } = require('electron');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const W = 400, H = 460;      // 必须与 main.js BASE_W / BASE_H、styles.css --w/--h 一致
const errs = [];

app.disableHardwareAcceleration();

function log(...a) { console.log(...a); }

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: W,
    height: H,
    show: false,
    transparent: true,
    frame: false,
    webPreferences: {
      preload: path.join(ROOT, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  // Electron >= 30 用 (event, details)，旧版用 (event, level, message, line, sourceId)
  win.webContents.on('console-message', (...args) => {
    const d = args[1];
    let level, message, src, line;
    if (d && typeof d === 'object' && 'message' in d) {
      level = d.level; message = d.message; src = d.sourceId; line = d.lineNumber;
    } else {
      level = args[1]; message = args[2]; line = args[3]; src = args[4];
    }
    log(`[console:${level}] ${message}  (${src}:${line})`);
    const lv = typeof level === 'number' ? level : (level === 'error' ? 3 : level === 'warning' ? 2 : 0);
    if (lv >= 2) errs.push('console: ' + message);
  });
  win.webContents.on('preload-error', (_e, p, err) => {
    log('[preload-error]', p, err && err.message);
    errs.push('preload: ' + (err && err.message));
  });
  win.webContents.on('render-process-gone', (_e, d) => {
    log('[render-process-gone]', JSON.stringify(d));
    errs.push('render-process-gone');
  });
  win.webContents.on('did-fail-load', (_e, code, desc, url) => {
    log('[did-fail-load]', code, desc, url);
    errs.push('did-fail-load ' + code + ' ' + desc);
  });

  await win.loadFile(path.join(ROOT, 'index.html'));
  await new Promise((r) => setTimeout(r, 1800));

  const probe = `(() => {
    const box = (s) => { const el = document.querySelector(s); if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }; };

    // 命中覆盖率：整个窗口按 8px 网格采样，统计有多少点会拦住桌面点击
    let hit = 0, tot = 0;
    const grid = [];
    for (let y = 0; y < ${H}; y += 8) {
      let row = '';
      for (let x = 0; x < ${W}; x += 8) { tot++; const h = hitTest(x + 4, y + 4); if (h) hit++; row += h ? '#' : '.'; }
      grid.push(row);
    }
    const boxes = { god: box('#god'), altar: box('#altar'), person: box('#person'),
                    shadow: box('#shadow'), smoke: box('#smokeLayer'), badge: box('#badge'),
                    bar: box('#bar'), tools: box('#tools'), rank: box('#rank') };

    return {
      viewport: { w: document.documentElement.clientWidth, h: document.documentElement.clientHeight },
      hitmapCount: Object.keys(window.HITMAPS || {}).length,
      brokenImages: [...document.images].filter(i => i.complete && i.naturalWidth === 0).map(i => i.getAttribute('src')),
      natural: { person: [document.querySelector('#person').naturalWidth, document.querySelector('#person').naturalHeight] },
      boxes,
      chips: [...document.querySelectorAll('.chip')].map(c => c.textContent),
      merit: document.querySelector('#merit').textContent,
      rankName: document.querySelector('#rankName').textContent,
      zoomText: (document.querySelector('#zoomVal') || {}).textContent,
      accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
      coverage: { hit, tot, pct: +(100 * hit / tot).toFixed(1) },
      // 关键点位：面板必须可命中，透明处必须放行
      hitPanelBar: hitTest(30, 24),
      hitPanelTools: hitTest(${W} - 30, 24),
      hitPerson: hitTest(${Math.round(14 + 194 / 2)}, 340),
      hitGod: hitTest(248, 120),
      hitEmptyTL: hitTest(4, ${H - 4}),
      hitEmptyTR: hitTest(4, 200),
      grid,
    };
  })()`;

  const out = await win.webContents.executeJavaScript(probe);
  const grid = out.grid;
  delete out.grid;
  log('PROBE=' + JSON.stringify(out, null, 2));
  log('命中覆盖率图（# = 会拦住桌面点击，. = 鼠标穿透）:');
  grid.forEach((r, i) => log(String(i * 8).padStart(3, ' ') + ' ' + r));
  log('ERRORS=' + errs.length);
  app.exit(errs.length ? 1 : 0);
});
