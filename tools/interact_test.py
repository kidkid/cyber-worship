# -*- coding: utf-8 -*-
"""
端到端交互测试（真实系统光标 + 真实主进程）：
  1. 光标移到神像上      -> 窗口必须恢复"可交互"（WS_EX_TRANSPARENT 清除）
  2. 光标移到透明空白处  -> 窗口必须变成"鼠标穿透"
  3. 再移回人物身上      -> 必须能恢复可交互
     （第 3 步是回归重点：早先用 setIgnoreMouseEvents(forward) + 转发 mousemove
       的方案，一旦进入穿透就再也回不来，整个宠物点不动、场景也切不了）
  4. 在神像上按住拖动    -> 窗口应跟着移动（验证页面缩放下拖拽区没错位）
  5. 在"涨停"标签上真点  -> 神像区域的平均颜色应发生剧变（场景真的切了）

用法： python tools/interact_test.py [dev|exe]
"""
import ctypes
import ctypes.wintypes as wt
import glob
import os
import subprocess
import sys
import time

from PIL import ImageGrab

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV_EXE = os.path.join(ROOT, "node_modules", "electron", "dist", "electron.exe")


def find_pkg_exe():
    """挑最新打出来的免安装版 exe：dist* 目录都可能存在（历史产物不清），取修改时间最新的那个。"""
    pats = [
        os.path.join(ROOT, "dist*", "赛博朝拜_免安装版.exe"),
        os.path.join(os.path.dirname(ROOT), "赛博朝拜_免安装版.exe"),
    ]
    cands = []
    for p in pats:
        cands += glob.glob(p)
    cands = [p for p in cands if os.path.isfile(p)]
    if not cands:
        raise SystemExit("!! 找不到任何打包产物，请先跑 electron-builder")
    return max(cands, key=os.path.getmtime)
PKG_EXE = find_pkg_exe()
TMP_UD = os.path.join(os.environ.get("TEMP", "."), "cw-interact-test")
ZOOM = 0.8          # main.js DEFAULT_ZOOM
BASE_W, BASE_H = 400, 460

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

fails = []


def check(cond, label, extra=""):
    print(("PASS  " if cond else "FAIL  ") + label + (("  -> " + str(extra)) if extra != "" else ""))
    if not cond:
        fails.append(label)


def proc_name(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "?"
    try:
        size = wt.DWORD(1024)
        b = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, b, ctypes.byref(size)):
            return os.path.basename(b.value)
    finally:
        kernel32.CloseHandle(h)
    return "?"


