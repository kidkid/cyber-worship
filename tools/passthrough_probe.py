# -*- coding: utf-8 -*-
"""
穿透区域探针：直接读主进程判定出来的"可点/穿透"结果。

做法：启动 exe（用全新的临时 userData，保证窗口回到默认右下角），
把真实光标按网格逐个挪过去，读窗口的 WS_EX_TRANSPARENT 位，
画出一张"哪些位置会挡住桌面点击"的图，并与 tools/smoke_test.js 算出的
命中网格对照 —— 用来判断主进程的判定和渲染层的网格是否一致。

用法： python tools/passthrough_probe.py [dev|exe]
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV_EXE = os.path.join(ROOT, "node_modules", "electron", "dist", "electron.exe")
PKG_CANDIDATES = [
    os.path.join(ROOT, "dist-final", "赛博朝拜_免安装版.exe"),
    os.path.join(ROOT, "dist-new", "赛博朝拜_免安装版.exe"),
]
PKG_EXE = next((p for p in PKG_CANDIDATES if os.path.exists(p)), PKG_CANDIDATES[0])
TMP_UD = os.path.join(os.environ.get("TEMP", "."), "cw-pt-probe")
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
        if r.right - r.left > 100 and r.bottom - r.top > 100:
            rows.append((r.left, r.top, r.right, r.bottom))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return rows


def transparent(hwnd):
    return bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TRANSPARENT)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "exe"
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
    print("启动:", cmd[0], " (全新 userData)")
    subprocess.Popen(cmd, cwd=cwd, env=env)
    time.sleep(wait)

    ws = top_windows()
    if not ws:
        print("!! 没找到宠物窗口")
        return 1
    l, t, r, b = ws[0]
    l = max(l, 0)
    t = max(t, 0)
    print("窗口 rect =", ws[0], " 尺寸 =", (ws[0][2] - ws[0][0], ws[0][3] - ws[0][1]))

    ox, oy = wt.POINT(), None
    user32.GetCursorPos(ctypes.byref(ox))
    oy = ox.y
    ox = ox.x
    hwnd = None

    # 重新枚举拿到 hwnd
    rows = []

    def cb2(h, _l):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        nm = proc_name(p.value).lower()
        if any(k in nm for k in ("electron", "cyber-worship", "赛博朝拜")):
            rr = wt.RECT()
            user32.GetWindowRect(h, ctypes.byref(rr))
            if user32.IsWindowVisible(h) and not user32.GetWindow(h, GW_OWNER) \
               and rr.right - rr.left > 100:
                rows.append(h)
        return True

    user32.EnumWindows(EnumWindowsProc(cb2), 0)
    hwnd = rows[0]

    STEP = 8
    lines = []
    try:
        for cy in range(0, BASE_H, STEP):
            line = ""
            for cx in range(0, BASE_W, STEP):
                user32.SetCursorPos(l + int(cx * ZOOM), t + int(cy * ZOOM))
                time.sleep(0.045)
                line += "." if transparent(hwnd) else "#"
            lines.append("%3d %s" % (cy, line))
    finally:
        user32.SetCursorPos(ox, oy)

    print("\n主进程判定图（# = 挡住点击 / . = 鼠标穿透），每格 %d CSS px:" % STEP)
    for ln in lines:
        print("  " + ln)

    subprocess.run(["taskkill", "/F", "/IM", "electron.exe"], capture_output=True)
    return 0


sys.exit(main())
