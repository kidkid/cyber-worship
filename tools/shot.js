'use strict';
/**
 * 真实渲染截图：用与 main.js 完全一致的窗口参数（含 zoomFactor）跑起来，
 * 分别抓「默认状态 / 悬停出面板 / 磕头第三帧」三张图，用于肉眼验收。
 * 透明度会被保留（PNG 带 alpha），配合 PIL 合成到浅色桌面背景上看。
 *
 * 用法： node_modules/.bin/electron tools/shot.js
 */
const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const os = require('os');
const fs = require('fs');

const ROOT = path.join(__dirname, '..');
const BASE_W = 400, BASE_H = 460;
const ZOOM = Number(process.env.CW_SHOT_ZOOM || 0.8);
const OUT = path.join(ROOT, '_preview');
fs.mkdirSync(OUT, { recursive: true });

const tmp = path.join(os.tmpdir(), 'cw-shot-' + Date.now());
fs.mkdirSync(tmp, { recursive: true });
app.setPath('userData', tmp);

// 渲染层启动会问主进程要缩放值，这里给个固定的
ipcMain.handle('zoom:get', () => ZOOM);
ipcMain.handle('zoom:set', () => ZOOM);
ipcMain.handle('zoom:step', () => ZOOM);

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: Math.round(BASE_W * ZOOM),
    height: Math.round(BASE_H * ZOOM),
    x: 40, y: 40,
    show: true,
    transparent: true,
    frame: false,
    hasShadow: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(ROOT, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: false,
      backgroundThrottling: false,
      zoomFactor: ZOOM,
    },
  });
  const js = (s) => win.webContents.executeJavaScript(s);

  await win.loadFile(path.join(ROOT, 'index.html'));
  await wait(2000);

  const shot = async (name) => {
    const img = await win.webContents.capturePage();
    const f = path.join(OUT, 'shot_' + name + '.png');
    fs.writeFileSync(f, img.toPNG());
    console.log('saved', f, img.getSize());
  };

  console.log('zoomFactor =', win.webContents.getZoomFactor());

  // 1) 默认状态（面板隐藏）
  await shot('idle');

  // 2) 悬停：面板浮出
  await js(`document.querySelector('#stage').classList.add('hover-ui')`);
  await wait(400);
  await shot('hover');
  await js(`document.querySelector('#stage').classList.remove('hover-ui')`);

  // 3) 磕头第三帧（整个趴下，检查与供桌的关系）
  await js(`setFrame(3)`);
  await wait(500);
  await shot('frame3');

  // 4) 切到考研场景看看
  await js(`applyScene('study')`);
  await wait(900);
  await js(`setFrame(2)`);
  await wait(400);
  await shot('study_frame2');

  app.exit(0);
});
