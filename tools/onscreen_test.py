# -*- coding: utf-8 -*-
"""
窗口位置夹取测试（显示器感知）：

存档里可能留着"到不了的"位置（换过分辨率、拔过外接屏、或者被拖出去之后关掉），
如果不夹回来，下次启动宠物就落在看不见的地方 —— 既看不见也点不到。
main.js 的 clampToWorkArea() 用 screen.getDisplayMatching() 把坐标夹回**最近的显示器**。

⚠️ 这台机器是双显示器（副屏在主屏右侧，x=1920 起）：
   判定标准必须写成"窗口完整落在**某一个**显示器的工作区内"，
   只拿主屏尺寸（GetSystemMetrics(0/1)）去断言会误判 ——
   窗口落在副屏上其实完全合法。

用法： python tools/onscreen_test.py [dev|exe]
"""
import ctypes
import ctypes.wintypes as wt
import glob
import json
import os
import subprocess
import sys
import time

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
TMP_UD = os.path.join(os.environ.get("TEMP", "."), "cw-onscreen-test")
ZOOM = 0.8
BASE_W, BASE_H = 400, 460

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
GW_OWNER = 4
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
MONITORINFOF_PRIMARY = 1

fails = []


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('rcMonitor', wt.RECT), ('rcWork', wt.RECT),
                ('dwFlags', wt.DWORD), ('szDevice', ctypes.c_wchar * 32)]


def check(cond, label, extra=""):
    print(("PASS  " if cond else "FAIL  ") + label + (("  -> " + str(extra)) if extra != "" else ""))
    if not cond:
        fails.append(label)


def monitors():
    """所有显示器的工作区 [(name, (l,t,r,b), primary)]"""
    out = []

    def cb(h, hdc, rc, lp):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        user32.GetMonitorInfoW(h, ctypes.byref(mi))
        out.append((mi.szDevice,
                    (mi.rcWork.left, mi.rcWork.top, mi.rcWork.right, mi.rcWork.bottom),
                    bool(mi.dwFlags & MONITORINFOF_PRIMARY)))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    out.sort(key=lambda x: not x[2])          # 主屏排前面
    return out


def contained_in_some_monitor(rect):
    """窗口矩形是否完整落在某个显示器的工作区内"""
    wx, wy, wr, wb = rect
    for _, (l, t, r, b), _p in monitors():
        if wx >= l and wy >= t and wr <= r and wb <= b:
            return True, (l, t, r, b)
    return False, None


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


def pet_window():
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
    return rows[0] if rows else None


def kill_all():
    for n in ("electron.exe", "赛博朝拜_免安装版.exe", "cyber-worship.exe"):
        subprocess.run(["taskkill", "/F", "/IM", n], capture_output=True)


def run_case(mode, name, state, expect):
    # 每次都用全新的 userData
    subprocess.run(["cmd", "/c", "rmdir", "/S", "/Q", TMP_UD], capture_output=True)
    os.makedirs(TMP_UD, exist_ok=True)
    with open(os.path.join(TMP_UD, "window-state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f)

    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    if mode == "exe":
        cmd, cwd, boot = [PKG_EXE, "--user-data-dir=" + TMP_UD], os.path.dirname(PKG_EXE), 22
    else:
        cmd, cwd, boot = [DEV_EXE, ".", "--user-data-dir=" + TMP_UD], ROOT, 15

    subprocess.Popen(cmd, cwd=cwd, env=env)
    time.sleep(boot)
    rect = pet_window()
    print("\n[%s] 存档位置 = %s   期望 = %s" % (name, state, expect))
    if rect is None:
        check(False, "%s：能找到宠物窗口" % name, "没找到")
        kill_all()
        time.sleep(2)
        return
    ok, mon = contained_in_some_monitor(rect)
    ms = monitors()
    print("     显示器工作区 = %s" % [m[1] for m in ms])
    print("     实际窗口 = %s  尺寸 = %dx%d" % (rect, rect[2] - rect[0], rect[3] - rect[1]))

    check((rect[2] - rect[0], rect[3] - rect[1]) == (BASE_W * ZOOM, BASE_H * ZOOM),
          "%s：窗口尺寸 = 80%% 档位" % name, (rect[2] - rect[0], rect[3] - rect[1]))
    check(ok, "%s：窗口完整落在某个显示器的工作区内" % name,
          {"rect": rect, "显示器数": len(ms)})

    if expect == "keep":
        check((rect[0], rect[1]) == (state["x"], state["y"]),
              "%s：合法位置原样保留（没被乱挪）" % name, (rect[0], rect[1]))
    kill_all()
    time.sleep(2)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "exe"
    print("目标:", PKG_EXE if mode == "exe" else DEV_EXE)
    ms = monitors()
    print("显示器共 %d 个：" % len(ms))
    for nm, wa, pri in ms:
        print("   %s 工作区=%s %s" % (nm, wa, "PRIMARY" if pri else ""))
    kill_all()
    time.sleep(1.5)

    # 右下越界：1800+320=2120 越过主屏右边界（主屏宽 1920）
    # -> 应被吸附到最近的显示器（本机是副屏 x=1920 起）并完整落在其工作区内
    run_case(mode, "右下越界", {"x": 1800, "y": 900, "zoom": ZOOM}, "clamp")
    # 完全在所有显示器之外：必须拉回某个显示器
    run_case(mode, "完全屏外", {"x": 5000, "y": 2000, "zoom": ZOOM}, "clamp")
    # 左上负坐标
    run_case(mode, "左上负坐标", {"x": -900, "y": -600, "zoom": ZOOM}, "clamp")
    # 屏幕内正常位置：必须原样保留
    run_case(mode, "屏幕内正常位置", {"x": 300, "y": 200, "zoom": ZOOM}, "keep")
    # 副屏上的合法位置：也必须原样保留（不能被粗暴拽回主屏）
    if len(ms) > 1:
        sx = ms[1][1][0] + 180
        run_case(mode, "副屏合法位置", {"x": sx, "y": 300, "zoom": ZOOM}, "keep")

    print("\nFAILS=%d" % len(fails))
    print("ALL PASS" if not fails else "FAILED: " + " | ".join(fails))
    return 1 if fails else 0


sys.exit(main())
