import re, sys

def patch(path, pairs):
    s = open(path, encoding="utf-8").read()
    for old, new in pairs:
        if old not in s:
            print("MISS:", path, "|", old[:70].replace("\n", "\\n"))
            sys.exit(1)
        s = s.replace(old, new, 1)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("ok:", path)

# ---------------- chip_core/paint.rs ----------------
patch(r"D:\DSH\sysmon-chip\chip_core\src\paint.rs", [
    ("pub const COL_CPU: i32 = 8;", "pub const COL_CPU: i32 = 10;"),
    ("pub const COL_MEM: i32 = 54;", "pub const COL_MEM: i32 = 56;"),
    ("pub const COL_DISK: i32 = 100;", "pub const COL_DISK: i32 = 102;"),
    ("pub const COL_NET: i32 = 146;", "pub const COL_NET: i32 = 148;"),
    ("pub const RIGHT_EDGE: i32 = 244;", "pub const RIGHT_EDGE: i32 = 242;"),
    ("""    pub fn create(dpi: u32) -> Self {
        let d = dpi as i32;""",
     """    pub fn create(h: i32) -> Self {
        let h = h.max(24);"""),
    ("        let h_label = -((39 * d + 144) / 288); // 9.75 pt",
     "        let h_label = -((h * 29) / 100);"),
    ("        let h_value = -((40 * d + 144) / 288); // 10.0 pt",
     "        let h_value = -((h * 32) / 100);"),
])

# ---------------- chip_core/metrics.rs ----------------
patch(r"D:\DSH\sysmon-chip\chip_core\src\metrics.rs", [
    ("""    pub fn sample(&mut self) -> Metrics {""",
     """    /// 快速采样：CPU/内存/磁盘，跳过网卡枚举（首帧尽快上屏用）
    pub fn sample_fast(&mut self) -> Metrics {
        let now = self.qpc();
        self.last_qpc = now;
        let cpu = unsafe { self.sample_cpu() };
        let mem = unsafe { self.sample_mem() };
        if self.disk_tick == 0 {
            self.disk_pct = unsafe { sample_disk() };
        }
        self.disk_tick = (self.disk_tick + 1) % DISK_EVERY;
        Metrics { cpu, mem, disk: self.disk_pct, up: 0, down: 0 }
    }

    pub fn sample(&mut self) -> Metrics {"""),
])

# ---------------- app_ultra/app_impl.rs ----------------
p = r"D:\DSH\sysmon-chip\app_ultra\src\app_impl.rs"
s = open(p, encoding="utf-8").read()

# 1) 字体/画布尺寸
s = s.replace("""        self.pal = self.effective_palette();
        self.fonts = Some(Fonts::create(self.dpi));
        self.canvas = Canvas::new(self.w, self.h);""",
"""        self.pal = self.effective_palette();
        self.fonts = Some(Fonts::create(self.h));
        self.canvas = Canvas::new(self.w, self.h);
        self.layered = Layered::new(self.w, self.h);""", 1)

# 2) 高度：任务栏高 - 1 逻辑像素（露出任务栏顶部细线）
s = s.replace("""        self.h = match Self::taskbar_rect() {
            Some(r) => (r.bottom - r.top).max(scale(24, self.dpi)),
            None => scale(BASE_H, self.dpi),
        };""",
"""        self.h = match Self::taskbar_rect() {
            Some(r) => ((r.bottom - r.top) - scale(1, self.dpi)).max(scale(24, self.dpi)),
            None => scale(BASE_H, self.dpi),
        };""", 1)

# 3) 任务栏定位：下移 1 逻辑像素，让顶部细线露出来
s = s.replace("""        Some((bar.left, bar.top + scale(1, self.dpi)))""",
"""        Some((bar.left, bar.top + scale(1, self.dpi)))""", 1)
s = s.replace("""    fn taskbar_pos(&self) -> Option<(i32, i32)> {
        let bar = unsafe { Self::taskbar_rect() }?;
        Some((bar.left, bar.top + scale(1, self.dpi)))
    }""",
"""    fn taskbar_pos(&self) -> Option<(i32, i32)> {
        let bar = unsafe { Self::taskbar_rect() }?;
        Some((bar.left, bar.top + scale(1, self.dpi)))
    }
""", 1)

