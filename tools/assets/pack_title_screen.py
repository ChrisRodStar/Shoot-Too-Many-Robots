#!/usr/bin/env python3
"""Pack a 3840 × 2880 title image into a separate Seoul SAR v3 archive."""
from __future__ import annotations

import argparse
import io
import os
import struct
import tempfile
import zlib
from pathlib import Path

from PIL import Image

from extract_sar import SIGNATURE, VERSION, decrypt

TITLE = b"UI\\TitleScreen.gfx"
TEXTURE = b"UI\\TitleScreen_4K.dds"
IMAGE_ID = 0x7000
SHAPE_ID = 0x7001
WIDTH, HEIGHT = 3840, 2880


class Bits:
    def __init__(self):
        self.fields = []

    def add(self, value, width):
        self.fields.append(format(value & ((1 << width) - 1), f"0{width}b"))

    def finish(self):
        bits = "".join(self.fields)
        return int(bits.ljust((len(bits) + 7) // 8 * 8, "0"), 2).to_bytes(
            (len(bits) + 7) // 8, "big"
        )


def tag(code, payload):
    if len(payload) < 63:
        return struct.pack("<H", code << 6 | len(payload)) + payload
    return struct.pack("<HI", code << 6 | 63, len(payload)) + payload


def artwork_shape():
    # Fit the 4:3 art in the 1280 × 720 stage. Flash positions use twentieths of a pixel.
    width, height = 19200, 14400
    bounds = Bits()
    bounds.add(16, 5)
    for edge in (0, width, 0, height):
        bounds.add(edge, 16)
    scale = Bits()
    scale.add(1, 1)
    scale.add(20, 5)
    scale.add(5 << 16, 20)
    scale.add(5 << 16, 20)
    scale.add(0, 1)  # No rotation.
    scale.add(0, 5)  # No translation.
    shape = Bits()
    shape.add(0x10, 8)   # One fill-index bit, zero line-index bits.
    shape.add(0b000100, 6)  # Set fill style 1.
    shape.add(1, 1)
    # Split edges to stay within the SWF straight-edge signed-bit limit.
    for delta, vertical in [(width // 2, 0)] * 2 + [(height // 2, 1)] * 2 + [
        (-width // 2, 0)
    ] * 2 + [(-height // 2, 1)] * 2:
        shape.add(0b110000 | 13, 6)  # Straight edge, 15-bit delta.
        shape.add(0, 1)
        shape.add(vertical, 1)
        shape.add(delta, 15)
    shape.add(0, 6)
    return (struct.pack("<H", SHAPE_ID) + bounds.finish() + b"\x01\x41"
            + struct.pack("<H", IMAGE_ID) + scale.finish() + b"\x00" + shape.finish())


def replace_movie(movie):
    if movie[:3] != b"CFX":
        raise ValueError("expected a compressed Scaleform movie")
    body = zlib.decompress(movie[8:])
    cursor = (5 + (body[0] >> 3) * 4 + 7) // 8 + 4
    output = bytearray(body[:cursor])
    name = TEXTURE.split(b"\\")[-1]
    bitmap = struct.pack("<5HBB", IMAGE_ID, 0, 14, WIDTH, HEIGHT, 0, len(name))
    # Place the new image at depth 1, offset 160 px. Leave depths 7 and 8 for UI prompts.
    placement = Bits()
    placement.add(0, 2)
    placement.add(13, 5)
    placement.add(3200, 13)
    placement.add(0, 13)
    inserted = False
    while cursor < len(body):
        start = cursor
        header, = struct.unpack_from("<H", body, cursor)
        cursor += 2
        code, size = header >> 6, header & 63
        if size == 63:
            size, = struct.unpack_from("<I", body, cursor)
            cursor += 4
        payload = body[cursor:cursor + size]
        cursor += size
        if code == 9:
            output += tag(9, b"\x00\x00\x00")
        elif code == 26 and struct.unpack_from("<H", payload, 1)[0] in (1, 3, 5):
            if not inserted:
                output += tag(1009, bitmap + name + b"\x00")
                output += tag(2, artwork_shape())
                output += tag(26, struct.pack("<BHH", 6, 1, SHAPE_ID) + placement.finish())
                inserted = True
        else:
            output += body[start:cursor]
    if not inserted:
        raise ValueError("title artwork placements were missing")
    return movie[:4] + struct.pack("<I", len(output) + 8) + zlib.compress(output)


def pack(source, output, artwork):
    if source.resolve() == output.resolve():
        raise ValueError("choose a separate output path for the patched archive")
    with Image.open(artwork) as image:
        if image.size != (WIDTH, HEIGHT):
            raise ValueError(f"expected {WIDTH} × {HEIGHT} artwork")
        texture = io.BytesIO()
        image.convert("RGBA").save(texture, format="DDS")

    entries = []
    patches = {TEXTURE: texture.getvalue()}
    with source.open("rb") as archive:
        header = archive.read(24)
        signature, version, table, count = struct.unpack_from("<IIQI", header)
        if (signature, version) != (SIGNATURE, VERSION):
            raise ValueError("expected a Seoul SAR v3 archive")
        archive.seek(table)
        for _ in range(count):
            offset, size, length = struct.unpack("<QQI", archive.read(20))
            name = archive.read(length).rstrip(b"\x00")
            entries.append((name, offset, size))
        offset, size = next((o, s) for name, o, s in entries if name == TITLE)
        archive.seek(offset)
        patches[TITLE] = replace_movie(decrypt(archive.read(size), TITLE))
        if any(name == TEXTURE for name, _, _ in entries):
            raise ValueError("archive already has the replacement texture")

        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as result:
            temporary = Path(result.name)
            try:
                archive.seek(0)
                remaining = table
                while remaining:
                    chunk = archive.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise ValueError("archive ended before the original file table")
                    result.write(chunk)
                    remaining -= len(chunk)
                replacements = {}
                for name, data in patches.items():
                    replacements[name] = (name, result.tell(), len(data))
                    result.write(decrypt(data, name))
                entries = [replacements.get(entry[0], entry) for entry in entries]
                entries.append(replacements[TEXTURE])
                offset = result.tell()
                for name, start, size in entries:
                    result.write(struct.pack("<QQI", start, size, len(name) + 1) + name + b"\x00")
                result.seek(8)
                result.write(struct.pack("<QI", offset, len(entries)))
                result.close()
                os.replace(temporary, output)
            finally:
                temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("artwork", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    pack(args.source, args.output, args.artwork)


if __name__ == "__main__":
    main()
