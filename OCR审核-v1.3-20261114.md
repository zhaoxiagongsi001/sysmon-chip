# OCR 委派评审 · v1.3（2026-11-14）

- 评审对象：commit `e21b573 v1.3: 剥 mingw CRT、图标瘦身、ExtTextOutW 绘制`
- 模式：`ocr delegate preview` 选文件 + 规则，评审由本会话模型执行（不调外部 LLM）
- 覆盖率：**total 16 / reviewable 7 / reviewed 7 / skipped 9 / coverage 100%**
- 结论：**无 Critical / High / Medium，7 条 Low，全部为可接受或已记录项；不阻塞发布**

## 1 范围

| path | 状态 | 行数 | 评审 |
| --- | --- | --- | --- |
| `app_ultra/src/main.rs` | modified | +63 −0 | ✅ |
| `app_ultra/src/app_impl.rs` | modified | +20 −4 | ✅ |
| `tools/ld_wrap.py` | added | +82 | ✅ |
| `tools/build.ps1` | added | +46 | ✅ |
| `tools/ab_bench.py` | added | +112 | ✅ |
| `app_ultra/Cargo.toml` | modified | +1 −1 | ✅（版本号 1.2.0→1.3.0） |
| `chip_core/Cargo.toml` | modified | +1 −1 | ✅（同上） |

跳过 9 个：`README.md`、`app_ultra/Cargo.lock`、`chip_core/Cargo.lock`、`app_ultra/assets/app.rc`、`app_ultra/assets/icon.ico`、`tools/ldw.cmd`（2 行转发脚本）、`发布/SysMonChipLite.exe`、`发布/SysMonChipLite-v1.3.exe`（二进制）、`研究报告-体积与占用-2026-11-14.md`（文档）。README 与研究报告由人工核对。

规则组：`**/*.rs`（错误处理/unsafe 边界/热路径分配/类型设计）、`**/*.{py,pyi}`（死代码/边界/异常/资源/`is` 比较/安全）、`**/Cargo.toml`（清单卫生）。

## 2 发现

### T1 [low] mem* 替换实现没有空指针与重叠校验

- `app_ultra/src/main.rs:38-86`：新增 `memcpy/memmove/memset/memcmp`，按 C 运行时契约不校验参数。
- 影响：仅当编译器/链接器把越界或空指针调用降级到这里才会崩；当前所有调用点来自 Rust 自身的已知有效切片，风险可接受。
- 处置：保留现状，注释已说明「剥 CRT 后必须自带」。

### T2 [low] mem* 逐字节实现，大块拷贝无 SIMD

- 同一位置：四个函数都是 `while i < n` 单字节循环。
- 影响：当前最大拷贝是配置缓冲（1 KB）与指标结构（几十字节），实测无性能影响；若将来引入大缓冲需换成 `rep movsb` 或分块。
- 处置：记录，暂不改。

### T3 [low] `ExtTextOutW` 返回值未检查

- `app_ultra/src/app_impl.rs:draw_text`：`GetTextExtentPoint32W` 失败会 `return`，但 `ExtTextOutW` 的 BOOL 丢弃。
- 影响：GDI 出字失败本就没有可恢复动作（与改前的 `DrawTextW` 行为一致），不新增风险。
- 处置：保留。

### T4 [low] `ld_wrap.py` 的 `detect()` 在导入期调用 rustc

- `tools/ld_wrap.py:15-33`：`subprocess.run(["rustc","--print","target-libdir"])`，失败时静默退回 `"ld"`。
- 影响：rustc 不在 PATH 时会用系统 ld，报错信息会变成 ld 的「找不到库」，不易定位。
- 处置：记录；`build.ps1` 会先 dot-source `env.ps1`，正常路径已覆盖。

### T5 [low] 参数过滤用整串正则

- `tools/ld_wrap.py:16-19`：`DROP_ARG` 匹配的是整条参数文本，若某个 `-L` 目录名恰好含 `crt2.o` 字样会被误删。
- 影响：只在极端路径命名下触发；本机路径不含该串。
- 处置：记录。

### T6 [low] `ab_bench.py` 会杀掉所有 SysMonChip* 进程

- `tools/ab_bench.py:kill_all`：按映像名前缀 `sysmonchip` 枚举并 `TerminateProcess`。
- 影响：这是基准脚本的设计目的（单实例互斥会让新进程静默退出），但会连带结束老板正在用的实例。
- 处置：仅限开发测量使用，README 不推荐日常运行。

### T7 [low] `build.ps1` 通过改 mtime 强制重链

- `tools/build.ps1`：`(Get-Item "src/main.rs").LastWriteTime = Get-Date`，文件只读时会抛错。
- 影响：本仓库文件可写；CI/只读挂载场景需改造。
- 处置：记录。

## 3 已核对无问题

- `chip_entry`：`ExitProcess` 在 `-> !` 分支上，返回类型一致；入口点由链接器参数指定，PE 实测 `AddressOfEntryPoint` 落在 `.text`。
- `draw_text` 的新几何：右对齐 `x + w - sz.cx`、垂直居中 `y + (h - sz.cy)/2`，与 `DT_RIGHT | DT_VCENTER` 语义一致；截图逐像素核对无差异。
- `ld_wrap.py` 的库处理顺序：`-l` 统一挪到对象文件之后（ld 的从左到右解析要求），必需库去重后补齐。
- `ab_bench.py`：`EnumProcesses` 走 psapi（kernel32 无此导出）、按 token 解析 bench 输出、中位数统计。
- `build.ps1`：点源 `env.ps1` 会覆盖 `$PSScriptRoot`，已改用 `$MyInvocation.MyCommand.Path` 计算根目录。
- 两个 `Cargo.toml`：仅版本号变化，`license`/`repository` 已在 v1.0 补全。
- 版本一致性：`Cargo.toml` 1.3.0、`app.rc` 1,3,0,0、PE 资源回读 1.3.0.0 —— 三处一致。

## 4 与发布相关的证据

| 项 | 值 |
| --- | --- |
| 体积 | 52 224 → **39 424 B（−24.5%）** |
| 导入 | 8 DLL → **7 DLL**，`msvcrt.dll` 与重复的 `KERNEL32.dll` 消失 |
| PE 版本 | 1.3.0.0 |
| SHA256 | `7611952470F9A487220D1816526C3EA3422F8715F195F3DB5E66D861A1C65816` |
| 单测 | 16 passed |
| 功能回归 | `verify.py layout/padding/region/tray` 全 PASS（宽度 491/317/221、rgn type=3、托盘 5.5/5.4 ms） |
