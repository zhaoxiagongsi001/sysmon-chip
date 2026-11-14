//! 窗口、消息循环、三模式定位、托盘与右键菜单。
//!
//! 设计要点：单线程、单窗口、1 个 1s 定时器；稳态零堆分配；
//! 任务栏模式用「置顶覆盖」而不是 SetParent，explorer 重启也不会把我们的窗口带走。

use std::ptr;
use std::time::Instant;

use windows_sys::Win32::Foundation::{
    GetLastError, HINSTANCE, HWND, LPARAM, LRESULT, POINT, RECT, WPARAM, ERROR_ALREADY_EXISTS,
};
use windows_sys::Win32::Graphics::Gdi::{
    BeginPaint, CreateRoundRectRgn, CreateSolidBrush, DeleteObject, EndPaint, GetDC, GetMonitorInfoW,
    InvalidateRect, MonitorFromWindow, ReleaseDC, SetWindowRgn, UpdateWindow, MONITORINFO,
    MONITOR_DEFAULTTONEAREST, HDC, HGDIOBJ, PAINTSTRUCT,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::{
    CreateMutexW, GetCurrentProcess, SetProcessWorkingSetSize,
};
use windows_sys::Win32::UI::HiDpi::{GetDpiForSystem, GetDpiForWindow};
use windows_sys::Win32::UI::Shell::{
    Shell_NotifyIconW, NIF_ICON, NIF_MESSAGE, NIF_TIP, NIM_ADD, NIM_DELETE, NIM_MODIFY,
    NOTIFYICONDATAW,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    AppendMenuW, CreatePopupMenu, CreateWindowExW, DefWindowProcW, DestroyMenu, DestroyWindow,
    DispatchMessageW, FindWindowExW, FindWindowW, GetClassNameW, GetCursorPos, GetForegroundWindow,
    GetMessageW,
    GetWindowLongPtrW, GetWindowRect, IsWindowVisible, KillTimer, LoadCursorW, LoadImageW,
    PostMessageW, PostQuitMessage, RegisterClassExW, RegisterWindowMessageW, SetForegroundWindow,
    SetTimer, SetWindowLongPtrW, SetWindowPos, ShowWindow, TrackPopupMenuEx, TranslateMessage,
    CREATESTRUCTW, HMENU, MSG, WNDCLASSEXW,
};

use windows_sys::Win32::UI::Input::KeyboardAndMouse::{ReleaseCapture, SetCapture};

use crate::config::{self, Config, PosMode, Theme};
use crate::metrics::{Metrics, Sampler};
use crate::paint::{
    scale, wide, Canvas, Fonts, Palette, Texts, BASE_H, BASE_W, COL_CPU, COL_DISK, COL_MEM,
    COL_NET, RIGHT_EDGE, ROW1_H, ROW1_Y, ROW2_H, ROW2_Y,
};

// ---- 消息 / 样式常量（用字面量，避免依赖 windows-sys 的常量命名） ----
const WM_NULL: u32 = 0;
const WM_DESTROY: u32 = 2;
const WM_PAINT: u32 = 15;
const WM_ERASEBKGND: u32 = 20;
const WM_SETTINGCHANGE: u32 = 26;
const WM_DISPLAYCHANGE: u32 = 126;
const WM_NCCREATE: u32 = 129;
const WM_TIMER: u32 = 275;
const WM_MOUSEMOVE: u32 = 512;
const WM_LBUTTONDOWN: u32 = 513;
const WM_LBUTTONUP: u32 = 514;
const WM_RBUTTONUP: u32 = 517;
const WM_CONTEXTMENU: u32 = 123;
const WM_DPICHANGED: u32 = 736;
const WM_APP: u32 = 0x8000;
const WM_QUIT_APP: u32 = WM_APP + 2;

const WS_POPUP: u32 = 0x8000_0000;
const WS_EX_TOOLWINDOW: u32 = 0x0000_0080;
const WS_EX_TOPMOST: u32 = 0x0000_0008;
const WS_EX_NOACTIVATE: u32 = 0x0800_0000;
const SW_HIDE: i32 = 0;
const SW_SHOWNOACTIVATE: i32 = 4;
const SWP_NOSIZE: u32 = 0x0001;
const SWP_NOMOVE: u32 = 0x0002;
const SWP_NOACTIVATE: u32 = 0x0010;
const SWP_NOOWNERZORDER: u32 = 0x0200;
const GWLP_USERDATA: i32 = -21;
const IMAGE_ICON: u32 = 1;
const LR_DEFAULTSIZE: u32 = 0x0040;
const LR_SHARED: u32 = 0x8000;
const IDC_ARROW: u32 = 32512;
const TPM_RETURNCMD: u32 = 0x0100;
const TPM_NONOTIFY: u32 = 0x0080;
const MF_STRING: u32 = 0x0000;
const MF_CHECKED: u32 = 0x0008;
const MF_SEPARATOR: u32 = 0x0800;
const MF_POPUP: u32 = 0x0010;

fn hwnd_topmost() -> HWND {
    -1isize as HWND
}

fn rect_zero() -> RECT {
    RECT { left: 0, top: 0, right: 0, bottom: 0 }
}

fn eq_wide(a: &[u16], s: &str) -> bool {
    a.len() == s.len() && a.iter().zip(s.bytes()).all(|(x, b)| *x == b as u16)
}

pub struct App {
    hwnd: HWND,
    hinst: HINSTANCE,
    cfg: Config,
    sampler: Sampler,
    metrics: Metrics,
    texts: Texts,
    fonts: Option<Fonts>,
    pal: Palette,
    canvas: Option<Canvas>,
    brush: HGDIOBJ,
    dpi: u32,
    w: i32,
    h: i32,
    tick: u32,
    drag: Option<(i32, i32)>,
    dragging: bool,
    in_menu: bool,
    visible: bool,
    tray_ok: bool,
    tray_cb: u32,
    taskbar_created: u32,
    trace: bool,
    demo: bool,
    t0: Instant,
}

impl App {
    fn new(cfg: Config, trace: bool, demo: bool, t0: Instant) -> Self {
        Self {
            hwnd: ptr::null_mut(),
            hinst: ptr::null_mut(),
            cfg,
            sampler: Sampler::new(),
            metrics: Metrics::default(),
            texts: Texts::new(),
            fonts: None,
            pal: Palette::light(),
            canvas: None,
            brush: ptr::null_mut(),
            dpi: 96,
            w: BASE_W,
            h: BASE_H,
            tick: 0,
            drag: None,
            dragging: false,
            in_menu: false,
            visible: false,
            tray_ok: false,
            tray_cb: WM_APP + 1,
            taskbar_created: 0,
            trace,
            demo,
            t0,
        }
    }

    unsafe fn init_graphics(&mut self) {
        self.dpi = GetDpiForWindow(self.hwnd);
        if self.dpi == 0 {
            self.dpi = 96;
        }
        self.w = scale(BASE_W, self.dpi);
        // v0.3：高度 = 任务栏真实高度（整条覆盖），取不到时退回 48 逻辑
        self.h = match Self::taskbar_rect() {
            Some(r) => (r.bottom - r.top).max(scale(24, self.dpi)),
            None => scale(BASE_H, self.dpi),
        };
        self.pal = self.effective_palette();
        self.fonts = Some(Fonts::create(self.dpi));
        self.canvas = Canvas::new(self.w, self.h);
        self.brush = CreateSolidBrush(self.pal.bg) as HGDIOBJ;
        self.apply_corners();
    }

    fn effective_palette(&self) -> Palette {
        let light = match self.cfg.theme {
            Theme::Light => true,
            Theme::Dark => false,
            Theme::Auto => config::theme_is_light(),
        };
        if light {
            Palette::light()
        } else {
            Palette::dark()
        }
    }

    unsafe fn apply_corners(&self) {
        // v0.3：整条覆盖任务栏，直角矩形即可；显式清掉可能残留的区域
        SetWindowRgn(self.hwnd, ptr::null_mut(), 1);
    }

    // ------------------------------------------------------------ 定位

    unsafe fn monitor_info(&self) -> MONITORINFO {
        let mon = MonitorFromWindow(self.hwnd, MONITOR_DEFAULTTONEAREST);
        let mut mi: MONITORINFO = std::mem::zeroed();
        mi.cbSize = std::mem::size_of::<MONITORINFO>() as u32;
        GetMonitorInfoW(mon, &mut mi);
        mi
    }

    /// 桌面模式：右下角，贴任务栏上沿与屏幕右缘（0 间距，视觉上与任务栏连成一体）
    fn desktop_pos(&self) -> (i32, i32) {
        let mi = unsafe { self.monitor_info() };
        (mi.rcWork.right - self.w, mi.rcWork.bottom - self.h)
    }

    unsafe fn taskbar_rect() -> Option<RECT> {
        let h = FindWindowW(wide("Shell_TrayWnd").as_ptr(), ptr::null());
        if h.is_null() {
            return None;
        }
        let mut r = rect_zero();
        if GetWindowRect(h, &mut r) == 0 {
            return None;
        }
        Some(r)
    }

    fn taskbar_pos(&self) -> Option<(i32, i32)> {
        let bar = unsafe { Self::taskbar_rect() }?;
        let bh = bar.bottom - bar.top;
        Some((bar.left, bar.top + (bh - self.h) / 2))
    }

    /// 托盘通知区左边界（物理坐标）：用于「贴任务栏右端」避开时钟/图标
    unsafe fn tray_notify_rect() -> Option<RECT> {
        let tray = FindWindowW(wide("Shell_TrayWnd").as_ptr(), ptr::null());
        if tray.is_null() {
            return None;
        }
        let tn = FindWindowExW(tray, ptr::null_mut(), wide("TrayNotifyWnd").as_ptr(), ptr::null());
        if tn.is_null() {
            return None;
        }
        let mut r = rect_zero();
        if GetWindowRect(tn, &mut r) == 0 {
            return None;
        }
        Some(r)
    }

    fn taskbar_right_pos(&self) -> Option<(i32, i32)> {
        let bar = unsafe { Self::taskbar_rect() }?;
        let bh = bar.bottom - bar.top;
        let pad = scale(4, self.dpi);
        let x = match unsafe { Self::tray_notify_rect() } {
            Some(tn) if tn.left - self.w - pad > bar.left => tn.left - self.w - pad,
            _ => bar.right - self.w - scale(150, self.dpi),
        };
        Some((x, bar.top + (bh - self.h) / 2))
    }

    fn taskbar_offscreen(&self) -> bool {
        let Some(bar) = (unsafe { Self::taskbar_rect() }) else {
            return true;
        };
        let mi = unsafe { self.monitor_info() };
        let m = mi.rcMonitor;
        bar.top >= m.bottom || bar.bottom <= m.top || bar.left >= m.right || bar.right <= m.left
    }

    unsafe fn apply_position(&mut self) {
        let (x, y) = match self.cfg.mode {
            PosMode::Taskbar => self.taskbar_pos().unwrap_or_else(|| self.desktop_pos()),
            PosMode::TaskbarRight => {
                self.taskbar_right_pos().unwrap_or_else(|| self.desktop_pos())
            }
            PosMode::Free => (self.cfg.x, self.cfg.y),
            PosMode::Desktop => self.desktop_pos(),
        };
        SetWindowPos(self.hwnd, hwnd_topmost(), x, y, self.w, self.h, SWP_NOACTIVATE);
    }

    // ------------------------------------------------------------ 绘制

    unsafe fn render(&self, dst: HDC) {
        let (Some(c), Some(f)) = (&self.canvas, &self.fonts) else {
            return;
        };
        c.clear(self.brush as _);
        let dpi = self.dpi;

        let m = &self.metrics;
        let cols = [
            (COL_CPU, &self.texts.cpu_lab, &self.texts.cpu_val, self.pal.level(m.cpu)),
            (COL_MEM, &self.texts.mem_lab, &self.texts.mem_val, self.pal.level(m.mem)),
            (COL_DISK, &self.texts.disk_lab, &self.texts.disk_val, self.pal.level(m.disk)),
        ];
        for (x, lab, val, color) in cols {
            let px = scale(x, dpi);
            let pw = scale(33, dpi);
            c.text(lab, px, scale(ROW1_Y, dpi), pw, scale(ROW1_H, dpi), false, self.pal.label, f.label);
            c.text(val, px, scale(ROW2_Y, dpi), pw, scale(ROW2_H, dpi), false, color, f.value);
        }

        // 网速列：箭头固定宽，数值右对齐到 RIGHT_EDGE
        let nx = scale(COL_NET, dpi);
        let aw = scale(8, dpi);
        let sx = nx + aw;
        let sw = scale(RIGHT_EDGE - COL_NET, dpi) - aw;
        c.text(&self.texts.up_arrow, nx, scale(ROW1_Y, dpi), aw, scale(ROW1_H, dpi), false, self.pal.up, f.label);
        c.text(&self.texts.up_speed, sx, scale(ROW1_Y, dpi), sw, scale(ROW1_H, dpi), true, self.pal.label, f.label);
        c.text(&self.texts.down_arrow, nx, scale(ROW2_Y, dpi), aw, scale(ROW2_H, dpi), false, self.pal.down, f.value);
        c.text(&self.texts.down_speed, sx, scale(ROW2_Y, dpi), sw, scale(ROW2_H, dpi), true, self.pal.label, f.value);

        c.blit_to(dst);
    }

    unsafe fn paint_now(&mut self) {
        let hdc = GetDC(self.hwnd);
        if !hdc.is_null() {
            self.render(hdc);
            ReleaseDC(self.hwnd, hdc);
        }
    }

    unsafe fn on_paint(&mut self) {
        let mut ps: PAINTSTRUCT = std::mem::zeroed();
        let hdc = BeginPaint(self.hwnd, &mut ps);
        self.render(hdc);
        EndPaint(self.hwnd, &ps);
    }

    // ------------------------------------------------------------ 定时

    unsafe fn on_timer(&mut self) {
        self.tick = self.tick.wrapping_add(1);
        // 菜单/拖动时不抢 z 序；其余每秒重提一次，避免被任务栏盖住
        if !self.in_menu && !self.dragging {
            self.raise_topmost();
        }
        // --demo：固定最坏读数，专门用来自检排版（网速最大值/100%）
        let m = if self.demo {
            Metrics { cpu: 100, mem: 99, disk: 100, up: 999_999, down: 12_345_678 }
        } else {
            self.sampler.sample()
        };
        self.metrics = m;
        let mut t = self.texts;
        t.apply(&m, &self.cfg.items);
        // 宽度自适应：网速右对齐放不下时退成整数格式，绝不和箭头重叠
        if let (Some(c), Some(f)) = (&self.canvas, &self.fonts) {
            let avail = scale(RIGHT_EDGE - COL_NET, self.dpi) - scale(9, self.dpi);
            if c.measure(f.label, &t.up_speed) > avail {
                t.up_speed.set_rate_compact(m.up);
            }
            if c.measure(f.value, &t.down_speed) > avail {
                t.down_speed.set_rate_compact(m.down);
            }
        }
        if t != self.texts {
            self.texts = t;
            InvalidateRect(self.hwnd, ptr::null(), 0);
        }

        self.update_visibility();

        // 周期性归还工作集：默认 1s 刷新时，常驻内存可压在 ~3MB 以内
        if self.tick == 3 || self.tick % 120 == 0 {
            self.trim();
        }

        if matches!(self.cfg.mode, PosMode::Taskbar | PosMode::TaskbarRight) {
            if self.taskbar_offscreen() {
                return;
            }
            let pos = if self.cfg.mode == PosMode::TaskbarRight {
                self.taskbar_right_pos()
            } else {
                self.taskbar_pos()
            };
            if let Some((x, y)) = pos {
                let mut cur = rect_zero();
                GetWindowRect(self.hwnd, &mut cur);
                if cur.left != x || cur.top != y {
                    SetWindowPos(self.hwnd, hwnd_topmost(), x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE);
                }
            }
        }
    }

    unsafe fn update_visibility(&mut self) {
        let mut want = true;
        if self.cfg.hide_fs && self.is_fullscreen_foreground() {
            want = false;
        }
        if matches!(self.cfg.mode, PosMode::Taskbar | PosMode::TaskbarRight)
            && self.taskbar_offscreen()
        {
            want = false;
        }
        if want != self.visible {
            ShowWindow(self.hwnd, if want { SW_SHOWNOACTIVATE } else { SW_HIDE });
            self.visible = want;
            if want {
                self.paint_now();
            }
        }
    }

    unsafe fn is_fullscreen_foreground(&self) -> bool {
        let fg = GetForegroundWindow();
        if fg.is_null() || fg == self.hwnd {
            return false;
        }
        let mut cls = [0u16; 64];
        let n = GetClassNameW(fg, cls.as_mut_ptr(), 64);
        if n <= 0 {
            return false;
        }
        let name = &cls[..n as usize];
        if eq_wide(name, "Progman") || eq_wide(name, "WorkerW") || eq_wide(name, "Shell_TrayWnd") {
            return false;
        }
        if IsWindowVisible(fg) == 0 {
            return false;
        }
        let mut r = rect_zero();
        if GetWindowRect(fg, &mut r) == 0 {
            return false;
        }
        let mi = self.monitor_info();
        let m = mi.rcMonitor;
        r.left <= m.left && r.top <= m.top && r.right >= m.right && r.bottom >= m.bottom
    }

    // ------------------------------------------------------------ 拖动

    unsafe fn on_drag_begin(&mut self) {
        if self.cfg.locked {
            return;
        }
        let mut pt = POINT { x: 0, y: 0 };
        GetCursorPos(&mut pt);
        let mut r = rect_zero();
        GetWindowRect(self.hwnd, &mut r);
        self.drag = Some((pt.x - r.left, pt.y - r.top));
        self.dragging = true;
        SetCapture(self.hwnd);
    }

    unsafe fn on_drag_move(&mut self) {
        if !self.dragging {
            return;
        }
        let Some((ox, oy)) = self.drag else { return };
        let mut pt = POINT { x: 0, y: 0 };
        GetCursorPos(&mut pt);
        SetWindowPos(self.hwnd, hwnd_topmost(), pt.x - ox, pt.y - oy, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE);
    }

    unsafe fn on_drag_end(&mut self) {
        if !self.dragging {
            return;
        }
        self.dragging = false;
        self.drag = None;
        ReleaseCapture();
        let mut r = rect_zero();
        GetWindowRect(self.hwnd, &mut r);
        self.cfg.mode = PosMode::Free;
        self.cfg.x = r.left;
        self.cfg.y = r.top;
        self.cfg.save();
    }

    // ------------------------------------------------------------ 菜单

    unsafe fn on_menu(&mut self) {
        let menu = CreatePopupMenu();
        let items = CreatePopupMenu();
        append_item(items, 1, "显示 CPU", self.cfg.items.cpu);
        append_item(items, 2, "显示 内存", self.cfg.items.mem);
        append_item(items, 3, "显示 磁盘", self.cfg.items.disk);
        append_item(items, 4, "显示 网速", self.cfg.items.net);
        AppendMenuW(menu, MF_POPUP, items as usize, wide("显示指标").as_ptr());

        let pos = CreatePopupMenu();
        append_item(pos, 11, "桌面右下角（贴任务栏）", self.cfg.mode == PosMode::Desktop);
        append_item(pos, 12, "贴任务栏左端", self.cfg.mode == PosMode::Taskbar);
        // 贴任务栏右端：本机任务栏图标居中且已排到托盘，硬放会盖图标，故不进菜单（保留 config 项 taskbar-right）
        AppendMenuW(menu, MF_POPUP, pos as usize, wide("位置").as_ptr());

        let itv = CreatePopupMenu();
        append_item(itv, 21, "0.5 秒", self.cfg.interval == 500);
        append_item(itv, 22, "1 秒", self.cfg.interval == 1000);
        append_item(itv, 23, "2 秒", self.cfg.interval == 2000);
        append_item(itv, 24, "5 秒", self.cfg.interval == 5000);
        AppendMenuW(menu, MF_POPUP, itv as usize, wide("刷新间隔").as_ptr());

        let theme = CreatePopupMenu();
        append_item(theme, 31, "跟随系统", self.cfg.theme == Theme::Auto);
        append_item(theme, 32, "浅色", self.cfg.theme == Theme::Light);
        append_item(theme, 33, "深色", self.cfg.theme == Theme::Dark);
        AppendMenuW(menu, MF_POPUP, theme as usize, wide("主题").as_ptr());

        AppendMenuW(menu, MF_SEPARATOR, 0, ptr::null());
        append_item(menu, 43, "开机自启", self.cfg.autostart);
        AppendMenuW(menu, MF_SEPARATOR, 0, ptr::null());
        append_item(menu, 99, "退出", false);

        let mut pt = POINT { x: 0, y: 0 };
        GetCursorPos(&mut pt);
        SetForegroundWindow(self.hwnd);
        self.in_menu = true;
        let cmd = TrackPopupMenuEx(
            menu,
            TPM_RETURNCMD | TPM_NONOTIFY,
            pt.x,
            pt.y,
            self.hwnd,
            ptr::null(),
        );
        DestroyMenu(menu);
        self.in_menu = false;
        PostMessageW(self.hwnd, WM_NULL, 0, 0);
        if cmd != 0 {
            self.on_cmd(cmd as u32);
        }
    }

    unsafe fn on_cmd(&mut self, cmd: u32) {
        match cmd {
            1 => self.cfg.items.cpu = !self.cfg.items.cpu,
            2 => self.cfg.items.mem = !self.cfg.items.mem,
            3 => self.cfg.items.disk = !self.cfg.items.disk,
            4 => self.cfg.items.net = !self.cfg.items.net,
            11 => {
                self.cfg.mode = PosMode::Desktop;
                self.apply_position();
            }
            12 => {
                self.cfg.mode = PosMode::Taskbar;
                self.apply_position();
            }
            13 => {
                self.cfg.mode = PosMode::TaskbarRight;
                self.apply_position();
            }
            14 => {
                let mut r = rect_zero();
                GetWindowRect(self.hwnd, &mut r);
                self.cfg.mode = PosMode::Free;
                self.cfg.x = r.left;
                self.cfg.y = r.top;
            }
            21 => self.set_interval(500),
            22 => self.set_interval(1000),
            23 => self.set_interval(2000),
            24 => self.set_interval(5000),
            31 => {
                self.cfg.theme = Theme::Auto;
                self.refresh_palette();
            }
            32 => {
                self.cfg.theme = Theme::Light;
                self.refresh_palette();
            }
            33 => {
                self.cfg.theme = Theme::Dark;
                self.refresh_palette();
            }
            41 => self.cfg.locked = !self.cfg.locked,
            42 => self.cfg.hide_fs = !self.cfg.hide_fs,
            43 => {
                let on = !self.cfg.autostart;
                if config::set_autostart(on) {
                    self.cfg.autostart = on;
                }
            }
            99 => {
                DestroyWindow(self.hwnd);
                return;
            }
            _ => {}
        }
        self.cfg.save();
        let mut t = self.texts;
        t.apply(&self.metrics, &self.cfg.items);
        self.texts = t;
        InvalidateRect(self.hwnd, ptr::null(), 1);
    }

    fn set_interval(&mut self, ms: u32) {
        self.cfg.interval = ms;
        unsafe {
            KillTimer(self.hwnd, 1);
            SetTimer(self.hwnd, 1, ms, None);
        }
    }

    unsafe fn refresh_palette(&mut self) {
        self.pal = self.effective_palette();
        if !self.brush.is_null() {
            DeleteObject(self.brush);
        }
        self.brush = CreateSolidBrush(self.pal.bg) as HGDIOBJ;
        InvalidateRect(self.hwnd, ptr::null(), 1);
    }

    // ------------------------------------------------------------ 主题 / DPI / 生命周期

    unsafe fn on_setting_change(&mut self) {
        if self.cfg.theme == Theme::Auto {
            self.refresh_palette();
        }
    }

    unsafe fn on_display_change(&mut self) {
        let dpi = GetDpiForWindow(self.hwnd);
        self.dpi = if dpi == 0 { GetDpiForSystem() } else { dpi };
        let w = scale(BASE_W, self.dpi);
        let h = scale(BASE_H, self.dpi);
        self.w = w;
        self.h = h;
        if let Some(c) = &mut self.canvas {
            c.recreate(w, h);
        }
        self.fonts = Some(Fonts::create(self.dpi));
        self.apply_corners();
        SetWindowPos(self.hwnd, hwnd_topmost(), 0, 0, w, h, SWP_NOMOVE | SWP_NOACTIVATE);
        self.apply_position();
        InvalidateRect(self.hwnd, ptr::null(), 1);
    }

    unsafe fn on_destroy(&mut self) {
        KillTimer(self.hwnd, 1);
        self.del_tray();
        self.canvas = None;
        self.fonts = None;
        if !self.brush.is_null() {
            DeleteObject(self.brush);
            self.brush = ptr::null_mut();
        }
        PostQuitMessage(0);
    }

    // ------------------------------------------------------------ 托盘

    unsafe fn update_tray(&mut self) {
        let icon = LoadImageW(self.hinst, 1 as *const u16, IMAGE_ICON, 0, 0, LR_DEFAULTSIZE | LR_SHARED);
        let mut nid: NOTIFYICONDATAW = std::mem::zeroed();
        nid.cbSize = std::mem::size_of::<NOTIFYICONDATAW>() as u32;
        nid.hWnd = self.hwnd;
        nid.uID = 1;
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
        nid.uCallbackMessage = self.tray_cb;
        nid.hIcon = icon as _;
        let tip: Vec<u16> = "SysMon Chip · 资源条".encode_utf16().take(127).collect();
        for (i, ch) in tip.iter().enumerate() {
            nid.szTip[i] = *ch;
        }
        if self.tray_ok {
            Shell_NotifyIconW(NIM_MODIFY, &nid);
        } else {
            self.tray_ok = Shell_NotifyIconW(NIM_ADD, &nid) != 0;
        }
    }

    unsafe fn del_tray(&mut self) {
        if self.tray_ok {
            let mut nid: NOTIFYICONDATAW = std::mem::zeroed();
            nid.cbSize = std::mem::size_of::<NOTIFYICONDATAW>() as u32;
            nid.hWnd = self.hwnd;
            nid.uID = 1;
            Shell_NotifyIconW(NIM_DELETE, &nid);
            self.tray_ok = false;
        }
    }

    unsafe fn on_tray(&mut self, _wp: u32, lp: u32) {
        let low = lp & 0xFFFF;
        match low {
            WM_LBUTTONUP => {
                if self.visible {
                    ShowWindow(self.hwnd, SW_HIDE);
                    self.visible = false;
                } else {
                    ShowWindow(self.hwnd, SW_SHOWNOACTIVATE);
                    self.visible = true;
                    self.raise_topmost();
                    self.paint_now();
                }
            }
            WM_RBUTTONUP | WM_CONTEXTMENU => self.on_menu(),
            _ => {}
        }
    }

    unsafe fn on_taskbar_created(&mut self) {
        self.tray_ok = false;
        self.update_tray();
        self.raise_topmost();
        if self.cfg.mode == PosMode::Taskbar {
            self.apply_position();
        }
    }

    /// 任务栏/开始菜单等会把自己提到 topmost 之上，这里把窗口重新提回最上层。
    fn raise_topmost(&self) {
        unsafe {
            SetWindowPos(
                self.hwnd,
                hwnd_topmost(),
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
            );
        }
    }

    unsafe fn trim(&mut self) {
        SetProcessWorkingSetSize(GetCurrentProcess(), usize::MAX, usize::MAX);
    }

    fn write_trace(&self) {
        if !self.trace {
            return;
        }
        let ms = self.t0.elapsed().as_secs_f64() * 1000.0;
        let exe_bytes = std::env::current_exe()
            .ok()
            .and_then(|p| p.metadata().ok())
            .map(|m| m.len())
            .unwrap_or(0);
        let mut path = std::env::temp_dir();
        path.push("sysmonchip-trace.txt");
        let _ = std::fs::write(
            path,
            format!("startup_ms={ms:.2}\nexe_bytes={exe_bytes}\ndpi={}\nw={}\nh={}\n", self.dpi, self.w, self.h),
        );
    }
}

unsafe fn append_item(menu: HMENU, id: usize, label: &str, checked: bool) {
    let flags = if checked { MF_STRING | MF_CHECKED } else { MF_STRING };
    AppendMenuW(menu, flags, id, wide(label).as_ptr());
}

unsafe extern "system" fn wndproc(hwnd: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    if msg == WM_NCCREATE {
        let cs = &*(lp as *const CREATESTRUCTW);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, cs.lpCreateParams as isize);
        return DefWindowProcW(hwnd, msg, wp, lp);
    }
    let app_ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut App;
    if app_ptr.is_null() {
        return DefWindowProcW(hwnd, msg, wp, lp);
    }
    let app = &mut *app_ptr;
    match msg {
        WM_PAINT => {
            app.on_paint();
            0
        }
        WM_TIMER => {
            if wp == 1 {
                app.on_timer();
            }
            0
        }
        WM_ERASEBKGND => 1,
        WM_LBUTTONDOWN => {
            0
        }
        WM_MOUSEMOVE => {
            0
        }
        WM_LBUTTONUP => {
            0
        }
        WM_RBUTTONUP => {
            app.on_menu();
            0
        }
        WM_SETTINGCHANGE => {
            app.on_setting_change();
            0
        }
        WM_DISPLAYCHANGE | WM_DPICHANGED => {
            app.on_display_change();
            0
        }
        WM_DESTROY => {
            app.on_destroy();
            0
        }
        _ => {
            if msg == app.tray_cb {
                app.on_tray(wp as u32, lp as u32);
                return 0;
            }
            if app.taskbar_created != 0 && msg == app.taskbar_created {
                app.on_taskbar_created();
                return 0;
            }
            if msg == WM_QUIT_APP {
                DestroyWindow(hwnd);
                return 0;
            }
            DefWindowProcW(hwnd, msg, wp, lp)
        }
    }
}

