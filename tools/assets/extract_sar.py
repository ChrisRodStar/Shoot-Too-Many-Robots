#!/usr/bin/env python3
"""Extract version 3 Seoul Engine .sar assets used by Shoot Many Robots."""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
import shutil
import struct
import sys
from pathlib import Path, PurePosixPath

SIGNATURE = 0xDA7F
VERSION = 3
DEFAULT_DATA_DIR = Path("work/inputs/installed/app/ShootManyRobots/Data")
LOOSE_ASSET_EXTENSIONS = {".bmp", ".png", ".jpg", ".jpeg", ".gif", ".tga", ".dds", ".sif", ".wav", ".ogg", ".mp3", ".mp4"}


def filename_key(name: bytes) -> int:
    key = 0x54007B47
    for value in name.lower():
        key = (key * 33 + value) & 0xFFFFFFFF
    return key


def decrypt(data: bytes, name: bytes) -> bytes:
    key = filename_key(name)
    stream = bytes(
        ((key >> (8 * (i % 4))) + (i // 4) * 101) & 0xFF
        for i in range(1024)
    )
    return bytes(value ^ stream[i % len(stream)] for i, value in enumerate(data))


def safe_member_path(name: str) -> Path:
    # SAR paths are Windows-style; reject absolute paths and traversal segments.
    normalized = name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if member.is_absolute() or not member.parts or any(p in ("", ".", "..") for p in member.parts):
        raise ValueError(f"unsafe archive path: {name!r}")
    if ":" in member.parts[0]:
        raise ValueError(f"unsafe archive path: {name!r}")
    return Path(*member.parts)


def extract_archive(archive: Path, output: Path) -> list[dict[str, object]]:
    root = output / archive.stem
    root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []

    with archive.open("rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if len(data) < 24:
            raise ValueError(f"{archive}: too small to be a SAR archive")
        signature, version = struct.unpack_from("<II", data, 0)
        if signature != SIGNATURE or version != VERSION:
            raise ValueError(f"{archive}: expected Seoul Engine SAR v3, got signature 0x{signature:04x}, version {version}")

        table_offset = struct.unpack_from("<Q", data, 8)[0]
        entry_count = struct.unpack_from("<I", data, 16)[0]
        if table_offset < 24 or table_offset >= len(data):
            raise ValueError(f"{archive}: invalid file table offset {table_offset}")

        cursor = table_offset
        for index in range(entry_count):
            if cursor + 20 > len(data):
                raise ValueError(f"{archive}: truncated file table at entry {index}")
            offset, size, name_size = struct.unpack_from("<QQI", data, cursor)
            cursor += 20
            if name_size < 2 or name_size > 1_048_576 or cursor + name_size > len(data):
                raise ValueError(f"{archive}: invalid member name length {name_size} at entry {index}")
            raw_name = data[cursor:cursor + name_size]
            cursor += name_size
            if raw_name[-1] != 0:
                raise ValueError(f"{archive}: member name at entry {index} is not NUL terminated")
            name_bytes = bytes(raw_name[:-1])
            name = name_bytes.decode("utf-8", errors="replace")
            if offset + size > len(data):
                raise ValueError(f"{archive}: member {name!r} extends beyond the archive")

            member_path = safe_member_path(name)
            destination = root / member_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            payload = decrypt(bytes(data[offset:offset + size]), name_bytes)
            destination.write_bytes(payload)
            records.append({
                "archive": archive.name,
                "path": member_path.as_posix(),
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            })

    return records


def build_image_previews(records: list[dict[str, object]], output: Path) -> int:
    """Make PNG gallery previews for cooked DDS/SIF textures when Pillow is available."""
    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed; DDS/SIF originals are extracted, but PNG previews were skipped.")
        return 0

    made = 0
    for record in records:
        member = Path(str(record["path"]))
        extension = member.suffix.casefold()
        converted = extension in (".dds", ".sif", ".bmp", ".tga")
        if not converted and extension not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            continue
        source = output / Path(str(record["archive"])).stem / member
        target = output / "__previews__" / Path(str(record["archive"])).stem / (member.as_posix() + ".png")
        try:
            with Image.open(source) as image:
                record["image"] = {
                    "width": image.width,
                    "height": image.height,
                    "format": getattr(image, "pixel_format", None) or image.format,
                }
                if not converted:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                image.seek(0)
                image.thumbnail((512, 512), Image.Resampling.LANCZOS)
                image.convert("RGBA").save(target, format="PNG", optimize=False)
            record["preview"] = target.relative_to(output).as_posix()
            record.pop("preview_error", None)
            made += 1
        except (OSError, ValueError) as error:
            record["preview_error"] = str(error)
    return made


def copy_loose_assets(data_dir: Path, output: Path) -> list[dict[str, object]]:
    records = []
    for source in sorted(data_dir.iterdir()):
        if not source.is_file() or source.suffix.casefold() not in LOOSE_ASSET_EXTENSIONS:
            continue
        destination = output / "Loose" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        payload = destination.read_bytes()
        records.append({
            "archive": "Loose",
            "path": source.name,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help="folder containing the game's .sar bundles")
    parser.add_argument("--output", type=Path, default=Path("work/assets/extracted"),
                        help="destination for extracted members (default: work/assets/extracted)")
    parser.add_argument("--previews-only", action="store_true",
                        help="build PNG previews from a previous extraction without re-reading the archives")
    args = parser.parse_args()
    manifest_path = args.output / "manifest.json"
    if args.previews_only:
        if not manifest_path.exists():
            parser.error(f"no manifest found at {manifest_path}; run a normal extraction first")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        all_records = manifest["files"]
    else:
        archives = sorted(args.data_dir.glob("*.sar"))
        if not archives:
            parser.error(f"no .sar files found in {args.data_dir}")

        all_records = []
        for archive in archives:
            try:
                records = extract_archive(archive, args.output)
            except (OSError, ValueError, struct.error) as error:
                print(f"ERROR {archive.name}: {error}", file=sys.stderr)
                return 1
            all_records.extend(records)
            total = sum(int(record["size"]) for record in records)
            print(f"{archive.name}: extracted {len(records):,} files ({total / 1024 / 1024:.1f} MiB)")
        loose_records = copy_loose_assets(args.data_dir, args.output)
        all_records.extend(loose_records)
        if loose_records:
            print(f"Loose game assets: copied {len(loose_records):,} files")

    preview_count = build_image_previews(all_records, args.output)
    manifest = manifest if args.previews_only else {
        "format": "Shoot Many Robots / Seoul Engine SAR v3",
        "source_directory": os.fspath(args.data_dir.resolve()),
        "files": all_records,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    temporary_manifest = manifest_path.with_suffix(".json.tmp")
    temporary_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary_manifest.replace(manifest_path)
    print(f"Image previews: {preview_count:,} PNGs")
    print(f"Total: {len(all_records):,} files exported to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
