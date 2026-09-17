# 赛博朝拜 · Cyber Worship

> 桌面电子磕头神器 —— 一个用 Electron 写的透明置顶桌面宠物。点小人磕头、上香，攒功德、升境界。

![License](https://img.shields.io/badge/license-MIT-yellow.svg)
![Platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D4.svg)
![Electron](https://img.shields.io/badge/Electron-38-47848F.svg?logo=electron&logoColor=white)
![Dependencies](https://img.shields.io/badge/runtime%20deps-0-brightgreen.svg)

<p align="center">
  <img src="docs/images/hero.png" width="240" alt="赛博朝拜">
</p>

<p align="center">
  <img src="docs/images/scenes.png" width="100%" alt="四种场景：财运 · 涨停 · 健康 · 考研">
</p>

---

## 这是什么

一个跑在 Windows 桌面上的透明无边框小挂件。屏幕角落里供着一尊神、一张香案，前面跪着个会磕头的小人。
点一下小人就磕一个头，功德 +1；点「上香」一次 +10。功德攒够了自动升境界：凡人 → 香客 → 居士 → 真人 → 半仙 → 大罗金仙。

四种场景可切：**财运 · 财神爷**、**涨停 · 暴富牛神**、**健康 · 长寿星**、**考研 · 文昌帝君**。

## 特性

- **真·透明窗口**：无边框、置顶、无任务栏图标，只占据它自己那块画面
- **鼠标穿透**：宠物身上的透明像素不吃鼠标事件，不挡你干活
- **四种场景**：神像 + 香案 + 配色整组切换，带切换提示气泡
- **功德系统**：磕头 +1 / 上香 +10，境界升级有特效与提示，本地存档
- **大小可调**：50% ~ 140% 共十档，默认 80%，缩放锚定右下角不跑位
- **可拖可藏**：任意位置拖动，老板键 `Ctrl + Alt + H` 一键隐藏
- **托盘常驻**：托盘菜单切换场景 / 调大小 / 显示隐藏 / 退出
- **拖动位置与功德持久化**：下次启动还在原地

## 快速开始

```bash
git clone https://github.com/kidkid/cyber-worship.git
cd cyber-worship
npm install
npm start
```

> 国内网络 `npm install` 卡在下载 Electron 时，可以先设镜像：
> ```bash
> npm config set registry https://registry.npmmirror.com
> npm config set electron_mirror https://npmmirror.com/mirrors/electron/
> npm config set electron_builder_binaries_mirror https://npmmirror.com/mirrors/electron-builder-binaries/
> ```

### 打包成免安装 exe

```bash
npm run build
```

`electron-builder` 会输出 `dist/赛博朝拜_免安装版.exe`。产物是 portable 单文件，双击即用，不需要安装。

打包产物已经关闭了 `signAndEditExecutable`（避免无签名环境下写图标失败），图标由 `tools/after_pack.js` 这个 afterPack 钩子写入。

## 怎么玩

| 操作 | 效果 |
| --- | --- |
| 点小人 | 磕一个头，功德 +1 |
| `空格` | 同上 |
| 「上香 +10」按钮 | 功德 +10 |
| 点顶部场景标签 | 换场景（财运 / 涨停 / 健康 / 考研） |
| 拖神像 / 香案 / 功德牌 | 挪动宠物位置 |
| 右键 | 菜单：切场景 / 上香 / 调大小 / 隐藏 / 退出 |
| `Ctrl + 滚轮` | 缩放宠物（50% ~ 140%） |
| `Ctrl` + `+` / `-` | 同上 |
| `Ctrl + Alt + H` | 老板键：隐藏 / 显示 |
| 托盘图标单击 / 双击 | 显示 / 隐藏 |

所有按钮和标签栏平时是半透明的，鼠标移到宠物上会浮出来；它们始终可点，不需要先悬停。

## 技术要点

做这类透明桌面挂件有几个坑，这里踩过一遍，记下来给后来人：

### 1. 鼠标穿透不要用 `setIgnoreMouseEvents(true, { forward: true })`

直觉做法是在渲染层监听 `mousemove`，命中不透明像素就 `setIgnoreMouseEvents(false)`，否则
`setIgnoreMouseEvents(true, { forward: true })` 靠转发事件维持恢复能力。

**实测这套在透明窗口下会失效**：一旦进入穿透状态，即使把光标移到完全不透明的像素上也恢复不过来
（用 `GetWindowLongW(GWL_EXSTYLE) & WS_EX_TRANSPARENT` 检查，状态始终为真）。

本项目改用**主进程轮询**：

1. 渲染层预计算一张低分辨率「命中网格」（`CELL = 4`，按 alpha 掩码 + 面板矩形），通过 IPC 推给主进程
2. 主进程每 40ms `screen.getCursorScreenPoint()`，把屏幕坐标换算成网格坐标查表
3. 命中就 `setIgnoreMouseEvents(false)`，不命中就 `true`

实测恢复延迟 **0.05 秒**，稳定可靠。网格用的是 CSS 像素坐标，所以和窗口缩放互不干扰。

### 2. 缩放要用页面缩放，不要用 CSS `transform: scale()`

`transform: scale()` 会把 `getBoundingClientRect()` 的坐标系也一起缩放，导致命中判定和拖拽区错位。
这里用 `webContents.setZoomFactor()` + 同步修改窗口物理尺寸（`尺寸 = 基准 × 缩放比`），
CSS 像素坐标系保持不变，拖拽和命中都不用改。缩放时锚定右下角，调小之后仍然贴着原来那个角落。

### 3. 窗口尺寸是「基准尺寸 × 缩放比」

基准版面 `400 × 460`。改版面尺寸时要同步 5 个地方，否则会出现「多出一块可点空白区」或者
「宠物被裁掉一角」：

| 文件 | 内容 |
| --- | --- |
| `main.js` | `BASE_W` / `BASE_H` / `ZOOM_STEPS` / `DEFAULT_ZOOM` |
| `styles.css` | `--w` / `--h` 以及各元素定位变量 |
| `renderer.js` | 命中判定的 `BASE_W` / `BASE_H` / `CELL` |
| `tools/layout_mock.py` | 同名版面常量（用于离线出对照图） |
| `index.html` | 只放结构，不写死尺寸 |

### 4. 面板要 `pointer-events: auto`，哪怕 `opacity: 0`

如果按钮栏设成 `pointer-events: none` + 悬停才显示，而命中判定又依赖悬停，就会互锁——
永远点不到场景标签。让它们始终 `pointer-events: auto`，只是视觉上透明。

### 5. 位置存档要夹取回可见区域

用户换了分辨率、拔了外接屏之后，存档里的窗口坐标可能落在屏幕外，宠物就彻底消失且摸不到。
启动时会调用 `screen.getDisplayNearestPoint()` 把坐标夹回最近显示器的工作区。

## 项目结构

```
.
├── main.js            # 主进程：窗口 / 托盘 / 全局快捷键 / 穿透轮询 / 缩放 / 位置存档
├── preload.js         # contextBridge 桥接
├── renderer.js        # 渲染层：场景、动画、功德、命中网格、面板交互
├── index.html         # 结构（尺寸全部走 CSS 变量）
├── styles.css         # 版面与主题
├── hitmaps.js         # 由素材 alpha 通道生成的低分辨率命中掩码
├── assets/
│   ├── icon.ico / icon.png
│   └── images/        # 神像 / 香案 / 磕头三帧 / 香烟 / 金币
├── docs/images/       # README 配图
└── tools/             # 素材处理、版面校验、自动化测试
```

## 自动化测试

测试脚本在 `tools/` 下，分三层：

```bash
# 1) 界面冒烟：加载页面，检查 DOM、素材、命中覆盖率，收集控制台报错
node_modules/electron/dist/electron.exe tools/smoke_test.js

# 2) 功能测试：用合成鼠标事件跑场景切换、缩放、命中判定
node_modules/electron/dist/electron.exe tools/func_test.js

# 3) 端到端：真实系统光标 + 真实窗口（穿透恢复 / 拖拽 / 真点击切场景）
python tools/interact_test.py dev     # 跑源码版本；传 exe 则跑打包产物
python tools/onscreen_test.py dev     # 窗口位置夹取（越界 / 屏外 / 副屏）
```

另有几个探针用于排查特定问题：

| 脚本 | 用途 |
| --- | --- |
| `tools/recover_probe.py` | 穿透状态时间线：光标在若干关键点之间移动，输出每次状态翻转的耗时 |
| `tools/passthrough_probe.py` | 打印主进程实际判定出的整张「可点区域」地图 |
| `tools/dpi_probe.py` | 显示器 / DPI / 虚拟屏边界诊断 |
| `tools/clamp_probe.js` | 打印 `workArea`、多显示器边界，验证位置夹取 |
| `tools/layout_mock.py` | 离线合成版面对照图，改版面时先在这里看效果 |
| `tools/scene_sheet.js` / `tools/shot.js` | 批量抓四场景截图 / 单帧截图 |

> **写这类测试要注意两件事**（都是真实踩过的）：
> 1. **多显示器**：`GetSystemMetrics(0/1)` 只返回主屏尺寸。窗口落在副屏上时，
>    「是否在屏幕内」的判定会误报。用 `EnumDisplayMonitors` + `GetMonitorInfo`，或直接查虚拟屏边界（76~79 号指标）。
> 2. **测试跑在用户正在用的桌面上**：模拟光标会被用户的真实鼠标抢走（落点需要用 `GetCursorPos` 回读校验），
>    透明窗口截图会混入背后的桌面内容（同一场景两次截图可能差 26%~65% 像素）。
>    断言要基于「相对变化率 + 环境噪声自校准」，不要写死绝对阈值。

## 素材

`assets/images/` 里的神像、香案、磕头三帧等图像，是用 AI 生成后经 `tools/prepare_assets.py`（抠底/切帧）
和 `tools/optimize_assets.py`（压缩）处理得到的。`hitmaps.js` 由 `tools/measure_assets.py` 从 alpha 通道生成。

## 环境

- Windows 10 / 11
- Node.js 18+
- Electron 38 / electron-builder 25

> 本项目只针对 Windows 做了适配（窗口穿透、托盘图标、portable 打包都按 Windows 来）。
> 窗口逻辑本身是跨平台的，想跑在 macOS / Linux 上需要改穿透与打包部分。

## License

[MIT](LICENSE)
