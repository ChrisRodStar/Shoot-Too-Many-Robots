# Agent guide — decompilation progress dashboard

This file is for an AI agent working in this repository, especially one doing
decompilation or matching work. It explains how to tell the user that you are
active, and how the progress dashboard gets its numbers.

## Read first

- [`../../README.md`](../../README.md) — the decompilation project and its limits
- [`../../docs/STATUS.md`](../../docs/STATUS.md) — current coverage and known gaps
- [`../../docs/MATCHING.md`](../../docs/MATCHING.md) — the byte-exact workflow
- [`../../docs/ROADMAP.md`](../../docs/ROADMAP.md) — the next milestones

## What this app is

A local Next.js 16 dashboard. It reads completed indexes; it is not a compiler
service and it does not execute or stream matching jobs. The only definition of
"matched" is an entry in `../../config/matched.json` that passes
`tools/match/verify.py`.

Data paths:

| Path | Meaning |
| --- | --- |
| `../../config/matched.json` | Verified registry: address, size, symbol, source, kind, note |
| `../../build/game/functions.jsonl` | All `.text` functions, names, banks, calls, strings |
| `../../build/game/vtables.csv` | RTTI vtable/class/slot counts |
| `../../build/game/names_applied.csv` | Vtable-derived labels |
| `../../build/game/suggested_names.csv` | Pending name suggestions |
| `../../config/project.json` | Image and toolchain metadata |
| `work/dev/agent-status.json` (repo root) | Agent presence heartbeat; **git-ignored** |

Never fabricate progress. If a function is not in the registry and verified, it
is not matched.

## Agent status heartbeat — required

The dashboard displays `work/dev/agent-status.json` as a
**DECOMPILATION AGENT** strip, so the user can see whether an agent is working.
Write it relative to the repository root (not this directory).

Start of a session:

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

Rules:

- `state` is `working`, `idle`, or `blocked`.
- Refresh `updatedAt` at least every 5 minutes during a long run. The dashboard
  treats a working status as active only for **10 minutes**; after that it shows
  `LAST SEEN`, so a crashed session cannot leave a false "working" badge.
- When done, set `state: "idle"`, keep the last `task`, and update `updatedAt`.
- If waiting on the user or a tool, use `"blocked"` and put the reason in
  `detail`.
- Do not claim a task you are not actually running in `task`/`detail`.

This file lives under `work/`, which is git-ignored. Do not commit it.

## How live updates work

- The server component `src/lib/progress.ts` reads the indexes and caches by
  mtime.
- `src/app/api/progress/watch/route.ts` watches `config/`, `build/game/`, and
  `work/dev/` with `fs.watch` and emits Server-Sent Events.
- `src/app/live-refresh.tsx` opens the `EventSource`, debounces a
  `router.refresh()`, and keeps a 30-second poll as a fallback.
- The topbar shows `LIVE WATCH` while connected, `POLL 30S` otherwise.
- Editing the registry or indexes updates the page within about a second; no
  restart or rebuild needed.

If you add a new source file that should trigger a refresh, update **both** the
mtime cache list in `src/lib/progress.ts` and the `WATCHED` set/directories in
`src/app/api/progress/watch/route.ts`.

## Architecture map

| File | Role |
| --- | --- |
| `src/app/page.tsx` | Server-rendered layout, coverage meters, agent strip, naming stats |
| `src/app/explorer.tsx` | Client bank map, registry filters/search/table |
| `src/lib/progress.ts` | Filesystem loader, types, mtime cache, agent status reader |
| `src/app/live-refresh.tsx` | SSE client, fallback polling, manual refresh |
| `src/app/api/progress/route.ts` | Summary JSON (`/api/progress`) |
| `src/app/api/progress/watch/route.ts` | SSE feed (`/api/progress/watch`) |
| `src/app/globals.css` | Terminal theme, layout, responsive rules |
| `scripts/run.mjs` | Port launcher: 3000, then 3001 |
| `README.md` | Human setup and data contract |

## Run and verify

```sh
npm ci --prefix Decompile/tools/progress
npm --prefix Decompile/tools/progress run dev
```

The launcher uses `localhost:3000`, falling back to `localhost:3001` if 3000 is
already serving. Do not kill another project's listener to free 3000; the
fallback exists for that case. `SMR_PROGRESS_PORT` pins a port.

Before handing back:

```sh
npm --prefix Decompile/tools/progress run typecheck
npm --prefix Decompile/tools/progress run build
```

Smoke checks:

```sh
curl -s http://localhost:3001/api/progress
curl -N http://localhost:3001/api/progress/watch   # should emit ready
```

## Rules

- No game bytes, assets, or executable content in this app.
- Do not edit generated files under `build/` or `src/game/` by hand.
- No fake numbers, placeholder metrics, or "matched" entries that were not
  verified.
- Keep the page useful at the current early stage: the coverage bar is a sliver;
  the bank map and registry carry the detail.
- Preserve `force-dynamic`, `no-store`, and the SSE headers.
- Do not commit `node_modules/`, `.next/`, `work/`, or other generated output.