def top_windows():
    rows = []

    def cb(hwnd, _l):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        nm = proc_name(p.value).lower()
        if not any(k in nm for k in ("electron", "cyber-worship", "赛博朝拜")):
            return True
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
            return True
        r = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        if w > 100 and h > 100:
            rows.append((w * h, hwnd, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    rows.sort(reverse=True)
    return rows


def rect_of(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def transparent(hwnd):
    return bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TRANSPARENT)


def cursor():
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def move(x, y, settle=0.35):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(settle)


def move_checked(x, y, tries=6):
    """把光标移到目标点，并确认真的落上去了。

    测试是跑在**用户正在使用的桌面上**的：用户自己动一下鼠标，SetCursorPos 的结果就被抢走，
    光标落点跟预期差几十上百像素，后面的断言全都会莫名其妙地失败。
    所以要重试 + 回读落点；拖拽断言也不能拿"预期位移"当基准，得拿"光标实际位移"当基准。
    """
    for _ in range(tries):
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.12)
        if cursor() == (int(x), int(y)):
            time.sleep(0.2)
            return cursor() == (int(x), int(y))
    return False


def wait_state(hwnd, want_transparent, timeout=4.0):
    """等窗口的穿透状态变成期望值，返回实际耗时（秒）；超时返回 -1。
    主进程是 40ms 轮询一次，4s = 100 个轮询周期，足够。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if transparent(hwnd) == want_transparent:
            return time.time() - t0
        time.sleep(0.05)
    return -1


def mouse(flag):
    user32.mouse_event(flag, 0, 0, 0, 0)


LEFTDOWN, LEFTUP = 0x0002, 0x0004


def grab_css_box(hwnd, box_css):
    """按「渲染层 CSS 坐标」截取窗口内的一块区域（换算到屏幕绝对坐标）"""
    l, t, _, _ = rect_of(hwnd)
    x0, y0, x1, y1 = box_css
    box = (l + int(x0 * ZOOM), t + int(y0 * ZOOM), l + int(x1 * ZOOM), t + int(y1 * ZOOM))
    return ImageGrab.grab(bbox=box, all_screens=True).convert("RGB")


# 神像所在的 CSS 区域（居中于 x=248，底边 y=190）—— 不含人物，人物在 y>=220
GOD_BOX = (173, 35, 323, 190)


def mean_rgb(im):
    px = list(im.getdata())
    n = len(px)
    return tuple(sum(c[i] for c in px) // n for i in range(3))


def changed_ratio(im0, im1, thr=24):
    """两张同尺寸截图里"颜色明显变了"的像素占比 —— 比平均色稳得多：
    平均色会把透明区域的背景色一起平均进去，两个场景的均值可能只差一点点。"""
    p0, p1 = list(im0.getdata()), list(im1.getdata())
    n = min(len(p0), len(p1))
    if n == 0:
        return 0.0
    hit = 0
    for i in range(n):
        a, b = p0[i], p1[i]
        if abs(a[0] - b[0]) > thr or abs(a[1] - b[1]) > thr or abs(a[2] - b[2]) > thr:
            hit += 1
    return hit / n


def god_mean(hwnd):
    """神像区域的屏幕平均色（保留给旧断言用）"""
    return mean_rgb(grab_css_box(hwnd, GOD_BOX))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "dev"
    for n in ("electron.exe", "赛博朝拜_免安装版.exe"):
        subprocess.run(["taskkill", "/F", "/IM", n], capture_output=True)
    time.sleep(1.5)
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    os.makedirs(TMP_UD, exist_ok=True)

    if mode == "exe":
        cmd = [PKG_EXE, "--user-data-dir=" + TMP_UD]
        cwd = os.path.dirname(PKG_EXE)
        print("启动打包好的 exe:", PKG_EXE)
        boot_wait = 22
    else:
        cmd = [DEV_EXE, ".", "--user-data-dir=" + TMP_UD]
        cwd = ROOT
        print("启动开发模式（临时 userData）...")
        boot_wait = 15
    # 清掉上一次留下的窗口位置存档：
    # 拖动测试每次都会把窗口右移下移 (+60,+40) 并存进 window-state.json，
    # 不清的话跑几轮之后窗口就漂到屏幕外了，后面的坐标断言全都会莫名其妙地失败。
    state_file = os.path.join(TMP_UD, "window-state.json")
    if os.path.exists(state_file):
        os.remove(state_file)
        print("已清除上一次的窗口位置存档")
    subprocess.Popen(cmd, cwd=cwd, env=env)
    time.sleep(boot_wait)

    ws = top_windows()
    if not ws:
        print("!! 没找到宠物窗口")
        return 1
    _, hwnd, rect = ws[0]
    l, t, r, b = rect
    print("宠物窗口 rect =", rect, "尺寸 =", (r - l, b - t),
          "（期望 %dx%d）" % (BASE_W * ZOOM, BASE_H * ZOOM))
    check((r - l, b - t) == (BASE_W * ZOOM, BASE_H * ZOOM), "默认窗口尺寸 = 80% 档位", (r - l, b - t))

    # 窗口必须完整落在屏幕内，否则后面的 SetCursorPos 会被系统夹到屏幕边界，
    # 光标实际落点就跟预期差一大截。
    # ⚠️ 用 GetSystemMetrics(0/1) 只能拿到主屏尺寸 —— 本机是双显示器（副屏在主屏右侧），
    #    必须按"虚拟屏"边界判定，否则窗口落在副屏上会误报失败。
    vx = user32.GetSystemMetrics(76)      # SM_XVIRTUALSCREEN
    vy = user32.GetSystemMetrics(77)      # SM_YVIRTUALSCREEN
    vw = user32.GetSystemMetrics(78)      # SM_CXVIRTUALSCREEN
    vh = user32.GetSystemMetrics(79)      # SM_CYVIRTUALSCREEN
    check(l >= vx and t >= vy and r <= vx + vw and b <= vy + vh,
          "窗口完整落在虚拟屏内（否则光标到不了指定位置）",
          {"rect": rect, "virtual": (vx, vy, vx + vw, vy + vh)})

    # 把窗口摆到主屏上的一处确定位置，再开始跑交互断言。
    # 存档位置可能带出副屏/屏幕边角的坐标，会让下面的"局部坐标 x 缩放 -> 屏幕坐标"
    # 换算落在一个跨屏的尴尬位置；先归位，测试才可复现。
    SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
    user32.SetWindowPos(hwnd, 0, 300, 200, int(BASE_W * ZOOM), int(BASE_H * ZOOM),
                        SWP_NOZORDER | SWP_NOACTIVATE)
    time.sleep(1.0)
    rect = rect_of(hwnd)
    l, t, r, b = rect
    print("归位后窗口 rect =", rect)

    ox, oy = cursor()
    try:
        def css(cx, cy):
            return l + int(cx * ZOOM), t + int(cy * ZOOM)

        def step(label, cx, cy, want_transparent):
            """移动到某个 CSS 坐标，等穿透状态到位，返回是否成功"""
            sx, sy = css(cx, cy)
            landed = move_checked(sx, sy)
            dt = wait_state(hwnd, want_transparent)
            ok = landed and dt >= 0
            print("%s  %s  css=(%d,%d) 屏幕=(%d,%d) 落点=%s 期望=%s 耗时=%s" % (
                "PASS" if ok else "FAIL", label, cx, cy, sx, sy,
                cursor(), "穿透" if want_transparent else "可交互",
                ("%.2fs" % dt) if dt >= 0 else "超时"))
            if not landed:
                print("       ↑ 光标没落到目标点！窗口 rect=%s" % (rect_of(hwnd),))
            if not ok:
                fails.append(label)
            return ok

        # ---- 1. 移到神像上 -> 可交互
        step("光标在神像上 -> 窗口可交互（不穿透）", 248, 110, False)

        # ---- 2. 移到透明空白处 -> 穿透
        step("光标在透明区域 -> 窗口鼠标穿透", 4, 300, True)

        # ---- 3. 再移回人物身上 -> 必须恢复可交互（回归重点）
        step("光标移回人物身上 -> 恢复可交互（回归点）", 70, 380, False)

        step("光标在神像下部 -> 保持可交互", 248, 150, False)

        # ---- 4. 拖动神像 -> 窗口跟着走（必须先从可交互状态起步）
        if transparent(hwnd):
            check(False, "在神像上拖动 -> 窗口跟着移动", "起点仍是穿透状态，已跳过以免误拖桌面")
        else:
            gx, gy = css(248, 110)
            before = rect_of(hwnd)
            move_checked(gx, gy)
            c0 = cursor()
            mouse(LEFTDOWN)
            time.sleep(0.25)
            for i in range(1, 9):
                user32.SetCursorPos(int(c0[0] + 60 * i / 8), int(c0[1] + 40 * i / 8))
                time.sleep(0.06)
            time.sleep(0.25)
            mouse(LEFTUP)
            time.sleep(1.0)
            c1 = cursor()
            after = rect_of(hwnd)
            # 拖拽是 CSS `-webkit-app-region: drag`（Chromium 自己实现）：
            # 起拖有几十毫秒的判定延迟，所以窗口位移会比光标位移略小一点点
            # （实测 60px 拖出 53px，长期如此，不是 bug）。这里只要求
            # "方向一致 + 量级接近 + 确实动了"，不追求像素级相等。
            wdx, wdy = after[0] - before[0], after[1] - before[1]
            cdx, cdy = c1[0] - c0[0], c1[1] - c0[1]
            same_dir = (wdx == 0 or cdx == 0 or (wdx > 0) == (cdx > 0)) and \
                       (wdy == 0 or cdy == 0 or (wdy > 0) == (cdy > 0))
            check(same_dir and abs(cdx) + abs(cdy) > 30
                  and abs(wdx - cdx) <= 12 and abs(wdy - cdy) <= 12,
                  "在神像上拖动 -> 窗口跟着移动",
                  {"窗口位移": (wdx, wdy), "光标位移": (cdx, cdy)})
            l, t = after[0], after[1]

        # ---- 5. 真点"涨停"标签 -> 神像区域应该明显变样
        #
        # ⚠️ 测试跑在用户正在使用的桌面上：宠物窗口是透明的，截到的是"宠物 + 背后桌面"的合成图，
        #    用户切个窗口、滚个页面，同一场景两次截图能差 60%+ 像素。
        #    所以判定不能写绝对阈值，要先量一遍"环境噪声"（同场景前后两次截图的差异），
        #    再要求"切换带来的差异显著大于环境噪声"。
        g0 = grab_css_box(hwnd, GOD_BOX)
        time.sleep(1.2)
        g0b = grab_css_box(hwnd, GOD_BOX)
        ambient = changed_ratio(g0, g0b)
        print("     环境噪声基线（同场景两次截图差异占比）= %.3f" % ambient)

        cx, cy = l + int(91 * ZOOM), t + int(25 * ZOOM)     # 第二个标签"涨停"
        move_checked(cx, cy)
        mouse(LEFTDOWN); time.sleep(0.08); mouse(LEFTUP)
        time.sleep(1.2)
        g1 = grab_css_box(hwnd, GOD_BOX)
        r01 = changed_ratio(g0, g1)
        need = max(0.20, ambient + 0.15)
        check(r01 > need, "真鼠标点击'涨停'标签 -> 神像换成了另一个场景",
              {"变化像素占比": round(r01, 3), "阈值": round(need, 3),
               "前均色": mean_rgb(g0), "后均色": mean_rgb(g1)})

        # 再点"财运" -> 换回来
        move_checked(l + int(30 * ZOOM), t + int(25 * ZOOM))
        mouse(LEFTDOWN); time.sleep(0.08); mouse(LEFTUP)
        time.sleep(1.2)
        g2 = grab_css_box(hwnd, GOD_BOX)
        r12 = changed_ratio(g1, g2)
        check(r12 > need, "再点'财运'标签 -> 又切回来了",
              {"变化像素占比": round(r12, 3), "阈值": round(need, 3),
               "中均色": mean_rgb(g1), "后均色": mean_rgb(g2)})

        # 闭环：回切后的画面应该更接近"最初那一版"，而不是更接近"涨停那一版"
        m0, m1, m2 = mean_rgb(g0), mean_rgb(g1), mean_rgb(g2)
        d02 = sum(abs(a - b) for a, b in zip(m0, m2))
        d12 = sum(abs(a - b) for a, b in zip(m1, m2))
        check(d02 < d12, "切回后更接近最初的画面（说明切回的是同一套场景）",
              {"|初-回|": d02, "|涨停-回|": d12, "均色": (m0, m1, m2)})
    finally:
        user32.SetCursorPos(ox, oy)

    subprocess.run(["taskkill", "/F", "/IM", "electron.exe"], capture_output=True)
    print("FAILS=%d" % len(fails))
    print("ALL PASS" if not fails else "FAILED: " + " | ".join(fails))
    return 1 if fails else 0


sys.exit(main())
