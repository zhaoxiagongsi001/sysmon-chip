//! 布局、文本缓冲与 GDI 绘制。
//! 坐标全部按 100% DPI 的基准像素设计（数值来自对参考图的像素实测），运行时按 DPI 缩放。

use windows_sys::Win32::Foundation::{COLORREF, RECT};
use windows_sys::Win32::Graphics::Gdi::{
    BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, CreateFontW, DeleteDC, DeleteObject,
    DrawTextW, FillRect, GetDC, GetTextExtentPoint32W, ReleaseDC, SelectObject, SetBkMode, SetTextColor, HBRUSH, HBITMAP,
    HDC, HFONT, HGDIOBJ,
};

use crate::metrics::Metrics;

pub const BASE_W: i32 = 236;
pub const BASE_H: i32 = 48;

/// 列起点（100% DPI）：CPU / MEM / DISK / 网速
pub const COL_CPU: i32 = 10;
pub const COL_MEM: i32 = 52;
pub const COL_DISK: i32 = 94;
pub const COL_NET: i32 = 140;
pub const RIGHT_EDGE: i32 = 228;

/// 两行文字的绘制矩形（相对面板顶端）
pub const ROW1_Y: i32 = 0;
pub const ROW1_H: i32 = 24;
pub const ROW2_Y: i32 = 24;
pub const ROW2_H: i32 = 24;

const DT_LEFT: u32 = 0x0000;
const DT_RIGHT: u32 = 0x0002;
const DT_VCENTER: u32 = 0x0004;
const DT_SINGLELINE: u32 = 0x0020;
const DT_NOPREFIX: u32 = 0x0800;
const DT_FLAGS: u32 = DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX;

pub fn scale(v: i32, dpi: u32) -> i32 {
    ((v * dpi as i32) + 48) / 96
}

pub fn rgb(r: u8, g: u8, b: u8) -> COLORREF {
    ((b as u32) << 16) | ((g as u32) << 8) | (r as u32)
}

/// &str -> 以 0 结尾的 UTF-16 栈缓冲
pub fn wide(s: &str) -> [u16; 64] {
    let mut out = [0u16; 64];
    for (i, ch) in s.encode_utf16().take(63).enumerate() {
        out[i] = ch;
    }
    out
}

// ---------------------------------------------------------------- 文本缓冲

#[derive(Clone, Copy, PartialEq, Eq)]
pub struct WText {
    pub units: [u16; 24],
    pub len: usize,
}

impl WText {
    pub const fn new() -> Self {
        Self { units: [0; 24], len: 0 }
    }

    pub fn clear(&mut self) {
        self.len = 0;
        self.units = [0; 24];
    }

    fn push(&mut self, ch: u16) {
        if self.len < 22 {
            self.units[self.len] = ch;
            self.len += 1;
            self.units[self.len] = 0;
        }
    }

    fn tail(&mut self, s: &[u8]) {
        for &b in s {
            self.push(b as u16);
        }
    }

    pub fn set_ascii(&mut self, s: &[u8]) {
        self.clear();
        self.tail(s);
    }

    pub fn set_arrow(&mut self, up: bool) {
        self.clear();
        self.push(if up { 0x2191 } else { 0x2193 });
    }

    pub fn set_pct(&mut self, v: u8) {
        self.clear();
        let v = v.min(100);
        if v >= 100 {
            self.push(b'1' as u16);
            self.push(b'0' as u16);
            self.push(b'0' as u16);
        } else {
            if v >= 10 {
                self.push(b'0' as u16 + (v / 10) as u16);
            }
            self.push(b'0' as u16 + (v % 10) as u16);
        }
        self.push(b'%' as u16);
    }

    fn push_num(&mut self, mut n: u64) {
        if n == 0 {
            self.push(b'0' as u16);
            return;
        }
        let mut digits = [0u8; 20];
        let mut i = 0usize;
        while n > 0 && i < 20 {
            digits[i] = (n % 10) as u8;
            n /= 10;
            i += 1;
        }
        while i > 0 {
            i -= 1;
            self.push(b'0' as u16 + digits[i] as u16);
        }
    }

