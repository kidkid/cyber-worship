# -*- coding: utf-8 -*-
"""
穿透恢复时间线探针。

背景：主进程每 40ms 轮询系统光标，按渲染层推来的命中网格决定窗口是否鼠标穿透。
"移回可见像素必须能恢复可交互"是这个方案的命门（早先的 forward 转发方案就是死在这）。
本探针把真实光标依次挪到若干 CSS 坐标，逐 50ms 采样 WS_EX_TRANSPARENT，
打印每次的状态翻转时间线 —— 用来区分"真·恢复不了"和"只是恢复得慢 / 测试等待不够"。

用法： python tools/recover_probe.py [dev|exe] [--no-move]
      --no-move  不把窗口归位到 (300,200)，保持默认右下角位置（对照用）
"""
import ctypes
import ctypes.wintypes as wt
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV_EXE = os.path.join(ROOT, "node_modules", "electron", "dist", "electron.exe")


def find_pkg_exe():
    pats = [os.path.join(ROOT, "dist*", "赛博朝拜_免安装版.exe"),
            os.path.join(os.path.dirname(ROOT), "赛博朝拜_免安装版.exe")]
    cands = []
    for p in pats:
        cands += glob.glob(p)
    cands = [p for p in cands if os.path.isfile(p)]
    if not cands:
        raise SystemExit("!! 找不到打包产物")
    return max(cands, key=os.path.getmtime)
PKG_EXE = find_pkg_exe()
TMP_UD = os.path.join(os.environ.get("TEMP", "."), "cw-recover-probe")
ZOOM = 0.8
BASE_W, BASE_H = 400, 460

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


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


def find_win():
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
        if r.right - r.left > 100 and r.bottom - r.top > 100:
            rows.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return rows[0] if rows else None


def rect_of(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def cursor():
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def set_cursor_keep(x, y, tries=6):
    """把光标钉在目标点。

    ⚠️ 这个探针跑在用户正在使用的桌面上：用户动一下鼠标就把光标抢走了，
    实测会出现"本来命中的点突然变穿透"的假象（其实就是光标飘到别处去了）。
    所以既要在移动时重试，也要在采样循环里持续校正。
    """
    for _ in range(tries):
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.1)
        if cursor() == (int(x), int(y)):
            return True
    return False


def transparent(hwnd):
    return bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TRANSPARENT)


POINTS = [
    ("神像中上 (248,110)", 248, 110, False),
    ("透明空白 (4,300)", 4, 300, True),
    ("人物下摆 (70,380)", 70, 380, False),
    ("人物躯干 (100,350)", 100, 350, False),
    ("神像下部 (248,150)", 248, 150, False),
    ("再次透明 (2,450)", 2, 450, True),
    ("人物膝盖 (150,400)", 150, 400, False),
    ("场景标签 (91,25)", 91, 25, False),
    ("总功德牌 (330,430)", 330, 430, False),
]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    no_move = "--no-move" in sys.argv
    mode = args[0] if args else "exe"
    for n in ("electron.exe", "赛博朝拜_免安装版.exe"):
        subprocess.run(["taskkill", "/F", "/IM", n], capture_output=True)
    time.sleep(1.5)
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    subprocess.run(["cmd", "/c", "rmdir", "/S", "/Q", TMP_UD], capture_output=True)
    os.makedirs(TMP_UD, exist_ok=True)
    if mode == "exe":
        cmd, cwd, wait = [PKG_EXE, "--user-data-dir=" + TMP_UD], os.path.dirname(PKG_EXE), 22
    else:
        cmd, cwd, wait = [DEV_EXE, ".", "--user-data-dir=" + TMP_UD], ROOT, 15
    print("目标:", cmd[0])
    subprocess.Popen(cmd, cwd=cwd, env=env)
    time.sleep(wait)

    hwnd = find_win()
    if not hwnd:
        print("!! 没找到宠物窗口")
        return 1
    print("初始窗口 rect =", rect_of(hwnd))

    if not no_move:
        SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
        user32.SetWindowPos(hwnd, 0, 300, 200, int(BASE_W * ZOOM), int(BASE_H * ZOOM),
                            SWP_NOZORDER | SWP_NOACTIVATE)
        time.sleep(1.2)
        print("SetWindowPos 归位后 rect =", rect_of(hwnd))

    ox, oy = cursor()

    bad = 0
    try:
        for name, cx, cy, want in POINTS:
            l, t, _, _ = rect_of(hwnd)
            sx, sy = l + int(cx * ZOOM), t + int(cy * ZOOM)
            landed = set_cursor_keep(sx, sy)
            t0 = time.time()
            tl = []
            last = transparent(hwnd)
            tl.append("%.2f%s" % (0.0, "T" if last else "I"))
            while time.time() - t0 < 3.0:
                time.sleep(0.05)
                # 光标被用户抢走就立刻钉回来，并记一笔（免得把假象当成产品缺陷）
                if cursor() != (sx, sy):
                    tl.append("飘")
                    set_cursor_keep(sx, sy)
                cur = transparent(hwnd)
                if cur != last:
                    tl.append("%.2f%s" % (time.time() - t0, "T" if cur else "I"))
                    last = cur
            ok = landed and (last == want)
            if not ok:
                bad += 1
            print("%-22s 屏幕(%4d,%4d) 期望=%-9s 实际=%-9s %s   时间线: %s"
                  % (name, sx, sy, "穿透" if want else "可交互",
                     "穿透" if last else "可交互",
                     "OK  " if ok else "BAD ", " ".join(tl)))
    finally:
        user32.SetCursorPos(ox, oy)

    print("\n不符合预期的点：%d / %d" % (bad, len(POINTS)))
    subprocess.run(["taskkill", "/F", "/IM", "electron.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "赛博朝拜_免安装版.exe"], capture_output=True)
    return 1 if bad else 0


sys.exit(main())
