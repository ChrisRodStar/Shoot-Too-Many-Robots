'use client';

import { ArrowDown, MagnifyingGlassMinus, MagnifyingGlassPlus, X } from '@phosphor-icons/react';
import { useEffect, useRef, useState, type PointerEvent } from 'react';
import { categories, formatSize, kinds, type Asset } from '../lib/asset-types';
import { CompareSlider, type Offset } from './compare-slider';

export function assetUrl(asset: Asset, mode: string) {
  return `/api/asset/${asset.id}?view=${mode}`;
}

const fileNotes: Partial<Record<Asset['kind'], string>> = {
  model: 'Cooked Seoul Engine model data.',
  animation: 'Cooked animation data.',
  physics: 'PhysX collision and rig data.',
  effect: 'Compiled shader or effect data.',
  movie: 'Cooked interface movie.',
  audio: 'FMOD sound banks and event data require an FMOD-compatible tool.',
  image: 'Run the extractor with Pillow to preview supported textures.',
};

function TextPreview({ asset }: { asset: Asset }) {
  const [result, setResult] = useState<{ text: string } | { error: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(assetUrl(asset, 'text'), { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('Text preview is unavailable.');
        return response.text();
      })
      .then((text) => setResult({ text }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setResult({ error: error instanceof Error ? error.message : 'Text preview is unavailable.' });
        }
      });
    return () => controller.abort();
  }, [asset]);

  if (!result) return <p>Loading text preview…</p>;
  if ('error' in result) return <p>{result.error}</p>;
  return <pre>{result.text}{asset.size > 65536 && '\n\n… Preview limited to 64 KiB'}</pre>;
}

function FilePreview({ asset }: { asset: Asset }) {
  if (asset.kind === 'text') return <TextPreview asset={asset} />;
  if (asset.kind === 'audio' && asset.preview) {
    return <audio aria-label={asset.name} controls preload="metadata" src={assetUrl(asset, 'preview')} />;
  }
  if (asset.kind === 'video' && asset.preview) {
    return <video aria-label={asset.name} controls preload="metadata" src={assetUrl(asset, 'preview')} />;
  }
  return <p>{fileNotes[asset.kind] ?? 'No inline preview for this file type.'}</p>;
}

const zoomSteps = [1, 1.5, 2, 3, 4, 6, 8];
type ViewMode = 'slider' | 'both' | 'before' | 'after';
const center: Offset = { x: 0, y: 0 };

function limitOffset(offset: Offset, scale: number): Offset {
  const limit = (scale - 1) * 50;
  return {
    x: Math.max(-limit, Math.min(limit, offset.x)),
    y: Math.max(-limit, Math.min(limit, offset.y)),
  };
}

