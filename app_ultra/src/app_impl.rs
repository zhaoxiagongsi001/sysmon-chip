//! 窗口、消息循环、三模式定位、托盘与右键菜单。
//!
//! 设计要点：单线程、单窗口、1 个 1s 定时器；稳态零堆分配；
//! 任务栏模式用「置顶覆盖」而不是 SetParent，explorer 重启也不会把我们的窗口带走。

use core::ptr;
use core::sync::atomic::{AtomicUsize, Ordering};

use windows_sys::Win32::Foundation::{COLORREF, SIZE,
    GetLastError, HINSTANCE, HWND, LPARAM, LRESULT, POINT, RECT, WPARAM, ERROR_ALREADY_EXISTS,
};
use windows_sys::Win32::Graphics::Gdi::{
    BeginPaint, CombineRgn, CreateRectRgn, CreateRoundRectRgn, CreateSolidBrush, DeleteObject,
    EndPaint, ExtTextOutW, FillRect, GetDC,
    GetTextExtentPoint32W,
    GetMonitorInfoW, InvalidateRect, MonitorFromWindow, ReleaseDC, SelectObject, SetBkMode,
    SetTextColor, SetWindowRgn, UpdateWindow, MONITORINFO, MONITOR_DEFAULTTONEAREST, RGN_OR, HDC,
    HFONT, HGDIOBJ, PAINTSTRUCT,
};
use windows_sys::Win32::System::LibraryLoader::{GetModuleHandleW, GetProcAddress};
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
    SetWindowTextW,
    DispatchMessageW, FindWindowExW, FindWindowW, GetClassNameW, GetCursorPos, GetForegroundWindow,
    GetMessageW, GetWindow,
    GetWindowLongPtrW, GetWindowRect, IsWindowVisible, KillTimer, LoadCursorW, LoadImageW,
    PostMessageW, PostQuitMessage, RegisterClassExW, RegisterWindowMessageW, SetForegroundWindow,
    SetTimer, SetWindowLongPtrW, SetWindowPos, ShowWindow, TrackPopupMenuEx, TranslateMessage,
    CREATESTRUCTW, HMENU, MSG, WNDCLASSEXW, MessageBoxW, MB_ICONINFORMATION, MB_ICONWARNING, MB_OK,
};

use windows_sys::Win32::UI::Input::KeyboardAndMouse::{ReleaseCapture, SetCapture};

use crate::config::{self, Config, PosMode, Theme};
use chip_core::metrics::{Metrics, Sampler};
use chip_core::paint::{
    arrow_fits, layout, net_group_x, rgb, scale, wide, Fonts, Palette, Texts, WText, BASE_H,
    CORNER_R, ITEM_W, NET_ARROW_W, NET_GAP,
};

// ---- 消息 / 样式常量（用字面量，避免依赖 windows-sys 的常量命名） ----
const WM_NULL: u32 = 0;
const WM_DESTROY: u32 = 2;
const WM_PAINT: u32 = 15;
const WM_ERASEBKGND: u32 = 20;
const WM_SETTINGCHANGE: u32 = 26;
const WM_COMMAND: u32 = 273;
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
/// WinEvent 钩子收到 z 序/前台变化后投给自己的消息
const WM_Z_EVENT: u32 = WM_APP + 3;
/// 另一个实例（启动器二次启动）要求把资源条唤出来
const WM_SHOW_CHIP: u32 = WM_APP + 4;

/// 防御性 z 序守护定时器：只在「检测到被任务栏压住 / 任务栏刚拿到前台」后跑一小段
const TIMER_GUARD: usize = 2;
const GUARD_MS: u32 = 16;
const GUARD_TICKS: u32 = 40;

const GW_HWNDPREV: u32 = 3;
const EVENT_SYSTEM_FOREGROUND: u32 = 0x0003;
const EVENT_OBJECT_REORDER: u32 = 0x8004;
const WINEVENT_SKIPOWNPROCESS: u32 = 0x0002;

const WS_POPUP: u32 = 0x8000_0000;
const WS_EX_TOOLWINDOW: u32 = 0x0000_0080;
const WS_EX_TOPMOST: u32 = 0x0000_0008;
const WS_EX_NOACTIVATE: u32 = 0x0800_0000;
const WS_EX_LAYERED: u32 = 0x0008_0000;
const ULW_ALPHA: u32 = 0x0000_0002;
const SW_HIDE: i32 = 0;
const SW_SHOWNOACTIVATE: i32 = 4;
const SWP_NOSIZE: u32 = 0x0001;
const SWP_NOMOVE: u32 = 0x0002;
const SWP_NOACTIVATE: u32 = 0x0010;
const SWP_NOOWNERZORDER: u32 = 0x0200;
const GWLP_USERDATA: i32 = -21;
const GWL_EXSTYLE: i32 = -20;
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



// ---------------------------------------------------------------- 亚克力模糊

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

