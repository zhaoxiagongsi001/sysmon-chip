//! 配置持久化（简单 INI，读一次写一次）、注册表自启、主题读取。

use std::path::PathBuf;
use std::ptr;

use windows_sys::Win32::System::Registry::{
    RegCloseKey, RegDeleteValueW, RegOpenKeyExW, RegQueryValueExW, RegSetValueExW, HKEY,
    HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE, REG_DWORD, REG_SZ,
};

use crate::paint::wide;

const RUN_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
const RUN_NAME: &str = "SysMonChip";
const THEME_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize";

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum PosMode {
    Desktop,
    Taskbar,
    TaskbarRight,
    Free,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Theme {
    Auto,
    Light,
    Dark,
}

pub use chip_core::items::Items;

#[derive(Clone, Copy)]
pub struct Config {
    pub mode: PosMode,
    pub x: i32,
    pub y: i32,
    pub interval: u32,
    pub items: Items,
    pub theme: Theme,
    pub locked: bool,
    pub hide_fs: bool,
    pub autostart: bool,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            mode: PosMode::Taskbar,
            x: 0,
            y: 0,
            interval: 1000,
            items: Items { cpu: true, mem: true, disk: true, net: true },
            theme: Theme::Auto,
            locked: false,
            hide_fs: true,
            autostart: false,
        }
    }
}

impl Config {
    pub fn dir() -> Option<PathBuf> {
        std::env::var_os("APPDATA").map(|p| PathBuf::from(p).join("SysMonChip"))
    }

    fn path() -> Option<PathBuf> {
        Self::dir().map(|d| d.join("config.ini"))
    }

    pub fn load() -> Self {
        let mut c = Config::default();
        if let Some(p) = Self::path() {
            if let Ok(s) = std::fs::read_to_string(p) {
                c.apply(&s);
            }
        }
        c.interval = c.interval.clamp(200, 10_000);
        c
    }

    fn apply(&mut self, s: &str) {
        for line in s.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') || line.starts_with(';') {
                continue;
            }
            let Some((k, v)) = line.split_once('=') else {
                continue;
            };
            let (k, v) = (k.trim(), v.trim());
            match k {
                "mode" => {
                    self.mode = match v {
                        "taskbar" => PosMode::Taskbar,
                        "taskbar-right" => PosMode::TaskbarRight,
                        "free" => PosMode::Free,
                        _ => PosMode::Desktop,
                    }
                }
                "x" => self.x = v.parse().unwrap_or(self.x),
                "y" => self.y = v.parse().unwrap_or(self.y),
                "interval" => self.interval = v.parse().unwrap_or(self.interval),
                "cpu" => self.items.cpu = v != "0",
                "mem" => self.items.mem = v != "0",
                "disk" => self.items.disk = v != "0",
                "net" => self.items.net = v != "0",
                "theme" => {
                    self.theme = match v {
                        "light" => Theme::Light,
                        "dark" => Theme::Dark,
                        _ => Theme::Auto,
                    }
                }
                "locked" => self.locked = v != "0",
                "hide_fs" => self.hide_fs = v != "0",
                "autostart" => self.autostart = v != "0",
                _ => {}
            }
        }
    }

    pub fn save(&self) {
        let Some(dir) = Self::dir() else { return };
        let _ = std::fs::create_dir_all(&dir);
        let Some(p) = Self::path() else { return };
        let mode = match self.mode {
            PosMode::Desktop => "desktop",
            PosMode::Taskbar => "taskbar",
            PosMode::TaskbarRight => "taskbar-right",
            PosMode::Free => "free",
        };
        let theme = match self.theme {
            Theme::Auto => "auto",
            Theme::Light => "light",
            Theme::Dark => "dark",
        };
        let body = format!(
            "; SysMonChip 配置\n\
             mode={mode}\n\
             x={}\n\
             y={}\n\
             interval={}\n\
             cpu={}\n\
             mem={}\n\
             disk={}\n\
             net={}\n\
             theme={theme}\n\
             locked={}\n\
             hide_fs={}\n\
             autostart={}\n",
            self.x,
            self.y,
            self.interval,
            self.items.cpu as u8,
            self.items.mem as u8,
            self.items.disk as u8,
            self.items.net as u8,
            self.locked as u8,
            self.hide_fs as u8,
            self.autostart as u8,
        );
        let _ = std::fs::write(p, body);
    }
}

// ---------------------------------------------------------------- 注册表

unsafe fn read_dword(sub: &str, name: &str) -> Option<u32> {
    let sub = wide(sub);
    let name = wide(name);
    let mut hkey: HKEY = ptr::null_mut();
    if RegOpenKeyExW(HKEY_CURRENT_USER, sub.as_ptr(), 0, KEY_READ, &mut hkey) != 0 {
        return None;
    }
    let mut ty: u32 = 0;
    let mut data: u32 = 0;
    let mut cb: u32 = 4;
    let rc = RegQueryValueExW(
        hkey,
        name.as_ptr(),
        ptr::null(),
        &mut ty,
        &mut data as *mut u32 as *mut u8,
        &mut cb,
    );
    RegCloseKey(hkey);
    if rc == 0 && ty == REG_DWORD {
        Some(data)
    } else {
        None
    }
}

unsafe fn read_string(sub: &str, name: &str) -> Option<u32> {
    let sub = wide(sub);
    let name = wide(name);
    let mut hkey: HKEY = ptr::null_mut();
    if RegOpenKeyExW(HKEY_CURRENT_USER, sub.as_ptr(), 0, KEY_READ, &mut hkey) != 0 {
        return None;
    }
    let mut ty: u32 = 0;
    let mut buf = [0u16; 512];
    let mut cb: u32 = (buf.len() * 2) as u32;
    let rc = RegQueryValueExW(
        hkey,
        name.as_ptr(),
        ptr::null(),
        &mut ty,
        buf.as_mut_ptr() as *mut u8,
        &mut cb,
    );
    RegCloseKey(hkey);
    if rc == 0 && ty == REG_SZ {
        Some(cb)
    } else {
        None
    }
}

/// 系统主题是否为浅色
pub fn theme_is_light() -> bool {
    unsafe {
        match read_dword(THEME_KEY, "AppsUseLightTheme") {
            Some(v) => v != 0,
            None => true,
        }
    }
}

/// 自启是否已配置（只判断存在，不比较路径）
pub fn autostart_registered() -> bool {
    unsafe { read_string(RUN_KEY, RUN_NAME).is_some() }
}

/// 写入/删除 HKCU Run 项
pub fn set_autostart(on: bool) -> bool {
    unsafe {
        let sub = wide(RUN_KEY);
        let name = wide(RUN_NAME);
        let mut hkey: HKEY = ptr::null_mut();
        if RegOpenKeyExW(HKEY_CURRENT_USER, sub.as_ptr(), 0, KEY_SET_VALUE, &mut hkey) != 0 {
            return false;
        }
        let ok = if on {
            let exe = std::env::current_exe()
                .map(|p| p.to_string_lossy().to_string())
                .unwrap_or_default();
            let cmd = format!("\"{exe}\" --autostart");
            let utf16: Vec<u16> = cmd.encode_utf16().collect();
            RegSetValueExW(
                hkey,
                name.as_ptr(),
                0,
                REG_SZ,
                utf16.as_ptr() as *const u8,
                (utf16.len() * 2) as u32,
            ) == 0
        } else {
            RegDeleteValueW(hkey, name.as_ptr()) == 0
        };
        RegCloseKey(hkey);
        ok
    }
}




