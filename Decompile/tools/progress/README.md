# Decompilation progress dashboard

A local Next.js 16 dashboard for the `Decompile/` matching effort. It reads the
real generated indexes and the byte-verified registry directly, so there is no
second copy of the numbers to drift:

| Input | Used for |
| --- | --- |
| `Decompile/config/matched.json` | verified functions, bytes, kinds, evidence |
| `Decompile/build/game/functions.jsonl` | totals, names, bank membership, decompile status |
| `Decompile/build/game/vtables.csv` | vtable / class / slot counts |
| `Decompile/build/game/names_applied.csv` | vtable-derived labels |
| `Decompile/build/game/suggested_names.csv` | pending name suggestions |
| `Decompile/config/project.json` | game, image, compiler metadata |

No game bytes, assets, or generated C are copied into this app.

> Working on this app as an agent? Read [`AGENTS.md`](AGENTS.md) first — it
> covers the data contract, the live watcher, and the status heartbeat.

## Agent status & handoff

The dashboard shows a **DECOMPILATION AGENT** strip so the user can tell whether
a session is active. It reads `work/dev/agent-status.json` at the repository
root (git-ignored); the app never invents this state.

```json
{
  "state": "working",
  "agent": "OpenCode · model name",
  "task": "Matching bank_0088",
  "detail": "Rebuilding tail thunks and checking relocations.",
  "startedAt": "2026-11-28T09:16:18Z",
  "updatedAt": "2026-11-28T09:16:18Z"
}
```

- `state` is `working`, `idle`, or `blocked`.
- A `working` entry is shown as active for 10 minutes after `updatedAt`, then
  becomes `LAST SEEN`. This prevents a crashed agent from leaving a false
  "working" badge.
- Agents refresh `updatedAt` at least every 5 minutes and set `idle` (or
  `blocked` with a reason) when they stop.
- The strip updates through the same SSE watcher as the registry.

The full agent contract is in [`AGENTS.md`](AGENTS.md). Root
[`AGENTS.md`](../../../AGENTS.md) points sessions here.

## Run it

Generate the tree first if needed (`./Decompile/tools/export.sh game 4`), then:

```sh
npm ci --prefix Decompile/tools/progress
npm --prefix Decompile/tools/progress run dev
```

Open [http://localhost:3000](http://localhost:3000). The server watches
`config/` and `build/game/` and pushes a change event over Server-Sent Events,
so a registry edit or a rewritten index appears in the dashboard within a
second. A 30-second poll remains as a fallback if the live connection drops.
Use **REFRESH** to pull immediately.

The launcher checks ports **3000** and **3001** before starting Next.js and uses
the first free one. If something is already listening on 3000, the dashboard
starts at [http://localhost:3001](http://localhost:3001). To force a port:

```sh
SMR_PROGRESS_PORT=4000 npm --prefix Decompile/tools/progress run dev
```

### What actually updates

The dashboard is a view over completed data, not a stream of compiler output.
It moves when these files change:

- `config/matched.json` — the verified function registry
- `build/game/functions.jsonl` — totals, names, bank membership
- `build/game/vtables.csv`, `names_applied.csv`, `suggested_names.csv`
- `work/dev/agent-status.json` — agent presence strip

Running `verify.py` on its own does **not** modify the registry; it prints
results to stdout. Add the verified entries to `config/matched.json` (or use the
promotion workflow) and the dashboard updates automatically. During a long
`verify.py` run the displayed registry is the one currently on disk.

Set `SMR_DECOMPILE_ROOT` to point at another checkout:

```sh
SMR_DECOMPILE_ROOT=/path/to/Decompile npm --prefix Decompile/tools/progress run dev
```

## What it shows

- Overall byte-exact function coverage, plus the byte share it represents.
- Named-symbol coverage, Ghidra decompile coverage, and registry integrity as
  separate rails so "the tree decompiles" is never confused with "the tree
  matches".
- The verified manifest split by kind (tail thunks, field accessors,
  relocations, leaf checks).
- A 186-cell bank map; select a bank to filter the registry, or use the
  search and kind filters.
- The full verified-function registry with address, size, unit, source file,
  and the evidence note from `config/matched.json`.
- Naming and structure counts: exports/RTTI names, vtable labels, vtable and
  class totals, virtual slots, suggestions, string-bearing functions, call
  edges, and generated C size.
- A **DECOMPILATION AGENT** strip with live/idle/blocked state, current task,
  and heartbeat age.

## JSON endpoint

`GET /api/progress` returns a small machine-readable summary for badges or
external trackers, including the agent heartbeat. It returns `503` with an
expected-file list when the generated tree is missing.
`GET /api/progress/watch` is the Server-Sent Events feed used by the page; it
emits `ready` and `change` events when a watched file is written.

## Stack

Next.js 16 App Router, React 19, TypeScript 7, Tailwind CSS 4 (reset/utilities
only), custom CSS for the terminal treatment, `next/font` for IBM Plex Mono and
VT323. The server component loads and mtime-caches the indexes; a client
`EventSource` refreshes the route when the files change, with a 30-second poll
as a fallback. The registry table filters locally.

`scripts/run.mjs` is the dev/start launcher. It probes ports 3000 and 3001
before spawning Next.js, so `npm run dev` and `npm run start` behave the same
way. Set `SMR_PROGRESS_PORT` to pin a different port.
