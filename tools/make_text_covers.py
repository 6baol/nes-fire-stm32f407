"""Generate text covers for ROMs that have no artwork.

The menu shows a plain "NO COVER" panel otherwise. This renders a 456x360 card
with the game title (Chinese supported), a colour derived from the file, and a
small NES tag, then writes the same NCV1 format the firmware already decodes.

Usage:
    make_text_covers.py --roms "F:/NES" --recursive
    make_text_covers.py --roms Roms --output-staging Release/text_covers
"""
import argparse, zlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_sd import encode_cover_image

W, H = 456, 360


def palette(seed):
    base = seed & 0xFF
    r = 24 + (base * 37) % 120
    g = 24 + (base * 71) % 120
    b = 40 + (base * 53) % 140
    return (r, g, b)


def wrap(draw, text, font, limit):
    lines, current = [], ''
    for ch in text:
        trial = current + ch
        if draw.textlength(trial, font=font) <= limit or not current:
            current = trial
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def make_cover(name, seed, font_path):
    title = name.rsplit('.', 1)[0]
    image = Image.new('RGB', (W, H), palette(seed))
    draw = ImageDraw.Draw(image)
    # A few flat bands keep the card from looking like a solid colour block.
    for y in range(0, H, 24):
        shade = 0.72 + 0.28 * ((y // 24) % 2)
        band = tuple(int(c * shade) for c in palette(seed))
        draw.rectangle([0, y, W, y + 23], fill=band)
    draw.rectangle([10, 10, W - 11, H - 11], outline=(255, 255, 255), width=3)
    title_font = ImageFont.truetype(str(font_path), 30, index=0)
    lines = wrap(draw, title, title_font, W - 60)[:4]
    top = (H - len(lines) * 40) // 2 - 12
    for i, line in enumerate(lines):
        width = draw.textlength(line, font=title_font)
        draw.text(((W - width) // 2, top + i * 40), line, font=title_font,
                  fill=(255, 255, 255))
    tag = ImageFont.truetype(str(font_path), 18, index=0)
    draw.text((26, H - 46), 'FAMICOM', font=tag, fill=(235, 235, 235))
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roms', type=Path, required=True)
    parser.add_argument('--recursive', action='store_true')
    parser.add_argument('--font', default=r'C:\Windows\Fonts\simsun.ttc')
    parser.add_argument('--output-staging', type=Path,
                        help='write <name>.COV here instead of next to the ROM')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    root = args.roms
    pattern = '**/*' if args.recursive else '*'
    made = skipped = 0
    for rom in sorted(root.glob(pattern)):
        if not rom.is_file() or rom.suffix.lower() not in ('.nes', '.fds'):
            continue
        cover = (args.output_staging / (rom.stem + '.COV')) if args.output_staging else (rom.with_suffix('.COV'))
        if cover.exists() and not args.force:
            skipped += 1
            continue
        seed = zlib.crc32(rom.name.encode('utf-8')) ^ zlib.crc32(rom.read_bytes()[:4096])
        cover.parent.mkdir(parents=True, exist_ok=True)
        cover.write_bytes(encode_cover_image(make_cover(rom.name, seed, args.font)))
        made += 1
    print(f'wrote {made} covers, skipped {skipped} existing')


if __name__ == '__main__':
    main()