    /// 字节/秒 -> "2.9 KB/s" / "512 B/s" / "1.2 MB/s"（整数运算，无浮点格式化）。
    /// 数值 >=100 时去掉小数位，保证网速列宽度有上界、不撞左侧箭头。
    pub fn set_rate(&mut self, bps: u64) {
        self.clear();
        if bps >= 1_048_576 {
            let tenths = (bps.saturating_mul(10) + 524_288) / 1_048_576;
            self.push_num(tenths / 10);
            if tenths < 1000 {
                self.push(b'.' as u16);
                self.push(b'0' as u16 + (tenths % 10) as u16);
            }
            self.tail(b" MB/s");
        } else if bps >= 1024 {
            let tenths = (bps.saturating_mul(10) + 512) / 1024;
            self.push_num(tenths / 10);
            if tenths < 1000 {
                self.push(b'.' as u16);
                self.push(b'0' as u16 + (tenths % 10) as u16);
            }
            self.tail(b" KB/s");
        } else {
            self.push_num(bps);
            self.tail(b" B/s");
        }
    }

    /// 紧凑格式（放不下时用）：KB/MB 一律取整，例如 "37 KB/s" / "9 MB/s"
    pub fn set_rate_compact(&mut self, bps: u64) {
        self.clear();
        if bps >= 1_048_576 {
            let mb = (bps + 524_288) / 1_048_576;
            self.push_num(mb);
            self.tail(b" MB/s");
        } else if bps >= 1024 {
            let kb = (bps + 512) / 1024;
            self.push_num(kb);
            self.tail(b" KB/s");
        } else {
            self.push_num(bps);
            self.tail(b" B/s");
        }
    }

    pub fn ptr(&self) -> *const u16 {
        self.units.as_ptr()
    }

    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Texts {
    pub cpu_lab: WText,
    pub mem_lab: WText,
    pub disk_lab: WText,
    pub cpu_val: WText,
    pub mem_val: WText,
    pub disk_val: WText,
    pub up_arrow: WText,
    pub down_arrow: WText,
    pub up_speed: WText,
    pub down_speed: WText,
}

impl Texts {
    pub fn new() -> Self {
        let mut t = Self {
            cpu_lab: WText::new(),
            mem_lab: WText::new(),
            disk_lab: WText::new(),
            cpu_val: WText::new(),
            mem_val: WText::new(),
            disk_val: WText::new(),
            up_arrow: WText::new(),
            down_arrow: WText::new(),
            up_speed: WText::new(),
            down_speed: WText::new(),
        };
        t.cpu_lab.set_ascii(b"CPU");
        t.mem_lab.set_ascii(b"MEM");
        t.disk_lab.set_ascii(b"DISK");
        t.up_arrow.set_arrow(true);
        t.down_arrow.set_arrow(false);
        t
    }

    /// 按开关重算所有文本。
    ///
    /// 标签与箭头必须每次按开关**重新写入**（而不是只在 `new()` 里写一次）：
    /// 关掉某项时 `clear()` 后，如果再打开却只写数值，标签和 ↑↓ 会永久消失。
    pub fn apply(&mut self, m: &Metrics, items: &crate::items::Items) {
        let (cpu, mem, disk, net) = (items.cpu, items.mem, items.disk, items.net);
        if cpu {
            self.cpu_lab.set_ascii(b"CPU");
            self.cpu_val.set_pct(m.cpu);
        } else {
            self.cpu_lab.clear();
            self.cpu_val.clear();
        }
        if mem {
            self.mem_lab.set_ascii(b"MEM");
            self.mem_val.set_pct(m.mem);
        } else {
            self.mem_lab.clear();
            self.mem_val.clear();
        }
        if disk {
            self.disk_lab.set_ascii(b"DISK");
            self.disk_val.set_pct(m.disk);
        } else {
            self.disk_lab.clear();
            self.disk_val.clear();
        }
        if net {
            self.up_arrow.set_arrow(true);
            self.down_arrow.set_arrow(false);
            self.up_speed.set_rate(m.up);
            self.down_speed.set_rate(m.down);
        } else {
            self.up_arrow.clear();
            self.down_arrow.clear();
            self.up_speed.clear();
            self.down_speed.clear();
        }
    }
}

#[cfg(test)]
mod v08_regression {
    use super::*;
    use crate::items::Items;

    fn text(t: &WText) -> String {
        String::from_utf16_lossy(&t.units[..t.len.min(t.units.len())])
    }

    fn metrics() -> Metrics {
        Metrics { cpu: 100, mem: 7, disk: 42, up: 2_949_760, down: 1536 }
    }

