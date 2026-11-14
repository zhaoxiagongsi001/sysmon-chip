"""lite-1：体积 / PE 结构 / 依赖 / Rust std 痕迹核查（Lite vs Std）。

自写 PE 解析（不依赖 pefile）：COFF、OptionalHeader(Subsystem)、数据目录、
导入 DLL + 导入函数数、资源类型（图标/组图标/版本/manifest）、调试目录、
版本资源（version.dll）、ExtractIconEx 图标总数、字符串指纹（std 运行时痕迹）。
"""
import ctypes
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lite_common as L

version = ctypes.WinDLL("version", use_last_error=True)
version.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
version.GetFileVersionInfoSizeW.restype = ctypes.c_ulong
version.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
                                        ctypes.c_void_p]
version.GetFileVersionInfoW.restype = ctypes.c_int
version.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_uint)]
version.VerQueryValueW.restype = ctypes.c_int


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def u64(b, o):
    return struct.unpack_from("<Q", b, o)[0]


class PE:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        d = self.data
        self.path = path
        assert d[:2] == b"MZ", "not MZ"
        pe = u32(d, 0x3C)
        assert d[pe:pe + 4] == b"PE\0\0", "not PE"
        coff = pe + 4
        self.machine = u16(d, coff)
        self.nsections = u16(d, coff + 2)
        self.timestamp = u32(d, coff + 4)
        self.opt_size = u16(d, coff + 16)
        self.characteristics = u16(d, coff + 18)
        opt = coff + 20
        self.magic = u16(d, opt)
        self.pe32plus = self.magic == 0x20B
        self.entry = u32(d, opt + 16)
        self.image_base = u64(d, opt + 24) if self.pe32plus else u32(d, opt + 28)
        self.section_align = u32(d, opt + 32)
        self.file_align = u32(d, opt + 36)
        self.size_image = u32(d, opt + 56)
        self.subsystem = u16(d, opt + 68)
        self.dll_characteristics = u16(d, opt + 70)
        self.linker = (u16(d, opt + 2), u16(d, opt + 3))
        dd_off = opt + (112 if self.pe32plus else 96)
        self.ndirs = u32(d, opt + (108 if self.pe32plus else 92))
        self.dirs = []
        for i in range(min(self.ndirs, 16)):
            self.dirs.append((u32(d, dd_off + i * 8), u32(d, dd_off + i * 8 + 4)))
        self.sections = []
        sec = opt + self.opt_size
        for i in range(self.nsections):
            o = sec + i * 40
            name = d[o:o + 8].split(b"\0")[0].decode("ascii", "replace")
            vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", d, o + 8)
            chars = u32(d, o + 36)
            self.sections.append({"name": name, "vsize": vsize, "vaddr": vaddr,
                                  "rawsize": rawsize, "rawptr": rawptr, "chars": chars})

    def rva2off(self, rva):
        for s in self.sections:
            if s["vaddr"] <= rva < s["vaddr"] + max(s["vsize"], s["rawsize"]):
                return s["rawptr"] + (rva - s["vaddr"])
        return None

    def cstr(self, rva):
        o = self.rva2off(rva)
        if o is None:
            return None
        end = self.data.find(b"\0", o)
        return self.data[o:end].decode("ascii", "replace") if end > 0 else None

    def imports(self):
        rva, size = self.dirs[1]
        if not rva:
            return []
        o = self.rva2off(rva)
        out = []
        while True:
            oft, ts, fwd, name_rva, ft = struct.unpack_from("<IIIII", self.data, o)
            if name_rva == 0:
                break
            dll = self.cstr(name_rva)
            # 统计 thunk 数
            thunk_rva = oft or ft
            to = self.rva2off(thunk_rva)
            n = 0
            step = 8 if self.pe32plus else 4
            while to is not None:
                v = u64(self.data, to) if self.pe32plus else u32(self.data, to)
                if v == 0:
                    break
                n += 1
                to += step
            out.append({"dll": dll, "functions": n})
            o += 20
        return out

    def resources(self):
        rva, size = self.dirs[2]
        if not rva:
            return {}
        base = self.rva2off(rva)
        types = {}

        def walk(off, depth, path):
            nonlocal base
            n_named = u16(self.data, off + 12)
            n_id = u16(self.data, off + 14)
            for i in range(n_named + n_id):
                e = off + 16 + i * 8
                name_id = u32(self.data, e)
                child = u32(self.data, e + 4)
                if name_id & 0x80000000:
                    label = "named"
                else:
                    label = name_id & 0xFFFF
                if child & 0x80000000:
                    walk(base + (child & 0x7FFFFFFF), depth + 1, path + [label])
                else:
                    if depth == 0:
                        types.setdefault(label, 0)
                        types[label] += 1
                    elif len(path) >= 2:
                        types[path[0]] = types.get(path[0], 0) + 1
                        return
                    else:
                        types[label] = types.get(label, 0) + 1
        walk(base, 0, [])
        # 重新按资源类型统计叶子数（更可靠：直接统计第二层条目数）
        counts = {}
        n_named = u16(self.data, base + 12)
        n_id = u16(self.data, base + 14)
        for i in range(n_named + n_id):
            e = base + 16 + i * 8
            name_id = u32(self.data, e)
            child = u32(self.data, e + 4)
            tid = None if (name_id & 0x80000000) else (name_id & 0xFFFF)
            if tid is None or not (child & 0x80000000):
                continue
            second = base + (child & 0x7FFFFFFF)
            m = u16(self.data, second + 12) + u16(self.data, second + 14)
            counts[tid] = m
        return counts

    def debug_dirs(self):
        rva, size = self.dirs[6]
        if not rva:
            return []
        o = self.rva2off(rva)
        out = []
        for i in range(size // 28):
            t, sz, rsz, rp, pptr = struct.unpack_from("<IIIII", self.data, o + i * 28)
            out.append({"type": t, "size": sz})
        return out


RT_NAMES = {1: "cursor", 2: "bitmap", 3: "icon", 4: "menu", 5: "dialog", 6: "string",
            7: "fontdir", 8: "font", 9: "accelerators", 10: "rcdata", 11: "messagetable",
            12: "groupcursor", 14: "groupicon", 16: "version", 24: "manifest"}


def version_info(path):
    size = version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, buf):
        return None
    out = {}

    def query(sub, chars=False):
        p = ctypes.c_void_p()
        ln = ctypes.c_uint(0)
        if version.VerQueryValueW(buf, sub, ctypes.byref(p), ctypes.byref(ln)) and ln.value:
            n = ln.value * 2 if chars else ln.value
            return ctypes.string_at(p, n)
        return None

    fixed = query("\\")
    if fixed and len(fixed) >= 52:
        ms, ls = struct.unpack_from("<II", fixed, 8)
        out["file_version"] = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
        pms, pls = struct.unpack_from("<II", fixed, 16)
        out["product_version"] = f"{pms >> 16}.{pms & 0xFFFF}.{pls >> 16}.{pls & 0xFFFF}"
    # 翻译表
    trans = query("\\VarFileInfo\\Translation")
    langs = []
    if trans:
        for i in range(0, len(trans) - 3, 4):
            lang, cp = struct.unpack_from("<HH", trans, i)
            langs.append((lang, cp))
    if not langs:
        langs = [(0x0804, 1200), (0x0409, 1200)]
    for lang, cp in langs[:2]:
        for key in ("FileVersion", "ProductVersion", "ProductName", "FileDescription",
                    "CompanyName", "InternalName", "OriginalFilename", "LegalCopyright"):
            v = query(f"\\StringFileInfo\\{lang:04x}{cp:04x}\\{key}", chars=True)
            if v:
                try:
                    out[key] = v.decode("utf-16le", "replace").strip("\0").strip()
                except Exception:
                    out[key] = repr(v[:80])
        if out.get("FileVersion"):
            break
    return out


