'use client';

import { useCallback, useEffect, useRef, useState, useTransition } from 'react';
import { useRouter } from 'next/navigation';

export function LiveRefresh() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [watching, setWatching] = useState(false);
  const pendingRefresh = useRef<number | undefined>(undefined);

  const refresh = useCallback(() => {
    startTransition(() => router.refresh());
  }, [router, startTransition]);

  useEffect(() => {
    const source = new EventSource('/api/progress/watch');

    const onReady = () => setWatching(true);
    const onError = () => setWatching(false);
    const onChange = () => {
      window.clearTimeout(pendingRefresh.current);
      pendingRefresh.current = window.setTimeout(refresh, 250);
    };

    source.addEventListener('open', onReady);
    source.addEventListener('ready', onReady);
    source.addEventListener('error', onError);
    source.addEventListener('change', onChange);

    // Fallback in case EventSource is unavailable or the watcher cannot start.
    const poll = window.setInterval(refresh, 30_000);

    return () => {
      source.removeEventListener('open', onReady);
      source.removeEventListener('ready', onReady);
      source.removeEventListener('error', onError);
      source.removeEventListener('change', onChange);
      source.close();
      window.clearInterval(poll);
      window.clearTimeout(pendingRefresh.current);
    };
  }, [refresh]);

  return (
    <span className="refresh-control">
      <span className={`live-status${watching ? ' is-live' : ''}`}>
        <span className="status-dot" aria-hidden="true" />
        {watching ? 'LIVE WATCH' : 'POLL 30S'}
      </span>
      <button
        type="button"
        className="refresh-button"
        onClick={refresh}
        disabled={isPending}
        aria-label="Refresh decompilation progress now"
      >
        {isPending ? 'SYNCING…' : 'REFRESH'}
      </button>
    </span>
  );
}
