#!/usr/bin/env bash
# Download Visual Studio 2008 Express (SP1 + original) and extract the VC9
# compiler and Windows SDK into work/toolchains/msvc9/{sp1,rtm}.
#
#   Decompile/tools/msvc/setup.sh            # both flavors
#   Decompile/tools/msvc/setup.sh sp1        # just SP1
#
# Requires Docker (OrbStack) with linux/386 support and ~4 GB free.
# Microsoft's official ISOs are used; nothing is redistributed by this repo.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
home="${SMR_MSVC_HOME:-$repo/work/toolchains/msvc9}"
isos="${SMR_ISO_DIR:-$repo/work/inputs/toolchains}"
image="${SMR_MSVC_IMAGE:-smr-msvc9}"
want="${1:-all}"

SP1_ISO="VS2008ExpressWithSP1ENUX1504728.iso"
SP1_URL="https://download.microsoft.com/download/E/8/E/E8EEB394-7F42-4963-A2D8-29559B738298/$SP1_ISO"
RTM_ISO="VS2008ExpressENUX1397868.iso"
RTM_URL="https://download.microsoft.com/download/8/B/5/8B5804AD-4990-40D0-A6AA-CE894CBBB3DC/$RTM_ISO"

mkdir -p "$home" "$isos"

download() {
  local url="$1" dest="$isos/$2"
  if [[ -s "$dest" ]]; then
    echo "have $(basename "$dest")"
    return
  fi
  echo "downloading $2 ..."
  curl -L --fail --retry 3 -C - -o "$dest" "$url"
}

if [[ "$want" == "all" || "$want" == "sp1" ]]; then
  download "$SP1_URL" "$SP1_ISO"
fi
if [[ "$want" == "all" || "$want" == "rtm" ]]; then
  download "$RTM_URL" "$RTM_ISO"
fi

echo "building docker image $image ..."
docker build --platform linux/386 -t "$image" "$here" >/dev/null

extract() {
  local flavor="$1" iso="$2" root="$home/$1"
  if [[ -f "$root/VC/bin/cl.exe" ]]; then
    echo "have $flavor/VC/bin/cl.exe"
    return
  fi
  echo "extracting $flavor from $iso ..."
  docker run --rm --platform linux/386 \
    -v "$home:/msvc" -v "$isos:/isos:ro" \
    -e FLAVOR="$flavor" -e ISO="$iso" \
    "$image" -lc '
      set -e
      root="/msvc/$FLAVOR"
      tmp="/msvc/.build-$FLAVOR"
      rm -rf "$tmp"
      mkdir -p "$tmp/iso" "$tmp/ixp" "$tmp/vcx" "$tmp/sdkx" "$tmp/sdko"
      7z x -y -o"$tmp/iso" "/isos/$ISO" VCExpress >/dev/null
      cabextract -q -d "$tmp/ixp" "$tmp/iso/VCExpress/Ixpvc.exe"
      (cd "$tmp/ixp" && msiextract -C "$tmp/vcx" vs_setup.msi >/dev/null)

      V="$tmp/vcx/Program Files/Microsoft Visual Studio 9.0"
      mkdir -p "$root/VC" "$root/SDK"
      cp -r "$V/VC:Vc7/." "$root/VC/"
      for f in mspdb80.dll msobj80.dll mspdbcore.dll mspdbsrv.exe; do
        find "$V/Common7" -iname "$f" -exec cp -n {} "$root/VC/bin/" \; 2>/dev/null || true
      done
      for f in msvcr90.dll msvcp90.dll; do
        p="$(find "$tmp/vcx/Windows" -iname "$f" 2>/dev/null | head -1 || true)"
        [[ -n "$p" ]] && cp -n "$p" "$root/VC/bin/" || true
      done

      if [[ -f "$tmp/iso/VCExpress/WCU/WinSDK/WinSDK_Build.exe" ]]; then
        cabextract -q -d "$tmp/sdkx" "$tmp/iso/VCExpress/WCU/WinSDK/WinSDK_Build.exe"
        (cd "$tmp/sdkx" && msiextract -C "$tmp/sdko" VistaClientHeadersLibs-x86.msi >/dev/null)
        base="$(find "$tmp/sdko" -type d -name "v6.0A*" | head -1)"
        if [[ -n "$base" ]]; then
          cp -r "$base/Include" "$root/SDK/"
          cp -r "$base/Lib" "$root/SDK/"
        fi
      fi
      rm -rf "$tmp"
      echo "done: $root"
    '
}

if [[ "$want" == "all" || "$want" == "sp1" ]]; then
  extract sp1 "$SP1_ISO"
fi
if [[ "$want" == "all" || "$want" == "rtm" ]]; then
  extract rtm "$RTM_ISO"
  # The RTM ISO predates the Vista SDK used by SP1; reuse SP1's if RTM has none.
  if [[ ! -f "$home/rtm/SDK/Include/windows.h" && -f "$home/sp1/SDK/Include/windows.h" ]]; then
    cp -r "$home/sp1/SDK/." "$home/rtm/SDK/"
  fi
fi

echo
echo "toolchains:"
for f in sp1 rtm; do
  if [[ -f "$home/$f/VC/bin/cl.exe" ]]; then
    echo "  $f: $home/$f"
  fi
done
echo
echo "Next: Decompile/tools/msvc/cl.sh   (first run creates the Wine prefix)"
echo "      python3 Decompile/tools/match/verify.py"
