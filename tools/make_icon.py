"""生成 SysMonChip 图标（多尺寸 ICO）。无外部依赖，只用 Pillow。"""
from PIL import Image, ImageDraw

SIZE = 256
im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(im)

# 底板：深色圆角方
d.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=52, fill=(28, 28, 32, 255),
                    outline=(52, 52, 60, 255), width=3)

# 四根柱子：CPU / MEM / DISK / NET
bars = [
    (44, 192 - 96, (76, 194, 255, 255)),
    (100, 192 - 128, (61, 220, 151, 255)),
    (156, 192 - 72, (255, 200, 87, 255)),
    (212, 192 - 112, (179, 136, 255, 255)),
]
for left, top, color in bars:
    d.rounded_rectangle((left, top, left + 26, 192), radius=13, fill=color)

# 底线
d.rounded_rectangle((44, 204, 238, 208), radius=2, fill=(90, 90, 100, 255))

im.save(r"D:\DSH\sysmon-chip\app\assets\icon.ico", format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
im.resize((128, 128), Image.LANCZOS).save(r"D:\DSH\sysmon-chip\app\assets\icon-preview.png")
print("icon ok")
