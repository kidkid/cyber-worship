# -*- coding: utf-8 -*-
"""诊断：确认测试进程的 DPI 感知级别与屏幕度量，判断坐标系是否与 Electron 的 DIP 一致。"""
import ctypes
import ctypes.wintypes as wt

user32 = ctypes.windll.user32
shcore = ctypes.windll.shcore

print("GetSystemMetrics (virtualized):", user32.GetSystemMetrics(0), "x", user32.GetSystemMetrics(1))

try:
    print("GetDpiForSystem:", user32.GetDpiForSystem())
except Exception as e:
    print("GetDpiForSystem n/a", e)

try:
    print("GetDpiForWindow(GetDesktopWindow):", user32.GetDpiForWindow(user32.GetDesktopWindow()))
except Exception as e:
    print("GetDpiForWindow n/a", e)

try:
    aw = wt.INT()
    shcore.GetProcessDpiAwareness(None, ctypes.byref(aw))
    print("process DPI awareness:", aw.value, "(0=unaware 1=system 2=permonitor)")
except Exception as e:
    print("GetProcessDpiAwareness n/a", e)

mon = user32.MonitorFromPoint(wt.POINT(0, 0), 2)
dx, dy = wt.UINT(), wt.UINT()
try:
    shcore.GetDpiForMonitor(mon, 0, ctypes.byref(dx), ctypes.byref(dy))
    print("monitor effective dpi:", dx.value, dy.value)
except Exception as e:
    print("GetDpiForMonitor n/a", e)

# 当前光标
p = wt.POINT()
user32.GetCursorPos(ctypes.byref(p))
print("cursor:", p.x, p.y)

# 主显示器工作区（虚拟化坐标）
r = wt.RECT()
user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
print("work area:", (r.left, r.top, r.right, r.bottom))
