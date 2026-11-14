# OCR 委派评审 · v1.2（2026-11-14）

评审工具：alibaba/open-code-review v1.13.9（`ocr delegate` 委派模式，宿主 agent 评审）
提交范围：`07ca831..510c005`（v1.1 报告 → v1.2 修复）
评审人：DSH 独立验证助手（lead）

## 覆盖率

| 指标 | 数值 |
| --- | --- |
| total_files | 12 |
| reviewable_files | 6 |
| reviewed_files | 6 |
| skipped_files | 6 |
| coverage_rate | 100%（对可评审文件） |
| diff 规模 | +200 −26 |

可评审文件 6 个，全部逐行审完：

| path | diff |
| --- | --- |
| `app_ultra/Cargo.toml` | +1 −1 |
| `app_ultra/src/app_impl.rs` | +80 −8 |
| `app_ultra/src/config.rs` | +36 −3 |
| `chip_core/Cargo.toml` | +1 −1 |
| `chip_core/src/paint.rs` | +40 −0 |
| `tools/verify.py` | +15 −3 |

跳过 6 个（OCR 判定不可评审，均在人工侧核对）：`README.md`、`app_ultra/Cargo.lock`、`chip_core/Cargo.lock`、`app_ultra/assets/app.rc`（unsupported_ext：版本号 1,2,0,0 已对 PE 回读确认）；`发布/SysMonChipLite.exe`、`发布/SysMonChipLite-v1.2.exe`（binary：已核对 PE 1.2.0.0 / 52224 B）。

规则组：`**/*.rs`（错误处理与 panic、unsafe 边界与 FFI 校验、所有权、热路径分配、类型设计）、`**/Cargo.toml`（清单卫生、发布元数据）。

## 发现（本轮 5 条，全部当场修复）

| # | severity | path:line（修复前） | category | 问题 | 处置 |
| --- | --- | --- | --- | --- | --- |
| W1 | low | `app_ultra/src/app_impl.rs:533-536` | API Design / Docs | 插入 `report_save_failed` 时把 `persist` 的文档注释留在了它上方，rustdoc 会挂到错误的函数上，`persist` 反而没有注释 | 已修：注释下移回 `persist`，新函数自带注释 |
| W2 | low | `app_ultra/src/app_impl.rs:535-540` | Diagnostics | 诊断文件头部写 `err=` 却紧跟指标列表，标签与实际内容不符，排障时会误读 | 已修：改为 `items=` 列表 + 单独一行 `last_error=` |
| W3 | low | `app_ultra/src/app_impl.rs:558` | Error Handling | `GetLastError()` 在拼完整个缓冲区之后才取，中间任何 Win32 调用都会覆盖它，错误码基本没意义 | 已修：`save()` 返回 false 后立刻取样，作为参数传入 |
| W4 | low | `app_ultra/src/config.rs:351-368` | Boundary Cases | `.tmp` 回读只覆盖「主文件完全读不到」；主文件若是直写中途断电留下的半截，仍然信它并丢掉 `.tmp` 里的完整配置 | 已修：主文件与 `.tmp` 都读，取更完整（字节更多）的一份；主文件已读满缓冲区时早退省一次打开 |
| W5 | low | `tools/verify.py:199-202` | Test Robustness | 容差 2 px 把「末位数字字形不同」的正常抖动（实测 18/21 → 差 3 px）判成失败，会反复假红 | 已修：容差 4 px（≈1.8 逻辑 px），注释写明右对齐对齐的是字宽、而脚本量的是墨迹 |

结论：**无 Critical / High / Medium**；W1–W5 已在本提交内修完，`cargo test` 16 项通过，`tools/verify.py layout|padding|region|tray` 全绿。

## 已核对无问题的部分

- `paint::Layout::last_on()`、`paint::arrow_fits()` 是纯函数，只有一处几何来源，且各有单测（`last_on_follows_the_rightmost_enabled_item`、`arrow_fits_only_when_it_stays_left_of_the_text`）。
- `net_group_x` 同时夹 `text_x` 与 `arrow_x` 到列左缘，与 `arrow_fits` 判定自洽；测试覆盖「放得下 / 正好贴边 / 夹死」三种边界。
- `write_file` 的所有权：`CreateFileW` 失败早退；`CloseHandle` 返回值参与判定；改名成功后不再碰 `.tmp`；直写失败时**故意保留** `.tmp`（有注释说明）。
- `read_path` 拆分后没有改变原 `read_config` 的关闭路径（`CloseHandle` 在两条返回路径前都已调用）。
- 新增诊断只写 `%TEMP%`，不写配置文件目录，不参与启动路径，失败也不影响主循环（`write_temp` 返回值被忽略且无副作用）。
- 版本三元组一致：`app_ultra/Cargo.toml` 1.2.0、`chip_core/Cargo.toml` 1.2.0、`assets/app.rc` 1,2,0,0 / "1.2.0.0"，PE 回读 1.2.0.0。

## 记录但未改（可接受）

1. `net_clipped` 每次会话最多落一份诊断，超宽恢复后复位——按设计。
2. `budget` 用当前 `interval` 计算，用户中途改刷新间隔会让预算跳变——影响仅在「放弃重试」的时机，可接受。
3. `Layout` 单测用结构体字面量构造，将来加字段要同步改测试——结构体本身即布局契约，可接受。
4. `verify.py` 的失败文案是中文，GBK 控制台按 UTF-8 解码会显示乱码（仅影响观感，不影响判定结果）。
5. V8（`.appdata-test/` 曾进过历史）：已随 v1.1 tag 发布，**不改写已发布历史**，仅在 `.gitignore` 与新提交中保证不再出现。

## 实测（PE 1.2.0.0，52224 B，3456×2160 @225%）

| 项 | 结果 |
| --- | --- |
| 布局 | 全开 218 逻辑（491 物理）→ 关网速 141（317）→ 再关磁盘 98（221） |
| 对齐 | 桌面右下角右缘锁 3456；任务栏左端左缘恒为 0 |
| 留白 | 左 8.0 逻辑 / 右 8.9–9.3 逻辑（≤4 物理 px 差） |
| 圆角 | `GetWindowRgn` type=3，box (0,0)-(491,107)，贴屏侧方角、外露侧圆角 |
| 托盘 | 隐藏 5.1 ms / 显示 5.4 ms，各自稳定 |
| 单测 | 16 passed |
| 配置 | `--selftest` 往返 ok；`.tmp` 回读两场景（主截断 / tmp 更短）行为正确 |
