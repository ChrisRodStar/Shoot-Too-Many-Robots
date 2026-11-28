import { watch, type FSWatcher } from 'node:fs';
import path from 'node:path';
import { agentStatusPath, findDecompileRoot } from '@/lib/progress';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const WATCHED = new Set([
  'matched.json',
  'project.json',
  'functions.jsonl',
  'vtables.csv',
  'names_applied.csv',
  'suggested_names.csv',
  'agent-status.json',
]);

export async function GET(request: Request) {
  const root = findDecompileRoot();
  const encoder = new TextEncoder();
  const watchers: FSWatcher[] = [];
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  let heartbeat: ReturnType<typeof setInterval> | undefined;
  let closed = false;

  const cleanup = () => {
    if (closed) return;
    closed = true;
    for (const watcher of watchers) watcher.close();
    watchers.length = 0;
    if (heartbeat) clearInterval(heartbeat);
    try {
      controller?.close();
    } catch {
      // The consumer may already have closed the stream.
    }
  };

  const write = (chunk: string) => {
    if (closed || !controller) return;
    try {
      controller.enqueue(encoder.encode(chunk));
    } catch {
      cleanup();
    }
  };

  const send = (event: string, data: unknown) => {
    write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  };

  const onChange = (_event: string, filename: string | Buffer | null) => {
    const name = filename ? filename.toString() : '';
    if (name && !WATCHED.has(name)) return;
    send('change', { file: name || 'index', at: Date.now() });
  };

  const stream = new ReadableStream<Uint8Array>({
    start(nextController) {
      controller = nextController;

      if (!root) {
        send('ready', { watching: false, reason: 'no-decompile-root' });
      } else {
        send('ready', { watching: true });
        for (const directory of [
          path.join(root, 'config'),
          path.join(root, 'build', 'game'),
          path.dirname(agentStatusPath(root)),
        ]) {
          try {
            watchers.push(watch(directory, { persistent: false }, onChange));
          } catch {
            // The client still polls every 30 seconds if a watch cannot be set up.
          }
        }
      }

      heartbeat = setInterval(() => write(': keepalive\n\n'), 20_000);
      request.signal.addEventListener('abort', cleanup, { once: true });
    },
    cancel() {
      cleanup();
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
