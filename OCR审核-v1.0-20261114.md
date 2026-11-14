# OCR 工程评审 —— SysMonChip v1.0

- **评审工具**：alibaba/open-code-review v1.13.9（`ocr delegate preview` + `ocr delegate rule`，委派模式：OCR 只做确定性选文件与规则解析，评审由本会话模型执行）
- **评审范围**：`c20265a`（v0.9.1）→ `76822c8`（v1.0 首帧修复），即提交 `3777e4b`、`60b2a97`、`76822c8`
- **评审时间**：2026-11-14
- **结论**：**无 Critical / 无 High / 无 Medium**；10 条 Low，均为文档与失败路径的边角，不影响 v1.0 发布。发布后建议在 v1.1 一并清掉。

## 覆盖率

| 项 | 数量 |
|---|---|
| total_files（变更文件） | 50 |
| reviewable_files（进入评审） | 9 |
| reviewed_files（逐行审完） | 9 |
| skipped_files（跳过） | 41 |
| coverage_rate | **9/9 = 100%** |
| 变更量 | +649 / −2082 |

跳过原因：`deleted` 32（删除的一次性探针脚本，已由 `tools/verify.py` 取代）、`unsupported_ext` 6（`README.md`、`OCR审核-*.md`、`Cargo.lock`）、`binary` 2（`发布/*.exe`）、`default_path` 1（`发布/启动 SysMonChip.cmd`）。README 与启动器已人工核对，未发现与代码不一致。

## 逐文件评审

| 文件 | 变更 | 结论 |
|---|---|---|
| `LICENSE` | +21 | 标准 MIT 全文，年份与署名 `2026 zhaoxiagongsi001` 与三个 `Cargo.toml` 的 `license = "MIT"` 一致，无问题 |
| `app/Cargo.toml` | +3−1 | 补 `license`/`repository` 正确；版本 1.1.2→0.3.0 见 L8 |
| `app/src/wnd.rs` | +13−4 | 布局常量本地化 + `Fonts::create(self.dpi as i32)` 两处类型对齐，改动最小、语义正确，无问题 |
| `app_ultra/Cargo.toml` | +3−1 | 同上，无问题 |
| `app_ultra/src/app_impl.rs` | +51−18 | 网速组排布改走缓存 + `net_group_x`、预算由常量推导、初始宽度改用 `layout()`、首帧兜底测量；逻辑正确，见 L3 |
| `app_ultra/src/config.rs` | +27−3 | 临时文件 + `MoveFileExW` 原子替换，路径拼接与长度校验正确；见 L4、L5、L6 |
| `chip_core/Cargo.toml` | +3−1 | 同上，无问题 |
| `chip_core/src/paint.rs` | +107−16 | `ITEM_W[3]=77`、`NET_ARROW_W`/`NET_GAP`、`net_group_x`、GB 档与 3 条新单测；公式与边界正确，见 L1、L2、L9 |
| `tools/verify.py` | +302 | 五项自检替代 32 个一次性脚本，退出码语义正确、采样与判定合理；见 L7、L10 |

## 发现（10 条，全部 Low）

### L1 网速数字超宽时未被夹住，只夹了箭头
- `path`: `chip_core/src/paint.rs` · `content`: `net_group_x` · `start_line`: 56 · `end_line`: 66 · `category`: 边界与越界 · `severity`: low
- 函数注释写「即使数字宽度超出预算也不会压到左边的磁盘列」，实际只对 `arrow_x` 取 `max(min_x)`；`text_x = right - text_w` 不设下限（`net_group_x_keeps_arrow_inside_column` 里 `text_x == -77` 就是数字左溢 77px）。数字真超宽时会压进磁盘列。
- 可达性：正常路径靠 `on_timer` 的紧凑化兜底；只有 `set_rate_compact` 之后仍超宽才触发（见 L9）。
- 建议：`text_x = text_x.max(min_x)`，或把注释改成「箭头不越界，数字由上游预算保证」。

### L2 `set_rate` 的文档与实现不符（GB 档）
- `path`: `chip_core/src/paint.rs` · `content`: 文档注释 · `start_line`: 171 · `end_line`: 172 · `category`: 文档/可读性 · `severity`: low
- 注释写「数值 >=100 时去掉小数位，保证网速列宽度有上界」，但 GB 档的判据是 `tenths < 1000`，即 `15.0 GB/s` 仍带一位小数，到 ≥100 GB/s 才取整。
- 建议：把注释改成「MB 档 >=100 去小数；GB 档 >=100 GB 去小数」。

### L3 新增的裸指针解引用没有 SAFETY 说明
- `path`: `app_ultra/src/app_impl.rs` · `content`: `create_window` 取面板宽度 · `start_line`: 1213 · `end_line`: 1213 · `category`: unsafe 边界 · `severity`: low
- `let w = scale((*app_ptr).w, ...)`：`app_ptr` 由 `run()` 传入且保证指向栈上 `App`，但该 `unsafe fn` 没有注释说明这个前提（文件内其它 `unsafe fn` 通篇如此，本次属新增代码）。
- 建议：加一行「`// SAFETY: run() 保证 app_ptr 指向存活的 App`」。

### L4 `MoveFileExW` 未要求写穿透
- `path`: `app_ultra/src/config.rs` · `content`: 原子替换 · `start_line`: 426 · `end_line`: 430 · `category`: 资源/崩溃一致性 · `severity`: low
- 只加了 `MOVEFILE_REPLACE_EXISTING`，没加 `MOVEFILE_WRITE_THROUGH`：断电时改名元数据仍可能丢失。相比原来「写到一半覆盖」已是实质改进，但不构成完整事务。
- 建议：补 `MOVEFILE_WRITE_THROUGH`（单次写盘成本，可忽略）。

