#!/usr/bin/env bash
# Run Visual C++ 2008 (cl 15.00) under Wine in the smr-msvc9 container.
#
# The first run initializes a 32-bit Wine prefix in
# work/toolchains/msvc9/wine. Arguments are passed to cl.exe unchanged.
#
#   Decompile/tools/msvc/cl.sh /nologo /c /TC /O2 /Fotest.obj test.c
#
# Environment:
#   SMR_MSVC_HOME   extracted toolchain root (default work/toolchains/msvc9)
#   SMR_MSVC_FLAVOR sp1 or rtm (default sp1)
#   SMR_MSVC_IMAGE  docker image (default smr-msvc9)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
home="${SMR_MSVC_HOME:-$repo/work/toolchains/msvc9}"
flavor="${SMR_MSVC_FLAVOR:-sp1}"
image="${SMR_MSVC_IMAGE:-smr-msvc9}"
root="$home/$flavor"

if [[ ! -f "$root/VC/bin/cl.exe" ]]; then
  echo "error: $root/VC/bin/cl.exe not found; run Decompile/tools/msvc/setup.sh" >&2
  exit 1
fi
if ! docker image inspect "$image" >/dev/null 2>&1; then
  echo "error: docker image $image missing; run Decompile/tools/msvc/setup.sh" >&2
  exit 1
fi
if [[ ! -d "$home/wine/drive_c" ]]; then
  echo "initializing 32-bit Wine prefix in $home/wine ..." >&2
  mkdir -p "$home/wine"
  docker run --rm --platform linux/386 \
    -v "$home:/msvc" \
    -e WINEPREFIX=/msvc/wine -e WINEARCH=win32 -e WINEDEBUG=-all \
    "$image" -lc 'wineboot -i >/dev/null 2>&1' || true
fi

# Windows paths as Wine sees them: the toolchain is mounted at /msvc.
win_root="Z:\\msvc\\$flavor"
export INCLUDE="$win_root\\VC\\include;${win_root}\\SDK\\Include"
export LIB="$win_root\\VC\\lib;${win_root}\\SDK\\Lib"

if [[ "$PWD" != "$repo" && "$PWD" != "$repo"/* ]]; then
  echo "error: run from inside the repository ($repo)" >&2
  exit 1
fi
cwd_rel="${PWD#"$repo"}"
workdir="/work${cwd_rel}"

args=()
for a in "$@"; do
  # Convert absolute host paths under the repo to container paths.
  if [[ "$a" == "$repo"/* ]]; then
    a="Z:\\work\\${a#"$repo"/}"
    a="${a//\//\\}"
  fi
  args+=("$a")
done

docker run --rm --platform linux/386 \
  -v "$home:/msvc" \
  -v "$repo:/work" \
  -w "$workdir" \
  -e WINEPREFIX=/msvc/wine -e WINEARCH=win32 -e WINEDEBUG=-all \
  -e INCLUDE="$INCLUDE" -e LIB="$LIB" \
  "$image" -lc 'wine "'"$win_root"'\\VC\\bin\\cl.exe" "$@"' -- ${args[@]+"${args[@]}"}
