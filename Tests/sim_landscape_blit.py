"""Simulate the landscape blit exactly as nes_port.c does, with a real title.

Portrait geometry: 8 NES pixels span 15 LCD columns, 240 lines span 450 rows.
Landscape: each source line becomes a 2-pixel-wide vertical strip, image x grows
down the panel and the strip is placed at (800-480)/2 + (450 - y1).
"""
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
src = Image.open(root/'Assets/posters/smb_title.png').convert('RGB')
if src.size != (256, 240):
    src = src.resize((256, 240), Image.NEAREST)

W, H = 800, 480
out = Image.new('RGB', (W, H), (0, 0, 0))
px = out.load()

for line in range(240):
    y0 = line*2
    y1 = y0+2
    row = []
    for g in range(32):
        for i in range(8):
            color = src.getpixel((g*8+i, line))
            row += [color]*4 if i == 7 else [color]*3
    x0 = 0
    for j, color in enumerate(row):
        for k in range(y1-y0):
            px[x0+j, y0+k] = color

dest = root/'Tests/nes_output/landscape_blit.png'
dest.parent.mkdir(exist_ok=True)
out.save(dest)
print('wrote', dest)
