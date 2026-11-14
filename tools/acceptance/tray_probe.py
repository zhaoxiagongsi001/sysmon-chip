"""托盘图标专项探测（必须在同一条命令内完成：启动 -> 查询 -> 截图 -> 收尾）。

手段：
 1. Shell_NotifyIconGetRect(NOTIFYICONIDENTIFIER{hwnd,uID=1})：能拿到托盘图标矩形即证明
    Shell 已注册该图标；返回 ERROR_FILE_NOT_FOUND 则表示未注册。
 2. 任务栏托盘区截图（运行中 / 退出后各一张），供人工核对。
 3. 可选：用 Windows PowerShell 5.1 的 UIAutomation 在任务栏树里按名称搜 "SysMon/资源条"。

产出：data/tray-probe.json + screenshots/verify-tray-*.png
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("guidItem", GUID)]


sh = ctypes.WinDLL("shell32", use_last_error=True)
sh.Shell_NotifyIconGetRect.argtypes = [ctypes.POINTER(NOTIFYICONIDENTIFIER),
                                       ctypes.POINTER(wintypes.RECT)]
sh.Shell_NotifyIconGetRect.restype = ctypes.c_long


def icon_rect(hwnd, uid=1):
    nid = NOTIFYICONIDENTIFIER()
    nid.cbSize = ctypes.sizeof(NOTIFYICONIDENTIFIER)
    nid.hWnd = hwnd
    nid.uID = uid
    r = wintypes.RECT()
    hr = sh.Shell_NotifyIconGetRect(ctypes.byref(nid), ctypes.byref(r))
    hr32 = hr & 0xFFFFFFFF
    return {"hr": hex(hr32), "hr_signed": hr,
            "ok": hr == 0,
            "file_not_found": hr32 == 0x80070002,
            "rect": [r.left, r.top, r.right, r.bottom]}


def tray_crop(tag):
    bar = c.taskbar_rect_physical()
    if not bar:
        return None
    right = (max(bar[0], bar[2] - 900), bar[1], bar[2], bar[3])
    p = os.path.join(c.SHOTS, f"verify-tray-{tag}.png")
    im = c.grab_crop(right, pad=0, path=p)
    im.resize((im.width * 2, im.height * 2)).save(
        os.path.join(c.SHOTS, f"verify-tray-{tag}-2x.png"))
    return {"path": os.path.basename(p),
            "region": right}


PS51 = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
UIA_SCRIPT = r"""
try {
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes
  $root = [System.Windows.Automation.AutomationElement]::RootElement
  $cond = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ClassNameProperty, 'Shell_TrayWnd')
  $tb = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
  if (-not $tb) { $tb = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond) }
  if ($tb) {
    $all = $tb.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                       [System.Windows.Automation.Condition]::TrueCondition)
    $hits = @()
    foreach ($e in $all) {
      try { $n = $e.Current.Name } catch { continue }
      if ($n -and ($n -match 'SysMon' -or $n -match '资源条')) {
        $hits += [pscustomobject]@{ Name = $n; Class = $e.Current.ClassName;
                                    AutomationId = $e.Current.AutomationId }
      }
    }
    if ($hits.Count -eq 0) { 'UIA: taskbar tree has no SysMon-named element' }
    else { $hits | ConvertTo-Json -Compress }
  } else { 'UIA: Shell_TrayWnd element not found' }
} catch {
  'UIA error: ' + $_.Exception.Message
}
"""


def uia_search(timeout=25):
    if not os.path.exists(PS51):
        return {"error": "powershell 5.1 not found"}
    try:
        p = subprocess.run([PS51, "-NoProfile", "-STA", "-Command", UIA_SCRIPT],
                           capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return {"stdout": p.stdout.strip(), "stderr": p.stderr.strip()[:500],
                "rc": p.returncode}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}


def main():
    c.ensure_dirs()
    c.write_config(mode="taskbar", theme="light")
    c.stop()
    time.sleep(0.4)
    p = c.launch()
    time.sleep(1.6)
    info = c.widget_info()
    hwnd = info["hwnd"]
    out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "hwnd": hwnd, "pid": p.pid,
           "rect": info["rect"]}
    out["icon_rect_uid1"] = icon_rect(hwnd, 1)
    out["icon_rect_uid0"] = icon_rect(hwnd, 0)
    out["tray_running"] = tray_crop("running-icons")
    out["uia"] = uia_search()
    # 退出后再查一次：图标应随 NIM_DELETE 消失
    code = c.stop(wait_exit=p)
    time.sleep(0.6)
    out["quit"] = {"exit_code": code, "pids": c.list_pids()}
    out["icon_rect_after_quit"] = icon_rect(hwnd, 1)
    out["tray_after_quit"] = tray_crop("after-quit")
    c.save_json(os.path.join(c.DATA, "tray-probe.json"), out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
