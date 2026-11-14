//! SysMon Chip：Win11 极轻量资源条。
//! 单进程 / 单线程 / GDI 双缓冲 / 稳态零堆分配。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
#![allow(clippy::missing_safety_doc)]

mod config;
mod wnd;

pub use chip_core::{metrics, paint};

use std::time::Instant;

use windows_sys::Win32::UI::HiDpi::{
    SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};

fn main() {
    unsafe {
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    }
    let t0 = Instant::now();
    let args: Vec<String> = std::env::args().skip(1).collect();

    if args.iter().any(|a| a == "--dump") {
        dump();
        return;
    }
    if args.iter().any(|a| a == "--quit") {
        wnd::quit_existing();
        return;
    }
    wnd::run(
        args.iter().any(|a| a == "--trace"),
        args.iter().any(|a| a == "--demo"),
        t0,
    );
}

/// 采样一次并落盘：给验收脚本读，不依赖控制台。
fn dump() {
    let mut sampler = metrics::Sampler::new();
    let _ = sampler.sample();
    std::thread::sleep(std::time::Duration::from_millis(1000));
    let m = sampler.sample();
    let cfg = config::Config::load();
    let cfg_path = config::Config::dir()
        .map(|d| d.display().to_string())
        .unwrap_or_else(|| "<no appdata>".to_string());
    let body = format!(
        "cpu={}\nmem={}\ndisk={}\nup={}\ndown={}\nif_seen={}\ncfg_dir={}\nmode={:?}\ntheme={:?}\n",
        m.cpu,
        m.mem,
        m.disk,
        m.up,
        m.down,
        sampler.if_seen,
        cfg_path,
        cfg.mode,
        cfg.theme
    );
    let mut path = std::env::temp_dir();
    path.push("sysmonchip-dump.txt");
    let _ = std::fs::write(&path, &body);
    #[cfg(debug_assertions)]
    println!("{body}");
}




