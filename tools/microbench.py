"""Win32 调用微基准：量化 1s tick 里每个采样子步骤的成本（近似值，python 调用开销已扣除）。"""
import ctypes
import time
from ctypes import wintypes

k32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32
iphlp = ctypes.windll.iphlpapi

N = 2000

class MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def bench(name, fn):
    for _ in range(50):
        fn()
    t0 = time.perf_counter()
    for _ in range(N):
        fn()
    dt = (time.perf_counter() - t0) / N
    print(f"{name:28s} {dt*1e6:9.2f} us")
    return dt


def empty():
    pass


base = bench("python call floor", empty)

ms = MEMSTAT()
ms.dwLength = ctypes.sizeof(MEMSTAT)
idt = wintypes.FILETIME(); kt = wintypes.FILETIME(); ut = wintypes.FILETIME()
buf = ctypes.create_string_buffer(64)


def f_getsystemtimes():
    k32.GetSystemTimes(ctypes.byref(idt), ctypes.byref(kt), ctypes.byref(ut))


def f_memstatus():
    k32.GlobalMemoryStatusEx(ctypes.byref(ms))


def f_disk():
    free = ctypes.c_ulonglong(); total = ctypes.c_ulonglong(); totfree = ctypes.c_ulonglong()
    k32.GetDiskFreeSpaceExW("C:\\", ctypes.byref(free), ctypes.byref(total), ctypes.byref(totfree))


def f_iftable():
    p = ctypes.c_void_p()
    r = iphlp.GetIfTable2(ctypes.byref(p))
    if r == 0 and p:
        iphlp.FreeMibTable(p)


def f_findwindow():
    user32.FindWindowW("Shell_TrayWnd", None)


def f_fg():
    user32.GetForegroundWindow()


hdc = user32.GetDC(None)


def f_text():
    sz = wintypes.SIZE()
    user32.GetTextExtentPoint32W(hdc, "999.9 MB/s", 10, ctypes.byref(sz))


def f_visible():
    user32.IsWindowVisible(1)


h = user32.FindWindowW("Shell_TrayWnd", None)
bench("GetSystemTimes", f_getsystemtimes)
bench("GlobalMemoryStatusEx", f_memstatus)
bench("GetDiskFreeSpaceExW", f_disk)
bench("GetIfTable2+Free", f_iftable)
bench("FindWindowW(Shell_TrayWnd)", f_findwindow)
bench("GetForegroundWindow", f_fg)
bench("GetTextExtentPoint32W", f_text)
bench("IsWindowVisible", f_visible)
user32.ReleaseDC(None, hdc)
