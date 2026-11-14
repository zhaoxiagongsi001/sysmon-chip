//! lite 版配置层：no_std，INI 读写 + 注册表（主题 / 自启）全部走 Win32。

use core::ptr;

use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE, ERROR_ALREADY_EXISTS};
use windows_sys::Win32::Storage::FileSystem::{
    CreateDirectoryW, CreateFileW, DeleteFileW, GetTempPathW, MoveFileExW, ReadFile, WriteFile,
    MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
};
use windows_sys::Win32::System::Environment::GetEnvironmentVariableW;
use windows_sys::Win32::System::LibraryLoader::GetModuleFileNameW;
use windows_sys::Win32::System::Registry::{
    RegCloseKey, RegDeleteValueW, RegOpenKeyExW, RegQueryValueExW, RegSetValueExW, HKEY,
    HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE, REG_DWORD, REG_SZ,
};

use chip_core::items::Items;
use chip_core::paint::wide;

// CreateFile / 共享 / 打开方式常量（字面量，避免依赖 feature 的常量命名）
const GENERIC_READ: u32 = 0x8000_0000;
const GENERIC_WRITE: u32 = 0x4000_0000;
const OPEN_EXISTING: u32 = 3;
const CREATE_ALWAYS: u32 = 2;
const FILE_SHARE_READ: u32 = 1;
const FILE_SHARE_WRITE: u32 = 2;
const FILE_ATTRIBUTE_NORMAL: u32 = 0x80;

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

#[derive(Clone, Copy, PartialEq, Eq)]
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
            // v2.0：默认贴任务栏左端（老板拍板）
            mode: PosMode::Taskbar,
            x: 0,
            y: 0,
            interval: 1000,
            items: Items::ALL,
            theme: Theme::Auto,
            locked: false,
            hide_fs: true,
            autostart: false,
        }
    }
}

impl Config {
    pub fn load() -> Self {
        let mut c = Config::default();
        let mut buf = [0u8; 1024];
        let n = unsafe { read_config(&mut buf) };
        if n > 0 {
            c.apply(&buf[..n]);
        }
        c.interval = c.interval.clamp(200, 10_000);
        // v0.9：四项全关会让面板缩成一条空白，配置被手改成全 0 时兜底回 CPU
        if !(c.items.cpu || c.items.mem || c.items.disk || c.items.net) {
            c.items.cpu = true;
        }
        c
    }

    fn apply(&mut self, s: &[u8]) {
        for raw in s.split(|&b| b == b'\n') {
            let line = trim(raw);
            if line.is_empty() || line[0] == b'#' || line[0] == b';' {
                continue;
            }
            let Some(eq) = line.iter().position(|&b| b == b'=') else {
                continue;
            };
            let k = trim(&line[..eq]);
            let v = trim(&line[eq + 1..]);
            if k == b"mode" {
                self.mode = if v == b"desktop" {
                    PosMode::Desktop
                } else if v == b"taskbar" {
                    PosMode::Taskbar
                } else if v == b"taskbar-right" {
                    PosMode::TaskbarRight
                } else {
                    PosMode::Free
                };
            } else if k == b"x" {
                if let Some(n) = parse_i32(v) {
                    self.x = n;
                }
            } else if k == b"y" {
                if let Some(n) = parse_i32(v) {
                    self.y = n;
                }
            } else if k == b"interval" {
                if let Some(n) = parse_u32(v) {
                    self.interval = n;
                }
            } else if k == b"cpu" {
                self.items.cpu = v != b"0";
            } else if k == b"mem" {
                self.items.mem = v != b"0";
            } else if k == b"disk" {
                self.items.disk = v != b"0";
            } else if k == b"net" {
                self.items.net = v != b"0";
            } else if k == b"theme" {
                self.theme = if v == b"light" {
                    Theme::Light
                } else if v == b"dark" {
                    Theme::Dark
                } else {
                    Theme::Auto
                };
            } else if k == b"locked" {
                self.locked = v != b"0";
            } else if k == b"hide_fs" {
                self.hide_fs = v != b"0";
            } else if k == b"autostart" {
                self.autostart = v != b"0";
            }
        }
    }

