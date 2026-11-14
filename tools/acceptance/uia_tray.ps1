param(
    [string]$Mode = 'list'
)
# ASCII-only script (PowerShell 5.1 reads no-BOM files as ANSI; CJK patterns built from char codes).
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$root = $AE::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, 'Shell_TrayWnd')
$tb = $root.FindFirst($TS::Children, $cond)
if (-not $tb) { $tb = $root.FindFirst($TS::Descendants, $cond) }
if (-not $tb) { '{"error":"no_taskbar"}'; exit 0 }

# "资源条" and "隐藏的图标"/"通知图标" built from code points to keep file ASCII.
$RES = [string][char]0x8D44 + [char]0x6E90 + [char]0x6761
$HID = [string][char]0x9690 + [char]0x85CF + [char]0x7684 + [char]0x56FE + [char]0x6807
$NOTIF = [string][char]0x901A + [char]0x77E5 + [char]0x56FE + [char]0x6807
$namePat = 'SysMon|' + $RES
$chevPat = 'NotifyChevron|Chevron|Overflow|Show hidden|Hidden|' + $HID + '|' + $NOTIF

function Get-Rows($element) {
    $all = $element.FindAll($TS::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    $rows = foreach ($e in $all) {
        try { $c = $e.Current } catch { continue }
        [pscustomobject]@{
            Name = $c.Name
            Class = $c.ClassName
            Aid = $c.AutomationId
            Type = $c.ControlType.ProgrammaticName
        }
    }
    return @($rows)
}

$out = [ordered]@{ mode = $Mode }

if ($Mode -eq 'list') {
    $rows = Get-Rows $tb
    $out.taskbar_elements = @($rows | Where-Object { $_.Name -or $_.Aid } | Select-Object -First 120)
    $out.count = $rows.Count
    $out | ConvertTo-Json -Depth 5
    exit 0
}

if ($Mode -eq 'search') {
    $rows = Get-Rows $root
    $out.hits = @($rows | Where-Object { $_.Name -match $namePat })
    $out.root_element_count = $rows.Count
    $out | ConvertTo-Json -Depth 5
    exit 0
}

if ($Mode -eq 'open-overflow') {
    $rows = Get-Rows $tb
    $chev = $rows | Where-Object {
        ($_.Aid -and $_.Aid -match $chevPat) -or ($_.Name -and $_.Name -match $chevPat)
    } | Select-Object -First 1
    if (-not $chev) {
        $out.error = 'no_chevron'
        $out.candidates = @($rows | Where-Object { $_.Aid } | Select-Object -First 60)
        $out | ConvertTo-Json -Depth 5
        exit 0
    }
    $out.chevron = $chev
    $pc = if ($chev.Aid) {
        New-Object System.Windows.Automation.PropertyCondition($AE::AutomationIdProperty, $chev.Aid)
    } else {
        New-Object System.Windows.Automation.PropertyCondition($AE::NameProperty, $chev.Name)
    }
    $el = $tb.FindFirst($TS::Descendants, $pc)
    if ($el) {
        try {
            $pat = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
            $pat.Invoke()
            $out.invoked = $true
        } catch { $out.invoke_error = $_.Exception.Message }
    } else { $out.find_error = 'element_not_refound' }
    Start-Sleep -Milliseconds 900
    $rows2 = Get-Rows $root
    $out.overflow_hits = @($rows2 | Where-Object { $_.Name -match $namePat })
    $out.after_count = $rows2.Count
    $out | ConvertTo-Json -Depth 5
    exit 0
}

'{"error":"unknown_mode"}'