    /// v0.8 回归：指标关掉再打开，标签与 ↑↓ 必须回来。
    #[test]
    fn toggling_items_back_on_restores_labels_and_arrows() {
        let m = metrics();
        let mut t = Texts::new();
        t.apply(&m, &Items::ALL);
        assert_eq!(text(&t.cpu_lab), "CPU");
        assert_eq!(text(&t.up_arrow), "\u{2191}");

        let off = Items { cpu: false, mem: false, disk: false, net: false };
        t.apply(&m, &off);
        assert_eq!(text(&t.cpu_lab), "");
        assert_eq!(text(&t.up_arrow), "");
        assert_eq!(text(&t.cpu_val), "");

        t.apply(&m, &Items::ALL);
        assert_eq!(text(&t.cpu_lab), "CPU");
        assert_eq!(text(&t.mem_lab), "MEM");
        assert_eq!(text(&t.disk_lab), "DISK");
        assert_eq!(text(&t.up_arrow), "\u{2191}");
        assert_eq!(text(&t.down_arrow), "\u{2193}");
        assert_eq!(text(&t.mem_val), "7%");
    }

    /// 单项关闭时其它项不受影响。
    #[test]
    fn disabling_cpu_keeps_mem_and_disk() {
        let m = metrics();
        let mut t = Texts::new();
        t.apply(&m, &Items { cpu: false, mem: true, disk: true, net: true });
        assert_eq!(text(&t.cpu_lab), "");
        assert_eq!(text(&t.mem_lab), "MEM");
        assert_eq!(text(&t.disk_lab), "DISK");
        assert_eq!(text(&t.mem_val), "7%");
    }
}

// ---------------------------------------------------------------- 配色

#[derive(Clone, Copy)]
pub struct Palette {
    pub bg: COLORREF,
    pub label: COLORREF,
    pub up: COLORREF,
    pub down: COLORREF,
    pub green: COLORREF,
    pub amber: COLORREF,
    pub red: COLORREF,
}

impl Palette {
    /// 颜色取自参考图像素：标签/网速纯黑，↑ 粉红，↓ 蓝，百分比按阈值着色。
    pub fn light() -> Self {
        Self {
            bg: rgb(0xF3, 0xF3, 0xF3),
            label: rgb(0x00, 0x00, 0x00),
            up: rgb(253, 80, 93),
            down: rgb(22, 139, 253),
            green: rgb(24, 120, 62),
            amber: rgb(166, 77, 0),
            red: rgb(200, 30, 30),
        }
    }

    pub fn dark() -> Self {
        Self {
            bg: rgb(0x20, 0x20, 0x20),
            label: rgb(0xE8, 0xE8, 0xE8),
            up: rgb(255, 122, 133),
            down: rgb(96, 165, 250),
            green: rgb(74, 222, 128),
            amber: rgb(251, 191, 36),
            red: rgb(248, 113, 113),
        }
    }

    /// 百分比阈值着色：<70 绿，70-89 橙，>=90 红
    pub fn level(&self, pct: u8) -> COLORREF {
        if pct >= 90 {
            self.red
        } else if pct >= 70 {
            self.amber
        } else {
            self.green
        }
    }
}

// ---------------------------------------------------------------- 字体

pub struct Fonts {
    pub label: HFONT,
    pub value: HFONT,
}

impl Fonts {
    pub fn create(h: i32) -> Self {
        let h = h.max(24);
        // v1.1：整体放大约 8%，与参考图字形比例更接近（9.75pt / 10.25pt）
        let h_label = -((h * 29) / 100);
        let h_value = -((h * 32) / 100);
        let face = wide("Segoe UI");
        unsafe {
            let label = CreateFontW(h_label, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 4, 0, face.as_ptr());
            let value = CreateFontW(h_value, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 4, 0, face.as_ptr());
            Self { label, value }
        }
    }
}

impl Drop for Fonts {
    fn drop(&mut self) {
        unsafe {
            DeleteObject(self.label as HGDIOBJ);
            DeleteObject(self.value as HGDIOBJ);
        }
    }
}

// ---------------------------------------------------------------- 画布

pub struct Canvas {
    mem: HDC,
    bmp: HBITMAP,
    old: HGDIOBJ,
    pub w: i32,
    pub h: i32,
}

impl Canvas {
    pub fn new(w: i32, h: i32) -> Option<Self> {
        unsafe {
            let screen = GetDC(core::ptr::null_mut());
            if screen.is_null() {
                return None;
            }
            let mem = CreateCompatibleDC(screen);
            let bmp = CreateCompatibleBitmap(screen, w, h);
            ReleaseDC(core::ptr::null_mut(), screen);
            if mem.is_null() || bmp.is_null() {
                return None;
            }
            let old = SelectObject(mem, bmp as HGDIOBJ);
            Some(Self { mem, bmp, old, w, h })
        }
    }

