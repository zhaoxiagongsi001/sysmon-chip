# 构建 SysMonChipLite 的两个版本
#
#   .\tools\build.ps1                # v1.3 发布版：剥掉 mingw CRT，39 KB 级
#   .\tools\build.ps1 -Plain         # 保留 CRT 的兼容版（51 KB 级，默认 cargo 链接器）
#   .\tools\build.ps1 -Plain -Copy   # 顺手覆盖 发布\ 里的可执行文件
#
# 剥 CRT 的做法：`-C linker-flavor=ld` 让 rustc 走 ld 原生参数，再用 tools/ld_wrap.py
# 拦掉 crt2.o / libmingw32 / msvcrt，入口改成 main.rs 里的 chip_entry。
param(
    [switch]$Plain,
    [switch]$Copy
)

$ErrorActionPreference = "Stop"
# 注意：点源 env.ps1 会覆盖 $PSScriptRoot，所以先用自己的路径算根目录
$scriptPath = $MyInvocation.MyCommand.Path
if (Test-Path "D:/DSH/.rust/env.ps1") { . "D:/DSH/.rust/env.ps1" }
$root = Split-Path -Parent (Split-Path -Parent $scriptPath)
$env:CARGO_NET_OFFLINE = "true"

Push-Location (Join-Path $root "app_ultra")
try {
    # 强制重链：cargo 认为 exe 新鲜就不会再跑链接器
    (Get-Item "src/main.rs").LastWriteTime = Get-Date
    if ($Plain) {
        & cargo build --release --bin SysMonChipLite
    } else {
        $ldw = (Join-Path $root "tools/ldw.cmd")
        if (-not (Test-Path $ldw)) { throw "缺少 $ldw" }
        & cargo rustc --release --bin SysMonChipLite -- -C "linker=$ldw" -C linker-flavor=ld
    }
    if ($LASTEXITCODE -ne 0) { throw "构建失败（exit $LASTEXITCODE）" }
}
finally {
    Pop-Location
}

$exe = "D:/DSH/.rust/target/release/SysMonChipLite.exe"
$item = Get-Item $exe
$sha = (Get-FileHash $exe -Algorithm SHA256).Hash
"{0}  {1} B  SHA256 {2}" -f $exe, $item.Length, $sha

if ($Copy) {
    Copy-Item $exe (Join-Path $root "发布/SysMonChipLite.exe") -Force
    "已覆盖 发布\SysMonChipLite.exe"
}
