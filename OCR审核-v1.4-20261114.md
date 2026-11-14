# OCR 委派评审 —— SysMonChip v1.4（开机自启真实化）

- 评审时间：2026-11-14 18:5x
- 评审工具：`alibaba/open-code-review` v1.13.9，**委派模式**（`ocr delegate preview` 选文件 + `ocr delegate rule` 给规则，评审由宿主 agent 完成）
- 评审范围：工作区改动（`ocr delegate preview --format json`，mode=workspace）
- 覆盖：**total 8 / reviewable 5 / reviewed 5 / skipped 3 / coverage 100%**
- 结论：**无 Critical / High / Medium**；8 条 Low，均为可记录项，不阻塞发布

## 1. 文件清单

| 文件 | 变更 | 结论 |
|---|---|---|
| `app_ultra/src/config.rs` | +108 −8 | 审完，4 条 Low |
| `app_ultra/src/app_impl.rs` | +20 −1 | 审完，1 条 Low |
| `app_ultra/src/main.rs` | +25 −2 | 审完，1 条 Low |
| `app_ultra/Cargo.toml` | +1 −1 | 审完，无问题（仅版本号） |
| `chip_core/Cargo.toml` | +1 −1 | 审完，无问题（仅版本号） |
| `app_ultra/Cargo.lock` | +2 −2 | 跳过：`unsupported_ext`（锁文件，版本号同步变更） |
| `chip_core/Cargo.lock` | +1 −1 | 跳过：`unsupported_ext`（同上） |
| `app_ultra/assets/app.rc` | +4 −4 | 跳过：`unsupported_ext`；人工核对：`1,4,0,0` / `"1.4.0.0"` 四字段一致 |

应用规则组：`**/Cargo.toml`（清单卫生 / edition / 发布元数据）、`**/*.rs`（拼写、所有权、错误处理与 panic、unsafe 边界与 FFI、并发、热路径分配、类型设计、宏、安全敏感）。

## 2. 发现（按严重度）

### L1 [low] 新增 unsafe 块缺 SAFETY 注释
- path: `app_ultra/src/config.rs` · content: `unsafe` 边界说明缺失 · start_line: 568 · end_line: 700 · category: Unsafe Boundaries · severity: low
- 说明：`autostart_points_to_current()`、`probe_run_access()`、`set_autostart_diag()` 里每个 `unsafe {}` 都没有不变量说明。文件既有风格确实如此（全文件仅 `create_window` 一处 SAFETY），但按规则应补。
- 处置：记录，下次重构时统一补（不在本次发布前动）。

### L2 [low] 超长值时 `points_to_current` 退化为 None
- path: `app_ultra/src/config.rs` · start_line: 578 · end_line: 592 · category: Error Handling · severity: low
- 说明：`RegQueryValueExW` 在值超过 512 个 UTF-16 单元时返回 `ERROR_MORE_DATA(234)`，函数返回 `None`（未知）而非 `Some(false)`，因此不会被启动自愈。实际 exe 路径远小于该上限，属理论缺口。
- 处置：记录。

### L3 [low] KEY_ALL_ACCESS 试探可能触发审计
- path: `app_ultra/src/config.rs` · start_line: 647 · end_line: 668 · category: Security-Sensitive · severity: low
- 说明：`probe_run_access()` 用 `KEY_SET_VALUE / KEY_WRITE / KEY_ALL_ACCESS / KEY_READ` 依次打开 Run 键；在启用注册表审核策略的机器上会产生额外审计事件。该函数只在 `--autostart-on/off` 诊断路径调用。
- 处置：记录（诊断路径成本可接受）。

### L4 [low] 诊断码 `rc_write=0` 有歧义
- path: `app_ultra/src/config.rs` · start_line: 661 · end_line: 690 · category: API Design · severity: low
- 说明：`GetModuleFileNameW` 失败时返回 `(false, 0, 0)`，与「打开键成功但未写值」的 `rc_write=0` 在诊断文件里无法区分。
- 处置：记录；`rc_open` 仍能区分「没权限」这一主要场景。

