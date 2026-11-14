"""链接器包装（ld 风格参数）：剥掉 rustc 显式塞进来的 mingw CRT 启动对象与库。

rustc 的 windows-gnu 后端会把 `<sysroot>/…/self-contained/crt2.o` 以及
`-lmsvcrt -lmingwex -lmingw32 -lgcc` 直接写进 ld 命令行，所以只能在调用前截下来。
配合 `-C linker-flavor=ld` 使用（此时 rustc 传的是 ld 原生参数，不再经 gcc 驱动）。

用法：
  LD_WRAP_REAL=<同目录 ld.exe> python tools/ld_wrap.py <ld 参数...>

不设环境变量时会自己问 rustc（`rustc --print target-libdir`）推出来，便于
`tools/build.ps1` 在任意目录直接调用。
"""
import os
import re
import subprocess
import sys


def detect():
    """返回 (真实 ld 路径, self-contained 导入库目录)，探测不到返回 (None, None)。"""
    try:
        r = subprocess.run(["rustc", "--print", "target-libdir"], capture_output=True, text=True)
    except OSError:
        return None, None
    libdir = (r.stdout or "").strip()
    if not libdir:
        return None, None
    ld = os.path.abspath(os.path.join(libdir, "..", "bin", "self-contained", "ld.exe"))
    imp = os.path.join(libdir, "self-contained")
    return (ld if os.path.exists(ld) else None), (imp if os.path.isdir(imp) else None)


DETECTED_LD, DETECTED_LIBDIR = detect()
REAL = os.environ.get("LD_WRAP_REAL") or DETECTED_LD or "ld"
DROP_ARG = re.compile(
    r"(?i)(crt2\.o|crtbegin\.o|crtend\.o|libmingw32\.a|libmsvcrt\.a|libmoldname\.a"
    r"|-lmingw32|-lmsvcrt|-lmoldname|-lmingwex|-lgcc_eh|-lgcc$|-l:libpthread\.a)"
)
REQUIRED_LIBS = ["-lkernel32", "-luser32", "-lgdi32", "-ladvapi32", "-liphlpapi", "-lshell32"]


def main():
    args = sys.argv[1:]
    out = []
    libs = []
    for a in args:
        if a.startswith("-Wl,"):
            out.extend(x for x in a[4:].split(",") if x)
            continue
        if DROP_ARG.search(a):
            continue
        if a.startswith("-l"):
            libs.append(a)
            continue
        out.append(a)
    if "--entry=chip_entry" not in out and not any(a.startswith("--entry") for a in out):
        out.append("--entry=chip_entry")
    seen = {x.lower() for x in libs}
    for need in REQUIRED_LIBS:
        if need.lower() not in seen:
            libs.append(need)
    # ld 风格下 rustc 不传 -L（那是 gcc 驱动补的），导入库由环境变量补进来
    extra_dirs = [d for d in os.environ.get("LD_WRAP_LIBDIRS", "").split(";") if d]
    if not extra_dirs and DETECTED_LIBDIR:
        extra_dirs = [DETECTED_LIBDIR]
    for d in extra_dirs:
        out.extend(["-L", d])
    cmd = [REAL] + out + libs
    log = os.environ.get("LD_WRAP_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write("CMD " + " ".join(cmd) + "\n")
    r = subprocess.run(cmd, capture_output=True)
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write("RC " + str(r.returncode) + "\n" + r.stderr.decode("utf-8", "replace") + "\n")
    sys.stderr.write(r.stderr.decode("utf-8", "replace"))
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
