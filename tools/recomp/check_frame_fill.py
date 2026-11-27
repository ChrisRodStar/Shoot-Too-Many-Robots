#!/usr/bin/env python3
"""Check that a dumped gameplay frame actually fills its output area.

The guest renders into its own backbuffer (the tutorial resets to 1024x768) and the
Metal presenter scales that into the window drawable.  A regression where Reset does
not resize the backbuffer leaves the image squashed into a sub-rectangle with black
bars (e.g. 820 px of a 1024 px frame), which is easy to see but not obvious in a log.

This tool reads the newest ``frame_*.png`` in a frame-dump directory, finds the
bounding box of non-black pixels and asserts:

  * horizontal fill  - the image reaches both edges (letterboxing on the left/right
    means the guest aspect no longer matches the output and the frame is wasted);
  * vertical coverage - the visible span is at least 65% of the height, which still
    allows for 16:9 content in a 4:3 frame or a cutscene letterbox, and fails for
    the old squashed 0.80-wide/centered render.

Exit status is 0 on success, 1 on a failed check, 2 when no frame can be read.

Examples:

    .venv/bin/python tools/recomp/check_frame_fill.py
    .venv/bin/python tools/recomp/check_frame_fill.py work/boot/window-full-frames
    .venv/bin/python tools/recomp/check_frame_fill.py --frame frame_2400.png
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def read_png(path: Path) -> tuple[int, int, int, bytearray]:
    """Decode a non-interlaced 8-bit PNG. Returns (width, height, channels, pixels)."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos = 8
    width = height = depth = color = interlace = None
    palette = None
    idat = bytearray()
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, depth, color, comp, filt, interlace = struct.unpack(">IIBBBBB", body)
            if comp != 0 or filt != 0:
                raise ValueError("unsupported PNG compression/filter method")
            if interlace != 0:
                raise ValueError("interlaced PNGs are not supported")
            if depth != 8:
                raise ValueError(f"unsupported bit depth {depth}")
        elif tag == b"PLTE":
            palette = body
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
    if width is None or color not in CHANNELS:
        raise ValueError("unsupported PNG (missing IHDR or color type)")

    channels = CHANNELS[color]
    if color == 3 and palette is None:
        raise ValueError("indexed PNG without palette")
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    pixels = bytearray(width * height * channels)
    prev = bytearray(stride)
    src = 0
    bpp = channels
    for y in range(height):
        if src + 1 + stride > len(raw):
            raise ValueError("truncated PNG data")
        ftype = raw[src]
        src += 1
        line = bytearray(raw[src:src + stride])
        src += stride
        if ftype == 1:                      # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:                    # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:                    # Average
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:                    # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa = abs(b - c)
                pb = abs(a - c)
                pc = abs(a + b - 2 * c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        elif ftype != 0:
            raise ValueError(f"unknown PNG filter {ftype}")
        pixels[y * stride:(y + 1) * stride] = line
        prev = line

    if color == 3:                          # expand palette to RGB
        rgb = bytearray(width * height * 3)
        for i, index in enumerate(pixels):
            base = index * 3
            rgb[i * 3:i * 3 + 3] = palette[base:base + 3]
        return width, height, 3, rgb
    if color == 0:                          # grayscale -> RGB
        rgb = bytearray(width * height * 3)
        for i, value in enumerate(pixels):
            rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = value
        return width, height, 3, rgb
    return width, height, channels, pixels


def bbox(width: int, height: int, channels: int, pixels: bytearray, threshold: int):
    """Bounding box of pixels with any of r/g/b above threshold."""
    min_x, min_y, max_x, max_y = width, height, -1, -1
    stride = width * channels
    for y in range(height):
        row = y * stride
        first = last = -1
        for x in range(width):
            base = row + x * channels
            if pixels[base] > threshold or pixels[base + 1] > threshold or pixels[base + 2] > threshold:
                if first < 0:
                    first = x
                last = x
        if first < 0:
            continue
        if y < min_y:
            min_y = y
        max_y = y
        if first < min_x:
            min_x = first
        if last > max_x:
            max_x = last
    return min_x, min_y, max_x, max_y


def frame_number(path: Path) -> int:
    stem = path.stem
    if stem.startswith("frame_") and stem[6:].isdigit():
        return int(stem[6:])
    return -1


def pick_latest(frames_dir: Path) -> Path | None:
    frames = [p for p in frames_dir.glob("frame_*.png") if p.is_file()]
    if not frames:
        return None
    # Newest write wins (so stale frames from an earlier run are ignored); frame number breaks ties.
    return max(frames, key=lambda p: (p.stat().st_mtime, frame_number(p)))


def describe_aspect(width: int, height: int, span_w: int, span_h: int) -> str:
    frame_aspect = width / height
    content_aspect = span_w / span_h if span_h else 0.0
    known = {
        4 / 3: "4:3 full frame",
        16 / 9: "16:9 widescreen",
        16 / 10: "16:10",
        21 / 9: "21:9 ultrawide",
    }
    label = None
    for aspect, name in known.items():
        if abs(frame_aspect - aspect) < 0.02:
            label = name
            break
    frame_name = label or f"{frame_aspect:.3f}:1"
    return f"frame {frame_name}, content {content_aspect:.3f}:1"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_frame_fill.py",
        description="Assert a dumped frame fills its output width and most of its height.",
    )
    parser.add_argument("frames_dir", nargs="?", default="work/boot/window-full-frames",
                        help="frame dump directory (default: work/boot/window-full-frames)")
    parser.add_argument("--frame", help="specific PNG to check instead of the newest frame_*.png")
    parser.add_argument("--threshold", type=int, default=5,
                        help="a pixel counts as image when r/g/b exceeds this (default: 5)")
    parser.add_argument("--min-coverage", type=float, default=0.65,
                        help="minimum fraction of the frame height the image must span (default: 0.65)")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    if args.frame:
        path = Path(args.frame)
        if not path.is_absolute():
            inside = root / path
            path = inside if inside.is_file() else Path.cwd() / path
    else:
        frames_dir = Path(args.frames_dir)
        if not frames_dir.is_absolute():
            frames_dir = root / frames_dir
        if not frames_dir.is_dir():
            print(f"FAIL: frame directory not found: {frames_dir}", file=sys.stderr)
            return 2
        path = pick_latest(frames_dir)
        if path is None:
            print(f"FAIL: no frame_*.png under {frames_dir}", file=sys.stderr)
            return 2

    if not path.is_file():
        print(f"FAIL: frame not found: {path}", file=sys.stderr)
        return 2

    try:
        width, height, channels, pixels = read_png(path)
    except (OSError, ValueError, zlib.error) as exc:
        print(f"FAIL: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    min_x, min_y, max_x, max_y = bbox(width, height, channels, pixels, args.threshold)
    print(f"file       {path}")
    print(f"size       {width}x{height} ({channels} channels)")
    if max_x < 0:
        print("FAIL: frame is entirely black", file=sys.stderr)
        return 1

    span_w = max_x - min_x + 1
    span_h = max_y - min_y + 1
    coverage = span_h / height
    print(f"bbox       x=[{min_x}..{max_x}] y=[{min_y}..{max_y}] "
          f"(span {span_w}x{span_h})")
    print(f"aspect     {describe_aspect(width, height, span_w, span_h)}")

    ok = True
    if min_x <= 2 and max_x >= width - 3:
        print(f"fill       OK  left={min_x} (<=2), right={max_x} (>= {width - 3})")
    else:
        ok = False
        print(f"fill       FAIL left={min_x} (need <=2), right={max_x} (need >= {width - 3}); "
              f"{width - span_w} px unused horizontally")

    if coverage >= args.min_coverage:
        print(f"coverage   OK  {span_h}/{height} = {coverage * 100:.1f}% "
              f"(>= {args.min_coverage * 100:.0f}%)")
    else:
        ok = False
        print(f"coverage   FAIL {span_h}/{height} = {coverage * 100:.1f}% "
              f"(< {args.min_coverage * 100:.0f}%)")

    # A frame that is wide-but-short (or narrow-but-tall) usually means the aspect fit
    # letterboxed instead of the guest backbuffer matching the drawable. Report the bars.
    frame_aspect = width / height
    content_aspect = span_w / span_h
    if abs(frame_aspect - content_aspect) > 0.02:
        if span_h < height:
            bar = (height - span_h) / 2
            print(f"note       aspect-fit bars: ~{bar:.0f} px top/bottom (cutscene or widescreen)")
        if span_w < width:
            bar = (width - span_w) / 2
            print(f"note       aspect-fit bars: ~{bar:.0f} px left/right")

    if ok:
        print("PASS: frame fills the output horizontally and has active vertical coverage")
        return 0
    print("FAIL: frame does not fill the output", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
