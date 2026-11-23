"""NCV1 cover codec shared by prepare_sd.py and the import GUI.

The firmware reads a 24-byte header followed by an RGB565 palette and packed
indices.  prepare_sd.py uses this to build cards; the import assistant uses it
to preview and generate covers.
"""
import struct
import zlib

from PIL import Image, ImageOps

COVER_HEADER = struct.Struct('<4sHHBBHIII')


def encode_cover(path, poster=False):
    image = Image.open(path).convert('RGB')
    if poster:
        image = ImageOps.fit(image, (240, 360), method=Image.Resampling.LANCZOS)
    return encode_cover_image(image)


def encode_cover_image(image, poster=False):
    """Pack an RGB image into the NCV1 layout the firmware reads."""
    if poster:
        image = ImageOps.fit(image, (240, 360), method=Image.Resampling.LANCZOS)
    if image.width > 512 or image.height > 480:
        raise ValueError('Cover capture exceeds 512x480')
    indexed = image.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    pixels = indexed.tobytes()
    bits = 4 if max(pixels) < 16 else 8
    count = 1 << bits
    pal = indexed.getpalette()
    pal += [0] * (768 - len(pal))
    palette = b''.join(
        struct.pack('<H', ((pal[i] >> 3) << 11) | ((pal[i + 1] >> 2) << 5) | (pal[i + 2] >> 3))
        for i in range(0, count * 3, 3))
    if bits == 4:
        pixels = bytes((pixels[i] << 4) | (pixels[i + 1] if i + 1 < len(pixels) else 0)
                       for i in range(0, len(pixels), 2))
    payload = palette + pixels
    return COVER_HEADER.pack(b'NCV1', image.width, image.height, bits, int(poster),
                             count, len(palette), len(pixels), zlib.crc32(payload)) + payload


def decode_cover(data):
    if len(data) < COVER_HEADER.size:
        raise ValueError('Truncated cover header')
    magic, w, h, bits, flags, count, pal_size, pixel_size, crc = COVER_HEADER.unpack_from(data)
    if (magic != b'NCV1' or not 0 < w <= 512 or not 0 < h <= 480 or bits not in (4, 8)
            or flags not in (0, 1) or count != (1 << bits)):
        raise ValueError('Invalid cover header')
    payload = data[COVER_HEADER.size:]
    if (pal_size != count * 2 or pixel_size != (w * h * bits + 7) // 8
            or len(payload) != pal_size + pixel_size or zlib.crc32(payload) != crc):
        raise ValueError('Invalid cover size or CRC')
    palette = struct.unpack('<' + 'H' * count, payload[:pal_size])
    pixels = payload[pal_size:]
    values = [palette[(pixels[i // 2] >> (0 if i & 1 else 4)) & 15] if bits == 4
              else palette[pixels[i]] for i in range(w * h)]
    return w, h, bits, values
