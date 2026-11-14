//! SysMon Chip Lite：no_std 极轻量版入口。
//!
//! 与 std 版功能一致：4 项指标、三模式定位、托盘/菜单、主题、自启、配置持久化、
//! `--dump / --trace / --quit / --demo`。区别是整条运行时只有 core + windows-sys，
//! 不链接 Rust std，exe 从 327 KB 压到几十 KB。

#![no_std]
#![no_main]
#![windows_subsystem = "windows"]

mod app_impl;
mod config;

use core::panic::PanicInfo;

use chip_core::metrics::{elapsed_ms, qpc_freq, qpc_now, Sampler};
use windows_sys::Win32::Foundation::HINSTANCE;
use windows_sys::Win32::System::Environment::GetCommandLineW;
use windows_sys::Win32::System::Threading::{ExitProcess, Sleep};
use windows_sys::Win32::UI::HiDpi::{
    SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    // no_std：panic 直接退出，不做展开；窗口消失比进程半死更好
    unsafe { ExitProcess(3) }
}

#[no_mangle]
pub extern "system" fn WinMain(_h: HINSTANCE, _p: HINSTANCE, _cmd: *const u8, _show: i32) -> i32 {
    unsafe {
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    }
    let t0 = qpc_now();

    if cmdline_has("quit") {
        app_impl::quit_existing();
        return 0;
    }
    if cmdline_has("selftest") {
        selftest();
        return 0;
    }
    if cmdline_has("autostart-on") || cmdline_has("autostart-off") {
        let on = cmdline_has("autostart-on");
        let ok = config::set_autostart(on);
        let registered = config::autostart_registered();
        let mut buf = [0u8; 160];
        let mut n = 0usize;
        push_str(&mut buf, &mut n, "autostart=");
        push_str(&mut buf, &mut n, if on { "on" } else { "off" });
        push_str(&mut buf, &mut n, "\nresult=");
        push_str(&mut buf, &mut n, if ok { "ok" } else { "fail" });
        push_str(&mut buf, &mut n, "\nregistered=");
        push_str(&mut buf, &mut n, if registered { "1" } else { "0" });
        push_str(&mut buf, &mut n, "\n");
        config::write_temp("sysmonchip-autostart.txt", &buf[..n]);
        return 0;
    }
    if cmdline_has("dump") {
        dump();
        return 0;
    }
    let trace = cmdline_has("trace");
    let demo = cmdline_has("demo");
    app_impl::run(trace, demo, t0);
    0
}

/// 命令行里是否有 `--name` 标记（大小写敏感、按 token 匹配）
fn cmdline_has(name: &str) -> bool {
    unsafe {
        let cl = GetCommandLineW();
        if cl.is_null() {
            return false;
        }
        let space = b' ' as u16;
        let tab = b'\t' as u16;
        let mut i = 0usize;
        while *cl.add(i) != 0 {
            let at_start = i == 0 || *cl.add(i - 1) == space || *cl.add(i - 1) == tab;
            if at_start && *cl.add(i) == b'-' as u16 && *cl.add(i + 1) == b'-' as u16 {
                let mut j = 0usize;
                let mut ok = true;
                for b in name.bytes() {
                    if *cl.add(i + 2 + j) != b as u16 {
                        ok = false;
                        break;
                    }
                    j += 1;
                }
                if ok {
                    let next = *cl.add(i + 2 + j);
                    if next == 0 || next == space || next == tab {
                        return true;
                    }
                }
            }
            i += 1;
        }
        false
    }
}

// ---------------------------------------------------------------- 输出助手

fn push_str(buf: &mut [u8], n: &mut usize, s: &str) {
    for &b in s.as_bytes() {
        if *n < buf.len() {
            buf[*n] = b;
            *n += 1;
        }
    }
}

fn push_u64(buf: &mut [u8], n: &mut usize, v: u64) {
    let mut tmp = [0u8; 20];
    let mut len = 0usize;
    let mut x = v;
    loop {
        tmp[len] = b'0' + (x % 10) as u8;
        len += 1;
        x /= 10;
        if x == 0 {
            break;
        }
    }
    while len > 0 {
        len -= 1;
        if *n < buf.len() {
            buf[*n] = tmp[len];
            *n += 1;
        }
    }
}

fn push_i64(buf: &mut [u8], n: &mut usize, v: i64) {
    if v < 0 {
        push_str(buf, n, "-");
        push_u64(buf, n, (v as i128).unsigned_abs() as u64);
    } else {
        push_u64(buf, n, v as u64);
    }
}

