"""Generate the on-card CJK font used by the menu.

Outputs (default: Assets/fonts/cjk):
    FONT.HZK  slots x bytes-per-glyph, GB2312 order ((lead-0xA1)*94 + trail-0xA1)
    FONT.MAP  "NESFM1" + cell size + reserved + count + sorted (uint16 code, uint16 slot)

Cell size is stored in FONT.MAP so the firmware adapts without a rebuild. Rendering
a TTF is a build-time asset step, not per-ROM processing.

SimSun at 24 px has 1 px horizontals; after the 128-level binarisation those
strokes (and thin diagonals) break into isolated dots, which reads as "断续" on
the panel.  SimHei keeps solid 2 px stems and connected counters at the same
cell size.  Glyphs are rasterised on a 2x canvas and then cropped to the ink
box, so ascenders/descenders cannot be clipped and every glyph is centred.

Usage:
    make_cjk_font.py [--size 24] [--font C:\\Windows\\Fonts\\simhei.ttf]
"""
import argparse, struct
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SLOTS = 94 * 94
DEFAULT_FONT = r'C:\Windows\Fonts\simhei.ttf'


def glyph_bytes(image, size, threshold):
    image = image.point(lambda v: 255 if v >= threshold else 0).convert('1')
    # Centre the ink box: CJK fonts sit off-centre and thin strokes break up
    # when the glyph is shifted against the cell edge.
    box = image.getbbox()
    canvas = Image.new('1', (size, size), 0)
    if box:
        glyph = image.crop(box)
        if glyph.width > size or glyph.height > size:
            glyph = glyph.convert('L')
            scale = min(size / glyph.width, size / glyph.height)
            glyph = glyph.resize((max(1, int(glyph.width * scale)),
                                  max(1, int(glyph.height * scale))), Image.LANCZOS)
            glyph = glyph.point(lambda v: 255 if v >= threshold else 0).convert('1')
        canvas.paste(glyph, ((size - glyph.width) // 2, (size - glyph.height) // 2))
    image = canvas
    stride = (size + 7) // 8
    out = bytearray(stride * size)
    for y in range(size):
        for x in range(size):
            if image.getpixel((x, y)):
                out[y * stride + x // 8] |= 0x80 >> (x % 8)
    return bytes(out)


def build(font_path, output, size, threshold):
    font = ImageFont.truetype(str(font_path), size, index=0)
    per = ((size + 7) // 8) * size
    hzk = bytearray(SLOTS * per)
    mapping = []
    for lead in range(0xA1, 0xF8):
        for trail in range(0xA1, 0xFF):
            try:
                ch = bytes([lead, trail]).decode('gb2312')
            except UnicodeDecodeError:
                continue
            if len(ch) != 1:
                continue
            slot = (lead - 0xA1) * 94 + (trail - 0xA1)
            # A 2x canvas leaves room for negative bearings and descenders.
            image = Image.new('L', (size * 2, size * 2), 0)
            ImageDraw.Draw(image).text((size // 2, size // 2), ch, font=font, fill=255)
            hzk[slot * per:(slot + 1) * per] = glyph_bytes(image, size, threshold)
            mapping.append((ord(ch), slot))
    mapping.sort()
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'FONT.HZK').write_bytes(bytes(hzk))
    blob = bytearray(b'NESFM1')
    blob += bytes([size & 0xFF, 0])
    blob += struct.pack('<I', len(mapping))
    for code, slot in mapping:
        blob += struct.pack('<HH', code, slot)
    (out / 'FONT.MAP').write_bytes(bytes(blob))
    print(f'wrote {len(mapping)} glyphs at {size}x{size} to {out}; '
          f'HZK {len(hzk)} bytes, MAP {len(blob)} bytes')
    return len(mapping)


def preview(font_path, text, path, size=24):
    font = ImageFont.truetype(str(font_path), size, index=0)
    image = Image.new('L', (size * len(text), size), 0)
    draw = ImageDraw.Draw(image)
    for i, ch in enumerate(text):
        draw.text((i * size, 0), ch, font=font, fill=255)
    image.point(lambda v: 255 if v >= 128 else 0).resize((size * len(text) * 3, size * 3), Image.NEAREST).save(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', default=DEFAULT_FONT)
    parser.add_argument('--size', type=int, default=24)
    parser.add_argument('--threshold', type=int, default=128)
    parser.add_argument('--output', type=Path, default=ROOT / 'Assets/fonts/cjk')
    args = parser.parse_args()
    build(args.font, args.output, args.size, args.threshold)
