//! 采样：CPU / 内存 / 系统盘 / 网速。
//! 全部走 Win32 轻量接口：稳态不分配堆内存、不碰 WMI/COM/PDH。

use core::ptr;

use windows_sys::Win32::Foundation::FILETIME;
use windows_sys::Win32::NetworkManagement::IpHelper::{
    FreeMibTable, GetIfEntry2, GetIfTable2, MIB_IF_ROW2, MIB_IF_TABLE2,
};
use windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceExW;
use windows_sys::Win32::System::Performance::{QueryPerformanceCounter, QueryPerformanceFrequency};
use windows_sys::Win32::System::SystemInformation::{
    GetWindowsDirectoryW, GlobalMemoryStatusEx, MEMORYSTATUSEX,
};
use windows_sys::Win32::System::Threading::GetSystemTimes;

const MAX_IF: usize = 8;
const IF_OPER_UP: i32 = 1;
const IF_TYPE_LOOPBACK: u32 = 24;
const DISK_EVERY: u32 = 30;
const IF_REFRESH_EVERY: u32 = 60;
const MAX_GAP_SECS: f64 = 10.0;

#[derive(Clone, Copy, Default, PartialEq, Eq)]
pub struct Metrics {
    pub cpu: u8,
    pub mem: u8,
    pub disk: u8,
    pub up: u64,
    pub down: u64,
}

pub struct Sampler {
    qpf: i64,
    last_qpc: i64,
    last_idle: u64,
    last_kernel: u64,
    last_user: u64,
    cpu_ready: bool,
    cpu_cached: u8,
    mem_cached: u8,
    disk_pct: u8,
    disk_tick: u32,
    ifs: [u32; MAX_IF],
    n_if: usize,
    last_in: [u64; MAX_IF],
    last_out: [u64; MAX_IF],
    net_ready: bool,
    if_tick: u32,
    pub if_seen: usize,
}

impl Sampler {
    pub fn new() -> Self {
        let mut qpf = 0i64;
        unsafe {
            QueryPerformanceFrequency(&mut qpf);
        }
        Self {
            qpf: if qpf > 0 { qpf } else { 10_000_000 },
            last_qpc: 0,
            last_idle: 0,
            last_kernel: 0,
            last_user: 0,
            cpu_ready: false,
            cpu_cached: 0,
            mem_cached: 0,
            disk_pct: 0,
            disk_tick: 0,
            ifs: [0; MAX_IF],
            n_if: 0,
            last_in: [0; MAX_IF],
            last_out: [0; MAX_IF],
            net_ready: false,
            if_tick: 0,
            if_seen: 0,
        }
    }

    fn qpc(&self) -> i64 {
        let mut v = 0i64;
        unsafe {
            QueryPerformanceCounter(&mut v);
        }
        v
    }

    /// 快速采样：CPU/内存/磁盘，跳过网卡枚举（首帧尽快上屏用）
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

    pub fn sample(&mut self) -> Metrics {
        let now = self.qpc();
        let mut elapsed = 0.0f64;
        if self.last_qpc != 0 && now > self.last_qpc {
            elapsed = (now - self.last_qpc) as f64 / self.qpf as f64;
        }
        self.last_qpc = now;

        let cpu = unsafe { self.sample_cpu() };
        let mem = unsafe { self.sample_mem() };

        if self.disk_tick == 0 {
            self.disk_pct = unsafe { sample_disk() };
        }
        self.disk_tick = (self.disk_tick + 1) % DISK_EVERY;

        if self.if_tick == 0 {
            unsafe { self.refresh_ifs() };
        }
        self.if_tick = (self.if_tick + 1) % IF_REFRESH_EVERY;

        let (up, down) = unsafe { self.sample_net(elapsed) };
        Metrics { cpu, mem, disk: self.disk_pct, up, down }
    }

    unsafe fn sample_cpu(&mut self) -> u8 {
        let mut idle = FILETIME::default();
        let mut kernel = FILETIME::default();
        let mut user = FILETIME::default();
        if GetSystemTimes(&mut idle, &mut kernel, &mut user) == 0 {
            return self.cpu_cached;
        }
        let di = to_u64(idle);
        let dk = to_u64(kernel);
        let du = to_u64(user);
        if self.cpu_ready {
            let d_idle = di.wrapping_sub(self.last_idle);
            let d_kernel = dk.wrapping_sub(self.last_kernel);
            let d_user = du.wrapping_sub(self.last_user);
            let total = d_kernel.saturating_add(d_user);
            if total > 0 {
                let busy = total.saturating_sub(d_idle);
                let pct = busy.saturating_mul(100).saturating_add(total / 2) / total;
                self.cpu_cached = pct.min(100) as u8;
            }
        }
        self.last_idle = di;
        self.last_kernel = dk;
        self.last_user = du;
        self.cpu_ready = true;
        self.cpu_cached
    }