### L5 [low] 菜单每次弹出都读注册表
- path: `app_ultra/src/app_impl.rs` · start_line: 800 · end_line: 803 · category: Performance · severity: low
- 说明：`on_menu()` 每次调用 `autostart_points_to_current()`（`RegOpenKeyExW` + `RegQueryValueExW` + `GetModuleFileNameW`），每次约几十微秒。
- 处置：有意为之（勾选必须真实），不优化。

### L6 [low] 三态压成两态
- path: `app_ultra/src/app_impl.rs` · start_line: 800 · end_line: 803 · category: Type Design · severity: low
- 说明：`points_to_current` 的 `None`（读不到）与 `Some(false)`（指向别处）在菜单里都表现为「未勾」，语义可接受，但诊断价值丢失。
- 处置：记录。

### L7 [low] 构建不可比特复现
- path: （构建侧，非源码） · category: Reproducibility · severity: low
- 说明：同一份源码重新链接，exe 的 SHA256 每次都不同（本次实测：`8CECCF30…` → `E41EEC17…` → `E0E8D394…`，体积恒为 40960 B）。ld 未传 `--build-id=none`，且链接命令行含时间戳。
- 处置：记录；发布校验以「体积 + PE 版本资源 + 功能回归」为准，不以跨构建 SHA 相等为准。

### L8 [low] `%TEMP%` 留痕无清理策略
- path: `app_ultra/src/app_impl.rs` · start_line: 1415 · end_line: 1419 · category: Resource Management · severity: low
- 说明：自愈成功时每次启动写 `sysmonchip-autostart-heal.txt`（8 字节覆盖写，不增长），但与 `sysmonchip-save-error.txt`、`sysmonchip-net-clipped.txt` 一样没有清理机制，长年累积的是文件数而非体积（每个文件名固定）。
- 处置：记录。

## 3. 已核对无问题

- 写入值仍是 `"<exe>" --autostart`，与 v1.3 已存在的注册表项兼容（旧值会被识别为 `Some(true)`）。
- 关闭时把 `ERROR_FILE_NOT_FOUND(2)` 也当成功，删除幂等。
- 自愈是短路径求值：`registered == false` 时不会调用 `set_autostart`，不会误写。
- 失败弹窗文案 26 个 UTF-16 单元，未触及 `wide()` 的 63 上限。
- 命令 43 失败分支不会把 `cfg.autostart` 置真，菜单不会虚勾。
- 新增代码无 `unwrap()` / `expect()` / `panic!`；缓冲均为定长数组，写入前有长度判断。
- 版本三处一致：`app_ultra/Cargo.toml` 1.4.0 · `chip_core/Cargo.toml` 1.4.0 · `app.rc` 1,4,0,0 / `"1.4.0.0"`（PE 资源 read-back 实测 1.4.0.0）。

## 4. 回归实测（本次发布的 exe）

| 项 | 结果 |
|---|---|
| `cargo test` | 16 passed |
| `tools/verify.py layout` | PASS（491 / 317 / 221 物理 px；右下角 `rect=(3235,1946,3456,2052)`） |
| `tools/verify.py padding` | PASS（左右留白对称，容差 4 px） |
| `tools/verify.py region` | PASS（rgn type=3，`box=(0,0)-(491,107)`） |
| `tools/verify.py tray` | PASS（隐藏 5.2 ms / 显示 5.4 ms） |
| 体积 / PE | 40960 B（40.0 KB）/ 1.4.0.0 |
| 自启写入（沙箱低权限） | 预期失败：`rc_open=5`，`probe=5/5/5/0` |
| 自启写入（Medium，计划任务 `reg add` 同键） | 成功（证明键可写，失败源自完整性级别） |