    pub fn recreate(&mut self, w: i32, h: i32) {
        unsafe {
            let screen = GetDC(core::ptr::null_mut());
            let mem = CreateCompatibleDC(screen);
            let bmp = CreateCompatibleBitmap(screen, w, h);
            ReleaseDC(core::ptr::null_mut(), screen);
            if mem.is_null() || bmp.is_null() {
                return;
            }
            SelectObject(self.mem, self.old);
            DeleteObject(self.bmp as HGDIOBJ);
            DeleteDC(self.mem);
            self.old = SelectObject(mem, bmp as HGDIOBJ);
            self.mem = mem;
            self.bmp = bmp;
            self.w = w;
            self.h = h;
        }
    }

    pub fn clear(&self, brush: HBRUSH) {
        let rc = RECT { left: 0, top: 0, right: self.w, bottom: self.h };
        unsafe {
            FillRect(self.mem, &rc, brush);
        }
    }

    /// 用当前字体测量文本像素宽度（用于宽度自适应）
    pub fn measure(&self, font: HFONT, t: &WText) -> i32 {
        unsafe {
            SelectObject(self.mem, font as HGDIOBJ);
            let mut sz = windows_sys::Win32::Foundation::SIZE { cx: 0, cy: 0 };
            GetTextExtentPoint32W(self.mem, t.ptr(), t.len as i32, &mut sz);
            sz.cx
        }
    }

    pub fn text(
        &self,
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
        let fmt = DT_FLAGS | if right { DT_RIGHT } else { DT_LEFT };
        unsafe {
            SelectObject(self.mem, font as HGDIOBJ);
            SetTextColor(self.mem, color);
            SetBkMode(self.mem, 1); // TRANSPARENT
            DrawTextW(self.mem, t.ptr(), t.len as i32, &mut rc, fmt);
        }
    }

    pub fn blit_to(&self, dst: HDC) {
        unsafe {
            BitBlt(dst, 0, 0, self.w, self.h, self.mem, 0, 0, 0x00CC_0020); // SRCCOPY
        }
    }
}

impl Drop for Canvas {
    fn drop(&mut self) {
        unsafe {
            SelectObject(self.mem, self.old);
            DeleteObject(self.bmp as HGDIOBJ);
            DeleteDC(self.mem);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(t: &WText) -> String {
        String::from_utf16_lossy(&t.units[..t.len])
    }

    #[test]
    fn pct() {
        let mut t = WText::new();
        t.set_pct(0);
        assert_eq!(s(&t), "0%");
        t.set_pct(7);
        assert_eq!(s(&t), "7%");
        t.set_pct(16);
        assert_eq!(s(&t), "16%");
        t.set_pct(100);
        assert_eq!(s(&t), "100%");
        t.set_pct(120);
        assert_eq!(s(&t), "100%");
    }

    #[test]
    fn rate() {
        let mut t = WText::new();
        t.set_rate(0);
        assert_eq!(s(&t), "0 B/s");
        t.set_rate(512);
        assert_eq!(s(&t), "512 B/s");
        t.set_rate(2900);
        assert_eq!(s(&t), "2.8 KB/s");
        t.set_rate(1024);
        assert_eq!(s(&t), "1.0 KB/s");
        t.set_rate(1_200_000);
        assert_eq!(s(&t), "1.1 MB/s");
        t.set_rate(120_000);
        assert_eq!(s(&t), "117 KB/s");
        t.set_rate(300_000_000);
        assert_eq!(s(&t), "286 MB/s");
        t.set_rate(12_600_000);
        assert_eq!(s(&t), "12.0 MB/s");
    }

    #[test]
    fn arrows() {
        let mut t = WText::new();
        t.set_arrow(true);
        assert_eq!(s(&t), "↑");
        t.set_arrow(false);
        assert_eq!(s(&t), "↓");
    }
}