const WCA_ACCENT_POLICY: i32 = 19;
const ACCENT_ENABLE_ACRYLICBLURBEHIND: i32 = 4;

fn acrylic_tint(pal: &Palette) -> u32 {
    if pal.bg == rgb(0xF3, 0xF3, 0xF3) {
        0xB8F3F3F3
    } else {
        0xB8202020
    }
}

/// 给窗口加任务栏同款亚克力模糊；失败返回 false（调用方退回半透明实色）
unsafe fn enable_acrylic(hwnd: HWND, tint: u32) -> bool {
    type SetWca = unsafe extern "system" fn(HWND, *mut WinCompAttrData) -> i32;
    let user32 = GetModuleHandleW(wide("user32.dll").as_ptr());
    if user32.is_null() {
        return false;
    }
    let proc = GetProcAddress(user32, wide("SetWindowCompositionAttribute").as_ptr().cast());
    let Some(f) = proc else { return false };
    let set_wca: SetWca = core::mem::transmute(f);
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


/// 透明背景上画文字（灰色抗锯齿，避免 ClearType 在透明底上的彩边）
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
    // v1.3：DrawTextW 每次都要走一遍 DT_ 格式解析与断行计算，实测每 tick 占掉绘制成本的
    // 大头。数字/字母都是单行 ASCII，这里自己量宽定位后一次 ExtTextOutW 出字，
    // 语义等价（水平居中/右对齐由 x 算出，垂直居中由 (h - cy) / 2 复刻 DT_VCENTER）。
    SelectObject(hdc, font as HGDIOBJ);
    SetTextColor(hdc, color);
    SetBkMode(hdc, 1);
    let mut sz = SIZE { cx: 0, cy: 0 };
    if GetTextExtentPoint32W(hdc, t.ptr(), t.len as i32, &mut sz) == 0 {
        return;
    }
    let tx = if right { x + w - sz.cx } else { x };
    let ty = y + (h - sz.cy) / 2;
    ExtTextOutW(
        hdc,
        tx,
        ty,
        0,
        ptr::null(),
        t.ptr(),
        t.len as u32,
        ptr::null(),
    );
}


/// 测量文本像素宽（用于网速列自适应）
unsafe fn measure_text(hdc: HDC, font: HFONT, t: &WText) -> i32 {
    SelectObject(hdc, font as HGDIOBJ);
    let mut sz = SIZE { cx: 0, cy: 0 };
    GetTextExtentPoint32W(hdc, t.ptr(), t.len as i32, &mut sz);
    sz.cx
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

    acrylic: bool,
    brush: HGDIOBJ,
    dpi: u32,
    w: i32,
    h: i32,
    tick: u32,
    drag: Option<(i32, i32)>,
    dragging: bool,
    in_menu: bool,
    visible: bool,
    /// 用户用托盘左键手动隐藏：为真时 `update_visibility` 不再把它显示回来
    hidden_by_user: bool,
    tray_ok: bool,
    tray_cb: u32,
    taskbar_created: u32,
    evt_reorder: *mut core::ffi::c_void,
    evt_fg: *mut core::ffi::c_void,
    guard_ticks: u32,
    raises: u32,
    /// 网速两行文字在当前 DPI 下的实测宽度（px）：每 tick 算一次，render 不再每帧量
    up_w: i32,
    dn_w: i32,
    /// 上一次写配置失败（文件被占用等）：下一个 tick 自动重试
    save_pending: bool,
    /// 连续重试次数：按 tick 累计，放弃阈值由刷新间隔换算成「约两分钟」
    save_tries: u32,
    /// 压缩后仍放不下（极端读数）：只落一次诊断，避免每 tick 刷临时文件
    net_clipped: bool,
    trace: bool,
    demo: bool,
    t0: i64,
}