    /// 写配置到 `%APPDATA%\SysMonChip\config.ini`。
    /// 返回 false 表示没写进去（文件被占用等），调用方应安排重试。
    pub fn save(&self) -> bool {
        let mut buf = [0u8; 640];
        let mut n = 0usize;
        push(&mut buf, &mut n, b"; SysMonChip config\n");
        push(&mut buf, &mut n, b"mode=");
        let m: &[u8] = match self.mode {
            PosMode::Desktop => b"desktop",
            PosMode::Taskbar => b"taskbar",
            PosMode::TaskbarRight => b"taskbar-right",
            PosMode::Free => b"free",
        };
        push(&mut buf, &mut n, m);
        push(&mut buf, &mut n, b"\nx=");
        push_i64(&mut buf, &mut n, self.x as i64);
        push(&mut buf, &mut n, b"\ny=");
        push_i64(&mut buf, &mut n, self.y as i64);
        push(&mut buf, &mut n, b"\ninterval=");
        push_i64(&mut buf, &mut n, self.interval as i64);
        push(&mut buf, &mut n, b"\ncpu=");
        push_bool(&mut buf, &mut n, self.items.cpu);
        push(&mut buf, &mut n, b"\nmem=");
        push_bool(&mut buf, &mut n, self.items.mem);
        push(&mut buf, &mut n, b"\ndisk=");
        push_bool(&mut buf, &mut n, self.items.disk);
        push(&mut buf, &mut n, b"\nnet=");
        push_bool(&mut buf, &mut n, self.items.net);
        push(&mut buf, &mut n, b"\ntheme=");
        let th: &[u8] = match self.theme {
            Theme::Auto => b"auto",
            Theme::Light => b"light",
            Theme::Dark => b"dark",
        };
        push(&mut buf, &mut n, th);
        push(&mut buf, &mut n, b"\nlocked=");
        push_bool(&mut buf, &mut n, self.locked);
        push(&mut buf, &mut n, b"\nhide_fs=");
        push_bool(&mut buf, &mut n, self.hide_fs);
        push(&mut buf, &mut n, b"\nautostart=");
        push_bool(&mut buf, &mut n, self.autostart);
        push(&mut buf, &mut n, b"\n");
        unsafe {
            create_config_dir();
            write_config(&buf[..n])
        }
    }
}

// ---------------------------------------------------------------- 小工具

fn trim(mut s: &[u8]) -> &[u8] {
    while let Some((&b, rest)) = s.split_first() {
        if b == b' ' || b == b'\t' || b == b'\r' {
            s = rest;
        } else {
            break;
        }
    }
    while let Some((&b, rest)) = s.split_last() {
        if b == b' ' || b == b'\t' || b == b'\r' {
            s = rest;
        } else {
            break;
        }
    }
    s
}

fn parse_u32(s: &[u8]) -> Option<u32> {
    if s.is_empty() {
        return None;
    }
    let mut v: u32 = 0;
    for &b in s {
        if !b.is_ascii_digit() {
            return None;
        }
        v = v.checked_mul(10)?.checked_add((b - b'0') as u32)?;
    }
    Some(v)
}

fn parse_i32(s: &[u8]) -> Option<i32> {
    let (neg, digits) = match s.split_first() {
        Some((b'-', rest)) => (true, rest),
        _ => (false, s),
    };
    let v = parse_u32(digits)? as i64;
    let v = if neg { -v } else { v };
    if v < i32::MIN as i64 || v > i32::MAX as i64 {
        None
    } else {
        Some(v as i32)
    }
}

fn push(buf: &mut [u8], n: &mut usize, s: &[u8]) {
    for &b in s {
        if *n < buf.len() {
            buf[*n] = b;
            *n += 1;
        }
    }
}

fn push_bool(buf: &mut [u8], n: &mut usize, v: bool) {
    push(buf, n, if v { b"1" } else { b"0" });
}

fn push_i64(buf: &mut [u8], n: &mut usize, v: i64) {
    let mut tmp = [0u8; 20];
    let mut len = 0usize;
    let neg = v < 0;
    let mut x = if neg { (v as i128).unsigned_abs() as u64 } else { v as u64 };
    loop {
        tmp[len] = b'0' + (x % 10) as u8;
        len += 1;
        x /= 10;
        if x == 0 {
            break;
        }
    }
    if neg {
        push(buf, n, b"-");
    }
    while len > 0 {
        len -= 1;
        push(buf, n, &[tmp[len]]);
    }
}