unsafe fn create_window(app_ptr: *mut App) -> HWND {
    let hinst = GetModuleHandleW(ptr::null());
    let class = wide("SysMonChipWnd");
    let mut wc: WNDCLASSEXW = std::mem::zeroed();
    wc.cbSize = std::mem::size_of::<WNDCLASSEXW>() as u32;
    wc.style = 0;
    wc.lpfnWndProc = Some(wndproc);
    wc.hInstance = hinst;
    wc.hCursor = LoadCursorW(ptr::null_mut(), IDC_ARROW as *const u16);
    wc.lpszClassName = class.as_ptr();
    RegisterClassExW(&wc);

    let dpi = GetDpiForSystem();
    let w = scale(BASE_W, if dpi == 0 { 96 } else { dpi });
    let h = scale(BASE_H, if dpi == 0 { 96 } else { dpi });
    CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        class.as_ptr(),
        ptr::null(),
        WS_POPUP,
        0,
        0,
        w,
        h,
        ptr::null_mut(),
        ptr::null_mut(),
        hinst,
        app_ptr as *const _,
    )
}

/// 请求已运行的实例退出（验收脚本与命令行都用它，避免 taskkill 的权限问题）
pub fn quit_existing() {
    unsafe {
        if let Some(h) = find_existing() {
            PostMessageW(h, WM_QUIT_APP, 0, 0);
        }
    }
}