impl App {
    fn new(cfg: Config, trace: bool, demo: bool, t0: i64) -> Self {
        // 建窗之前就要按当前指标算出宽度，否则会先按旧的固定宽闪一下再缩
        let w0 = layout(&cfg.items).width;
        Self {
            hwnd: ptr::null_mut(),
            hinst: ptr::null_mut(),
            cfg,
            sampler: Sampler::new(),
            metrics: Metrics::default(),
            texts: Texts::new(),
            fonts: None,
            pal: Palette::light(),

            acrylic: false,
            brush: ptr::null_mut(),
            dpi: 96,
            w: w0,
            h: BASE_H,
            tick: 0,
            drag: None,
            dragging: false,
            in_menu: false,
            visible: false,
            hidden_by_user: false,
            tray_ok: false,
            tray_cb: WM_APP + 1,
            taskbar_created: 0,
            evt_reorder: ptr::null_mut(),
            evt_fg: ptr::null_mut(),
            guard_ticks: 0,
            raises: 0,
            up_w: 0,
            dn_w: 0,
            save_pending: false,
            save_tries: 0,
            net_clipped: false,
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
        self.w = scale(layout(&self.cfg.items).width, self.dpi);
        // v0.3：高度 = 任务栏真实高度（整条覆盖），取不到时退回 48 逻辑
        self.h = match Self::taskbar_rect() {
            Some(r) => ((r.bottom - r.top) - scale(1, self.dpi)).max(scale(24, self.dpi)),
            None => scale(BASE_H, self.dpi),
        };
        self.pal = self.effective_palette();
        self.fonts = Some(Fonts::create(self.h));
        self.brush = CreateSolidBrush(self.pal.bg) as HGDIOBJ;
        // 真高斯模糊：DWM 亚克力（普通窗口 + SetWindowCompositionAttribute）
        self.acrylic = enable_acrylic(self.hwnd, acrylic_tint(&self.pal));
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
        // v0.9：只圆「外露的那条竖边」——贴着屏幕/任务栏的那一侧保持直角，
        // 这样看起来是嵌在那里的；矩形窗口自身不做圆角，靠窗口区域裁出来。
        if self.w <= 0 || self.h <= 0 {
            return;
        }
        let r = scale(CORNER_R, self.dpi).max(2);
        let (rw, rh) = (self.w + 1, self.h + 1);
        let right = self.rounds_right();
        let rgn = CreateRoundRectRgn(0, 0, rw, rh, r * 2, r * 2);
        if rgn.is_null() {
            return;
        }
        // 把贴屏一侧被圆掉的两个角补回直角
        let sq = CreateRectRgn(
            if right { 0 } else { rw - r - 1 },
            0,
            if right { r + 1 } else { rw },
            rh,
        );
        if !sq.is_null() {
            CombineRgn(rgn, rgn, sq, RGN_OR);
            DeleteObject(sq as _);
        }
        // SetWindowRgn 成功后区域归系统所有，不能再 DeleteObject
        if SetWindowRgn(self.hwnd, rgn, 1) == 0 {
            DeleteObject(rgn as _);
        }
    }

    /// 圆角该长在哪一侧：窗口在屏幕左半边 → 外露边是右边（左缘贴屏）。
    unsafe fn rounds_right(&self) -> bool {
        let mi = self.monitor_info();
        let mut r = rect_zero();
        if GetWindowRect(self.hwnd, &mut r) == 0 {
            return true;
        }
        let cx = (r.left + r.right) / 2;
        cx < (mi.rcMonitor.left + mi.rcMonitor.right) / 2
    }

    // ------------------------------------------------------------ 定位

    unsafe fn monitor_info(&self) -> MONITORINFO {
        let mon = MonitorFromWindow(self.hwnd, MONITOR_DEFAULTTONEAREST);
        let mut mi: MONITORINFO = core::mem::zeroed();
        mi.cbSize = core::mem::size_of::<MONITORINFO>() as u32;
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
        // v0.4：下移 1 逻辑像素，露出任务栏顶部那条细线；底边与任务栏底对齐
        Some((bar.left, bar.top + scale(1, self.dpi)))
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
        self.apply_corners();
    }

    // ------------------------------------------------------------ 绘制

    unsafe fn render(&self, dst: HDC) {
        let Some(f) = &self.fonts else { return };
        let dpi = self.dpi;
        let row_h = self.h / 2;
        // 亚克力可用：只画文字（模糊由 DWM 合成在窗口后面）；失败则自己填实色底
        if !self.acrylic {
            let rc = RECT { left: 0, top: 0, right: self.w, bottom: self.h };
            FillRect(dst, &rc, self.brush as _);
        }
        let m = &self.metrics;
        let lay = layout(&self.cfg.items);
        let cells = [
            (0usize, &self.texts.cpu_lab, &self.texts.cpu_val, self.pal.level(m.cpu)),
            (1, &self.texts.mem_lab, &self.texts.mem_val, self.pal.level(m.mem)),
            (2, &self.texts.disk_lab, &self.texts.disk_val, self.pal.level(m.disk)),
        ];
        // 最后一列（网速关掉时就是磁盘）的数值右对齐到列右缘：
        // 否则右侧留白会随数字宽度变化，和左边 8px 的固定内边距对不上。
        let last_on = lay.last_on().unwrap_or(0);
        for (i, lab, val, color) in cells {
            if !lay.on[i] {
                continue;
            }
            let px = scale(lay.x[i], dpi);
            let pw = scale(ITEM_W[i] - 2, dpi);
            let last = i == last_on;
            draw_text(dst, lab, px, 0, pw, row_h, false, self.pal.label, f.label);
            // 末列的数值用整格宽度右对齐，右缘正好落在 面板宽 − PAD_R
            let vw = if last { scale(ITEM_W[i], dpi) } else { pw };
            draw_text(dst, val, px, row_h, vw, self.h - row_h, last, color, f.value);
        }
        if lay.on[3] {
            let nx = scale(lay.x[3], dpi);
            let aw = scale(NET_ARROW_W, dpi);
            let gap = scale(NET_GAP, dpi);
            // 列右缘 = 面板右缘 - PAD_R：箭头和数字作为一组右对齐，箭头永远紧贴
            // 数字，右侧留白恒等于左侧 PAD_L（不再随数值长短浮动）。
            // 宽度是 on_timer 量好的；这里再用 net_group_x 夹一次，保证箭头不越界。
            let right = nx + scale(ITEM_W[3], dpi);
            // 首帧（run() 里第一次 paint_now）还没跑过 on_timer，缓存宽度是 0；
            // 此时现场量一次，否则速度文字会以 0 宽画不出来，只剩箭头。
            let up_w = if self.up_w > 0 {
                self.up_w
            } else {
                measure_text(dst, f.label, &self.texts.up_speed)
            };
            let dn_w = if self.dn_w > 0 {
                self.dn_w
            } else {
                measure_text(dst, f.value, &self.texts.down_speed)
            };
            let (up_x, up_ax) = net_group_x(right, up_w, aw, gap, nx);
            let (dn_x, dn_ax) = net_group_x(right, dn_w, aw, gap, nx);
            let upw = right - up_x;
            let dnw = right - dn_x;
            draw_text(dst, &self.texts.up_speed, up_x, 0, upw, row_h, false, self.pal.label, f.label);
            draw_text(dst, &self.texts.down_speed, dn_x, row_h, dnw, self.h - row_h, false, self.pal.label, f.value);
            // 两者都被夹在列左缘：极端宽读数下箭头会与数字重叠，这时宁可不画箭头。
            // 能不能放得下由 paint::arrow_fits 判定，渲染层不自己做几何。
            if arrow_fits(up_ax, aw, up_x) {
                draw_text(dst, &self.texts.up_arrow, up_ax, 0, aw, row_h, false, self.pal.up, f.label);
            }
            if arrow_fits(dn_ax, aw, dn_x) {
                draw_text(dst, &self.texts.down_arrow, dn_ax, row_h, aw, self.h - row_h, false, self.pal.down, f.value);
            }
        }
    }

    unsafe fn paint_now(&mut self) {
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

    // ------------------------------------------------------------ 定时

    /// 配置反复写不进去（盘被占、只读、权限）时留一份可查的现场：写失败后没有任何痕迹，
    /// 用户只会觉得「我改了设置怎么没保存」，所以落一个 %TEMP% 诊断文件。
    fn report_save_failed(&self, err: u32) {
        let mut buf = [0u8; 128];
        let mut n = 0usize;
        for b in b"reason=save_failed_after_retry\nitems=" {
            buf[n] = *b;
            n += 1;
        }
        let it = &self.cfg.items;
        for (flag, name) in [
            (it.cpu, b"cpu " as &[u8]),
            (it.mem, b"mem "),
            (it.disk, b"disk "),
            (it.net, b"net"),
        ] {
            if flag {
                for b in name {
                    buf[n] = *b;
                    n += 1;
                }
            }
        }
        buf[n] = b'\n';
        n += 1;
        for b in b"last_error=" {
            buf[n] = *b;
            n += 1;
        }
        crate::push_u64(&mut buf, &mut n, err as u64);
        buf[n] = b'\n';
        n += 1;
        config::write_temp("sysmonchip-save-error.txt", &buf[..n]);
    }

    /// 写配置：失败（文件被占用等）就记下来，下一个 tick 自动重试，不打断用户操作。
    unsafe fn persist(&mut self) {
        if !self.cfg.save() {
            self.save_pending = true;
            self.save_tries = 0;
        }
    }

    unsafe fn on_timer(&mut self) {
        self.tick = self.tick.wrapping_add(1);
        self.raises = 0;
        // 上一次写配置没成功：每秒重试一次；连续失败约两分钟就放弃，
        // 否则磁盘被锁死时这里会一直空转
        if self.save_pending {
            if self.cfg.save() {
                self.save_pending = false;
            } else {
                // 立刻取样：再拖几步，GetLastError 就会被别的 Win32 调用覆盖
                let err = unsafe { GetLastError() };
                self.save_tries += 1;
                // 预算按时间算：约两分钟，不绑定刷新间隔（5 秒间隔下是 24 次而不是 120 次）
                let budget = (120_000 / self.cfg.interval.max(200)).max(4);
                if self.save_tries >= budget {
                    self.save_pending = false;
                    self.save_tries = 0;
                    self.report_save_failed(err);
                }
            }
        }
        // 菜单/拖动时不抢 z 序；其余每秒自查一次是否被任务栏压住（真的被压才提层）
        if !self.in_menu && !self.dragging && self.covered_by_taskbar() {
            self.raise_above_taskbar();
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
        // 网速列预算 = 列宽 − 箭头 − 间隙。v1.0 起由常量推导（原来只减 9 逻辑 px，
        // 漏算了箭头左侧的间隙，≥100 MB/s 时箭头会压进磁盘列）。
        // 超宽先退紧凑格式（MB 取整 / GB 一位小数），量完再存，render 不再每帧测量。
        let mut up_w = self.up_w;
        let mut dn_w = self.dn_w;
        if let Some(f) = &self.fonts {
            let avail = scale(ITEM_W[3] - NET_ARROW_W - NET_GAP, self.dpi);
            let hdc = GetDC(self.hwnd);
            if !hdc.is_null() {
                up_w = measure_text(hdc, f.label, &t.up_speed);
                if up_w > avail {
                    t.up_speed.set_rate_compact(m.up);
                    up_w = measure_text(hdc, f.label, &t.up_speed);
                }
                dn_w = measure_text(hdc, f.value, &t.down_speed);
                if dn_w > avail {
                    t.down_speed.set_rate_compact(m.down);
                    dn_w = measure_text(hdc, f.value, &t.down_speed);
                }
                ReleaseDC(self.hwnd, hdc);
                // 压缩后仍放不下（速率极端）：留一次诊断，否则用户只看到数字被裁掉
                let clipped = up_w > avail || dn_w > avail;
                if clipped && !self.net_clipped {
                    self.net_clipped = true;
                    let mut buf = [0u8; 96];
                    let mut n = 0usize;
                    for b in b"reason=net_text_clipped\navail=" {
                        buf[n] = *b;
                        n += 1;
                    }
                    crate::push_u64(&mut buf, &mut n, avail as u64);
                    for b in b"\nup_w=" {
                        buf[n] = *b;
                        n += 1;
                    }
                    crate::push_u64(&mut buf, &mut n, up_w as u64);
                    for b in b"\ndn_w=" {
                        buf[n] = *b;
                        n += 1;
                    }
                    crate::push_u64(&mut buf, &mut n, dn_w as u64);
                    buf[n] = b'\n';
                    n += 1;
                    config::write_temp("sysmonchip-net-clipped.txt", &buf[..n]);
                } else if !clipped {
                    self.net_clipped = false;
                }
            }
        }
        let width_changed = up_w != self.up_w || dn_w != self.dn_w;
        self.up_w = up_w;
        self.dn_w = dn_w;
        if t != self.texts || width_changed {
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
        let mut want = !self.hidden_by_user;
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
        self.persist();
    }

    // ------------------------------------------------------------ 菜单

    unsafe fn on_menu(&mut self) {
        // v1.4：勾选状态以注册表为准，而且只有「指向当前 exe」才算真的开着——
        // 换过版本后残留的旧路径不会让菜单虚勾。用户也可能在注册表里手改过。
        self.cfg.autostart = config::autostart_points_to_current() == Some(true);
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
            1..=4 => {
                let mut items = self.cfg.items;
                match cmd {
                    1 => items.cpu = !items.cpu,
                    2 => items.mem = !items.mem,
                    3 => items.disk = !items.disk,
                    _ => items.net = !items.net,
                }
                // v0.9：至少保留一项，否则面板会缩成一条空白
                if !(items.cpu || items.mem || items.disk || items.net) {
                    return;
                }
                self.cfg.items = items;
            }
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
                } else {
                    // v1.4：写注册表失败不再静默（低权限运行、组策略锁定都会走到这里）
                    // 注意 wide() 上限 63 个 UTF-16 单元，文案要短，否则会被截断
                    MessageBoxW(
                        self.hwnd,
                        wide("没有权限写入开机自启项，请从桌面正常启动后再试。").as_ptr(),
                        wide("SysMonChip").as_ptr(),
                        MB_OK | MB_ICONWARNING,
                    );
                }
            }
            99 => {
                DestroyWindow(self.hwnd);
                return;
            }
            _ => {}
        }
        self.relayout();
        self.persist();
        let mut t = self.texts;
        t.apply(&self.metrics, &self.cfg.items);
        self.texts = t;
        InvalidateRect(self.hwnd, ptr::null(), 1);
    }

    /// v0.9：按当前可见指标重算宽度。贴屏那一侧保持不动：左对齐（任务栏左端）
    /// 宽度从右侧缩回，右对齐（桌面右下角 / 贴托盘）左缘左移，视觉上都还是贴边的。
    unsafe fn relayout(&mut self) {
        let w = scale(layout(&self.cfg.items).width, self.dpi);
        if w == self.w {
            self.apply_corners();
            return;
        }
        self.w = w;
        self.apply_position();
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
        let w = scale(layout(&self.cfg.items).width, self.dpi);
        let h = match Self::taskbar_rect() {
            Some(r) => ((r.bottom - r.top) - scale(1, self.dpi)).max(scale(24, self.dpi)),
            None => scale(BASE_H, self.dpi),
        };
        self.w = w;
        self.h = h;
        self.fonts = Some(Fonts::create(self.h));
        self.apply_corners();
        SetWindowPos(self.hwnd, hwnd_topmost(), 0, 0, w, h, SWP_NOMOVE | SWP_NOACTIVATE);
        self.apply_position();
        InvalidateRect(self.hwnd, ptr::null(), 1);
    }

    unsafe fn on_destroy(&mut self) {
        KillTimer(self.hwnd, 1);
        self.del_tray();
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
        let mut nid: NOTIFYICONDATAW = core::mem::zeroed();
        nid.cbSize = core::mem::size_of::<NOTIFYICONDATAW>() as u32;
        nid.hWnd = self.hwnd;
        nid.uID = 1;
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
        nid.uCallbackMessage = self.tray_cb;
        nid.hIcon = icon as _;
        let tip = "SysMon Chip · 资源条".encode_utf16();
        for (i, ch) in tip.take(127).enumerate() {
            nid.szTip[i] = ch;
        }
        if self.tray_ok {
            Shell_NotifyIconW(NIM_MODIFY, &nid);
        } else {
            self.tray_ok = Shell_NotifyIconW(NIM_ADD, &nid) != 0;
        }
    }

    unsafe fn del_tray(&mut self) {
        if self.tray_ok {
            let mut nid: NOTIFYICONDATAW = core::mem::zeroed();
            nid.cbSize = core::mem::size_of::<NOTIFYICONDATAW>() as u32;
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
                // 托盘左键 = 手动显示/隐藏。必须记状态，否则下一个 tick 的
                // update_visibility 会立刻把它重新显示出来（v0.7 及以前的实际表现）。
                self.hidden_by_user = !self.hidden_by_user;
                self.update_visibility();
                if self.visible {
                    self.raise_above_taskbar();
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
        self.raise_above_taskbar();
        if self.cfg.mode == PosMode::Taskbar {
            self.apply_position();
        }
    }

    /// 把自己提到任务栏之上。
    ///
    /// 任务栏（Shell_TrayWnd）自己也是 WS_EX_TOPMOST：点它空白处时 explorer 会
    /// SetWindowPos(HWND_TOPMOST) 把自己提到 topmost 带顶，于是把我们压住 ——
    /// 视觉上就是「资源条消失、约半秒后又被定时器提回来」。
    /// 首选插到任务栏正上方（不挡后升起的开始菜单）；跨进程插位被系统拒绝时
    /// （低完整性下实测 SetWindowPos 返回 0）退回 HWND_TOPMOST，仍然高于任务栏。
    unsafe fn raise_above_taskbar(&self) {
        let flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER;
        let tray = FindWindowW(wide("Shell_TrayWnd").as_ptr(), ptr::null());
        // SetWindowPos 的 hWndInsertAfter 是「排在目标窗口前面」的那一个：
        // 直接传任务栏句柄会把自己塞到任务栏*后面*，必须传任务栏前面那一个。
        if !tray.is_null() {
            let front = GetWindow(tray, GW_HWNDPREV);
            if !front.is_null() {
                let ex = GetWindowLongPtrW(front, GWL_EXSTYLE) as u32;
                if ex & WS_EX_TOPMOST != 0
                    && SetWindowPos(self.hwnd, front, 0, 0, 0, 0, flags) != 0
                {
                    return;
                }
            }
        }
        SetWindowPos(self.hwnd, hwnd_topmost(), 0, 0, 0, 0, flags);
    }

    /// 任务栏是否在 z 序里压着我们：沿 GW_HWNDPREV 往上找若干层。
    unsafe fn covered_by_taskbar(&self) -> bool {
        let tray = FindWindowW(wide("Shell_TrayWnd").as_ptr(), ptr::null());
        if tray.is_null() {
            return false;
        }
        let mut h = self.hwnd;
        for _ in 0..12 {
            let prev = GetWindow(h, GW_HWNDPREV);
            if prev.is_null() || prev == self.hwnd {
                return false;
            }
            if prev == tray {
                return true;
            }
            h = prev;
        }
        false
    }

    unsafe fn fg_is_taskbar(&self) -> bool {
        let fg = GetForegroundWindow();
        if fg.is_null() {
            return false;
        }
        let mut cls = [0u16; 64];
        let n = GetClassNameW(fg, cls.as_mut_ptr(), 64);
        n > 0 && eq_wide(&cls[..n as usize], "Shell_TrayWnd")
    }

    /// z 序守护：被压住时的兜底自查（16ms 一次，只跑一小段，不影响稳态开销）
    /// 已经在跑就不续期，避免事件风暴把定时器一直顶在 16ms
    unsafe fn start_guard(&mut self) {
        if self.guard_ticks > 0 {
            return;
        }
        self.guard_ticks = GUARD_TICKS;
        SetTimer(self.hwnd, TIMER_GUARD, GUARD_MS, None);
    }

    unsafe fn on_guard(&mut self) {
        self.guard_ticks = self.guard_ticks.saturating_sub(1);
        if self.guard_ticks == 0 {
            KillTimer(self.hwnd, TIMER_GUARD);
        }
        if !self.in_menu && !self.dragging && self.covered_by_taskbar() {
            self.raise_above_taskbar();
        }
    }

    /// WinEvent 触发的即时自查：钩子回调只投消息，真正干活在这里（避免钩子里重入）。
    /// `event` 区分事件类型：z 序重排只做「被压住才提层」；只有前台切换才开守护窗口期
    /// （鼠标停在任务栏上时 Explorer 会持续重排，不能让重排事件反复唤醒定时器）。
    unsafe fn on_z_event(&mut self, event: u32) {
        if self.in_menu || self.dragging {
            return;
        }
        if self.covered_by_taskbar() {
            if self.raises < 60 {
                self.raise_above_taskbar();
                self.raises += 1;
            }
            self.start_guard();
            return;
        }
        if event == EVENT_SYSTEM_FOREGROUND && self.fg_is_taskbar() {
            // 任务栏刚拿到前台，接下来一小段时间它可能还会再抢一次 z 序
            self.start_guard();
        }
    }

    unsafe fn install_z_hooks(&mut self) {
        type WinEventProc =
            unsafe extern "system" fn(*mut core::ffi::c_void, u32, HWND, i32, i32, u32, u32);
        type SetHook = unsafe extern "system" fn(
            u32,
            u32,
            *mut core::ffi::c_void,
            Option<WinEventProc>,
            u32,
            u32,
            u32,
        ) -> *mut core::ffi::c_void;
        let user32 = GetModuleHandleW(wide("user32.dll").as_ptr());
        if user32.is_null() {
            return;
        }
        // GetProcAddress 要 ANSI 名字：这里必须是字节串，用 wide() 传 UTF-16 会查成 "S" 而静默返回空
        let Some(p) = GetProcAddress(user32, b"SetWinEventHook\0".as_ptr().cast()) else {
            return;
        };
        let set_hook: SetHook = core::mem::transmute(p);
        self.evt_reorder = set_hook(
            EVENT_OBJECT_REORDER,
            EVENT_OBJECT_REORDER,
            ptr::null_mut(),
            Some(win_event_cb),
            0,
            0,
            WINEVENT_SKIPOWNPROCESS,
        );
        self.evt_fg = set_hook(
            EVENT_SYSTEM_FOREGROUND,
            EVENT_SYSTEM_FOREGROUND,
            ptr::null_mut(),
            Some(win_event_cb),
            0,
            0,
            WINEVENT_SKIPOWNPROCESS,
        );
    }

    /// 调试：把最近一次内部事件写进窗口标题（外部探针可读）
    #[allow(dead_code)]
    unsafe fn dbg_title(&self, tag: &str) {
        let w = wide(tag);
        SetWindowTextW(self.hwnd, w.as_ptr());
    }

    unsafe fn trim(&mut self) {
        SetProcessWorkingSetSize(GetCurrentProcess(), usize::MAX, usize::MAX);
    }

    fn write_trace(&self) {
        if !self.trace {
            return;
        }
        crate::trace_write(self.t0, self.dpi, self.w, self.h);
    }
}

unsafe fn append_item(menu: HMENU, id: usize, label: &str, checked: bool) {
    let flags = if checked { MF_STRING | MF_CHECKED } else { MF_STRING };
    AppendMenuW(menu, flags, id, wide(label).as_ptr());
}

/// WinEvent 回调没有用户参数，投消息只能走全局
static CHIP_HWND: AtomicUsize = AtomicUsize::new(0);

unsafe extern "system" fn win_event_cb(
    _hook: *mut core::ffi::c_void,
    ev: u32,
    _hwnd: HWND,
    _obj: i32,
    _child: i32,
    _thr: u32,
    _time: u32,
) {
    let h = CHIP_HWND.load(Ordering::Relaxed);
    if h != 0 {
        // wParam 带上事件类型，消息处理侧据此区分「重排」与「前台切换」
        PostMessageW(h as HWND, WM_Z_EVENT, ev as usize, 0);
    }
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
            } else if wp == TIMER_GUARD {
                app.on_guard();
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
        // 菜单走 TPM_RETURNCMD 自己派发命令；这里额外接受 WM_COMMAND，
        // 便于用脚本/自动化驱动同一条命令通道（也符合 Windows 常规用法）。
        WM_COMMAND if lp == 0 => {
            let cmd = (wp & 0xFFFF) as u32;
            if cmd != 0 {
                app.on_cmd(cmd);
            }
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
            if msg == WM_Z_EVENT {
                app.on_z_event(wp as u32);
                return 0;
            }
            if msg == WM_SHOW_CHIP {
                // 从外部 ShowWindow 会绕开本实例的状态：它仍以为自己是隐藏的（hidden_by_user=true），
                // 之后点托盘第一下会「显示但看不出变化」。改成发消息，由本实例自己复位状态。
                app.hidden_by_user = false;
                app.update_visibility();
                app.raise_above_taskbar();
                if app.visible {
                    app.paint_now();
                }
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
    let mut wc: WNDCLASSEXW = core::mem::zeroed();
    wc.cbSize = core::mem::size_of::<WNDCLASSEXW>() as u32;
    wc.style = 0;
    wc.lpfnWndProc = Some(wndproc);
    wc.hInstance = hinst;
    wc.hCursor = LoadCursorW(ptr::null_mut(), IDC_ARROW as *const u16);
    wc.lpszClassName = class.as_ptr();
    RegisterClassExW(&wc);

    let dpi = GetDpiForSystem();
    let h = scale(BASE_H, if dpi == 0 { 96 } else { dpi });
    // v1.0：初始宽度跟菜单里实际生效的指标走（原来是固定 BASE_W，启动瞬间会多出 24 逻辑 px）
    // SAFETY: 调用方 `run()` 传的是 `&mut app` 的地址，App 在消息循环期间一直存活。
    let w = scale((*app_ptr).w, if dpi == 0 { 96 } else { dpi });
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

pub fn run(trace: bool, demo: bool, t0: i64) {
    unsafe {
        let mutex = CreateMutexW(ptr::null(), 0, wide("Local\\SysMonChip.v1").as_ptr());
        if mutex.is_null() {
            return;
        }
        if GetLastError() == ERROR_ALREADY_EXISTS {
            if let Some(h) = find_existing() {
                // 交给窗口线程自己处理，不要在别的进程里直接 ShowWindow（会让它的状态脱节）
                PostMessageW(h, WM_SHOW_CHIP, 0, 0);
            } else {
                // 互斥体被一个没有窗口的僵尸实例占着（上次非正常退出）。
                // 以前这里直接 return —— 用户看到的现象是「双击启动器毫无反应」，所以给一句人话。
                MessageBoxW(
                    ptr::null_mut(),
                    wide("SysMonChip 已在运行（窗口丢失）。请在任务管理器结束 SysMonChipLite.exe 后重试。").as_ptr(),
                    wide("SysMonChip").as_ptr(),
                    MB_OK | MB_ICONINFORMATION,
                );
            }
            return;
        }

        let mut cfg = Config::load();
        // v1.4：只有注册表确实指向本次运行的 exe 才算「自启已开」。
        // 已注册但指向别的 exe（换版本、挪目录）时静默改写，改写失败就当没开，
        // 避免菜单打勾、登录却启动不到。
        let registered = config::autostart_registered();
        let points_here = config::autostart_points_to_current() == Some(true);
        let healed = registered && !points_here && config::set_autostart(true);
        if healed {
            // 留一条痕：用户反馈「自启指向不对」时能确认是不是这里改写过的
            config::write_temp("sysmonchip-autostart-heal.txt", b"healed=1\n");
        }
        cfg.autostart = points_here || healed;

        // no_std：App 放栈上（WinMain 帧贯穿整个消息循环），指针经 GWLP_USERDATA 传给窗口过程
        let mut app = App::new(cfg, trace, demo, t0);
        let app_ptr: *mut App = &mut app;
        let hwnd = create_window(app_ptr);
        if hwnd.is_null() {
            return;
        }
        app.hwnd = hwnd;
        app.hinst = GetModuleHandleW(ptr::null());
        app.taskbar_created = RegisterWindowMessageW(wide("TaskbarCreated").as_ptr());
        CHIP_HWND.store(hwnd as usize, Ordering::Relaxed);
        app.install_z_hooks();
        app.init_graphics();
        // v0.4：首帧只采 CPU/内存/磁盘（跳过网卡枚举），先把界面显示出来
        app.metrics = app.sampler.sample_fast();
        let mut t0texts = app.texts;
        t0texts.apply(&app.metrics, &app.cfg.items);
        app.texts = t0texts;
        app.apply_position();
        app.paint_now();
        ShowWindow(hwnd, SW_SHOWNOACTIVATE);
        UpdateWindow(hwnd);
        app.visible = true;
        app.trim();
        app.update_tray();
        if trace {
            app.write_trace();
        }
        // 首帧之后补全网络数据，再刷一次（此时已可见，用户看不到延迟）
        app.metrics = app.sampler.sample();
        let mut t1texts = app.texts;
        t1texts.apply(&app.metrics, &app.cfg.items);
        app.texts = t1texts;
        app.paint_now();

        SetTimer(hwnd, 1, app.cfg.interval, None);

        let mut msg: MSG = core::mem::zeroed();
        while GetMessageW(&mut msg, ptr::null_mut(), 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}















