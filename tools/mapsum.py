"""从 lld/ld 的 map 文件里汇总 .text 段各函数大小（按来源库聚合）。"""
import re
import sys
from collections import Counter

path = sys.argv[1] if len(sys.argv) > 1 else r"D:/DSH/.tmp/sysmon.map"
sizes = []
for line in open(path, encoding="utf-8", errors="replace"):
    m = re.match(r"\s+\.text\S*\s+0x[0-9a-f]+\s+0x([0-9a-f]+)\s+(\S+)", line)
    if m:
        sizes.append((int(m.group(1), 16), m.group(2)))
sizes.sort(reverse=True)
print("functions:", len(sizes), "total", sum(s for s, _ in sizes))
for s, n in sizes[:30]:
    print(f"{s:6d}  {n}")

c = Counter()
for s, n in sizes:
    key = "own/rust"
    low = n.lower()
    for pat in ("msvcrt", "libmingwex", "libmingw32", "libgcc", "crt2", "crtbegin",
                "crtend", "kernel32", "user32", "libkernel32", "libuser32"):
        if pat in low:
            key = pat
            break
    c[key] += s
print()
for k, v in c.most_common(12):
    print(f"{v:6d}  {k}")
