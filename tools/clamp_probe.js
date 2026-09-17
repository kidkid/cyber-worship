// 探针：打印 Electron 主进程看到的显示器 / 工作区，并复算 clampToWorkArea 的结果。
// 用法： env -u ELECTRON_RUN_AS_NODE ./node_modules/electron/dist/electron.exe tools/clamp_probe.js
const { app, screen } = require('electron');

const BASE_W = 400, BASE_H = 460;

function winSize(z) { return { width: Math.round(BASE_W * z), height: Math.round(BASE_H * z) }; }

function clampToWorkArea(x, y, w, h) {
  const d = screen.getDisplayMatching({ x: Math.round(x), y: Math.round(y), width: w, height: h });
  const wa = d.workArea;
  return {
    x: Math.round(Math.min(Math.max(x, wa.x), Math.max(wa.x, wa.x + wa.width - w))),
    y: Math.round(Math.min(Math.max(y, wa.y), Math.max(wa.y, wa.y + wa.height - h))),
    wa,
  };
}

app.whenReady().then(() => {
  const z = 0.8;
  const { width, height } = winSize(z);
  console.log('scaleFactor (primary) =', screen.getPrimaryDisplay().scaleFactor);
  console.log('winSize(0.8) =', width, 'x', height);
  for (const d of screen.getAllDisplays()) {
    console.log('display', d.id,
      'bounds=', JSON.stringify(d.bounds),
      'workArea=', JSON.stringify(d.workArea),
      'scale=', d.scaleFactor);
  }
  for (const [name, s] of [
    ['右下越界', { x: 1800, y: 900 }],
    ['左上负坐标', { x: -900, y: -600 }],
    ['屏幕内正常', { x: 300, y: 200 }],
  ]) {
    const r = clampToWorkArea(s.x, s.y, width, height);
    const d = screen.getDisplayMatching({ x: s.x, y: s.y, width, height });
    console.log(`\n[${name}] 存档=(${s.x},${s.y})  ->  clamp=(${r.x},${r.y})`);
    console.log(`   getDisplayMatching 命中 display=${d.id}  workArea=${JSON.stringify(d.workArea)}  bounds=${JSON.stringify(d.bounds)}`);
  }
  app.quit();
});

app.on('window-all-closed', () => app.quit());
