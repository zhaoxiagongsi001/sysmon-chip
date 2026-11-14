# OCR 委派评审 · SysMonChip v1.1

- **评审工具**：alibaba/open-code-review（`ocr` v1.13.9）委派模式——OCR 只做确定性的选文件与规则解析，逐行评审由宿主 agent 完成
- **评审范围**：`d4674fe..b0e8729`（v1.0 发布后 → v1.1 完成）
- **评审时间**：2026-11-14
- **结论**：**无 Critical / 无 High / 无 Medium**；8 条 Low，均为注释口径、失败路径与脚本细节，不阻塞 v1.1 发布。

## 覆盖率

| 指标 | 值 |
| --- | --- |
| total_files | 16 |
| reviewable_files | 7 |
| reviewed_files | 7 |
| skipped_files | 9 |
| coverage_rate | 100%（7/7） |
| 变更规模 | +165 / −43 |

排除的 9 个文件及原因：`unsupported_ext` 6 个（2 个 README/评审报告 md、2 个 Cargo.lock、1 个 app.rc、1 个 .gitignore 之外的文本）、`binary` 3 个（2 个 exe、1 个 shot.png）。README 与 .gitignore 已人工核过。

## 逐文件评审

| 文件 | 变更 | 结论 |
| --- | --- | --- |
| `.gitignore` | +3 | 通过（`.appdata-test/` 与 target 同类临时产物） |
| `app_ultra/Cargo.toml` | +1−1 | 通过（1.0.0 → 1.1.0，与 PE 资源一致） |
| `app_ultra/src/app_impl.rs` | +43−5 | 3 条 Low |
| `app_ultra/src/config.rs` | +48−11 | 2 条 Low |
| `chip_core/Cargo.toml` | +1−1 | 通过 |
| `chip_core/src/paint.rs` | +35−11 | 2 条 Low |
| `tools/verify.py` | +8−1 | 1 条 Low |

## 发现（8 条，全部 Low）

### V1 · 注释口径与刷新间隔耦合

- `path`: `app_ultra/src/app_impl.rs` · `content`: `on_timer` 的写盘重试 `if self.save_tries >= 120` · `start_line`: 550 · `end_line`: 553 · `category`: 文档/注释一致性 · `severity`: low

  注释写「连续失败约两分钟就放弃」，但重试发生在 1 秒定时器里；用户把刷新间隔改成 5 秒后，120 次实际是 **10 分钟**。建议改成「最多 120 次（默认刷新间隔下约两分钟）」，或按 `interval` 换算次数。

### V2 · 写盘失败没有可观测性

- `path`: `app_ultra/src/app_impl.rs` · `content`: `persist()` · `start_line`: 533 · `end_line`: 537 · `category`: 错误处理 · `severity`: low

  `cfg.save()` 返回 false 时只置 `save_pending`，重试用尽后静默丢弃。程序里有 `trace_write` 与 `write_temp`，建议在放弃时落一行诊断（或 `--trace` 模式下打一条），否则「设置改完重启又变回去」无法归因。

### V3 · 兜底写盘失败即终止

- `path`: `app_ultra/src/config.rs` · `content`: `write_file` 末段的 `write_direct(path, data)` · `start_line`: 441 · `end_line`: 445 · `category`: 错误路径 · `severity`: low

  改名失败 → 直接覆盖写，若覆盖也失败则本次设置丢失、且可能留下截断文件（v1.0 的老行为）。属降级路径、影响有限；可考虑「覆盖失败就保留 `.tmp` 供下次启动读取」。

### V4 · 超宽读数走「截断」分支

- `path`: `chip_core/src/paint.rs` · `content`: `net_group_x` 的 `(right - text_w.max(0)).max(min_x)` · `start_line`: 59 · `end_line`: 61 · `category`: 边界处理 · `severity`: low

  数字超宽时被夹到列左缘，右侧由绘制矩形裁掉——会切掉「MB/s」后缀。当前不可达（紧凑格式最宽 148 px < 预算 150 px，且有单测与 `verify.py padding` 兜底），保留作防御可以，但注释里的「宁可裁掉右端」应有对应的可观测手段（例如 `--trace` 记一次）。

