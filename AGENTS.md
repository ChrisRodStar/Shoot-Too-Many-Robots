# Agent notes

This repository has two halves:

- The static-recompilation port (`src/`, `vendor/`, `tools/recomp/`) that
  actually runs the game.
- The readable decompilation in [`Decompile/`](Decompile/), which is the source
  of truth for matching progress.

## Before doing decompilation or matching work

- Read [`Decompile/README.md`](Decompile/README.md),
  [`Decompile/docs/STATUS.md`](Decompile/docs/STATUS.md), and
  [`Decompile/docs/MATCHING.md`](Decompile/docs/MATCHING.md).
- A function is only "matched" if it is in `Decompile/config/matched.json` and
  passes `Decompile/tools/match/verify.py`. Never claim otherwise.
- Do not edit generated trees (`Decompile/build/`, `Decompile/src/game/`,
  `Decompile/include/game/`) by hand.

## Tell the user you are active

The decompilation dashboard at `Decompile/tools/progress/` watches
`work/dev/agent-status.json` (git-ignored) and shows a **DECOMPILATION AGENT**
strip.

At the start of a session, write:

```json
{
  "state": "working",
  "agent": "OpenCode · model name",
  "task": "Matching bank_0088",
  "detail": "What you are doing right now.",
  "startedAt": "2026-11-28T09:16:18Z",
  "updatedAt": "2026-11-28T09:16:18Z"
}
```

Refresh `updatedAt` at least every 5 minutes. On finish, set `state` to `idle`
(or `blocked` with a reason). The dashboard expires an unrefreshed `working`
status after 10 minutes, so stale sessions show `LAST SEEN` instead of lying.

## Dashboard work

Read [`Decompile/tools/progress/AGENTS.md`](Decompile/tools/progress/AGENTS.md)
before changing the app. It documents the data contract, the SSE watcher, the
port launcher, and the verification checklist.
