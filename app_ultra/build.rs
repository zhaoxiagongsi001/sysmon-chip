//! 用 windres 把图标与版本信息编进 lite exe（与 std 版同一套做法）。

use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=assets/app.rc");
    println!("cargo:rerun-if-changed=assets/icon.ico");
    println!("cargo:rerun-if-changed=assets/preproc.bat");
    println!("cargo:rerun-if-changed=assets/app.manifest");

    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
    let obj = out_dir.join("app_res.o");
    let manifest = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let pp = manifest.join("assets").join("preproc.bat");

    let candidates = [
        "windres".to_string(),
        r"D:\DSH\.rust\mingw\mingw64\bin\windres.exe".to_string(),
        r"C:\Program Files\mingw64\bin\windres.exe".to_string(),
    ];

    for exe in candidates {
        let pp_arg = format!("--preprocessor={}", pp.display());
        let status = Command::new(&exe)
            .arg(pp_arg)
            .arg("-I")
            .arg("assets")
            .arg("-i")
            .arg("assets/app.rc")
            .arg("-O")
            .arg("coff")
            .arg("-o")
            .arg(&obj)
            .status();
        if let Ok(st) = status {
            if st.success() {
                println!("cargo:rustc-link-arg={}", obj.display());
                return;
            }
        }
    }
    println!("cargo:warning=windres 编译资源失败，跳过图标");
}