function ImagePane({ label, src, fallback, scale, offset, onPan, onZoom }: {
  label: string;
  src: string;
  fallback?: string;
  scale: number;
  offset: Offset;
  onPan: (offset: Offset) => void;
  onZoom: () => void;
}) {
  const [failed, setFailed] = useState(false);
  const [usingFallback, setUsingFallback] = useState(false);
  const [size, setSize] = useState('');
  const gesture = useRef<{ x: number; y: number; start: Offset; moved: boolean } | null>(null);

  function pointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (!event.isPrimary || event.button !== 0 || scale === 1) return;
    gesture.current = { x: event.clientX, y: event.clientY, start: offset, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function pointerMove(event: PointerEvent<HTMLButtonElement>) {
    const drag = gesture.current;
    if (!drag || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
    const x = event.clientX - drag.x;
    const y = event.clientY - drag.y;
    if (Math.hypot(x, y) > 4) drag.moved = true;
    if (!drag.moved) return;
    const box = event.currentTarget.getBoundingClientRect();
    onPan({ x: drag.start.x + (x / box.width) * 100, y: drag.start.y + (y / box.height) * 100 });
  }

  return (
    <figure className="detail-pane grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)]">
      <figcaption className="flex min-h-8 items-center justify-between gap-2 px-3 text-xs">
        <span>{label}</span>
        <span className="detail-muted font-mono">{size}{usingFallback ? ' · preview' : ''}</span>
      </figcaption>
      {failed ? <div className="grid place-items-center p-4">Image preview unavailable.</div> : (
        <button type="button" className="detail-canvas checker relative min-h-0 w-full overflow-hidden"
          aria-label={`Zoom ${label.toLowerCase()} image`}
          data-zoomed={scale > 1}
          onPointerDown={pointerDown}
          onPointerMove={pointerMove}
          onPointerCancel={() => { gesture.current = null; }}
          onClick={(event) => {
            if (event.detail === 0 || !gesture.current?.moved) onZoom();
            gesture.current = null;
          }}>
          <img src={usingFallback ? fallback : src} alt={label} draggable={false}
            className="pointer-events-none absolute inset-0 h-full w-full select-none object-contain"
            style={{ transform: `translate(${offset.x}%, ${offset.y}%) scale(${scale})` }}
            onLoad={(event) => {
              const { naturalWidth, naturalHeight } = event.currentTarget;
              setSize(`${naturalWidth} × ${naturalHeight}`);
            }}
            onError={() => {
              if (fallback && !usingFallback) setUsingFallback(true);
              else setFailed(true);
            }} />
        </button>
      )}
    </figure>
  );
}

export function AssetDetail({ asset, batches, splash, onClose }: {
  asset: Asset;
  batches: string[];
  splash: boolean;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [selectedBatch, setSelectedBatch] = useState<string>();
  const batch = selectedBatch && batches.includes(selectedBatch) ? selectedBatch : batches[0];
  const [mode, setMode] = useState<ViewMode>('slider');
  const [zoomIndex, setZoomIndex] = useState(0);
  const [offset, setOffset] = useState<Offset>(center);
  const scale = zoomSteps[zoomIndex];
  const image = asset.kind === 'image' && Boolean(asset.preview);
  const comparison = image && (splash || Boolean(batch));
  const original = assetUrl(asset, 'preview');
  const after = splash ? '/compare/splash/master' : batch
    ? `${assetUrl(asset, 'after')}&batch=${encodeURIComponent(batch)}`
    : undefined;
  const before = splash ? '/compare/splash/original' : batch
    ? `${assetUrl(asset, 'before')}&batch=${encodeURIComponent(batch)}`
    : original;

  useEffect(() => { ref.current?.showModal(); }, []);

  function setZoom(index: number) {
    const next = Math.max(0, Math.min(index, zoomSteps.length - 1));
    setZoomIndex(next);
    setOffset((value) => limitOffset(value, zoomSteps[next]));
  }

  const pan = (next: Offset) => setOffset(limitOffset(next, scale));
  const zoom = () => setZoom(zoomIndex === zoomSteps.length - 1 ? 0 : zoomIndex + 1);

  return (
    <dialog ref={ref} className="asset-detail" aria-labelledby="detail-title" onClose={onClose}
      onKeyDown={(event) => {
        if (!image || event.target instanceof HTMLSelectElement) return;
        if (event.key === '+' || event.key === '=') setZoom(zoomIndex + 1);
        if (event.key === '-') setZoom(zoomIndex - 1);
        if (event.key === '0') setZoom(0);
        const arrows: Partial<Record<string, Offset>> = {
          ArrowLeft: { x: 8, y: 0 }, ArrowRight: { x: -8, y: 0 },
          ArrowUp: { x: 0, y: 8 }, ArrowDown: { x: 0, y: -8 },
        };
        const direction = arrows[event.key];
        if (direction && scale > 1) {
          event.preventDefault();
          pan({ x: offset.x + direction.x, y: offset.y + direction.y });
        }
      }}>
      <div className="detail-shell grid h-full min-h-0 grid-rows-[auto_auto_minmax(0,1fr)_auto]">
        <header className="detail-header flex min-w-0 items-start justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="min-w-0">
            <h2 id="detail-title" className="truncate text-lg font-semibold tracking-tight sm:text-xl" title={asset.name}>{asset.name}</h2>
            <p className="detail-muted mt-1 truncate font-mono text-xs" title={asset.path}>{asset.path}</p>
          </div>
          <button type="button" className="detail-control shrink-0" aria-label="Close asset" onClick={() => ref.current?.close()} autoFocus><X size={19} /></button>
        </header>
        {image ? (
          <div className="detail-toolbar flex flex-wrap items-center justify-between gap-2 px-4 py-2 sm:px-6">
            {comparison && (
              <div className="flex items-center gap-1" role="group" aria-label="Comparison display">
                {([['slider', 'Slider'], ['both', 'Side by side'], ['before', 'Before'], ['after', 'After']] as const).map(([value, label]) => (
                  <button key={value} type="button" className="detail-control" aria-pressed={mode === value} onClick={() => setMode(value)}>{label}</button>
                ))}
              </div>
            )}
            {batches.length > 1 && (
              <select aria-label="Upscale batch" value={batch} onChange={(event) => setSelectedBatch(event.target.value)}>
                {batches.map((name) => <option key={name}>{name}</option>)}
              </select>
            )}
            <div className="flex items-center gap-1" role="group" aria-label="Zoom controls">
              <button type="button" className="detail-control" aria-label="Zoom out" disabled={zoomIndex === 0} onClick={() => setZoom(zoomIndex - 1)}><MagnifyingGlassMinus size={17} /></button>
              <button type="button" className="detail-control min-w-13 font-mono" aria-label="Fit images" onClick={() => setZoom(0)}>{zoomIndex ? `${scale * 100}%` : 'Fit'}</button>
              <button type="button" className="detail-control" aria-label="Zoom in" disabled={zoomIndex === zoomSteps.length - 1} onClick={() => setZoom(zoomIndex + 1)}><MagnifyingGlassPlus size={17} /></button>
              <span className="detail-muted ml-2 hidden text-xs sm:inline">
                {comparison && mode === 'slider' ? 'Drag the divider · Click to zoom' : 'Click to zoom · Drag to pan'}
              </span>
            </div>
          </div>
        ) : <div />}
        {image ? (
          comparison && after && mode === 'slider' ? (
            <div className="detail-images grid min-h-0 grid-cols-1 gap-2 p-2 sm:gap-3 sm:p-3">
              <figure className="detail-pane grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)]">
                <figcaption className="flex min-h-8 items-center justify-between gap-2 px-3 text-xs">
                  <span>{splash ? 'Startup splash' : 'Upscale'}</span>
                  <span className="detail-muted font-mono">Original left · new right</span>
                </figcaption>
                <CompareSlider before={before} after={after}
                  beforeLabel={splash ? 'Original' : 'Before'} afterLabel={splash ? 'Generated' : 'After'}
                  scale={scale} offset={offset} onPan={pan} onZoom={zoom} />
              </figure>
            </div>
          ) : (
            <div className={`detail-images grid min-h-0 gap-2 p-2 sm:gap-3 sm:p-3 ${comparison && mode === 'both' ? 'grid-cols-2' : 'grid-cols-1'}`}>
              {(!comparison || mode !== 'after') && (
                <ImagePane key={before} label={comparison ? 'Before' : 'Original'} src={before}
                  fallback={before === original ? undefined : original} scale={scale} offset={offset} onPan={pan} onZoom={zoom} />
              )}
              {comparison && after && mode !== 'before' && (
                <ImagePane key={after} label="After" src={after} scale={scale} offset={offset} onPan={pan} onZoom={zoom} />
              )}
            </div>
          )
        ) : <div className="detail-media grid min-h-0 place-items-center overflow-auto p-4"><FilePreview asset={asset} /></div>}
        <footer className="detail-footer flex flex-wrap items-center justify-between gap-2 px-4 py-2 sm:px-6">
          <p className="detail-muted text-xs">{categories[asset.category]} · {asset.image?.format ?? kinds[asset.kind]} · {formatSize(asset.size)}</p>
          <div className="flex flex-wrap gap-2">
            <a className="detail-control" href={assetUrl(asset, 'download')} download={asset.name}><ArrowDown size={15} /> Save original</a>
            {after && <a className="detail-control" href={after} download={asset.name + '.png'}>Save upscaled PNG</a>}
            {splash && <a className="detail-control" href="/compare/splash/new" download="shoot-many-robots-remaster-4k.bmp">Save 4K BMP</a>}
            {!after && asset.preview === 'png' && <a className="detail-control" href={original} download={asset.name + '.png'}>Save PNG preview</a>}
          </div>
        </footer>
      </div>
    </dialog>
  );
}
