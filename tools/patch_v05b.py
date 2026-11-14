import re, sys

p = r"D:\DSH\sysmon-chip\app_ultra\src\app_impl.rs"
s = open(p, encoding="utf-8").read()
orig = s

# 1) imports
s = s.replace("""    BeginPaint, CreateCompatibleDC, CreateDIBSection, CreateRoundRectRgn, CreateSolidBrush, DeleteDC,
    DeleteObject, EndPaint, GetDC, GetMonitorInfoW, InvalidateRect, MonitorFromWindow, ReleaseDC,
    SelectObject, SetWindowRgn, UpdateWindow, BITMAPINFO, BITMAPINFOHEADER, BLENDFUNCTION, HBITMAP,
    MONITORINFO, MONITOR_DEFAULTTONEAREST, HDC, HGDIOBJ, PAINTSTRUCT,""",
"""    BeginPaint, CreateRoundRectRgn, CreateSolidBrush, DeleteObject, EndPaint, GetDC, GetMonitorInfoW,
    InvalidateRect, MonitorFromWindow, ReleaseDC, SetWindowRgn, UpdateWindow, MONITORINFO,
    MONITOR_DEFAULTTONEAREST, HDC, HGDIOBJ, PAINTSTRUCT,""")
s = s.replace("    UpdateLayeredWindow,\n", "")
s = s.replace("use windows_sys::Win32::System::LibraryLoader::{GetModuleHandleW, GetProcAddress};",
              "use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;")

# 2) 删掉 Layered 块
start = s.find("// ---------------------------------------------------------------- 半透明合成")
end = s.find("pub struct App {")
if start >= 0 and end > start:
    s = s[:start] + s[end:]

# 3) App 字段清理
for pat in [r"\n *layered: Option<Layered>,", r"\n *layered_ok: bool,", r"\n *gdi_mode: bool,",
            r"\n *layered: None,", r"\n *layered_ok: false,", r"\n *gdi_mode: false,"]:
    s = re.sub(pat, "", s, count=1)

# 4) init_graphics：去掉 layered 创建，加入丙烯酸
s = re.sub(
    r"        self\.pal = self\.effective_palette\(\);\n        self\.fonts = Some\(Fonts::create\(self\.h\)\);\n"
    r"        self\.canvas = Canvas::new\(self\.w, self\.h\);\n        self\.layered = Layered::new\(self\.w, self\.h\);\n"
    r"        self\.brush = CreateSolidBrush\(self\.pal\.bg\) as HGDIOBJ;\n"
    r"(?:        //[^\n]*\n)?        self\.apply_corners\(\);",
    """        self.pal = self.effective_palette();
        self.fonts = Some(Fonts::create(self.h));
        self.canvas = Canvas::new(self.w, self.h);
        self.brush = CreateSolidBrush(self.pal.bg) as HGDIOBJ;
        // 真高斯模糊：DWM 亚克力（普通窗口 + SetWindowCompositionAttribute）
        self.acrylic = enable_acrylic(self.hwnd, acrylic_tint(&self.pal));
        self.apply_corners();""",
    s, count=1)

# 5) render：整段替换成透明背景绘制
m = re.search(r"    unsafe fn render\(&self, dst: HDC\) \{.*?\n    \}\n", s, re.S)
if not m:
    print("MISS render")
    sys.exit(1)
new_render = '''    unsafe fn render(&self, dst: HDC) {
        let Some(f) = &self.fonts else { return };
        let dpi = self.dpi;
        let row_h = self.h / 2;
        // 不填背景：亚克力模糊由 DWM 画在窗口后面，我们只画文字
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
s = s[:m.start()] + new_render + s[m.end():]

# 6) paint_now / on_paint
m = re.search(r"    unsafe fn paint_now\(&mut self\) \{.*?\n    unsafe fn on_paint\(&mut self\) \{.*?\n    \}\n\n", s, re.S)
if not m:
    print("MISS paint")
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
s = s[:m.start()] + new_paint + s[m.end():]

# 7) 窗口样式
s = s.replace("WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED,",
              "WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,")

# 8) App 字段 acrylic
if "    acrylic: bool," not in s:
    s = s.replace("    canvas: Option<Canvas>,", "    canvas: Option<Canvas>,\n    acrylic: bool,", 1)
    s = s.replace("            canvas: None,", "            canvas: None,\n            acrylic: false,", 1)

# 9) on_display_change 不再重建 layered
s = s.replace("        self.layered = Layered::new(w, h);\n", "")

# 10) 辅助函数（若不存在则插入）
if "fn enable_acrylic" not in s:
    helper = '''// ---------------------------------------------------------------- 亚克力模糊 + 透明文本

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

/// 透明背景上画文字（灰色抗锯齿）
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
    let fmt = 0x0004u32 | 0x0020u32 | 0x0800u32 | if right { 0x0002u32 } else { 0x0000u32 };
    SelectObject(hdc, font as HGDIOBJ);
    SetTextColor(hdc, color);
    SetBkMode(hdc, 1);
    DrawTextW(hdc, t.ptr(), t.len as i32, &mut rc, fmt);
}

'''
    s = s.replace("pub struct App {", helper + "pub struct App {", 1)

# 11) 补齐 GetProcAddress 导入（脚本里被删过）
if "GetProcAddress" in s and "LibraryLoader::{GetModuleHandleW, GetProcAddress}" not in s:
    s = s.replace("use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;",
                  "use windows_sys::Win32::System::LibraryLoader::{GetModuleHandleW, GetProcAddress};", 1)

open(p, "w", encoding="utf-8", newline="\n").write(s)
print("patched, changed:", s != orig, "| length", len(s))
