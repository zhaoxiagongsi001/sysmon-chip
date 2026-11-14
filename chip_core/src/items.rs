//! 显示项开关（与配置解耦，供 no_std 核心使用）。

#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Items {
    pub cpu: bool,
    pub mem: bool,
    pub disk: bool,
    pub net: bool,
}

impl Items {
    pub const ALL: Self = Self { cpu: true, mem: true, disk: true, net: true };
}
