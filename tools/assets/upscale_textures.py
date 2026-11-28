#!/usr/bin/env python3
"""Upscale reviewed PC_ContentPC color textures and build an optional test archive."""
from __future__ import annotations

import argparse
import fnmatch
import io
import json
import mmap
import os
import struct
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from extract_sar import SIGNATURE, VERSION, decrypt, safe_member_path

ARCHIVE = "PC_ContentPC"
WORK = Path("work/assets/upgrades")
PILOT = [
    "Environment/Farmland/Ground_Tiles/Dirt_01.SIF",
    "Char/Char_RoomBoss_Overlord_NEW/Bones/RoomBoss_DiffuseMap.SIF",
]


def level_size(width, height, block):
    if block == 0:
        return width * height * 4
    return ((width + 3) // 4) * ((height + 3) // 4) * block


def mip_chain(header, image, encoding, count, block):
    mipmaps = []
    for _ in range(count):
        stream = io.BytesIO()
        if encoding == "RGBA":
            image.save(stream, format="DDS")
        else:
            image.save(stream, format="DDS", pixel_format=encoding)
        pixels = stream.getvalue()[128:]
        if len(pixels) != level_size(*image.size, block):
            raise ValueError(f"invalid compressed mip size for {image.size}")
        mipmaps.append(pixels)
        if image.size != (1, 1):
            image = image.resize(tuple(max(1, edge // 2) for edge in image.size), Image.Resampling.BOX)
    return bytes(header) + b"".join(mipmaps)


def upscale_texture(source, output, member, upscaler, scale, max_edge,
                    *, archive=ARCHIVE, method="ai", wrap=False):
    path = Path(member)
    if path.suffix.lower() in (".jpg", ".bmp"):
        with Image.open(source) as image:
            original = image.convert("RGB")
        size = tuple(edge * scale for edge in original.size)
        if max(size) > max_edge:
            raise ValueError(f"output {size} exceeds --max-edge {max_edge}")
        result = original.resize(size, Image.Resampling.LANCZOS)
        texture = output / "textures" / archive / path
        texture.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".jpg":
            result.save(texture, quality=96, subsampling=0)
        else:
            result.save(texture)
        save_comparison(output, archive, path, original, result)
        print(f"{archive}/{member}: {original.width} × {original.height} → {size[0]} × {size[1]}", flush=True)
        return texture

    original = source.read_bytes()
    encoding = original[84:88].decode("ascii", errors="replace")
    if original[:4] != b"DDS ":
        raise ValueError("expected a DDS-backed texture")
    if encoding == "\x00" * 4 and struct.unpack_from("<6I", original, 80) == (
        65, 0, 32, 0xFF0000, 0xFF00, 0xFF
    ) and struct.unpack_from("<I", original, 104)[0] == 0xFF000000:
        encoding, block = "RGBA", 0
    elif encoding in ("DXT1", "DXT5"):
        block = 8 if encoding == "DXT1" else 16
    else:
        raise ValueError(f"unsupported DDS encoding {encoding!r}")
    height, width, _, _, raw_levels = struct.unpack_from("<5I", original, 12)
    levels = max(1, raw_levels)
    if levels > max(width, height).bit_length() or len(original) != 128 + sum(
        level_size(max(1, width >> level), max(1, height >> level), block)
        for level in range(levels)
    ):
        raise ValueError("texture has unexpected mip data or extra bytes")
    size = (width * scale, height * scale)
    if max(size) > max_edge:
        raise ValueError(f"output {size} exceeds --max-edge {max_edge}")

    with Image.open(source) as image:
        rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    if encoding == "DXT1" and alpha.getextrema() != (255, 255):
        raise ValueError("DXT1 texture has cutout alpha")
    if method == "ai":
        result = upscale_color(rgba, upscaler, scale, wrap)
    else:
        result = rgba.resize(size, Image.Resampling.LANCZOS)
    if result.size != size:
        raise ValueError(f"expected {size}, got {result.size}")

    texture = output / "textures" / archive / path
    texture.parent.mkdir(parents=True, exist_ok=True)
    header = bytearray(original[:128])
    count = max(size).bit_length() if levels == max(width, height).bit_length() else levels
    stored_count = raw_levels if levels == 1 else count
    stride = size[0] * 4 if block == 0 else level_size(*size, block)
    struct.pack_into("<5I", header, 12, size[1], size[0], stride, 0, stored_count)
    texture.write_bytes(mip_chain(header, result, encoding, count, block))
    save_comparison(output, archive, path, rgba, result)
    print(f"{archive}/{member}: {width} × {height} → {size[0]} × {size[1]} ({encoding}, {count} levels)", flush=True)
    return texture


def upscale_color(image, upscaler, scale, wrap):
    color = image.convert("RGB")
    width, height = color.size
    border = min(16, width, height) if wrap else 0
    if border:
        padded = Image.new("RGB", (width + border * 2, height + border * 2))
        for y in (-height, 0, height):
            for x in (-width, 0, width):
                padded.paste(color, (x + border, y + border))
        color = padded
    with tempfile.TemporaryDirectory() as temp:
        src, dst = Path(temp) / "input.png", Path(temp) / "output.png"
        color.save(src)
        subprocess.run([
            str(upscaler), "-i", str(src), "-o", str(dst),
            "-m", str(upscaler.parent / "models"), "-n", "realesr-animevideov3",
            "-s", str(scale),
        ], check=True)
        with Image.open(dst) as upscaled:
            if upscaled.size != (color.width * scale, color.height * scale):
                raise ValueError(f"unexpected Real-ESRGAN dimensions: {upscaled.size}")
            result = upscaled.convert("RGBA")
    if border:
        result = result.crop((border * scale, border * scale, (border + width) * scale, (border + height) * scale))
    result.putalpha(image.getchannel("A").resize(result.size, Image.Resampling.LANCZOS))
    return result


def save_comparison(output, archive, path, original, result):
    png = path.with_suffix(path.suffix + ".png")
    before = output / "originals" / archive / png
    preview = output / "previews" / archive / png
    before.parent.mkdir(parents=True, exist_ok=True)
    preview.parent.mkdir(parents=True, exist_ok=True)
    original.save(before)
    with tempfile.NamedTemporaryFile(dir=preview.parent, delete=False) as pending:
        temporary = Path(pending.name)
        try:
            result.save(pending, format="PNG")
            pending.close()
            os.replace(temporary, preview)
        finally:
            temporary.unlink(missing_ok=True)


def write_member(output, source, name):
    # SAR's XOR stream repeats every 1024 bytes. Build it once per member.
    stream = decrypt(bytes(1024), name)
    mask = stream * 1024
    key = int.from_bytes(mask, "little")
    with source.open("rb") as payload:
        while chunk := payload.read(len(mask)):
            used_key = key if len(chunk) == len(mask) else int.from_bytes(mask[:len(chunk)], "little")
            output.write((int.from_bytes(chunk, "little") ^ used_key).to_bytes(len(chunk), "little"))


def repack(source, destination, replacements):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.resolve() == source.resolve():
        raise ValueError("choose a separate output archive")
    temporary = None
    try:
        with source.open("rb") as original, mmap.mmap(original.fileno(), 0, access=mmap.ACCESS_READ) as data:
            signature, version, table, count = struct.unpack_from("<IIQI", data)
            if (signature, version) != (SIGNATURE, VERSION):
                raise ValueError("expected Seoul Engine SAR v3")
            cursor = table
            entries = []
            remaining = replacements.copy()
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as out:
                temporary = Path(out.name)
                for start in range(0, table, 1024 * 1024):
                    out.write(data[start:min(start + 1024 * 1024, table)])
                for _ in range(count):
                    offset, length, name_len = struct.unpack_from("<QQI", data, cursor)
                    cursor += 20
                    name = data[cursor:cursor + name_len]
                    cursor += name_len
                    member = name[:-1].decode().replace("\\", "/")
                    if member in remaining:
                        payload = remaining.pop(member)
                        offset, length = out.tell(), payload.stat().st_size
                        write_member(out, payload, name[:-1])
                    entries.append((offset, length, name))
                if remaining:
                    raise ValueError(f"archive is missing members: {', '.join(remaining)}")
                new_table = out.tell()
                for offset, length, name in entries:
                    out.write(struct.pack("<QQI", offset, length, len(name)) + name)
                out.seek(8)
                out.write(struct.pack("<Q", new_table))
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("work/assets/extracted"))
    parser.add_argument("--output", type=Path, default=WORK / "texture-pilot")
    parser.add_argument("--upscaler", type=Path, default=WORK / "tools/realesrgan/realesrgan-ncnn-vulkan")
    parser.add_argument("--match", action="append", metavar="GLOB", help="repeat for reviewed color-map paths")
    parser.add_argument("--list", action="store_true", help="only list matching textures")
    parser.add_argument("--scale", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--max-edge", type=int, default=4096)
    parser.add_argument("--pack-from", type=Path, metavar="PC_ContentPC.sar")
    args = parser.parse_args()
    patterns = args.match or PILOT
    catalog = json.loads((args.source / "manifest.json").read_text())
    selected = sorted({
        entry["path"] for entry in catalog["files"]
        if entry["archive"] == f"{ARCHIVE}.sar"
        and entry["path"].startswith(("Char/", "Environment/"))
        and entry["path"].lower().endswith(".sif")
        and any(fnmatch.fnmatchcase(entry["path"], pattern) for pattern in patterns)
    })
    if not selected:
        parser.error("no character or environment SIF textures matched")
    if args.list:
        print("\n".join(selected))
        return

    replacements = {}
    for member in selected:
        source = args.source / ARCHIVE / safe_member_path(member)
        try:
            replacements[member] = upscale_texture(
                source, args.output, member, args.upscaler.resolve(), args.scale, args.max_edge
            )
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            parser.exit(1, f"{member}: {error}\n")
    if args.pack_from:
        target = args.output / f"{ARCHIVE}.sar"
        repack(args.pack_from, target, replacements)
        print(f"Test archive: {target}")


if __name__ == "__main__":
    main()
