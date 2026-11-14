"""PE 体积构成分析（无第三方依赖）。

用法：python tools/peinfo.py [exe] [--imports]
输出：总大小、各节（节名 / 虚拟大小 / 原始大小 / 占比）、资源目录块、导入 DLL 与函数清单。
"""
import struct
import sys


def rd(f, off, n):
    f.seek(off)
    return f.read(n)


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


class PE:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.data = f.read()
        d = self.data
        pe = u32(d, 0x3C)
        self.nsec = u16(d, pe + 6)
        self.opt_size = u16(d, pe + 20)
        self.opt_off = pe + 24
        magic = u16(d, self.opt_off)
        self.pe32plus = magic == 0x20B
        self.entry = u32(d, self.opt_off + 16)
        self.image_base = struct.unpack_from("<Q", d, self.opt_off + 24)[0] if self.pe32plus else u32(d, self.opt_off + 28)
        self.sect_align = u32(d, self.opt_off + 32)
        self.file_align = u32(d, self.opt_off + 36)
        self.size_image = u32(d, self.opt_off + 56)
        self.size_headers = u32(d, self.opt_off + 60)
        self.size_code = u32(d, self.opt_off + 4)
        self.size_init = u32(d, self.opt_off + 8)
        self.size_uninit = u32(d, self.opt_off + 12)
        dd = self.opt_off + (112 if self.pe32plus else 96)
        self.dirs = [(u32(d, dd + i * 8), u32(d, dd + i * 8 + 4)) for i in range(16)]
        self.sections = []
        so = self.opt_off + self.opt_size
        for i in range(self.nsec):
            o = so + i * 40
            name = d[o:o + 8].rstrip(b"\0").decode("ascii", "replace")
            vsize = u32(d, o + 8)
            vaddr = u32(d, o + 12)
            rawsize = u32(d, o + 16)
            rawptr = u32(d, o + 20)
            chars = u32(d, o + 36)
            self.sections.append(dict(name=name, vsize=vsize, vaddr=vaddr, rawsize=rawsize,
                                      rawptr=rawptr, chars=chars))

    def rva2off(self, rva):
        for s in self.sections:
            if s["vaddr"] <= rva < s["vaddr"] + max(s["vsize"], s["rawsize"]):
                return s["rawptr"] + (rva - s["vaddr"])
        return None

    def imports(self):
        rva, size = self.dirs[1]
        if not rva:
            return []
        base = self.rva2off(rva)
        d = self.data
        out = []
        i = 0
        while True:
            desc = base + i * 20
            oft = u32(d, desc)
            name_rva = u32(d, desc + 12)
            ft = u32(d, desc + 16)
            if oft == 0 and name_rva == 0 and ft == 0:
                break
            no = self.rva2off(name_rva)
            dll = d[no:d.index(b"\0", no)].decode("ascii", "replace")
            thunk = self.rva2off(oft or ft)
            names = []
            while True:
                if self.pe32plus:
                    ent = struct.unpack_from("<Q", d, thunk)[0]
                    step = 8
                    flag = 1 << 63
                else:
                    ent = u32(d, thunk)
                    step = 4
                    flag = 1 << 31
                if ent == 0:
                    break
                if not (ent & flag):
                    hn = self.rva2off((ent & 0x7FFFFFFF) + 2)
                    names.append(d[hn:d.index(b"\0", hn)].decode("ascii", "replace"))
                else:
                    names.append("#ord")
                thunk += step
            out.append((dll, names))
            i += 1
        return out


def main():
    args = [a for a in sys.argv[1:]]
    show_imports = "--imports" in args
    args = [a for a in args if not a.startswith("--")]
    path = args[0] if args else r"D:/DSH/sysmon-chip/发布/SysMonChipLite.exe"
    pe = PE(path)
    total = len(pe.data)
    print(f"file: {path}")
    print(f"size: {total} bytes ({total/1024:.1f} KB)")
    print(f"PE headers: {pe.size_headers}   image: {pe.size_image}   code(dir): {pe.size_code}")
    print()
    print(f"{'section':10s} {'vsize':>9s} {'rawsize':>9s} {'file%':>6s} {'chars':>10s}")
    raw_used = 0
    for s in pe.sections:
        pct = s["rawsize"] * 100.0 / total
        raw_used += s["rawsize"]
        print(f"{s['name']:10s} {s['vsize']:9d} {s['rawsize']:9d} {pct:5.1f}% 0x{s['chars']:08x}")
    print(f"{'sum(raw)':10s} {'':9s} {raw_used:9d} {raw_used*100.0/total:5.1f}%")
    print(f"{'slack':10s} {'':9s} {total-raw_used:9d} {(total-raw_used)*100.0/total:5.1f}%  (对齐/头部/签名)")
    print()
    names = ["export", "import", "resource", "exception", "security", "basereloc",
             "debug", "arch", "globalptr", "tls", "loadconfig", "boundimport",
             "iat", "delayimport", "clr", "reserved"]
    for i, (rva, size) in enumerate(pe.dirs[:15]):
        if size:
            print(f"dir {names[i]:12s} rva=0x{rva:08x} size={size:8d} ({size/1024:6.1f} KB)")
    print()
    imps = pe.imports()
    total_fns = sum(len(n) for _, n in imps)
    print(f"imports: {len(imps)} dll, {total_fns} functions")
    for dll, fns in imps:
        print(f"  {dll:32s} {len(fns):3d}")
    if show_imports:
        for dll, fns in imps:
            print()
            print(dll)
            for fn in sorted(fns):
                print("   ", fn)


main()