fn find_existing() -> Option<HWND> {
    let h = unsafe { FindWindowW(wide("SysMonChipWnd").as_ptr(), ptr::null()) };
    if h.is_null() {
        None
    } else {
        Some(h)
    }
}

pub fn run(trace: bool, demo: bool, t0: Instant) {
    unsafe {
        let mutex = CreateMutexW(ptr::null(), 0, wide("Local\\SysMonChip.v1").as_ptr());
        if mutex.is_null() {
            return;
        }
        if GetLastError() == ERROR_ALREADY_EXISTS {
            if let Some(h) = find_existing() {
                ShowWindow(h, SW_SHOWNOACTIVATE);
                SetWindowPos(h, hwnd_topmost(), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER);
            }
            return;
        }

        let mut cfg = Config::load();
        cfg.autostart = config::autostart_registered();
        let app_ptr = Box::into_raw(Box::new(App::new(cfg, trace, demo, t0)));
        let hwnd = create_window(app_ptr);
        if hwnd.is_null() {
            return;
        }
        (*app_ptr).hwnd = hwnd;
        (*app_ptr).hinst = GetModuleHandleW(ptr::null());
        (*app_ptr).taskbar_created = RegisterWindowMessageW(wide("TaskbarCreated").as_ptr());
        (*app_ptr).init_graphics();
        // 预采样一次：让第一个 1s 定时器就有 CPU/网速基线，不会先显示 0
        (*app_ptr).sampler.sample();
        (*app_ptr).apply_position();
        (*app_ptr).paint_now();
        ShowWindow(hwnd, SW_SHOWNOACTIVATE);
        UpdateWindow(hwnd);
        (*app_ptr).visible = true;
        (*app_ptr).trim();
        (*app_ptr).update_tray();
        if trace {
            (*app_ptr).write_trace();
        }

        SetTimer(hwnd, 1, (*app_ptr).cfg.interval, None);

        let mut msg: MSG = std::mem::zeroed();
        while GetMessageW(&mut msg, ptr::null_mut(), 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        drop(Box::from_raw(app_ptr));
    }
}