### V5 · 末列判定与固定列序强耦合

- `path`: `app_ultra/src/app_impl.rs` · `content`: `let last_on = (0..4).rev().find(|&i| lay.on[i]).unwrap_or(0);` · `start_line`: 466 · `end_line`: 466 · `category`: 类型设计 · `severity`: low

  `Layout.on` 是 4 元数组且第 4 项固定是网速，与 `cells` 的前三项靠人脑对齐。将来加列必须同步三处（`ITEM_W`、`layout`、`render`）。建议把「末列 = 最后一个 `on` 为真的列」封装进 `paint::Layout`，例如 `pub fn last_on(&self) -> Option<usize>`。

### V6 · 箭头重叠判定是渲染期的临时补丁

- `path`: `app_ultra/src/app_impl.rs` · `content`: `if up_ax + aw <= up_x { … }` · `start_line`: 506 · `end_line`: 511 · `category`: 边界处理 · `severity`: low

  真正的解是让 `net_group_x` 直接返回「是否放得下箭头」，渲染层不必知道几何。现在两处都判断一次，逻辑分散。

### V7 · 早退后未回读确认现场已还原

- `path`: `tools/verify.py` · `content`: `check_layout` 的早退分支 · `start_line`: 113 · `end_line`: 117 · `category`: 边界/副作用 · `severity`: low

  L7 修法会补发一次 `CMD_NET` 与（必要时）`CMD_DESKTOP`，但没有回读宽度确认真的恢复了。建议追加 `if size(h)[0] != before: fails.append("现场还原失败")`。

### V8 · `.gitignore` 规则晚于提交

- `path`: `.gitignore` · `content`: 新增 `.appdata-test/` · `start_line`: 1 · `end_line`: 8 · `category`: 仓库卫生 · `severity`: low

  `80d3a94` 曾把 `.appdata-test/SysMonChip/config.ini` 提交进库，随后 `8fe10ab` 才 `git rm --cached`。文件仍留在历史里（内容只是测试用的两行配置，无敏感信息）；如在意可在发布前 squash。

## 已核对无问题

- `save()` 的签名改动（`()` → `bool`）在全部 3 个调用点都处理了返回值，无忽略、无 `unwrap`。
- `write_file` 的临时文件在同目录，`MoveFileExW` 为同卷原子改名；失败分支会删除 `.tmp`，实测目录无残留（`.appdata-test` 验证：`config_roundtrip=ok`，无 `.tmp`）。
- `CloseHandle` 与 `WriteFile` 的返回值都参与判定，`written` 与 `data.len()` 严格比对。
- `write_direct` 的空指针/长度参数与 `write_file` 一致（`CreateFileW` + `WriteFile`，缓冲区来自栈上定长数组）。
- `persist()` 只在用户改设置（拖拽结束、菜单命令）与重试路径调用，不在渲染热路径；`on_timer` 的重试是每 tick 一次、有上限，不会造成写放大。
- `net_group_x` 的 3 个用例（正常 / 超宽 / 空文本）与新建的 KB 进位用例共 14 项单测全绿；`set_rate_compact` 的 KB→MB 进位不会产生 0（`.max(1)`）。
- `render` 末列右对齐后，`draw_text` 的宽度参数取整格 `ITEM_W[i]`，右缘与网速列一致落在「面板宽 − PAD_R」，`verify.py padding` 在四种指标组合下实测 19/18–20 px。
- `check_layout` 早退分支不再留下「网速被打开」的副作用，`verify.py layout|padding|region|tray` 连跑 4 次全 PASS。

## 建议处置

全部 8 条都不影响功能与安全，建议合并进 v1.2 的工程化批次：V1/V2 一起改（写盘可观测性 + 注释口径），V5/V6 一起改（把末列与箭头判定收进 `paint`），V7/V8 随手补。
