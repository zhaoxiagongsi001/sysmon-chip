import re, sys

p = r"D:\DSH\sysmon-chip\app_ultra\src\app_impl.rs"
s = open(p, encoding="utf-8").read()

def rep(old, new, cnt=1, name=""):
    global s
    if old not in s:
        print("MISS:", name or old[:60])
        sys.exit(1)
    s = s.replace(old, new, cnt)

# ---------- 1) 去掉分层窗口相关 imports ----------
rep("""    BeginPaint, CreateCompatibleDC, CreateDIBSection, CreateRoundRectRgn, CreateSolidBrush, DeleteDC,
    DeleteObject, EndPaint, GetDC, GetMonitorInfoW, InvalidateRect, MonitorFromWindow, ReleaseDC,
    SelectObject, SetWindowRgn, UpdateWindow, BITMAPINFO, BITMAPINFOHEADER, BLENDFUNCTION, HBITMAP,
    MONITORINFO, MONITOR_DEFAULTTONEAREST, HDC, HGDIOBJ, PAINTSTRUCT,""",
"""    BeginPaint, CreateRoundRectRgn, CreateSolidBrush, DeleteObject, EndPaint, GetDC, GetMonitorInfoW,
    InvalidateRect, MonitorFromWindow, ReleaseDC, SetWindowRgn, UpdateWindow, MONITORINFO,
    MONITOR_DEFAULTTONEAREST, HDC, HGDIOBJ, PAINTSTRUCT,""", name="gdi imports")
rep("""    GetWindowLongPtrW, GetWindowRect, IsWindowVisible, KillTimer, LoadCursorW, LoadImageW,
    UpdateLayeredWindow,""",
"""    GetWindowLongPtrW, GetWindowRect, IsWindowVisible, KillTimer, LoadCursorW, LoadImageW,""", name="UWM import")

# ---------- 2) 删除 Layered 结构与半透明合成块 ----------
start = s.find("// ---------------------------------------------------------------- 半透明合成")
end = s.find("pub struct App {")
if start < 0 or end < 0:
    print("MISS layered block")
    sys.exit(1)
s = s[:start] + s[end:]

# ---------- 3) App 字段：去掉 layered/layered_ok/gdi_mode ----------
rep("    layered: Option<Layered>,\n    layered_ok: bool,\n    gdi_mode: bool,\n", "", name="app fields")
rep("            layered: None,\n            layered_ok: false,\n            gdi_mode: false,\n", "", name="app init fields")

# ---------- 4) init_graphics：不改尺寸，创建字体/画布，开亚克力 ----------
rep("""        self.pal = self.effective_palette();
        self.fonts = Some(Fonts::create(self.h));
        self.canvas = Canvas::new(self.w, self.h);
        self.layered = Layered::new(self.w, self.h);
        self.brush = CreateSolidBrush(self.pal.bg) as HGDIOBJ;
        self.apply_corners();""",
"""        self.pal = self.effective_palette();
        self.fonts = Some(Fonts::create(self.h));
        self.canvas = Canvas::new(self.w, self.h);
        self.brush = CreateSolidBrush(self.pal.bg) as HGDIOBJ;
        // 真高斯模糊：DWM 亚克力（普通窗口 + SetWindowCompositionAttribute），失败退回半透明实色
        self.acrylic = enable_acrylic(self.hwnd, acrylic_tint(&self.pal));
        self.apply_corners();""", name="init_graphics")

# ---------- 5) 渲染：直接画到目标 DC，不填背景（让亚克力透出来） ----------
old_render = s[s.find("    unsafe fn render(&self, dst: HDC) {"):]
old_render = old_render[:old_render.find("\n    }\n") + len("\n    }\n")]
new_render = '''    unsafe fn render(&self, dst: HDC) {
        let Some(f) = &self.fonts else { return };
        let dpi = self.dpi;
        let row_h = self.h / 2;
        // 不清背景：亚克力模糊由 DWM 画在窗口后面，我们只画文字
        let m = &self.metrics;
        let cols = [
            (COL_CPU, &self.texts.cpu_lab, &self.texts.cpu_val, self.pal.level(m.cpu)),
            (COL_MEM, &self.texts.mem_lab, &self.texts.mem_val, self.pal.level(m.mem)),
            (COL_DISK, &self.texts.disk_lab, &self.texts.disk_val, self.pal.level(m.disk)),
        ];
        for (x, lab, val, color) in cols {
            let px = scale(x, dpi);
            let pw = scale(42, dpi);
            draw_text(dst, lab, px, 0, pw, row_h, false, self.pal.label, f.label);
            draw_text(dst, val, px, row_h, pw, self.h - row_h, false, color, f.value);
        }
        let nx = scale(COL_NET, dpi);
        let aw = scale(8, dpi);
        let sx = nx + aw;
        let sw = scale(RIGHT_EDGE - COL_NET, dpi) - aw;
        draw_text(dst, &self.texts.up_arrow, nx, 0, aw, row_h, false, self.pal.up, f.label);
        draw_text(dst, &self.texts.up_speed, sx, 0, sw, row_h, true, self.pal.label, f.label);
        draw_text(dst, &self.texts.down_arrow, nx, row_h, aw, self.h - row_h, false, self.pal.down, f.value);
        draw_text(dst, &self.texts.down_speed, sx, row_h, sw, self.h - row_h, true, self.pal.label, f.value);
    }
'''
s = s.replace(old_render, new_render, 1)

