'use strict';
/**
 * afterPack 钩子：在 Electron 可执行文件上写版本信息与图标。
 *
 * 为什么不用 electron-builder 内置的这一步？
 *   内置实现调用 rcedit 后只做"立即重试"，在 Windows 上刚写完的 200MB exe
 *   往往还处于杀软实时扫描/句柄未释放的状态，rcedit 会稳定报
 *   `Fatal error: Unable to commit changes`，导致整个打包失败。
 *   这里改成带间隔的重试，稳定得多。
 *
 * 配合 package.json 里的 "win.signAndEditExecutable": false 使用。
 */
const path = require('path');
const fs = require('fs');
const { execFileSync } = require('child_process');

function findRcedit() {
  const bases = [
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'electron-builder', 'Cache', 'winCodeSign'),
    process.env.APPDATA && path.join(process.env.APPDATA, 'electron-builder', 'Cache', 'winCodeSign'),
  ].filter(Boolean);
  for (const base of bases) {
    if (!fs.existsSync(base)) continue;
    for (const dir of fs.readdirSync(base)) {
      for (const exe of ['rcedit-x64.exe', 'rcedit-ia32.exe']) {
        const p = path.join(base, dir, exe);
        if (fs.existsSync(p)) return p;
      }
    }
  }
  return null;
}

/** 同步忙等：钩子本身是异步签名，但步骤顺序简单，忙等最不容易出意外 */
function sleepSync(ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) { /* busy wait */ }
}

exports.default = async function afterPack(context) {
  const { appOutDir, packager, electronPlatformName } = context;
  if (electronPlatformName !== 'win32') return;

  const info = packager.appInfo;
  const exe = path.join(appOutDir, info.productFilename + '.exe');
  if (!fs.existsSync(exe)) {
    console.log('[after_pack] 找不到可执行文件，跳过：' + exe);
    return;
  }

  const rcedit = findRcedit();
  if (!rcedit) {
    console.log('[after_pack] 未找到 rcedit，跳过 exe 元数据写入');
    return;
  }

  const icon = path.join(__dirname, '..', 'assets', 'icon.ico');
  const args = [
    exe,
    '--set-version-string', 'FileDescription', info.description || info.productName,
    '--set-version-string', 'ProductName', info.productName,
    '--set-version-string', 'CompanyName', info.companyName || info.productName,
    '--set-version-string', 'LegalCopyright', 'Copyright © ' + new Date().getFullYear() + ' ' + (info.companyName || info.productName),
    '--set-version-string', 'InternalName', info.productName,
    '--set-file-version', info.version,
    '--set-product-version', info.version,
  ];
  if (fs.existsSync(icon)) args.push('--set-icon', icon);

  let lastErr = null;
  for (let attempt = 1; attempt <= 12; attempt++) {
    try {
      execFileSync(rcedit, args, { cwd: appOutDir, stdio: 'pipe' });
      console.log(`[after_pack] 已写入版本信息与图标（第 ${attempt} 次尝试）`);
      return;
    } catch (e) {
      lastErr = e;
      const msg = (e.stderr && e.stderr.toString().trim()) || e.message;
      console.log(`[after_pack] rcedit 第 ${attempt} 次失败：${msg}`);
      sleepSync(1200);
    }
  }
  // 不抛出：即使元数据没写上，也要让打包继续产出可运行的 exe
  console.log('[after_pack] 警告：exe 元数据写入最终失败，' + (lastErr && lastErr.message));
};
