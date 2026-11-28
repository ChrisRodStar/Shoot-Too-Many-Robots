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

## Commit your work

**Any agent doing compilation or matching work must commit its tracked changes
before handing back.** Do not leave verified work uncommitted.

1. Run the verifier first:

   ```sh
   python3 Decompile/tools/match/verify.py
   ```

   Every entry in `Decompile/config/matched.json` must pass. If verification
   fails, fix it or report `blocked`; do not commit a broken registry.

2. Stage only the matching work — usually:

   ```sh
   git add AGENTS.md Decompile/README.md Decompile/config/matched.json \
       Decompile/docs Decompile/src/matched Decompile/tools/match
   ```

   Never stage `work/`, generated trees (`Decompile/src/game/`,
   `Decompile/build/`, `Decompile/include/game/`), compiler artifacts
   (`*.obj`, `*.pdb`, `*.ilk`, `*.exp`), or unrelated working-tree changes.
   Leave other agents' untracked work (for example `Decompile/tools/progress/`
   unless the task is the dashboard) out of the commit.

3. Use a descriptive commit message and include the verified result, for
   example:

   ```text
   feat(decompile): match 34 functions in bank_0088

   Registry: 196/196 functions, 1,547 bytes verified with
   MSVC 2008 SP1 (/O2 /MD) and the original release.
   ```

4. After committing, confirm `git status --short` shows no leftover matching
   changes. Update the agent heartbeat to `idle` (or `blocked`) as usual.

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
