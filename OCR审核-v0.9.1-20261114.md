# OCR 工程评审报告 · SysMonChip v0.9.1

- 评审工具：alibaba/open-code-review v1.13.9（`ocr delegate` 委派模式，OCR 只做文件筛选与规则解析，评审判断由本会话模型完成）
- 评审范围：`6c490ca..c20265a`（v0.9 + v0.9.1 两次提交，即当前发布版全量改动）
- 覆盖率：total 12 / reviewable 12 / reviewed 12 / skipped 0 → **coverage_rate 100%**
  - 排除 16 个：README、Cargo.lock、app.rc（unsupported_ext）、png（binary）
- 规则组：`**/Cargo.toml`（清单卫生 / edition / 发布元数据）、`**/*.rs`（错误处理、unsafe 边界、热路径分配、类型设计）、`**/*.{py,pyi}`（死代码、边界、异常、身份比较、资源管理）

## 结论

无 Critical / High。1 条 medium（网速列在高流量下会压到磁盘列），4 条 low。
核心布局逻辑（`layout()`、圆角区域、自适应重排、"至少保留一项"）经核对是正确的，且有单测覆盖。

## 发现

| # | 严重度 | 文件:行 | 类别 | 摘要 |
|---|--------|---------|------|------|
| 1 | medium | `app_ultra/src/app_impl.rs:465-473`、`:512` | bug | 网速 ≥100 MB/s 时箭头/数字溢出到磁盘列；紧凑兜底不重测，兜不住 |
| 2 | low | `chip_core/src/paint.rs:23-25` | documentation | 注释 "1.9 MB/s 69.6 逻辑宽" 与实测不符，且漏算箭头+间隔 10 px |
| 3 | low | `tools/_v09_pad.py:36` | bug | `first/last` 可能为 None，却在空值保护之前参与运算 → TypeError |
| 4 | low | `app_ultra/src/app_impl.rs:1179`、`chip_core/src/paint.rs:13-21` | maintainability | 创建窗口仍用 `BASE_W`(236)，与实际宽度 212 不符；旧的 `BASE_W/COL_*/RIGHT_EDGE` 与 `ITEM_W/PAD_*` 形成两套布局常量 |
| 5 | low | `tools/_v09_pad.py:38`、`_v09_m2.py:11`、`_v09_measure.py:16`；`_v09_pad.py:40`、`_v09_corner.py:21`、`_v09_modeshot.py:34`；`_v09_toggle4.py:10` | maintainability | 探针脚本硬编码 2.25 倍缩放、`resize(...,0)` 整数重采样（Pillow 已弃用）、`assert` 做运行时校验 |

### 1. medium — 网速列溢出（`app_impl.rs:465-473` + `:512`）

渲染按「列右缘 − 文字宽」定位，箭头再往左延伸 `arrow(8)+gap(2)=10` 逻辑像素；
但压缩阈值用的是 `ITEM_W[3] - 9`（`:512`），比实际占用少 1 px，且**压缩后不再复测**。

225% 下的实测几何：列宽 `scale(71,216)=160`、箭头 `18`、间隔 `5` → 文字最多 137 px；
阈值 `160-20=140 px`。字体实测（value 字体）：

| 文本 | 实测宽(px) | 是否触发压缩 | 压缩后 | 溢出 |
|------|-----------|-------------|--------|------|
| `1.9 MB/s` | 137 | 否 | — | 0 |
| `12.4 MB/s` | 156 | 是 | `12 MB/s`(129) | 0 |
| `100 MB/s` | 148 | 是 | `100 MB/s`(148) | 11 px（箭头压到磁盘列） |
| `999.9 MB/s` | 175 | 是 | `1000 MB/s`(167) | 30 px（数字+箭头一起压到磁盘列） |

即千兆网卡级别的读数（≥100 MB/s）就会让箭头与磁盘百分比重叠；`set_rate_compact` 对 MB 段只是去掉小数，
`100 → 1000 MB/s` 这种反而更宽，兜底失效。提交说明里「超长网速仍走 measure_text + set_rate_compact 兜底，不会压到箭头」不成立。

**修法**：阈值改为 `scale(ITEM_W[3], dpi) - scale(8, dpi) - scale(2, dpi)`（由同一组常量推导，别再写字面量 9）；
压缩后**重新测量**，仍超宽则降级（加 `GB/s` 档位，或 `up_x` 夹到列左缘并隐藏箭头），并补一条以固定字宽表为输入的布局单测。