# 4) render：行高按实际高度二等分
s = s.replace("""            let px = scale(x, dpi);
            let pw = scale(33, dpi);
            c.text(lab, px, scale(ROW1_Y, dpi), pw, scale(ROW1_H, dpi), false, self.pal.label, f.label);
            c.text(val, px, scale(ROW2_Y, dpi), pw, scale(ROW2_H, dpi), false, color, f.value);""",
"""            let px = scale(x, dpi);
            let pw = scale(42, dpi);
            c.text(lab, px, 0, pw, row_h, false, self.pal.label, f.label);
            c.text(val, px, row_h, pw, self.h - row_h, false, color, f.value);""", 1)
s = s.replace("""        c.clear(self.brush as _);
        let dpi = self.dpi;""",
"""        c.clear(self.brush as _);
        let dpi = self.dpi;
        let row_h = self.h / 2;""", 1)
s = s.replace("""        c.text(&self.texts.up_arrow, nx, scale(ROW1_Y, dpi), aw, scale(ROW1_H, dpi), false, self.pal.up, f.label);
        c.text(&self.texts.up_speed, sx, scale(ROW1_Y, dpi), sw, scale(ROW1_H, dpi), true, self.pal.label, f.label);
        c.text(&self.texts.down_arrow, nx, scale(ROW2_Y, dpi), aw, scale(ROW2_H, dpi), false, self.pal.down, f.value);
        c.text(&self.texts.down_speed, sx, scale(ROW2_Y, dpi), sw, scale(ROW2_H, dpi), true, self.pal.label, f.value);""",
"""        c.text(&self.texts.up_arrow, nx, 0, aw, row_h, false, self.pal.up, f.label);
        c.text(&self.texts.up_speed, sx, 0, sw, row_h, true, self.pal.label, f.label);
        c.text(&self.texts.down_arrow, nx, row_h, aw, self.h - row_h, false, self.pal.down, f.value);
        c.text(&self.texts.down_speed, sx, row_h, sw, self.h - row_h, true, self.pal.label, f.value);""", 1)

# 5) 绘制入口改为分层窗口
s = s.replace("""    fn paint_now(&mut self) {
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
    }""",
"""    fn paint_now(&mut self) {
        // 半透明：画到 32 位 DIB，再逐像素带 alpha 提交（UpdateLayeredWindow）
        let Some(dc) = self.layered.as_ref().map(|l| l.dc) else { return };
        self.render(dc);
        let bg = self.pal.bg;
        if let Some(l) = self.layered.as_mut() {
            unsafe {
                l.update(self.hwnd, bg, 222);
            }
        }
    }

    unsafe fn on_paint(&mut self) {
        let mut ps: PAINTSTRUCT = core::mem::zeroed();
        let _ = BeginPaint(self.hwnd, &mut ps);
        self.paint_now();
        EndPaint(self.hwnd, &ps);
    }""", 1)

# 6) App 字段 + 初始化
s = s.replace("    canvas: Option<Canvas>,", "    canvas: Option<Canvas>,\n    layered: Option<Layered>,", 1)
s = s.replace("            canvas: None,", "            canvas: None,\n            layered: None,", 1)

# 7) 窗口加 WS_EX_LAYERED
s = s.replace("        WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,",
              "        WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED,", 1)
s = s.replace("const WS_EX_NOACTIVATE: u32 = 0x0800_0000;",
              "const WS_EX_NOACTIVATE: u32 = 0x0800_0000;\nconst WS_EX_LAYERED: u32 = 0x0008_0000;\nconst ULW_ALPHA: u32 = 0x0000_0002;", 1)

# 8) imports
s = s.replace("""    InvalidateRect, MonitorFromWindow, ReleaseDC, SetWindowRgn, UpdateWindow, MONITORINFO,""",
"""    InvalidateRect, MonitorFromWindow, ReleaseDC, SetWindowRgn, UpdateWindow, MONITORINFO,
    CreateDIBSection, UpdateLayeredWindow, BITMAPINFO, BITMAPINFOHEADER, BLENDFUNCTION,""", 1)
