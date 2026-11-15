# SysMon Chip · Win11 任务栏资源条

一个 **40 KB** 的单文件小工具：贴在任务栏左端（或屏幕右下角），两行显示 **CPU、内存、系统盘占用、上下行网速**。免安装、不用管理员、不联网、不写驱动、不碰 WebView。

![任务栏左端效果](screenshots/v1.4-taskbar-left.png)

## 下载

最新版 **v1.4**（2026-11-14）：[SysMonChipLite-v1.4.exe](https://github.com/zhaoxiagongsi001/sysmon-chip/releases/download/v1.4/SysMonChipLite-v1.4.exe)

| 项目 | 值 |
|---|---|
| 体积 | 40 KB（40,960 B），PE 版本 1.4.0.0 |
| SHA256 | `E0E8D394B542EDE0569146B0C1D06EFB188A53AC3A852A585F9113CE77A58312` |
| 运行环境 | Windows 11 x64（本机 3456×2160 @ 225% 缩放实测） |
| 全部版本 | [Releases](https://github.com/zhaoxiagongsi001/sysmon-chip/releases) |

下载后可核对哈希：`Get-FileHash .\SysMonChipLite-v1.4.exe -Algorithm SHA256`。

## 启动

1. 把 exe 放到任意目录，双击即可：任务栏左端出现资源条，托盘出现图标。
2. 首次运行可能被 **SmartScreen** 拦（未做代码签名 + 没有下载声誉）。两种处理：
   - **推荐**：用仓库里的 `发布/启动 SysMonChip.cmd` 启动。它用 `start`（走 `CreateProcess`）拉起 exe，不经过 ShellExecute，不会触发 SmartScreen；
   - 或者右键 exe → 属性 → 勾「解除锁定」→ 确定。
   想彻底消掉提示需要 OV/EV 代码签名证书，个人工具不划算。
3. 不需要管理员权限，也不要用管理员身份运行（本工具没有任何需要提权的操作）。
4. 想开机就在：菜单里勾「开机自启」（原理见下文）。

**卸载**：菜单「退出」→ 取消「开机自启」→ 删掉 exe 和 `%APPDATA%\SysMonChip` 目录。

## 界面与操作

- 两行四项：上排是 `CPU / MEM / DISK` 标签和网速上行，下排是对应数值和网速下行。
- 百分比颜色：**<70% 绿、70–89% 橙、≥90% 红**；↑ 粉红、↓ 蓝。
- **位置只有两个**：任务栏左端（默认，整条任务栏高）、桌面右下角（贴任务栏上沿 + 屏幕右缘）。
- **不支持拖动**：早期版本可以左键拖着走，v0.3 界面改版时已移除（配置文件里的 `locked` 项还在，但已无作用）。换位置用菜单。
- 右键资源条或右键托盘图标打开菜单；左键点资源条没有反应。
- 托盘左键 = 显示/隐藏资源条（状态会记住），再点一次回来。

| 菜单项 | 可选值 | 说明 |
|---|---|---|
| 显示指标 | CPU / 内存 / 磁盘 / 网速 | 逐项开关；面板宽度跟着变，至少保留一项 |
| 位置 | 桌面右下角（贴任务栏）/ 贴任务栏左端 | 默认左端 |
| 刷新间隔 | 0.5 / 1 / 2 / 5 秒 | 默认 1 秒 |
| 主题 | 跟随系统 / 浅色 / 深色 | 默认跟随系统 |
| 开机自启 | 勾选 / 取消 | 写当前用户的 `Run` 项（见下文） |
| 退出 | — | 结束进程 |

- **全屏自动隐藏是固定行为**：前台窗口铺满本屏（PPT 放映、视频全屏、浏览器 F11）就自动隐藏，退出全屏自动回来。菜单里没有开关；想关掉只能改配置 `hide_fs=0`。
- 任务栏设成自动隐藏时，资源条跟着任务栏一起隐藏/露出。
- 单实例：重复启动不会开第二个，只会把已有实例唤出来（包括被托盘隐藏的情况）。

## 数据口径

| 指标 | 来源 | 说明 |
|---|---|---|
| CPU | `GetSystemTimes` | 两次采样差分，`100 × (1 − Δidle / (Δkernel + Δuser))`，整机口径 |
| 内存 | `GlobalMemoryStatusEx` | `dwMemoryLoad`，系统「已用百分比」 |
| 磁盘 | `GetDiskFreeSpaceExW` | **系统盘（Windows 所在盘）已用比例**，不是磁盘活动率；每 30 次刷新取一次（1 秒档约 30 秒/次，5 秒档约 2.5 分钟/次） |
| 网速 | `GetIfTable2`（启动时缓存网卡）+ `GetIfEntry2`（每次刷新） | 所有「已连接、非回环、非隧道、且是硬件网卡或 VPN 端点接口」的上下行字节合计 ÷ 实际间隔；排除 WFP/QoS 过滤层，避免重复计数 |

- 网速格式：`B/s`、`KB/s`、`MB/s`、`GB/s`；小于 100 保留一位小数，≥100 取整；读数特别长时自动换成更短的写法，保证不压到左边。
- 电脑睡眠/唤醒，或两次采样间隔异常大时，这一次差分直接丢弃，不会冒出假尖峰。
- 全部是 Win32 轻量接口，不用 WMI / COM / PDH / 性能计数器。

## 配置

位置：`%APPDATA%\SysMonChip\config.ini`（UTF-8，`key=value` 一行一项；损坏或缺失自动回退默认值）。

```ini
mode=taskbar     ; taskbar(默认) | desktop | free | taskbar-right(实验值，菜单未开放)
x=0              ; 仅 free 模式有意义：窗口左上角物理像素坐标
y=0
interval=1000    ; 刷新间隔毫秒，实际生效范围 200–10000
cpu=1            ; 四项开关：0/1；全关时强制恢复 cpu=1
mem=1
disk=1
net=1
theme=auto       ; auto | light | dark
locked=0         ; 旧版拖动锁，已无作用，保留只为兼容
hide_fs=1        ; 1 = 前台全屏时隐藏（默认），0 = 不隐藏
autostart=0      ; 仅作记录，真实状态以注册表为准
```

- 菜单里改的设置会立即写回这个文件；手改文件后需要重启程序才生效。`free` 模式只能在文件里配。
- 写入是「临时文件 + 替换」，失败会按刷新间隔重试，约 2 分钟后放弃，并在 `%TEMP%\sysmonchip-save-error.txt` 留诊断。
- 想恢复默认：退出程序，删掉 `config.ini`，再启动。

## 命令行

参数按 `--名称` 精确匹配（区分大小写），主要给脚本和排障用：

| 参数 | 作用 |
|---|---|
| `--quit` | 让已运行的实例退出（不弹窗） |
| `--dump` | 采样 1 秒，把 cpu/mem/disk/up/down/if_seen/mode 写到 `%TEMP%\sysmonchip-dump.txt` 后退出 |
| `--trace` | 正常启动，并把启动耗时、DPI、宽高写到 `%TEMP%\sysmonchip-trace.txt` |
| `--demo` | 正常启动，但读数固定为最坏值（CPU/磁盘 100%、内存 99%、网速最大），用来看排版够不够 |
| `--selftest` | 配置写入/读回往返自检，结果写 `%TEMP%\sysmonchip-selftest.txt` |
| `--autostart-on` / `--autostart-off` | 写入/删除开机自启项并回读校验，结果写 `%TEMP%\sysmonchip-autostart.txt` |
| `--autostart` | 只由自启项传入的标记；程序里没有对应动作，行为与双击一致 |

## 开机自启

- 勾选 = 在 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 写字符串值 `SysMonChip`，内容是 `"<exe 全路径>" --autostart`；登录时由 Explorer 拉起。写在 HKCU，**不需要管理员**，只对当前用户生效。
- v1.4 的行为：
  - 写不进去（权限不足、策略锁定）不再假装成功，菜单勾选时弹窗提示；
  - 菜单勾选状态以注册表为准，而且必须**指向当前这个 exe** 才算开着；
  - 换路径后启动时会自动把旧路径改成新路径（失败就当没开），并留痕 `%TEMP%\sysmonchip-autostart-heal.txt`；
  - 写完要回读确认才算成功。
- 坑：值里是绝对路径，移动/改名 exe 后自启会失效；从桌面双击一次新版即可自愈，或取消再勾一次。
- 验证：任务管理器 →「启动」页应看到 `SysMonChip`（已启用）；重启后资源条自动出现。

## 资源占用（实测）

| 项目 | 数值 | 说明 |
|---|---|---|
| exe 体积 | 40,960 B | v1.4，PE 1.4.0.0 |
| 常驻工作集 | 约 1.7 MB | v1.3 回归实测 |
| 冷启动到首帧 | 24–31 ms | v1.3 实测 |
| CPU | 约 1.2–1.7 ms/s | 90 秒窗口，约单核 0.12–0.17%；系统计时精度 15.625 ms，这个量级不能拿来比版本快慢 |
| 句柄 / GDI / USER | 137 / 11 / 7 | v1.3 实测稳定值 |
| 托盘隐藏 → 显示 | 约 5 ms | v1.4 `tools/verify.py tray` |
| 点任务栏后被压住 | 11 ms | v0.7 修复前后：251–462 ms → 11 ms |

- 对照：本机实测最简 eframe/egui 空窗口 126.9 MB；MangoDisk 是 Tauri + WebView2（47 MB exe + 数百 MB 进程族）。
- 完整测量口径与限制见 `研究报告-体积与占用-2026-11-14.md`。

## 为什么只有 40 KB

1. **不用 WebView / egui / WPF**：纯 Win32 + GDI 直接画，没有 GPU 上下文、没有 JS 运行时。运行时只导入 6 个系统 DLL（kernel32 / user32 / gdi32 / advapi32 / shell32 / iphlpapi），WinINet / WinHTTP / ws2_32 这些网络库都不在导入表里。
2. **不链接 Rust std**（`#![no_std]`）：只用 `core` + `windows-sys`；文件、注册表、命令行都直接调 Win32。链接时再剥掉 mingw 的 `crt2.o` 与 `msvcrt`，入口换成自定义 `chip_entry`，连 `memcpy/memmove/memset/memcmp` 都自己提供。体积从 51 KB 降到 38.5 KB 主要靠这一步。
3. **单进程、单线程、一个刷新定时器**：不建后台线程，不调 `timeBeginPeriod` 改系统计时精度；只有需要时跑一小段 16 ms × 40 tick 的 z 序守护定时器。
4. **程序自身不做堆分配**：没有 `alloc`，也没有 `malloc`/`HeapAlloc`，读到文本、网卡列表都在栈上定长缓冲里。
5. **少做无用功**：读数没变就不重绘；文字宽度每次刷新量一次缓存下来，绘制时不再量；宽度只在指标开关变化时重算。
6. **定期归还工作集**：启动后第 3 次刷新、之后每 120 次刷新调用一次 `SetProcessWorkingSetSize(-1,-1)`。
7. **图标 2.4 KB**：只保留 24/32 两帧 PNG 压缩图标；资源用 windres 编入。
8. **不做离屏位图**：直接 GDI 画到窗口 DC（`chip_core` 里的双缓冲 `Canvas` 目前没有任何调用方）。

## 已知限制

- **没有半透明/毛玻璃**：当前是实色底（浅色 `#F3F3F3`、深色 `#202020`）。代码里还留着亚克力入口，但 `GetProcAddress` 把 UTF-16 字符串传给只认 ANSI 的 API，永远拿不到函数地址；v0.4 那套分层半透明实现也已不在当前代码里。
- **贴任务栏左端会盖住 Win11 的天气小组件**，并且会吃掉那块区域的鼠标点击（没有点击穿透）。介意就切「桌面右下角」。
- **全屏隐藏靠轮询**：进入/退出全屏最多晚约一个刷新间隔（默认 1 秒）。
- **多显示器 / 混合 DPI 未实测**：代码按窗口所在显示器取信息，但只在本机单屏 225% 验证过。
- **磁盘显示的是占用率，不是读写活动**；网速是接口总吞吐，不区分进程。
- **未做代码签名**：可能触发 SmartScreen（处理方式见「启动」）。
- **单实例**：升级换版本前先退出旧实例。
- **explorer 重启**：收到 `TaskbarCreated` 后会重挂托盘并重新定位，但本机没有专门做重启 explorer 的验收。
- **开机自启在降权环境（如 agent 沙箱）会失败**，这是 Windows 完整性级别的预期行为。

## 从源码构建

需要：Rust stable（`x86_64-pc-windows-gnu`）、MinGW 的 `windres`（编图标）、Python（链接器包装脚本）、本地 cargo registry（离线构建）。

```powershell
. D:/DSH/.rust/env.ps1
cd D:/DSH/sysmon-chip
.\tools\build.ps1            # 默认：剥 CRT 版（约 40 KB）
.\tools\build.ps1 -Plain     # 保留 CRT 的兼容版
.\tools\build.ps1 -Copy      # 顺手覆盖 发布\SysMonChipLite.exe
# 产物：D:/DSH/.rust/target/release/SysMonChipLite.exe
```

- 测试：`cargo test`（chip_core 16 项：布局、格式化、回归）；验收：`python tools/verify.py layout|padding|region|tray`（需要程序已在运行，脚本会切指标再还原）。
- `app/` 是 2026-11-10 的原始 std 实现，已冻结在 v0.3.0（旧的小条界面），只作对照，不再更新。

## 目录结构

```
app_ultra/            Lite 外壳：窗口 / 菜单 / 托盘 / 配置 / 自启（no_std）
chip_core/            共享核心：布局、文本格式化、GDI 绘制、四项采样
app/                  std 旧版外壳（冻结在 v0.3，仅对照）
tools/                构建（build.ps1 / ld_wrap.py / ldw.cmd）与验收（verify.py / perf.py 等）
发布/                 成品 exe、启动器、历史版本
screenshots/          截图
评审报告-*.md          2026-11-14 代码评审
研究报告-*.md          体积与占用研究
OCR审核-v*.md          逐版本委派评审记录
```

## 版本

| 版本 | 日期 | 体积 | 主要变化 |
|---|---|---|---|
| [v1.4](https://github.com/zhaoxiagongsi001/sysmon-chip/releases/tag/v1.4) | 2026-11-14 | 40 KB | 开机自启真实化：失败提示、以注册表为准、路径自愈、回读校验 |
| [v1.3](https://github.com/zhaoxiagongsi001/sysmon-chip/releases/tag/v1.3) | 2026-11-14 | 38.5 KB | 剥 CRT、图标瘦身、`ExtTextOutW`，体积 −24.5% |
| [v1.2](https://github.com/zhaoxiagongsi001/sysmon-chip/releases/tag/v1.2) | 2026-11-14 | 51 KB | 修评审遗留的 8 条（写盘、诊断、回读） |
| [v1.1](https://github.com/zhaoxiagongsi001/sysmon-chip/releases/tag/v1.1) | 2026-11-14 | 49 KB | 修评审 10 条；末列右对齐 |
| [v1.0](https://github.com/zhaoxiagongsi001/sysmon-chip/releases/tag/v1.0) | 2026-11-14 | 48.5 KB | 首个公开发布；布局自适应、原子写配置、验收脚本合并 |

v0.3–v0.9 是公开发布前的内部迭代（整条任务栏改版、去掉拖动、宽度自适应、圆角、z 序修复等），更早的「v2.0」等是内部旧编号、从未公开发版，细节见 [CHANGELOG.md](CHANGELOG.md)。

## 常见问题

**双击没反应？** 大概率已经有一个实例在跑（单实例设计）：看托盘图标，或运行 `SysMonChipLite.exe --quit` 后再启动。

**任务栏上没看到资源条？** 依次排除：被托盘左键隐藏了（再点托盘图标）；当前有全屏窗口（退出全屏自动回来）；任务栏设为自动隐藏；被别的置顶窗口盖住。

**勾了开机自启，重启没起来？** 看任务管理器「启动」页里 `SysMonChip` 是否启用；刚换过 exe 路径的话，从桌面双击一次让它自愈；在降权环境里勾选会失败并弹窗。

**会不会偷偷联网/上传数据？** 不会：程序只调本机 Win32 接口（CPU、内存、磁盘、网卡统计），没有任何联网调用，也没有遥测。可以断网运行验证。

**能改字号/颜色/位置到任意坐标吗？** 不能。只有菜单里那两个位置；亚克力和拖动都已移除（见「已知限制」）。

## 许可

MIT，见 [LICENSE](LICENSE)。