/// `--trace` 输出：启动耗时 + DPI/尺寸（与 std 版字段兼容）
pub fn trace_write(t0: i64, dpi: u32, w: i32, h: i32) {
    let ms = elapsed_ms(t0, qpc_now(), qpc_freq());
    let mut buf = [0u8; 256];
    let mut n = 0usize;
    push_str(&mut buf, &mut n, "startup_ms=");
    push_u64(&mut buf, &mut n, ms);
    push_str(&mut buf, &mut n, "\ndpi=");
    push_u64(&mut buf, &mut n, dpi as u64);
    push_str(&mut buf, &mut n, "\nw=");
    push_i64(&mut buf, &mut n, w as i64);
    push_str(&mut buf, &mut n, "\nh=");
    push_i64(&mut buf, &mut n, h as i64);
    push_str(&mut buf, &mut n, "\n");
    config::write_temp("sysmonchip-trace.txt", &buf[..n]);
}

/// `--dump`：采样 1 秒后写 %TEMP%\sysmonchip-dump.txt（与 std 版格式兼容）
fn dump() {
    let mut sampler = Sampler::new();
    let _ = sampler.sample();
    unsafe { Sleep(1000) };
    let m = sampler.sample();
    let cfg = config::Config::load();
    let mode: &str = match cfg.mode {
        config::PosMode::Desktop => "desktop",
        config::PosMode::Taskbar => "taskbar",
        config::PosMode::TaskbarRight => "taskbar-right",
        config::PosMode::Free => "free",
    };
    let mut buf = [0u8; 512];
    let mut n = 0usize;
    push_str(&mut buf, &mut n, "cpu=");
    push_u64(&mut buf, &mut n, m.cpu as u64);
    push_str(&mut buf, &mut n, "\nmem=");
    push_u64(&mut buf, &mut n, m.mem as u64);
    push_str(&mut buf, &mut n, "\ndisk=");
    push_u64(&mut buf, &mut n, m.disk as u64);
    push_str(&mut buf, &mut n, "\nup=");
    push_u64(&mut buf, &mut n, m.up);
    push_str(&mut buf, &mut n, "\ndown=");
    push_u64(&mut buf, &mut n, m.down);
    push_str(&mut buf, &mut n, "\nif_seen=");
    push_u64(&mut buf, &mut n, sampler.if_seen as u64);
    push_str(&mut buf, &mut n, "\nmode=");
    push_str(&mut buf, &mut n, mode);
    push_str(&mut buf, &mut n, "\n");
    config::write_temp("sysmonchip-dump.txt", &buf[..n]);
}

/// `--selftest`：配置写入/读回往返自检（验收脚本用；不弹窗）
fn selftest() {
    let mut cfg = config::Config::default();
    cfg.mode = config::PosMode::Free;
    cfg.x = 1234;
    cfg.y = 567;
    cfg.interval = 2000;
    cfg.items.cpu = false;
    cfg.theme = config::Theme::Dark;
    cfg.locked = true;
    cfg.save();
    let back = config::Config::load();
    let ok = back == cfg;
    let mut buf = [0u8; 256];
    let mut n = 0usize;
    push_str(&mut buf, &mut n, "config_roundtrip=");
    push_str(&mut buf, &mut n, if ok { "ok" } else { "FAIL" });
    push_str(&mut buf, &mut n, "\nmode=");
    push_str(&mut buf, &mut n, match back.mode {
        config::PosMode::Desktop => "desktop",
        config::PosMode::Taskbar => "taskbar",
        config::PosMode::TaskbarRight => "taskbar-right",
        config::PosMode::Free => "free",
    });
    push_str(&mut buf, &mut n, "\nx=");
    push_i64(&mut buf, &mut n, back.x as i64);
    push_str(&mut buf, &mut n, "\ny=");
    push_i64(&mut buf, &mut n, back.y as i64);
    push_str(&mut buf, &mut n, "\ntheme=");
    push_str(&mut buf, &mut n, match back.theme {
        config::Theme::Auto => "auto",
        config::Theme::Light => "light",
        config::Theme::Dark => "dark",
    });
    push_str(&mut buf, &mut n, "\n");
    config::write_temp("sysmonchip-selftest.txt", &buf[..n]);
}

/// 诊断：ULW 结果
pub fn debug_ulw(rc: i32, err: u32, w: i32, h: i32, _bits: usize) {
    let mut buf = [0u8; 120];
    let mut n = 0usize;
    push_str(&mut buf, &mut n, "rc=");
    push_i64(&mut buf, &mut n, rc as i64);
    push_str(&mut buf, &mut n, "\ngle=");
    push_i64(&mut buf, &mut n, err as i64);
    push_str(&mut buf, &mut n, "\nw=");
    push_i64(&mut buf, &mut n, w as i64);
    push_str(&mut buf, &mut n, "\nh=");
    push_i64(&mut buf, &mut n, h as i64);
    push_str(&mut buf, &mut n, "\n");
    config::write_temp("sysmonchip-ulw.txt", &buf[..n]);
}
