#!/usr/bin/env python3
"""Build and catalog a local, mixed-method 2× art batch for Shoot Many Robots."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from subprocess import SubprocessError

from extract_sar import safe_member_path
from upscale_textures import WORK, repack, upscale_texture

DATA = Path("work/inputs/installed/app/ShootManyRobots/Data")
UI_DATA_MAP = re.compile(r"(?:^|_)(?:normal|mask|spec|lut)(?:_|\.|$)", re.I)
SPECIAL_MAP = re.compile(r"(?:_cfm|_spec|_normal|_mask|_lut|_em|damageeffect|darkgradient01)$", re.I)


def character_exclusions():
    path = WORK / "characters-2x/selection.tsv"
    if not path.is_file():
        return {}
    with path.open() as source:
        return {e["path"]: e["reason"] for e in csv.DictReader(source, delimiter="\t") if e["action"] == "skip"}


def plan(entry, exclusions):
    archive = Path(entry["archive"]).stem
    member = entry["path"]
    image = entry["image"]
    path = safe_member_path(member)
    if member in exclusions:
        return "keep", exclusions[member]
    if member in {"Fx/Environment/Weather/Snow.SIF", "Fx/Environment/Weather/Soot.SIF"}:
        return "keep", "weather cubemap"
    if max(image["width"], image["height"]) > 2048:
        return "keep", "already exceeds the 2× batch input limit"
    if SPECIAL_MAP.search(path.stem) or UI_DATA_MAP.search(path.stem):
        return "keep", "shader data or effect map"
    if archive == "PC_UI":
        return "resize", "preserve UI artwork, alpha, and logical layout"
    if archive in ("Loose", "PC_Content"):
        return "resize", "source image upscale"
    if archive != "PC_ContentPC":
        return "keep", "archive outside the art batch"
    if path.parts[0] in ("Char", "Environment", "Maps", "Weapons"):
        return "ai", "wrap-aware color upscale" if "Ground_Tiles" in path.parts else "color texture upscale"
    return "resize", "preserve painted effects, symbols, and atlases"


def existing_texture(archive, path):
    if archive != "PC_ContentPC":
        return None
    for batch in ("characters-2x", "farmland-dirt", "texture-pilot"):
        root = WORK / batch
        texture = root / "textures" / archive / path
        preview = root / "previews" / archive / path.with_suffix(path.suffix + ".png")
        if texture.is_file() and preview.is_file():
            return texture
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extracted", type=Path, default=Path("work/assets/extracted"))
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--output", type=Path, default=WORK / "all-art-2x")
    parser.add_argument("--upscaler", type=Path, default=WORK / "tools/realesrgan/realesrgan-ncnn-vulkan")
    parser.add_argument("--ui-base", type=Path, help="optional PC_UI archive containing the upgraded title screen")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    exclusions = character_exclusions()
    entries = json.loads((args.extracted / "manifest.json").read_text())["files"]
    images = sorted((entry for entry in entries if entry.get("image")),
                    key=lambda entry: (entry["archive"], entry["path"]))
    replacements = defaultdict(dict)
    outcomes = Counter()

    def process(entry, archive, path, method):
        member = entry["path"]
        return upscale_texture(
            args.extracted / archive / path, args.output, member, args.upscaler.resolve(),
            2, 4096, archive=archive, method=method, wrap="Ground_Tiles" in path.parts,
        )

    report = args.output / "inventory.tsv"
    with report.open("w", newline="") as destination, \
            ThreadPoolExecutor(max_workers=1) as gpu, \
            ThreadPoolExecutor(max_workers=3) as cpu:
        writer = csv.writer(destination, delimiter="\t")
        writer.writerow(("archive", "path", "source_width", "source_height", "action", "reason"))

        def record(entry, action, reason):
            image = entry["image"]
            writer.writerow((entry["archive"], entry["path"], image["width"], image["height"], action, reason))
            destination.flush()
            outcomes[action] += 1

        pending = {}
        for entry in images:
            member = entry["path"]
            archive = Path(entry["archive"]).stem
            path = safe_member_path(member)
            method, reason = plan(entry, exclusions)
            if method == "keep":
                record(entry, method, reason)
                continue
            existing = existing_texture(archive, path)
            if existing:
                replacements[archive][member] = existing
                record(entry, "reused", f"existing {existing.parents[len(path.parts) + 1].name} batch")
                continue
            pool = gpu if method == "ai" else cpu
            future = pool.submit(process, entry, archive, path, method)
            pending[future] = (entry, archive, method, reason)

        for future in as_completed(pending):
            entry, archive, method, reason = pending[future]
            try:
                replacements[archive][entry["path"]] = future.result()
            except (OSError, ValueError, SubprocessError) as error:
                record(entry, "kept original", str(error))
                print(f"Kept original {archive}/{entry['path']}: {error}", flush=True)
            else:
                record(entry, method, reason)

    for archive, members in sorted(replacements.items()):
        if archive == "Loose":
            continue
        name = f"{archive}.sar"
        source = args.ui_base if archive == "PC_UI" and args.ui_base else args.data / name
        output = args.output / name
        print(f"Packing {len(members)} replacements into {output}", flush=True)
        repack(source, output, members)
    print(f"Finished {len(images)} images: {dict(outcomes)}", flush=True)


if __name__ == "__main__":
    main()
