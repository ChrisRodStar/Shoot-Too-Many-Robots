#!/usr/bin/env python3
"""Package the native macOS recomp host as "Shoot Too Many Robots.app".

The bundle is written to work/dist/ (git-ignored). --dev records the live installed tree in
Contents/Resources/dev-env.sh (codesign --strict rejects symlinks that escape the bundle) while
also cloning it into the bundle for inspection; --standalone uses only the in-bundle clone so the
.app can be moved to another Mac. Game Mode is enabled through LSSupportsGameMode and saves live
in ~/Library/Application Support/Shoot Too Many Robots.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work'
RUNTIME = ROOT / 'vendor/macos-runtime'
APP_NAME = 'Shoot Too Many Robots'
BUNDLE_ID = 'com.smr.macos.recomp'
LAUNCHER_NAME = 'ShootTooManyRobots'
HOST_NAME = 'GameHost'

LAUNCHER = r'''#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CONTENTS="$(cd "$HERE/.." && pwd)"
RES="$CONTENTS/Resources"

export FNV_USER_DIR="${FNV_USER_DIR:-$HOME/Library/Application Support/Shoot Too Many Robots}"
mkdir -p "$FNV_USER_DIR"
HAVE_FNV_ROOT="${FNV_ROOT:+1}"
HAVE_VC90="${SMR_VC90_DIRECTORY:+1}"
HAVE_PHYSX="${SMR_PHYSX_DIRECTORY:+1}"
HAVE_D3DX="${SMR_D3DX_DIRECTORY:+1}"
FNV_ROOT="${FNV_ROOT:-$RES/GameData}"
SMR_VC90_DIRECTORY="${SMR_VC90_DIRECTORY:-$RES/vc90}"
SMR_PHYSX_DIRECTORY="${SMR_PHYSX_DIRECTORY:-$RES/GameData/Binaries}"
SMR_D3DX_DIRECTORY="${SMR_D3DX_DIRECTORY:-$RES/d3dx}"
GAME_EXE="$RES/GameData/ShootManyRobots.exe"

# A --dev bundle records the live installed tree so launches read (and write) outside the signed
# bundle; the in-bundle copies are then only a fallback for inspection.
if [ -f "$RES/dev-env.sh" ]; then
    # shellcheck disable=SC1090
    . "$RES/dev-env.sh"
    [ -n "$HAVE_FNV_ROOT" ] || FNV_ROOT="$DEV_GAME_ROOT"
    [ -n "$HAVE_VC90" ] || SMR_VC90_DIRECTORY="$DEV_VC90"
    [ -n "$HAVE_D3DX" ] || SMR_D3DX_DIRECTORY="$DEV_D3DX"
    [ -n "$HAVE_PHYSX" ] || SMR_PHYSX_DIRECTORY="$DEV_GAME_ROOT/Binaries"
    GAME_EXE="$DEV_GAME_EXE"
fi
export FNV_ROOT SMR_VC90_DIRECTORY SMR_PHYSX_DIRECTORY SMR_D3DX_DIRECTORY
export FNV_NO_QOS=1
export SMR_WINDOW=1
unset FNV_HEADLESS

if [ ! -f "$GAME_EXE" ]; then
    GAME_EXE="$RES/ShootManyRobots.exe"
fi
export FNV_FALLBACK_LOG="$FNV_USER_DIR/fallback_entries.txt"
# Run from a writable directory outside the bundle: the fallback interpreter writes
# fallback-*.bin diagnostics relative to the current directory, and a signed bundle must stay
# sealed after launch.
cd "$FNV_USER_DIR"
if [ "$#" -eq 0 ]; then
    exec "$HERE/GameHost" "$GAME_EXE"
fi
exec "$HERE/GameHost" "$@"
'''


def run(cmd, **kwargs):
    subprocess.run(cmd, check=True, **kwargs)


def data_root() -> Path:
    return Path(os.environ.get('SMR_DATA_ROOT') or WORK)


def game_paths():
    data = data_root()
    installed = data / 'installed/app/ShootManyRobots'
    if not installed.is_dir():
        installed = WORK / 'installed/app/ShootManyRobots'
    vc90 = data / 'vc90/dlls'
    if not vc90.is_dir():
        vc90 = WORK / 'vc90/dlls'
    d3dx = data / 'd3dx'
    if not d3dx.is_dir():
        d3dx = WORK / 'd3dx'
    return installed, vc90, d3dx


def host_candidates(release: bool, native: bool):
    """Ordered window-capable host binaries; release/native are preferred when available."""
    dirs = ['window-host-full', 'window-host', 'window-host-full-release', 'window-host-release',
            'startup-host-full', 'startup-host']
    if release:
        dirs.sort(key=lambda name: 0 if name.endswith('-release') else 1)
    names = ['fnv-startup', 'fnv-discovery'] if native else ['fnv-discovery', 'fnv-startup']
    for directory in dirs:
        for name in names:
            candidate = WORK / directory / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                yield candidate


def select_host(release: bool, native: bool) -> Path:
    for candidate in host_candidates(release, native):
        return candidate
    raise SystemExit(
        'package-app: no windowed host binary found.\n'
        '  Build one first: ./scripts/recomp build --full' + (' --release' if release else '') + '\n'
        '  Expected under work/window-host*/ (fnv-discovery or fnv-startup).'
    )


def otool_deps(path: Path):
    lines = subprocess.check_output(['otool', '-L', str(path)], text=True).splitlines()[1:]
    deps = []
    for line in lines:
        dep = line.strip().split(' (', 1)[0]
        if dep:
            deps.append(dep)
    return deps


def otool_rpaths(path: Path):
    lines = subprocess.check_output(['otool', '-l', str(path)], text=True).splitlines()
    rpaths = []
    for index, line in enumerate(lines):
        if 'cmd LC_RPATH' not in line:
            continue
        for follow in lines[index + 1:index + 6]:
            if 'path ' in follow:
                rpath = follow.split('path ', 1)[1].rsplit(' (offset', 1)[0].strip()
                if rpath not in rpaths:
                    rpaths.append(rpath)
                break
    return rpaths


def is_system(dep: str) -> bool:
    return dep.startswith('/usr/lib/') or dep.startswith('/System/')


def unicorn_search_dirs():
    directories = []
    for base in (ROOT / '.venv', Path.home() / '.venv'):
        for lib in base.glob('lib/python*/site-packages/unicorn/lib'):
            directories.append(lib)
    for base in ('/opt/homebrew/opt/unicorn/lib', '/opt/homebrew/lib',
                 '/usr/local/opt/unicorn/lib', '/usr/local/lib'):
        directories.append(Path(base))
    return directories


def resolve_dependency(dep: str, rpaths, search_dirs):
    if dep.startswith('@rpath/'):
        name = dep[len('@rpath/'):]
        for rpath in rpaths:
            if rpath.startswith('@'):
                continue
            candidate = Path(rpath) / name
            if candidate.is_file():
                return Path(os.path.realpath(candidate))
        for directory in search_dirs:
            candidate = Path(directory) / name
            if candidate.is_file():
                return Path(os.path.realpath(candidate))
    elif dep.startswith('@loader_path/'):
        return None
    elif dep.startswith('@executable_path/'):
        return None
    else:
        candidate = Path(dep)
        if candidate.is_file():
            return Path(os.path.realpath(candidate))
    return None


def copy_dylib_closure(host: Path, frameworks: Path):
    """Copy non-system dylibs (notably Unicorn) and rewrite references into Frameworks/."""
    frameworks.mkdir(parents=True, exist_ok=True)
    search_dirs = unicorn_search_dirs()
    host_rpaths = otool_rpaths(host)
    bundled = {}
    queue = [host]
    seen = {Path(os.path.realpath(host))}

    # Collect the dependency closure first so every reference can be rewritten consistently.
    while queue:
        current = queue.pop(0)
        rpaths = host_rpaths if current == host else otool_rpaths(current)
        for dep in otool_deps(current):
            if is_system(dep):
                continue
            target = resolve_dependency(dep, rpaths, search_dirs)
            if target is None:
                if dep.startswith(('@executable_path/', '@loader_path/')):
                    continue
                raise SystemExit(f'package-app: cannot resolve {dep!r} needed by {current}')
            real = Path(os.path.realpath(target))
            if real in seen:
                continue
            seen.add(real)
            name = real.name
            if name in bundled and bundled[name] != real:
                raise SystemExit(f'package-app: dylib basename collision for {name}')
            bundled[name] = real
            queue.append(real)

    if not bundled:
        # Unicorn is commonly linked statically; still strip absolute rpaths (the .venv
        # site-packages path) so the bundle is independent of the build machine.
        for rpath in otool_rpaths(host):
            if not rpath.startswith('@'):
                run(['install_name_tool', '-delete_rpath', rpath, str(host)])
        run(['install_name_tool', '-add_rpath', '@executable_path/../Frameworks', str(host)])
        return []

    copied = []
    for name, real in sorted(bundled.items()):
        destination = frameworks / name
        shutil.copy2(real, destination)
        os.chmod(destination, 0o755)
        run(['install_name_tool', '-id', f'@rpath/{name}', str(destination)])
        for dep in otool_deps(destination):
            if is_system(dep):
                continue
            target = resolve_dependency(dep, otool_rpaths(destination), search_dirs)
            new_ref = f'@loader_path/{target.name}' if target is not None else dep
            if target is not None and dep != new_ref:
                run(['install_name_tool', '-change', dep, new_ref, str(destination)])
        for rpath in otool_rpaths(destination):
            if not rpath.startswith('@'):
                run(['install_name_tool', '-delete_rpath', rpath, str(destination)])
        run(['install_name_tool', '-add_rpath', '@loader_path', str(destination)])
        copied.append(destination)

    for dep in otool_deps(host):
        if is_system(dep):
            continue
        target = resolve_dependency(dep, host_rpaths, search_dirs)
        if target is None:
            continue
        new_ref = f'@executable_path/../Frameworks/{target.name}'
        if dep != new_ref:
            run(['install_name_tool', '-change', dep, new_ref, str(host)])
    for rpath in otool_rpaths(host):
        if not rpath.startswith('@'):
            run(['install_name_tool', '-delete_rpath', rpath, str(host)])
    run(['install_name_tool', '-add_rpath', '@executable_path/../Frameworks', str(host)])

    allowed = ('/usr/lib/', '/System/', '@executable_path/', '@loader_path/', '@rpath/')
    for binary in [host, *copied]:
        for dep in otool_deps(binary):
            if not dep.startswith(allowed):
                raise SystemExit(f'package-app: external reference {dep!r} remains in {binary}')
    return copied


def build_icon(resources: Path):
    source = RUNTIME / 'macos/Assets/AppIcon.png'
    if not source.is_file():
        print(f'package-app: no icon source at {source}; continuing without an icon', file=sys.stderr)
        return False
    sys.path.insert(0, str(RUNTIME / 'tools'))
    try:
        from app_icon import compile_icon
    except ImportError as error:
        print(f'package-app: cannot import app_icon ({error}); continuing without an icon', file=sys.stderr)
        return False
    try:
        with tempfile.TemporaryDirectory() as temp:
            compile_icon(Path(temp), resources, source)
    except (subprocess.CalledProcessError, AssertionError, OSError) as error:
        print(f'package-app: icon generation failed ({error}); continuing without an icon', file=sys.stderr)
        if (resources / 'AppIcon.icns').exists():
            (resources / 'AppIcon.icns').unlink()
        return False
    return (resources / 'AppIcon.icns').is_file()


def clone_tree(source: Path, destination: Path):
    source = source.resolve()
    if destination.exists():
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    result = subprocess.run(['cp', '-cR', str(source), str(destination)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0 or not destination.exists():
        shutil.copytree(source, destination, symlinks=True)


def clone_file(source: Path, destination: Path):
    source = source.resolve()
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    result = subprocess.run(['cp', '-c', str(source), str(destination)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        shutil.copy2(source, destination)


def prune_runtime_diagnostics(root: Path):
    """Drop stale fallback interpreter artifacts copied from the build tree."""
    for pattern in ('fallback-*', 'fallback_entries.txt', 'fallback-instructions.jsonl'):
        for path in root.rglob(pattern):
            if path.is_file():
                path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--release', action='store_true', help='prefer a release host build')
    parser.add_argument('--native', action='store_true', help='prefer fnv-startup (no Unicorn fallback)')
    layout = parser.add_mutually_exclusive_group()
    layout.add_argument('--dev', action='store_true',
                        help='point the launcher at the live installed tree (default); cloned for inspection')
    layout.add_argument('--standalone', action='store_true',
                        help='clone game files into Contents/Resources for a movable app')
    parser.add_argument('--out', type=Path, default=WORK / 'dist', help='output directory')
    args = parser.parse_args()

    installed, vc90, d3dx = game_paths()
    # The game executable shipped with the recomp build is the prepared copy under work/boot
    # (entry-point/import patches applied by the installer); fall back to the pristine install.
    exe = data_root() / 'boot/ShootManyRobots.exe'
    if not exe.is_file():
        exe = installed / 'ShootManyRobots.exe'
    if not exe.is_file():
        exe = installed / 'Binaries/ShootManyRobots.exe'
    if not exe.is_file() or not (installed / 'Data').is_dir():
        raise SystemExit(f'package-app: missing installed game files at {installed}')
    host = select_host(args.release, args.native)
    print(f'package-app: host {host.relative_to(ROOT)}', flush=True)

    app = args.out.resolve() / f'{APP_NAME}.app'
    contents = app / 'Contents'
    macos_dir = contents / 'MacOS'
    resources = contents / 'Resources'
    if app.exists():
        shutil.rmtree(app)
    macos_dir.mkdir(parents=True)
    resources.mkdir(parents=True)

    bundled_host = macos_dir / HOST_NAME
    shutil.copy2(host, bundled_host)
    os.chmod(bundled_host, 0o755)
    dylibs = copy_dylib_closure(bundled_host, contents / 'Frameworks')
    if dylibs:
        print(f'package-app: bundled {len(dylibs)} dylib(s) into Contents/Frameworks', flush=True)

    launcher = macos_dir / LAUNCHER_NAME
    launcher.write_text(LAUNCHER)
    os.chmod(launcher, 0o755)

    if args.standalone:
        clone_tree(installed, resources / 'GameData')
        if vc90.is_dir():
            clone_tree(vc90, resources / 'vc90')
        if d3dx.is_dir():
            clone_tree(d3dx, resources / 'd3dx')
        clone_file(exe, resources / 'ShootManyRobots.exe')
    else:
        # The launcher uses dev-env.sh to read the live installed tree. The in-bundle copies are
        # APFS clones so the signed bundle is still complete and inspectable, but guest writes
        # (fallback diagnostics, config rewrites) land in the original tree, never in the seal.
        clone_tree(installed, resources / 'GameData')
        if vc90.is_dir():
            clone_tree(vc90, resources / 'vc90')
        if d3dx.is_dir():
            clone_tree(d3dx, resources / 'd3dx')
        clone_file(exe, resources / 'ShootManyRobots.exe')
        (resources / 'dev-env.sh').write_text(
            f'DEV_GAME_ROOT={shlex.quote(str(installed.resolve()))}\n'
            f'DEV_VC90={shlex.quote(str(vc90.resolve()))}\n'
            f'DEV_D3DX={shlex.quote(str(d3dx.resolve()))}\n'
            f'DEV_GAME_EXE={shlex.quote(str(exe.resolve()))}\n'
        )

    prune_runtime_diagnostics(resources / 'GameData')
    icon = build_icon(resources)

    info = {
        'CFBundleDevelopmentRegion': 'en',
        'CFBundleExecutable': LAUNCHER_NAME,
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': APP_NAME,
        'CFBundleIdentifier': BUNDLE_ID,
        'CFBundlePackageType': 'APPL',
        'CFBundleVersion': '1',
        'CFBundleShortVersionString': '0.1',
        'CFBundleInfoDictionaryVersion': '6.0',
        'NSHighResolutionCapable': True,
        'LSSupportsGameMode': True,
        'LSApplicationCategoryType': 'public.app-category.action-games',
        'LSMinimumSystemVersion': '14.0',
        'GCSupportedGameControllers': [{'ProfileName': 'ExtendedGamepad'}],
    }
    if icon:
        info['CFBundleIconFile'] = 'AppIcon'
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
    (contents / 'PkgInfo').write_text('APPL????')

    run(['plutil', '-lint', str(contents / 'Info.plist')], stdout=subprocess.DEVNULL)
    run(['codesign', '--force', '--deep', '--sign', '-', str(app)])
    run(['codesign', '--verify', '--deep', '--strict', str(app)])
    print(f'package-app: built {app}', flush=True)
    print(f'package-app: launcher sets FNV_USER_DIR to {Path.home()}/Library/Application Support/{APP_NAME}',
          flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
