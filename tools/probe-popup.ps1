$ErrorActionPreference = 'Continue'
$py = 'C:\Users\zhang\AppData\Local\Programs\Python\Python312\python.exe'

Write-Output '== widget state =='
& $py -c @'
import ctypes, sys
from ctypes import wintypes
u = ctypes.windll.user32
sys.path.insert(0, r"D:\DSH\sysmon-chip\tools")
import win32util as w
h = w.find_widget()
print("hwnd", hex(h) if h else None)
if h:
    print("visible", bool(u.IsWindowVisible(h)), "rect", w.widget_rect_physical())
'@

Write-Output '== MOTW read capability self-test =='
$found = $false
foreach ($f in (Get-ChildItem "$env:USERPROFILE\Downloads" -File -Recurse -Depth 1 -ErrorAction SilentlyContinue | Select-Object -First 40)) {
    try {
        $z = (Get-Item $f.FullName -Stream Zone.Identifier -ErrorAction Stop).StreamContent
        Write-Output ("MOTW readable: " + $f.Name + " -> " + ($z -replace "`r?`n", ' '))
        $found = $true
        break
    } catch { }
}
if (-not $found) { Write-Output 'no Zone.Identifier in first 40 Downloads files' }

Write-Output '== published exe ADS check via .NET =='
$p = 'D:\DSH\sysmon-chip\发布\SysMonChipLite.exe'
try {
    $has = $true
    try {
        $fs2 = [System.IO.File]::Open($p + ':Zone.Identifier', 'Open', 'Read', 'ReadWrite')
        Write-Output ("ADS exists length=" + $fs2.Length)
        $fs2.Close()
    } catch { $has = $false }
    if (-not $has) { Write-Output 'ADS absent: no MOTW on published exe' }
} catch { Write-Output ("open failed: " + $_.Exception.Message) }

Write-Output '== SmartScreen settings =='
$ah = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\AppHost' -ErrorAction SilentlyContinue
if ($ah) {
    ($ah.PSObject.Properties | Where-Object { $_.Name -notlike 'PS*' } | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join '; '
} else { Write-Output 'AppHost key absent' }
$ss = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer' -ErrorAction SilentlyContinue
Write-Output ('SmartScreenEnabled=' + $ss.SmartScreenEnabled)

Write-Output '== instance count =='
Write-Output @(Get-Process SysMonChipLite -ErrorAction SilentlyContinue).Count