/// 写 %TEMP%\<name>（trace / dump 用）
pub fn write_temp(name: &str, data: &[u8]) -> bool {
    let mut path = [0u16; 320];
    unsafe {
        let n = GetTempPathW(path.len() as u32, path.as_mut_ptr());
        if n == 0 || n as usize >= path.len() {
            return false;
        }
        let mut pos = n as usize;
        for b in name.bytes() {
            if pos >= path.len() - 1 {
                return false;
            }
            path[pos] = b as u16;
            pos += 1;
        }
        path[pos] = 0;
        write_file(&path, data)
    }
}

// ---------------------------------------------------------------- 文件 IO

unsafe fn appdata_dir(out: &mut [u16; 320]) -> Option<usize> {
    let mut tmp = [0u16; 260];
    let n = GetEnvironmentVariableW(wide("APPDATA").as_ptr(), tmp.as_mut_ptr(), tmp.len() as u32);
    if n == 0 || n as usize >= tmp.len() {
        return None;
    }
    let n = n as usize;
    out[..n].copy_from_slice(&tmp[..n]);
    Some(n)
}

unsafe fn config_path(out: &mut [u16; 320]) -> Option<usize> {
    let mut pos = appdata_dir(out)?;
    for b in r"\SysMonChip\config.ini".bytes() {
        if pos >= out.len() - 1 {
            return None;
        }
        out[pos] = b as u16;
        pos += 1;
    }
    out[pos] = 0;
    Some(pos)
}

unsafe fn create_config_dir() {
    let mut path = [0u16; 320];
    let Some(mut pos) = appdata_dir(&mut path) else { return };
    for b in r"\SysMonChip".bytes() {
        if pos >= path.len() - 1 {
            return;
        }
        path[pos] = b as u16;
        pos += 1;
    }
    path[pos] = 0;
    CreateDirectoryW(path.as_ptr(), ptr::null());
}

unsafe fn read_config(buf: &mut [u8]) -> usize {
    let mut path = [0u16; 320];
    if config_path(&mut path).is_none() {
        return 0;
    }
    let n = read_path(&path, buf);
    if n >= buf.len() {
        return n;
    }
    // v1.2：上次改名失败时 write_file 会故意留下完整的 .tmp（见那里的注释）。
    // 主文件可能是直写中途断电留下的半截内容，所以两份都在时取更完整的那份，
    // 而不是「主文件有内容就信它」——否则用户改过的设置会静默丢一半。
    let len = match path.iter().position(|&c| c == 0) {
        Some(i) => i,
        None => return n,
    };
    let mut tmp = [0u16; 320];
    if len + 4 >= tmp.len() {
        return n;
    }
    tmp[..len].copy_from_slice(&path[..len]);
    for (i, c) in ".tmp".encode_utf16().enumerate() {
        tmp[len + i] = c;
    }
    let mut alt = [0u8; 1024];
    let m = read_path(&tmp, &mut alt);
    if m > n {
        buf[..m].copy_from_slice(&alt[..m]);
        return m;
    }
    n
}

unsafe fn read_path(path: &[u16], buf: &mut [u8]) -> usize {
    let h = CreateFileW(
        path.as_ptr(),
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        ptr::null(),
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        ptr::null_mut(),
    );
    if h as isize == -1 {
        return 0;
    }
    let mut got: u32 = 0;
    let ok = ReadFile(
        h,
        buf.as_mut_ptr(),
        buf.len() as u32,
        &mut got,
        ptr::null_mut(),
    );
    CloseHandle(h);
    if ok == 0 {
        0
    } else {
        got as usize
    }
}

unsafe fn write_config(data: &[u8]) -> bool {
    let mut path = [0u16; 320];
    if config_path(&mut path).is_none() {
        return false;
    }
    write_file(&path, data)
}