STR_PATTERNS = {
    "rust_std_path": re.compile(rb"library[/\\](std|core|alloc)[/\\]"),
    "rust_panic_msg": re.compile(rb"panicked at|thread '.*' panicked"),
    "rust_backtrace": re.compile(rb"RUST_BACKTRACE|rust_begin_unwind|backtrace"),
    "rust_std_mod": re.compile(rb"\bstd::(io|fs|env|process|thread|sync|path|ffi|os)\b"),
    "rust_unwrap": re.compile(rb"unwrap\(\)|expect\("),
    "rust_core_mod": re.compile(rb"\bcore::(fmt|ptr|mem|option|result)\b"),
    "cargo_path": re.compile(rb"cargo[/\\]registry|\.rs:[0-9]+:[0-9]+"),
}


def strings_ascii(b, min_len=5):
    return re.findall(rb"[\x20-\x7e]{%d,}" % min_len, b)


def strings_utf16(b, min_len=5):
    pat = re.compile((rb"(?:[\x20-\x7e]\x00){%d,}" % min_len))
    return pat.findall(b)


def string_fingerprint(path):
    with open(path, "rb") as f:
        b = f.read()
    asc = strings_ascii(b)
    utf = strings_utf16(b)
    joined = b"\n".join(asc + utf)
    out = {"ascii_strings": len(asc), "utf16_strings": len(utf)}
    for key, pat in STR_PATTERNS.items():
        out[key] = len(pat.findall(joined))
    # 关键片段样例
    samples = {}
    for key, pat in STR_PATTERNS.items():
        hits = pat.findall(joined)
        if hits:
            samples[key] = [h.decode("latin1", "replace")[:80] for h in hits[:5]]
    out["samples"] = samples
    return out