    unsafe fn sample_mem(&mut self) -> u8 {
        let mut m: MEMORYSTATUSEX = core::mem::zeroed();
        m.dwLength = core::mem::size_of::<MEMORYSTATUSEX>() as u32;
        if GlobalMemoryStatusEx(&mut m) == 0 {
            return self.mem_cached;
        }
        self.mem_cached = m.dwMemoryLoad.min(100) as u8;
        self.mem_cached
    }

    unsafe fn refresh_ifs(&mut self) {
        let mut table: *mut MIB_IF_TABLE2 = ptr::null_mut();
        if GetIfTable2(&mut table) != 0 || table.is_null() {
            return;
        }
        let mut n = 0usize;
        let count = (*table).NumEntries as usize;
        let base = (*table).Table.as_ptr();
        for i in 0..count {
            let row = &*base.add(i);
            let flags = row.InterfaceAndOperStatusFlags._bitfield;
            if flags & 0x02 != 0 {
                continue; // 轻量过滤层（WFP/QoS），会重复计数
            }
            if flags & 0x01 == 0 && flags & 0x80 == 0 {
                continue; // 既非硬件接口也非端点接口（VPN）
            }
            if row.Type == IF_TYPE_LOOPBACK || row.TunnelType != 0 {
                continue;
            }
            if row.OperStatus != IF_OPER_UP {
                continue;
            }
            if n < MAX_IF {
                self.ifs[n] = row.InterfaceIndex;
                n += 1;
            }
        }
        FreeMibTable(table as *const _);
        self.if_seen = n;
        self.n_if = n;
        for i in 0..n {
            if let Some((a, b)) = read_if(self.ifs[i]) {
                self.last_in[i] = a;
                self.last_out[i] = b;
            }
        }
        self.net_ready = true;
    }

    unsafe fn sample_net(&mut self, elapsed: f64) -> (u64, u64) {
        if !self.net_ready || elapsed <= 0.0 || elapsed > MAX_GAP_SECS {
            // 首次 / 唤醒后：重建基线，本拍不出数
            for i in 0..self.n_if {
                if let Some((a, b)) = read_if(self.ifs[i]) {
                    self.last_in[i] = a;
                    self.last_out[i] = b;
                }
            }
            return (0, 0);
        }
        let mut din = 0u64;
        let mut dout = 0u64;
        for i in 0..self.n_if {
            if let Some((a, b)) = read_if(self.ifs[i]) {
                din += a.saturating_sub(self.last_in[i]);
                dout += b.saturating_sub(self.last_out[i]);
                self.last_in[i] = a;
                self.last_out[i] = b;
            }
        }
        ((dout as f64 / elapsed) as u64, (din as f64 / elapsed) as u64)
    }
}

fn to_u64(t: FILETIME) -> u64 {
    ((t.dwHighDateTime as u64) << 32) | t.dwLowDateTime as u64
}

unsafe fn read_if(index: u32) -> Option<(u64, u64)> {
    let mut row: MIB_IF_ROW2 = core::mem::zeroed();
    row.InterfaceIndex = index;
    if GetIfEntry2(&mut row) == 0 {
        Some((row.InOctets, row.OutOctets))
    } else {
        None
    }
}

unsafe fn sample_disk() -> u8 {
    let mut win_dir = [0u16; 260];
    let n = GetWindowsDirectoryW(win_dir.as_mut_ptr(), win_dir.len() as u32);
    if n == 0 || n as usize >= win_dir.len() {
        return 0;
    }
    // "C:\Windows" -> "C:\"
    let mut root = [0u16; 4];
    root[0] = win_dir[0];
    root[1] = win_dir[1];
    root[2] = b'\\' as u16;
    let mut free_caller = 0u64;
    let mut total = 0u64;
    let mut total_free = 0u64;
    if GetDiskFreeSpaceExW(root.as_ptr(), &mut free_caller, &mut total, &mut total_free) == 0 {
        return 0;
    }
    if total == 0 {
        return 0;
    }
    let used = total.saturating_sub(total_free);
    let pct = used.saturating_mul(100).saturating_add(total / 2) / total;
    pct.min(100) as u8
}


// ---- 轻量计时工具（trace / 性能自检用） ----
pub fn qpc_now() -> i64 {
    let mut v = 0i64;
    unsafe {
        QueryPerformanceCounter(&mut v);
    }
    v
}

pub fn qpc_freq() -> i64 {
    let mut f = 0i64;
    unsafe {
        QueryPerformanceFrequency(&mut f);
    }
    if f > 0 {
        f
    } else {
        10_000_000
    }
}

/// 把 (now - start) 换成毫秒（整数，避免浮点格式化）
pub fn elapsed_ms(start: i64, now: i64, freq: i64) -> u64 {
    if freq <= 0 || now <= start {
        return 0;
    }
    ((now - start) as u128 * 1000 / freq as u128) as u64
}