s = s.replace("use windows_sys::Win32::Foundation::{",
              "use windows_sys::Win32::Foundation::{SIZE,", 1)

# 9) Layered 结构体（插在 Canvas 之前，即 App impl 之后位置：放在 App struct 定义前）
layered = '''
// ---------------------------------------------------------------- 半透明合成

struct Layered {
    dc: HDC,
    bmp: HBITMAP,
    old: HGDIOBJ,
    bits: *mut u32,
    w: i32,
    h: i32,
}

impl Layered {
    unsafe fn new(w: i32, h: i32) -> Option<Self> {
        if w <= 0 || h <= 0 {
            return None;
        }
        let screen = GetDC(ptr::null_mut());
        if screen.is_null() {
            return None;
        }
        let dc = CreateCompatibleDC(screen);
        ReleaseDC(ptr::null_mut(), screen);
        if dc.is_null() {
            return None;
        }
        let mut bi: BITMAPINFO = core::mem::zeroed();
        bi.bmiHeader.biSize = core::mem::size_of::<BITMAPINFOHEADER>() as u32;
        bi.bmiHeader.biWidth = w;
        bi.bmiHeader.biHeight = -h;
        bi.bmiHeader.biPlanes = 1;
        bi.bmiHeader.biBitCount = 32;
        bi.bmiHeader.biCompression = 0;
        let mut bits: *mut core::ffi::c_void = ptr::null_mut();
        let bmp = CreateDIBSection(dc, &bi, 0, &mut bits, ptr::null_mut(), 0);
        if bmp.is_null() || bits.is_null() {
            DeleteDC(dc);
            return None;
        }
        let old = SelectObject(dc, bmp as HGDIOBJ);
        Some(Self { dc, bmp, old, bits: bits as *mut u32, w, h })
    }

    /// 把底色像素转成半透明、文字像素转成不透明，再提交给系统合成
    unsafe fn update(&mut self, hwnd: HWND, bg: COLORREF, alpha: u32) {
        let n = (self.w as usize) * (self.h as usize);
        let bg_r = (bg & 0xFF) as i32;
        let bg_g = ((bg >> 8) & 0xFF) as i32;
        let bg_b = ((bg >> 16) & 0xFF) as i32;
        let a0 = alpha.min(255);
        for i in 0..n {
            let px = *self.bits.add(i);
            let b = (px & 0xFF) as i32;
            let g = ((px >> 8) & 0xFF) as i32;
            let r = ((px >> 16) & 0xFF) as i32;
            let diff = (r - bg_r).abs().max((g - bg_g).abs()).max((b - bg_b).abs()) as u32;
            let a = if diff == 0 {
                a0
            } else {
                let t = (diff * 3).min(255);
                a0 + (255 - a0) * t / 255
            };
            let rr = (r as u32 * a) / 255;
            let gg = (g as u32 * a) / 255;
            let bb = (b as u32 * a) / 255;
            *self.bits.add(i) = bb | (gg << 8) | (rr << 16) | (a << 24);
        }
        let screen = GetDC(ptr::null_mut());
        if screen.is_null() {
            return;
        }
        let size = SIZE { cx: self.w, cy: self.h };
        let src = POINT { x: 0, y: 0 };
        let blend = BLENDFUNCTION {
            BlendOp: 0,
            BlendFlags: 0,
            SourceConstantAlpha: 255,
            AlphaFormat: 1,
        };
        UpdateLayeredWindow(
            hwnd,
            screen,
            ptr::null(),
            &size,
            self.dc,
            &src,
            0,
            &blend,
            ULW_ALPHA,
        );
        ReleaseDC(ptr::null_mut(), screen);
    }
}

impl Drop for Layered {
    fn drop(&mut self) {
        unsafe {
            SelectObject(self.dc, self.old);
            DeleteObject(self.bmp as HGDIOBJ);
            DeleteDC(self.dc);
        }
    }
}

'''
anchor = "pub struct App {"
if anchor not in s:
    print("MISS anchor App struct")
    sys.exit(1)
s = s.replace(anchor, layered + anchor, 1)

open(p, "w", encoding="utf-8", newline="\n").write(s)
print("ok:", p)
