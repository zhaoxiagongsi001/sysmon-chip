# OCR 委派评审报告 · SysMonChip v0.8（commit e3f9e03）

- 工具：`open-code-review v1.13.9 (0e9060d) windows/amd64`（alibaba/open-code-review），**委派模式**（`ocr delegate preview` + `ocr delegate rule` 做确定性选文件与规则，评审由本地 agent 完成，不调用外部 LLM、无 token 成本）
- 范围：`git -C D:/DSH/sysmon-chip`，commit `e3f9e03`（v0.8）
- 评审时间：2026-11-14

## 覆盖率

| 项 | 数值 |
|---|---|
| total_files（变更文件总数） | 9 |
| reviewable_files（OCR 选中可评审） | 4 |
| reviewed_files（实际逐行评审） | 4 |
| skipped_files（OCR 排除） | 5 |
| coverage_rate | 100%（对 reviewable 口径）；其中 5 个被排除文件中，`README.md` 与 `assets/app.rc` 已由人工核对（体积/版本号改动，见 v0.8 记录），`Cargo.lock`、两个 `.exe` 无需评审 |

| skipped 文件 | 原因 | 补充 |
|---|---|---|
| `README.md` | unsupported_ext | 人工核对：体积 46.5 KB、PE 0.8.0.0 与实测一致 |
| `Cargo.lock` | unsupported_ext | 依赖未变版本，仅 app_ultra 自身版本号 |
| `app_ultra/assets/app.rc` | unsupported_ext | 人工读回 PE 资源 = 0.8.0.0 ✅ |
| `发布/SysMonChipLite.exe` | binary | — |
| `发布/SysMonChipLite-v0.8.exe` | binary | — |

## 规则组

1. `app_ultra/Cargo.toml` — Manifest Hygiene / Edition / Feature Flags / Release Metadata
2. `**/*.rs`（`app_ultra/src/app_impl.rs`、`chip_core/src/paint.rs`）— Typos / Ownership / Error Handling / Unsafe Boundaries / Concurrency / Async / Collections / API Design / Macros / Security
3. `**/*.py`（`tools/_traytest2.py`）— 含 Identity and Equality Comparisons / Dead Code / Boundary Cases / Resource Management

## 发现（8 条，行号按 e3f9e03）

### app_impl.rs · Unsafe Boundaries / Error Handling

**1. [medium] 启动器对已运行实例直接 `ShowWindow`，与实例内部状态脱节**
- path: `app_ultra/src/app_impl.rs` · start_line 1127 · end_line 1129
- content: `if let Some(h) = find_existing() { ShowWindow(h, SW_SHOW); SetWindowPos(h, HWND_TOPMOST, …); return; }`
- 问题：v0.8 引入 `hidden_by_user` 后，「是否可见」是实例自己的状态；外部 `ShowWindow` 只改窗口、不改 `hidden_by_user=true`，于是窗口亮着但实例仍以为隐藏 —— 用户点托盘第一下想「显示」时 `want==visible`，毫无反应（要连点两次）。
- 类别：Unsafe Boundaries（跨线程窗口状态）× Error Handling
- 处置：**已修（v0.8.1）** → 改为 `PostMessageW(h, WM_SHOW_CHIP, 0, 0)`，由窗口线程复位 `hidden_by_user` 后再显示；实测隐藏态二次启动后可见，且再点托盘立刻隐藏（状态已同步）。

**2. [low] `wide()` 为 63 单元的定长缓冲，超长文案被静默截断**
- path: `app_ultra/src/app_impl.rs` · start_line 1134（v0.8.1 后行号移动）· end_line 1134
- content: `MessageBoxW(…, wide("SysMonChip 已在运行（窗口丢失）。请在任务管理器结束 SysMonChipLite.exe 后重试。").as_ptr(), …)`
- 问题：该文案 55 个 UTF-16 单元，逼近 63 上限；今后在这个提示里加字会静默截句、无编译错误。
- 类别：Boundary Cases
- 处置：未修（记录）。建议下次改文案时同时把 `wide()` 换成按需分配的 `Vec<u16>`。

