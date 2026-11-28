#!/usr/bin/env bash
# Decompile a program with the Ghidra project built by the parent repo and
# write a browsable C tree under Decompile/src/.
#
# Usage:
#   Decompile/tools/export.sh [module] [jobs]
#
# Environment overrides:
#   SMR_GHIDRA_PROJECT   default <repo>/work/ghidra/game
#   SMR_PROJECT_NAME     default smr
#   SMR_PROGRAM          default ShootManyRobots.exe
#   SMR_OUT              default <repo>/Decompile
#   SMR_BANK_SIZE        default 250
#   SMR_LIMIT            default 0 (all functions)
#   SMR_CODE_BLOCK       default .text (use * to include .bind packer stubs)
#
# The export is resume-safe: delete Decompile/src/<module> and
# Decompile/build/<module> to force a full re-decompile.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
module="${1:-game}"
jobs="${2:-4}"

project="${SMR_GHIDRA_PROJECT:-$root/work/ghidra/game}"
project_name="${SMR_PROJECT_NAME:-smr}"
program="${SMR_PROGRAM:-ShootManyRobots.exe}"
out="${SMR_OUT:-$root/Decompile}"
bank_size="${SMR_BANK_SIZE:-250}"
limit="${SMR_LIMIT:-0}"
code_block="${SMR_CODE_BLOCK:-.text}"

export JAVA_HOME="${JAVA_HOME:-$(brew --prefix openjdk@25)/libexec/openjdk.jdk/Contents/Home}"
headless="$(brew --prefix ghidra)/libexec/support/analyzeHeadless"

if [[ ! -x "$headless" ]]; then
  echo "error: analyzeHeadless not found; brew install ghidra" >&2
  exit 1
fi
if [[ ! -d "$project" ]]; then
  echo "error: Ghidra project not found: $project" >&2
  exit 1
fi

mkdir -p "$out/share/export-logs"
script_path="$here/ghidra"

# Ghidra takes an exclusive project lock even for read-only consumers, so
# parallel shards need their own (APFS-cloned, copy-on-write) project copy.
clone_project() {
  local k="$1"
  local dir="$out/share/ghidra-shards/shard${k}"
  rm -rf "$dir"
  mkdir -p "$dir"
  touch "$dir/${project_name}.gpr"
  cp "$project/${project_name}.gpr" "$dir/" 2>/dev/null || true
  if cp -cR "$project/${project_name}.rep" "$dir/" 2>/dev/null; then
    : # APFS clone
  else
    cp -R "$project/${project_name}.rep" "$dir/"
  fi
  echo "$dir"
}

run_shard() {
  local k="$1"
  local n="$2"
  local proj="$3"
  local log="$out/share/export-logs/${module}-shard-${k}-of-${n}.log"
  echo "== shard $k/$n -> $log"
  "$headless" "$proj" "$project_name" -process "$program" -noanalysis -readOnly \
    -scriptPath "$script_path" \
    -postScript ExportTree.java "$out" "$module" "$bank_size" "$limit" "$k" "$n" "$code_block" \
    >"$log" 2>&1
  if ! grep -q "ExportTree\[" "$log"; then
    echo "error: shard $k produced no summary; tail:" >&2
    tail -20 "$log" >&2
    return 1
  fi
  tail -2 "$log" | sed 's/^/   /'
}

if [[ "$jobs" -le 1 ]]; then
  run_shard 0 1 "$project"
else
  pids=()
  for ((k = 0; k < jobs; k++)); do
    clone="$(clone_project "$k")"
    run_shard "$k" "$jobs" "$clone" &
    pids+=("$!")
  done
  status=0
  for p in "${pids[@]}"; do
    wait "$p" || status=1
  done
  rm -rf "$out/share/ghidra-shards"
  [[ "$status" -eq 0 ]] || exit "$status"
  # A full single-shard pass skips finished banks and regenerates the merged
  # indexes (functions.jsonl, symbols.csv, prototypes.h, strings.tsv).
  run_shard 0 1 "$project"
fi

echo
echo "decompiled tree: $out/src/$module"
echo "indexes:         $out/build/$module"