def analyze(label, exe):
    pe = PE(exe)
    res = pe.resources()
    ico_total = None
    try:
        ico_total = int(L.shell32.ExtractIconExW(exe, -1, None, None, 0))
    except Exception:
        pass
    return {
        "label": label, "path": exe, "file_bytes": os.path.getsize(exe),
        "file_kb": round(os.path.getsize(exe) / 1024, 2),
        "sha256": L.sha256(exe),
        "machine": hex(pe.machine), "pe32plus": pe.pe32plus,
        "subsystem": pe.subsystem,
        "subsystem_name": {2: "WINDOWS_GUI", 3: "WINDOWS_CUI"}.get(pe.subsystem, "?"),
        "dll_characteristics": hex(pe.dll_characteristics),
        "linker": f"{pe.linker[0]}.{pe.linker[1]}",
        "size_of_image": pe.size_image, "size_of_image_kb": round(pe.size_image / 1024, 2),
        "sections": [{"name": s["name"], "vsize": s["vsize"], "rawsize": s["rawsize"]}
                     for s in pe.sections],
        "section_bytes": sum(s["rawsize"] for s in pe.sections),
        "imports": pe.imports(),
        "import_dll_count": len(pe.imports()),
        "import_func_total": sum(i["functions"] for i in pe.imports()),
        "resource_types": {RT_NAMES.get(k, str(k)): v for k, v in sorted(res.items())},
        "icon_count_extract": ico_total,
        "debug_dirs": pe.debug_dirs(),
        "version_info": version_info(exe),
        "strings": string_fingerprint(exe),
    }


def main():
    L.ensure_dirs()
    out = {}
    for label, exe in (("lite", L.EXE_LITE), ("std", L.EXE_STD)):
        out[label] = analyze(label, exe)
        a = out[label]
        print(f"\n=== {label}  {os.path.basename(exe)} ===")
        print(f"大小 {a['file_bytes']} B ({a['file_kb']} KB)  SizeOfImage {a['size_of_image_kb']} KB")
        print(f"subsystem={a['subsystem']} ({a['subsystem_name']})  machine={a['machine']}  "
              f"linker={a['linker']}  sha256={a['sha256'][:16]}…")
        print(f"导入 DLL {a['import_dll_count']} 个 / 函数 {a['import_func_total']} 个:")
        for imp in a["imports"]:
            print(f"   - {imp['dll']}: {imp['functions']} funcs")
        print(f"资源: {a['resource_types']}  图标总数={a['icon_count_extract']}  "
              f"debug={a['debug_dirs']}")
        print("版本: " + json.dumps(a["version_info"], ensure_ascii=False))
        s = a["strings"]
        print(f"字符串指纹: ascii={s['ascii_strings']} utf16={s['utf16_strings']} " +
              " ".join(f"{k}={s[k]}" for k in STR_PATTERNS))
    L.save_json("lite-1-pe.json", out)
    # 对照结论
    li, st = out["lite"], out["std"]
    print("\n=== 对照 ===")
    print(f"体积比: {li['file_bytes']}/{st['file_bytes']} = {li['file_bytes']/st['file_bytes']*100:.1f}%")
    lset = {i["dll"].lower() for i in li["imports"]}
    sset = {i["dll"].lower() for i in st["imports"]}
    print(f"导入 DLL: lite={sorted(lset)}")
    print(f"          std ={sorted(sset)}")
    print(f"仅 lite: {sorted(lset - sset)}  仅 std: {sorted(sset - lset)}")
    for k in STR_PATTERNS:
        print(f"std 痕迹 {k}: lite={li['strings'][k]} std={st['strings'][k]}")


if __name__ == "__main__":
    main()