**3. [low] 新增 import 插在既有分组中间，破坏可读性**
- path: `app_ultra/src/app_impl.rs` · start_line 29 · end_line 37
- content: `GetMessageW, GetWindow, MessageBoxW, MB_ICONINFORMATION, MB_OK,`
- 问题：`MessageBoxW/MB_*` 插在 `GetMessageW…SetWindowPos` 的字母序列中间，并把后面的导入挤到下一行。
- 类别：Typos（风格）× API Design
- 处置：**已修（v0.8.1）** → 移到 `WNDCLASSEXW` 之后（常量/类型在末尾）。

### chip_core/paint.rs · API Design / Dead Code

**4. [low] 新增测试模块插在两个逻辑段之间，割裂文件**
- path: `chip_core/src/paint.rs` · start_line 258
- content: `#[cfg(test)] mod v08_regression { … }`
- 问题：该模块落在 `impl Texts` 之后、`配色` 段之前；测试与「配色常量」混排，后续编辑易误改。
- 类别：API Design
- 处置：未修（纯风格）。建议后续统一放到文件末尾，与既有 `mod tests` 相邻。

### app_ultra/Cargo.toml · Release Metadata / Manifest Hygiene

**5. [low] 私有可执行缺 `license` / `repository` 元数据，且与 chip_core 版本各自为政**
- path: `app_ultra/Cargo.toml` · start_line 1 · end_line 6
- content: `[package]\nname = "sysmon-chip-lite"\nversion = "0.8.0"\nedition = "2021"`（无 license/repository）
- 问题：两 crate 版本号独立演进（v0.8 前 app_ultra 还是 2.0.2、chip_core 另一条线），已导致三次版本不一致（PE 资源 / README / Cargo.toml）。缺 `license` 对私有应用无实际影响，但版本同源是真问题。
- 类别：Release Metadata
- 处置：版本已统一到 0.8.0.0（v0.8）；`license/repository` 未加（私有，记录）。建议后续把版本提到 workspace 级 `[workspace.package] version`。

### tools/_traytest2.py · Error Handling / Identity / Dead Code

**6. [medium] 回归脚本恒返回 0，失败也不会让 CI/命令失败**
- path: `tools/_traytest2.py` · start_line 38 · end_line 44
- content: `print("RESULT:", "PASS" if failed == 0 else "FAIL"); return 0`
- 问题：`ok` 只被打印，失败计数 `failed` 从未影响退出码 —— 脚本作为「回归测试」没有约束力。
- 类别：Error Handling
- 处置：**已修（v0.8.1）** → 失败返回 1，并打印 `RESULT: PASS/FAIL`；实测通过路径 exit 0。

**7. [medium] `PostMessageW` 返回值未校验，进程已死时会读到旧状态并假通过**
- path: `tools/_traytest2.py` · start_line 27
- content: `u32.PostMessageW(hwnd, TRAY_CB, 0, WM_LBUTTONUP)`
- 问题：目标进程消亡后句柄失效，`PostMessageW` 返回 0，但脚本继续采样 → 窗口属性未变 → 断言「保持在隐藏」反而通过，掩盖真实故障。
- 类别：Error Handling
- 处置：**已修（v0.8.1）** → 返回值失败即打印 `get_last_error()` 并 return 1。

**8. [low] 用 `is` 做布尔身份比较**
- path: `tools/_traytest2.py` · start_line 42
- content: `ok = len(samples) == 2 and samples[-1][1] is desired`
- 问题：`desired` 由 `phase == 1` 生成，小整数布尔在 CPython 下恰好可用，但 `is` 比较值属实现细节（Identity and Equality Comparisons）。
- 类别：Identity and Equality Comparisons
- 处置：**已修（v0.8.1）** → 改 `==`。

## 结论

- 4/4 reviewable 文件逐行评审，8 条发现：medium 3 条（1 条跨进程状态、2 条测试脚本有效性）、low 5 条。
- **已修 5 条**（1、3、6、7、8），**留档 3 条**（2 文案上限、4 测试位置、5 元数据/版本同源），均已写入本报告与 README 的 v0.8/v0.8.1 说明。
- 无 High/Critical：无内存安全、无 UB、无资源泄漏。unsafe 块均为 Win32 调用且参数已按 API 约定校验。
- 修复后验证：`cargo test` 5 passed；`_traytest2.py` PASS（20.5 ms 隐藏、稳定 3 s）；启动器二次启动状态同步验证通过；exe 仍 47616 B。
