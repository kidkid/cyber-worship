'use strict';
/**
 * 四场景构图核对：把 4 个场景各抓「跪直（frame1）」和「趴下（frame3）」两张，
 * 拼成一张对照图，用来肉眼确认「人物是否朝右对着香案/神位」。
 * 透明像素会合成到浅灰背景上，便于观察。
 *
 * 用法： node_modules/.bin/electron tools/scene_sheet.js
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

const tmp = path.join(os.tmpdir(), 'cw-scene-' + Date.now());
fs.mkdirSync(tmp, { recursive: true });
app.setPath('userData', tmp);

ipcMain.handle('zoom:get', () => ZOOM);
ipcMain.handle('zoom:set', () => ZOOM);
ipcMain.handle('zoom:step', () => ZOOM);

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const SCENES = ['wealth', 'stock', 'health', 'study'];
const NAMES = { wealth: '财运', stock: '涨停', health: '健康', study: '考研' };

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

  const tiles = [];
  for (const s of SCENES) {
    await js(`applyScene('${s}')`);
    // 立刻抓一张：此时场景提示气泡正在显示，用来确认气泡没压在小人头上
    await wait(250);
    tiles.push({ scene: s, frame: 0, img: await win.webContents.capturePage() });
    // 切场景会弹 1.5s 的提示气泡，等它消失再截图，否则会误判构图
    await wait(1900);
    await js(`setFrame(1)`);
    await wait(400);
    tiles.push({ scene: s, frame: 1, img: await win.webContents.capturePage() });
    await js(`setFrame(3)`);
    await wait(400);
    tiles.push({ scene: s, frame: 3, img: await win.webContents.capturePage() });
    console.log('captured', s);
  }

  // 落盘单张
  for (const t of tiles) {
    const f = path.join(OUT, `scene_${t.scene}_f${t.frame}.png`);
    fs.writeFileSync(f, t.img.toPNG());
  }
  console.log('saved', tiles.length, 'tiles to', OUT);

  // 拼图：PIL 负责合成（这里把图先写出去，由调用方拼）
  app.exit(0);
});