unsafe fn write_file(path: &[u16], data: &[u8]) -> bool {
    // v1.0：先写同目录临时文件，写满再原子改名替换。
    // 原来直接 CREATE_ALWAYS 覆盖，写到一半断电/崩溃会留下半截 config.ini。
    let n = match path.iter().position(|&c| c == 0) {
        Some(i) => i,
        None => return false,
    };
    let mut tmp = [0u16; 320];
    if n + 4 >= tmp.len() {
        return false;
    }
    tmp[..n].copy_from_slice(&path[..n]);
    for (i, c) in ".tmp".encode_utf16().enumerate() {
        tmp[n + i] = c;
    }

    let h = CreateFileW(
        tmp.as_ptr(),
        GENERIC_WRITE,
        0,
        ptr::null(),
        CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        ptr::null_mut(),
    );
    if h as isize == -1 {
        return false;
    }
    let mut written: u32 = 0;
    let ok = WriteFile(
        h,
        data.as_ptr(),
        data.len() as u32,
        &mut written,
        ptr::null_mut(),
    );
    // 关闭失败意味着数据未必落盘，按失败处理
    let closed = CloseHandle(h);
    if ok == 0 || closed == 0 || written as usize != data.len() {
        DeleteFileW(tmp.as_ptr());
        return false;
    }
    // MOVEFILE_WRITE_THROUGH：让改名本身也落盘，否则断电后可能既没有临时文件也没有新文件
    if MoveFileExW(
        tmp.as_ptr(),
        path.as_ptr(),
        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
    ) != 0
    {
        return true;
    }
    // 改名被拒不等于数据丢了：杀软/索引器短暂占用目标文件是常见原因，
    // 这时退回直接覆盖写（牺牲原子性，换取这次设置不白改）。
    if write_direct(path, data) {
        let _ = DeleteFileW(tmp.as_ptr());
        return true;
    }
    // 直写也失败：保留 .tmp 不删——它内容是完整的，下次启动 read_config 会回读
    false
}

/// 兜底写盘：直接覆盖目标文件，不做临时文件 + 改名。
unsafe fn write_direct(path: &[u16], data: &[u8]) -> bool {
    let h = CreateFileW(
        path.as_ptr(),
        GENERIC_WRITE,
        0,
        ptr::null(),
        CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        ptr::null_mut(),
    );
    if h as isize == -1 {
        return false;
    }
    let mut written: u32 = 0;
    let ok = WriteFile(
        h,
        data.as_ptr(),
        data.len() as u32,
        &mut written,
        ptr::null_mut(),
    );
    let closed = CloseHandle(h);
    ok != 0 && closed != 0 && written as usize == data.len()
}

// ---------------------------------------------------------------- 注册表

unsafe fn reg_read_dword(sub: &str, name: &str) -> Option<u32> {
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

unsafe fn reg_has_value(sub: &str, name: &str) -> bool {
    let sub = wide(sub);
    let name = wide(name);
    let mut hkey: HKEY = ptr::null_mut();
    if RegOpenKeyExW(HKEY_CURRENT_USER, sub.as_ptr(), 0, KEY_READ, &mut hkey) != 0 {
        return false;
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
    rc == 0 && ty == REG_SZ
}

pub fn theme_is_light() -> bool {
    unsafe {
        match reg_read_dword(THEME_KEY, "AppsUseLightTheme") {
            Some(v) => v != 0,
            None => true,
        }
    }
}

pub fn autostart_registered() -> bool {
    unsafe { reg_has_value(RUN_KEY, RUN_NAME) }
}

pub fn set_autostart(on: bool) -> bool {
    unsafe {
        let sub = wide(RUN_KEY);
        let name = wide(RUN_NAME);
        let mut hkey: HKEY = ptr::null_mut();
        if RegOpenKeyExW(HKEY_CURRENT_USER, sub.as_ptr(), 0, KEY_SET_VALUE, &mut hkey) != 0 {
            return false;
        }
        let ok = if on {
            let mut exe = [0u16; 320];
            let n = GetModuleFileNameW(ptr::null_mut(), exe.as_mut_ptr(), exe.len() as u32);
            if n == 0 || n as usize >= exe.len() {
                false
            } else {
                let mut cmd = [0u16; 700];
                let mut pos = 0usize;
                cmd[pos] = b'"' as u16;
                pos += 1;
                for i in 0..n as usize {
                    cmd[pos] = exe[i];
                    pos += 1;
                }
                for b in b"\" --autostart" {
                    cmd[pos] = *b as u16;
                    pos += 1;
                }
                RegSetValueExW(
                    hkey,
                    name.as_ptr(),
                    0,
                    REG_SZ,
                    cmd.as_ptr() as *const u8,
                    (pos * 2) as u32,
                ) == 0
            }
        } else {
            RegDeleteValueW(hkey, name.as_ptr()) == 0
        };
        RegCloseKey(hkey);
        ok
    }
}

// 让编译器知道这些常量/函数不是死代码
#[allow(dead_code)]
fn _keep(_: HANDLE) {
    let _ = ERROR_ALREADY_EXISTS;
    let _ = GetLastError;
}


