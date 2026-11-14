"""生成小体积 ICO：32/48/24 三个 PNG 压缩层（Win7+ 支持 ICO 内的 PNG）。
目的：把 15.8 KB 的旧图标压到 ~3 KB，给 exe 腾出体积。"""
import io, struct
from PIL import Image, ImageDraw

SIZE = 256
im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=52, fill=(28, 28, 32, 255),
                    outline=(52, 52, 60, 255), width=3)
bars = [
    (44, 192 - 96, (76, 194, 255, 255)),
    (100, 192 - 128, (61, 220, 151, 255)),
    (156, 192 - 72, (255, 200, 87, 255)),
    (212, 192 - 112, (179, 136, 255, 255)),
]
for left, top, color in bars:
    d.rounded_rectangle((left, top, left + 26, 192), radius=13, fill=color)
d.rounded_rectangle((44, 204, 238, 208), radius=2, fill=(90, 90, 100, 255))

sizes = [24, 32, 48]
payloads = []
for s in sizes:
    buf = io.BytesIO()
    im.resize((s, s), Image.LANCZOS).save(buf, format="PNG", optimize=True)
    payloads.append(buf.getvalue())

header = struct.pack("<HHH", 0, 1, len(sizes))
offset = 6 + 16 * len(sizes)
entries = b""
for s, data in zip(sizes, payloads):
    entries += struct.pack("<BBBBHHII", s if s < 256 else 0, s if s < 256 else 0, 0, 0, 1, 32, len(data), offset)
    offset += len(data)

blob = header + entries + b"".join(payloads)
for path in (
    r"D:\DSH\sysmon-chip\app_ultra\assets\icon.ico",
    r"D:\DSH\sysmon-chip\app\assets\icon.ico",
):
    with open(path, "wb") as f:
        f.write(blob)
print("icon bytes:", len(blob), "sizes:", sizes)
