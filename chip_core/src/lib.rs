//! SysMon Chip 的 no_std 核心。
//! 只依赖 core + windows-sys，可同时被 std 外壳和 no_std 外壳复用。

#![cfg_attr(not(test), no_std)]

pub mod items;
pub mod metrics;
pub mod paint;