# ---------- 6) paint_now / on_paint：普通窗口 GDI ----------
start = s.find("    unsafe fn paint_now(&mut self) {")
end = s.find("    // ------------------------------------------------------------ 定时")
if start < 0 or end < 0:
    print("MISS paint block")
    sys.exit(1)
new_paint = '''    unsafe fn paint_now(&mut self) {
        let hdc = GetDC(self.hwnd);
        if !hdc.is_null() {
            self.render(hdc);
            ReleaseDC(self.hwnd, hdc);
        }
    }

    unsafe fn on_paint(&mut self) {
        let mut ps: PAINTSTRUCT = core::mem::zeroed();
        let hdc = BeginPaint(self.hwnd, &mut ps);
        self.render(hdc);
        EndPaint(self.hwnd, &ps);
    }

'''
s = s[:start] + new_paint + s[end:]

# ---------- 7) 窗口去掉 WS_EX_LAYERED ----------
rep("        WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED,",
    "        WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,", name="window exstyle")

# ---------- 8) 亚克力辅助函数 + 透明文本绘制 ----------
helper = '''
// ---------------------------------------------------------------- 亚克力模糊 + 透明文本

const WCA_ACCENT_POLICY: i32 = 19;
const ACCENT_ENABLE_ACRYLICBLURBEHIND: i32 = 4;

#[repr(C)]
struct AccentPolicy {
    accent_state: i32,
    accent_flags: i32,
    gradient_color: u32,
    animation_id: i32,
}

#[repr(C)]
struct WinCompAttrData {
    attribute: i32,
    data: *mut core::ffi::c_void,
    size_of_data: usize,
}

fn acrylic_tint(pal: &Palette) -> u32 {
    // 浅色：偏白 80% 不透明；深色：偏黑 80%
    if pal.bg == rgb(0xF3, 0xF3, 0xF3) {
        0xCCF3F3F3
    } else {
        0xCC202020
    }
}

/// 给普通（非分层）窗口开 DWM 亚克力：真高斯模糊，由 GPU 合成，不占进程内存
unsafe fn enable_acrylic(hwnd: HWND, tint: u32) -> bool {
    type SetWca = unsafe extern "system" fn(HWND, *mut WinCompAttrData) -> i32;
    let user32 = GetModuleHandleW(wide("user32.dll").as_ptr());
    if user32.is_null() {
        return false;
    }
    let Some(proc) = GetProcAddress(user32, wide("SetWindowCompositionAttribute").as_ptr().cast())
    else {
        return false;
    };
    let set_wca: SetWca = core::mem::transmute(proc);
    let mut policy = AccentPolicy {
        accent_state: ACCENT_ENABLE_ACRYLICBLURBEHIND,
        accent_flags: 2,
        gradient_color: tint,
        animation_id: 0,
    };
    let mut data = WinCompAttrData {
        attribute: WCA_ACCENT_POLICY,
        data: &mut policy as *mut _ as *mut core::ffi::c_void,
        size_of_data: core::mem::size_of::<AccentPolicy>(),
    };
    set_wca(hwnd, &mut data) != 0
}

/// 透明背景上画文字（灰色抗锯齿，避免 ClearType 在黑底上的彩边）
unsafe fn draw_text(
    hdc: HDC,
    t: &WText,
    x: i32,
    y: i32,
    w: i32,
    h: i32,
    right: bool,
    color: COLORREF,
    font: HFONT,
) {
    if t.is_empty() || w <= 0 {
        return;
    }
    let mut rc = RECT { left: x, top: y, right: x + w, bottom: y + h };
    let fmt = DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX | if right { DT_RIGHT } else { DT_LEFT };
    SelectObject(hdc, font as HGDIOBJ);
    SetTextColor(hdc, color);
    SetBkMode(hdc, 1);
    DrawTextW(hdc, t.ptr(), t.len as i32, &mut rc, fmt);
}

'''
anchor = "pub struct App {"
s = s.replace(anchor, helper + anchor, 1)

# ---------- 9) 字体改灰色抗锯齿 ----------
s = s.replace("CreateFontW(h_label, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, face.as_ptr())",
              "CreateFontW(h_label, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 4, 0, face.as_ptr())", 1)
s = s.replace("CreateFontW(h_value, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, face.as_ptr())",
              "CreateFontW(h_value, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 4, 0, face.as_ptr())", 1)

# ---------- 10) App 字段 acrylic ----------
rep("    canvas: Option<Canvas>,", "    canvas: Option<Canvas>,\n    acrylic: bool,", name="acrylic field")
rep("            canvas: None,", "            canvas: None,\n            acrylic: false,", name="acrylic init")

# ---------- 11) on_display_change 不再重建 layered ----------
rep("        self.layered = Layered::new(w, h);\n", "", name="dpi layered")

open(p, "w", encoding="utf-8", newline="\n").write(s)
print("app_impl refactored for acrylic blur")