### 2. low — 注释数值与实测不符（`paint.rs:23-25`）

注释称 "1.9 MB/s 在 225% 下 69.6 逻辑宽"，实测为 53.3（label）/ 60.9（value）逻辑像素；
68.4 是 `999.9 MB/s` 在 label 字体的宽度。该数值既不对应 1.9 MB/s，也没算箭头的 10 px，
是上一条溢出的认知来源。建议改成约束式描述：「文字 + 箭头 10 ≤ 71」。

### 3. low — `_v09_pad.py:36` 空值未保护

```python
first = next(..., None); last = next(..., None)
print(f"... gap_right={w - 1 - last} ...")   # ← None 参与运算
if first is not None and last is not None:   # ← 保护来晚了
```
面板空白或被遮挡时 `first/last` 为 None，脚本直接抛 TypeError 而不是给出可读信息。
修法：把判空提到第 36 行之前，或用 `or 0` 兜底。

### 4. low — 两套布局常量并存

`BASE_W=236 / COL_CPU..NET / RIGHT_EDGE=228` 是 std 版遗留，`ITEM_W/PAD_L/PAD_R` 是新布局；
v0.9.1 收窄后两者已不相等，`v09_layout` 测试因此不得不与 `COL_*` 解绑。
`app_impl.rs:1179` 创建窗口仍用 `BASE_W`，实际宽度 212 → 启动瞬间多出 24 逻辑 px，靠 `init_graphics` 再缩回来。
建议：创建尺寸改为 `layout(&cfg.items).width`；`app/` 若不再维护就删掉，常量随之收敛。

### 5. low — 探针脚本一致性

- 硬编码 `2.25`：换个缩放比例，"逻辑 px" 结论就失真（可用 `GetDpiForWindow`）。
- `img.resize(..., 0)`：Pillow ≥9.1 已弃用整数重采样，应写 `Image.NEAREST`。
- `_v09_toggle4.py:10` 用 `assert` 校验外部状态，`python -O` 下会被剥掉；其余脚本用的是 `if not h: SystemExit(1)`。

## 已核对无问题的点

- `layout()`：关闭项 `x=-1`、列前移、宽度 = 左内边距 + 开启列宽之和 + 右内边距，5 条单测覆盖（含单项、全关项位置）。
- `apply_corners()`：`SetWindowRgn` 成功后区域归系统、失败才 `DeleteObject`，所有权处理正确；`CombineRgn(RGN_OR)` 补回贴屏侧直角，方向由 `rounds_right()` 判定，取不到矩形时默认圆右边（合理兜底）。
- `relayout()`：宽度不变的路径只重设区域，不重复 `SetWindowPos`，无抖动；`on_cmd` 每次命令后调用，幂等。
- `on_cmd` 1..=4：先算到临时 `items` 再判「至少保留一项」，全关时直接 return，不会写入非法配置。
- `Config::load()` 兜底：手改成四项全关时回落 CPU，避免空白条。
- `WM_COMMAND` 分支：`lp == 0` 限定 + `cmd != 0` 防护，不会误吞其它命令。
- 未引入 `unwrap()/panic!`、无新的 `unsafe` 越界或未校验指针解引用。

## 进一步优化建议（按优先级）

1. **P0 修网速溢出**：阈值由常量推导 + 压缩后复测 + 增加 `GB/s` 档位（`1.2 GB/s` 只有 8 字符，比 `1000 MB/s` 短 1/3）。
2. **P1 文字宽缓存**：`measure_text` 现在每帧调用 2 次；应在 `on_timer` 算好存进 `Texts`，`render` 变成纯绘制——顺带让"宽度是否放得下"可单测。
3. **P1 收敛常量**：删 `app/` 或迁到 `layout()`，去掉 `BASE_W/COL_*/RIGHT_EDGE`；创建窗口用实际布局宽度。
4. **P2 布局快照测试**：把面板画进离屏 DIB，断言左右留白相等（当前靠 `_v09_pad.py` 截屏量像素），可自动挡住"右边多空 26 px"这类回归。
5. **P2 探针归并**：`tools/` 下现在有 8 个一次性 `_v09_*.py`，本次评审 12 个文件里 8 个是探针，稀释了评审信噪比；合并成一个 `tools/verify.py`（子命令：layout / region / padding / modeshot）。
6. **P3 配置原子写**：`config.rs:372-403` 仍是 `CREATE_ALWAYS` 直覆盖（v0.8 评审遗留），建议临时文件 + `MoveFileEx(REPLACE_EXISTING)`。