### L5 `CloseHandle` 的失败没检查
- `path`: `app_ultra/src/config.rs` · `content`: `write_file` · `start_line`: 421 · `end_line`: 421 · `category`: 错误处理 · `severity`: low
- `CloseHandle(h)` 的返回值被丢弃；若延迟写回失败，`WriteFile` 可能已报成功，最终数据不完整。
- 建议：`if CloseHandle(h) == 0 { DeleteFileW(tmp); return false; }`。

### L6 配置写盘失败对用户完全静默
- `path`: `app_ultra/src/config.rs` · `content`: `Config::save` → `write_config` · `start_line`: 195 · `end_line`: 195 · `category`: 错误处理 · `severity`: low
- `write_config` 返回 `()`，`write_file` 的 `false` 被吞掉。v1.0 之后写盘多了两条失败路径（临时文件写失败、目标被占用导致改名失败），菜单勾选看起来生效、重启后却还原，用户无任何提示。

### L7 `check_layout` 早退分支留下副作用
- `path`: `tools/verify.py` · `content`: `check_layout` · `start_line`: 106 · `end_line`: 111 · `category`: 边界/副作用 · `severity`: low
- 起始状态网速是关的时候：先 `cmd(h, CMD_TASKBAR)` 切了模式，再 `toggle_off(CMD_NET)` 把网速**打开**，然后直接 `return fails`，不恢复配置。下次运行时的初始状态已被改变。
- 建议：早退前把 `CMD_NET` 再按一次、`CMD_TASKBAR` 恢复。

### L8 `app` 版本号降级
- `path`: `app/Cargo.toml` · `content`: `version` · `start_line`: 3 · `end_line`: 3 · `category`: 清单/发布元数据 · `severity`: low
- `1.1.2 → 0.3.0` 是版本降级。本项目未 `cargo publish`，只是让 std 壳与其 `app.rc` 的 0.3.0.0 对齐，本地无影响；若将来发布，同名 crate 已存在 1.1.2 会让 0.3.0 无法上传。
- 建议：保持现状但在 README 注明「std 壳冻结于 0.3.0，不再发布」。

### L9 1000–1023 KB/s 一段紧凑格式压不进预算
- `path`: `chip_core/src/paint.rs` · `content`: `set_rate_compact` KB 档 · `start_line`: 219 · `end_line`: 225 · `category`: 边界与越界 · `severity`: low
- KB 档紧凑格式取整后仍是 4 位数："1023 KB/s" 实测 156 px（225%），而 `ITEM_W[3]=77` 给文字的预算是 151 px → 数字溢出 5 px，箭头被夹到列左缘后与数字重叠 1 px。
- 可达区间很窄（仅 1,024,000–1,048,575 B/s，约 24 KB/s 宽），持续 1 个刷新周期即过。
- 建议：KB 档在 `kb >= 1000` 时改用 `"1.0 MB/s"` 形式（或直接沿用 MB 分支四舍五入）。

### L10 `check_padding` 注释与重试次数不符
- `path`: `tools/verify.py` · `content`: `check_padding` docstring · `start_line`: 171 · `end_line`: 171 · `category`: 文档/可读性 · `severity`: low
- 注释写「两次都不对称才判失败」，代码是 `for _ in range(3)` 三次。
- 建议：把「两次」改成「三次」，或把循环改成 2。

## 已核对无问题

- `layout()` 的分段起点与宽度、`net_group_x` 的算术边界（含空文本、数字超宽两种输入）、`net_column_budget_covers_widest_compact_rate` 用 `(v*216+48)/96` 复刻 `scale` 的做法与生产代码一致。
- `set_rate` / `set_rate_compact` 的 GB 档取整（`(bps*10 + 536_870_912) / 1_073_741_824`）无溢出（`bps` 为 `u64`，先 `saturating_mul(10)`），任何输入都不产生 ≥11 字符的读数。
- `on_timer` 的新预算 `scale(ITEM_W[3] - NET_ARROW_W - NET_GAP)` 与 `paint` 侧 `net_group_x` 用的是同一组常量，不存在两侧口径漂移。
- `create_window` 的初始宽度改用 `(*app_ptr).w`，`App::new` 已按 `layout(&cfg.items).width` 初始化，`run()` 中 `App` 先建后建窗，生命周期成立。
- 首帧兜底：`render` 在缓存宽度为 0 时现场 `measure_text`，解决了 `run()` 第一次 `paint_now()` 早于 `on_timer` 导致的「速度文字 0 宽画不出来」。
- `config.rs` 临时文件路径构造：`n + 4 >= 320` 的上界检查正确（允许 `n+4 == 319`，最大写入下标 318，NUL 落在 319），`.tmp` 四个 UTF-16 单元写入无误。
- `app/src/wnd.rs` 本地常量与原 `chip_core` 常量逐值相等（236 / 10 / 52 / 94 / 140 / 228），std 版渲染结果不变。
- 三个 manifest 的 `license`/`repository` 与仓库实际地址一致；`LICENSE` 与 `license = "MIT"` 匹配。

## 建议处置

- v1.0 直接发布：无阻塞项，L1–L10 均为文档与失败路径边角。
- v1.1 打包：L1（夹数字或改注释）、L4+L5+L6（配置写盘可观测性）、L9（KB 档进位到 MB）、L7（探针副作用）、其余文档类顺手改。

---

**审计链**：`ocr delegate preview --from c20265a --to 76822c8` → `ocr delegate rule`（3 组规则：Cargo 清单 / Rust / Python）→ 逐文件 `git --no-pager diff` → 本报告。评审所用规则原文与 preview JSON 存于 `D:/DSH/.tmp/prev-v10.json`、`D:/DSH/.tmp/rules-v10.json`。
