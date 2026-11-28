'use client';

import { CaretLeft, CaretRight } from '@phosphor-icons/react';
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

export type Offset = { x: number; y: number };

type Gesture = {
  mode: 'split' | 'pan' | 'handle';
  x: number;
  y: number;
  startOffset: Offset;
  moved: boolean;
};

const clampSplit = (value: number) => Math.max(0, Math.min(100, value));

export function CompareSlider({
  before,
  after,
  beforeLabel = 'Before',
  afterLabel = 'After',
  scale = 1,
  offset = { x: 0, y: 0 },
  onPan,
  onZoom,
}: {
  before: string;
  after: string;
  beforeLabel?: string;
  afterLabel?: string;
  scale?: number;
  offset?: Offset;
  onPan?: (offset: Offset) => void;
  onZoom?: () => void;
}) {
  const canvas = useRef<HTMLDivElement>(null);
  const beforeImage = useRef<HTMLImageElement>(null);
  const afterImage = useRef<HTMLImageElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const [split, setSplit] = useState(50);
  const [failed, setFailed] = useState<'before' | 'after' | null>(null);
  const [sizes, setSizes] = useState<{ before?: string; after?: string }>({});

  useEffect(() => {
    const next: { before?: string; after?: string } = {};
    let error: 'before' | 'after' | null = null;
    for (const [side, image] of [['before', beforeImage.current], ['after', afterImage.current]] as const) {
      if (!image?.complete) continue;
      if (image.naturalWidth) next[side] = `${image.naturalWidth} × ${image.naturalHeight}`;
      else error = side;
    }
    setSizes(next);
    setFailed(error);
  }, [before, after]);

  function splitAt(clientX: number) {
    const box = canvas.current?.getBoundingClientRect();
    return box && box.width ? clampSplit(((clientX - box.left) / box.width) * 100) : 50;
  }

  function pointerDown(event: PointerEvent<HTMLDivElement>) {
    if (!event.isPrimary || event.button !== 0) return;
    const panning = scale > 1 && Boolean(onPan);
    gesture.current = {
      mode: panning ? 'pan' : 'split',
      x: event.clientX,
      y: event.clientY,
      startOffset: offset,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleDown(event: PointerEvent<HTMLDivElement>) {
    if (!event.isPrimary || event.button !== 0) return;
    event.stopPropagation();
    gesture.current = {
      mode: 'handle',
      x: event.clientX,
      y: event.clientY,
      startOffset: offset,
      moved: true,
    };
    canvas.current?.setPointerCapture(event.pointerId);
  }

  function pointerMove(event: PointerEvent<HTMLDivElement>) {
    const drag = gesture.current;
    if (!drag) return;
    if (drag.mode === 'handle') {
      setSplit(splitAt(event.clientX));
      return;
    }
    if (!canvas.current?.hasPointerCapture(event.pointerId)) return;
    const x = event.clientX - drag.x;
    const y = event.clientY - drag.y;
    if (Math.hypot(x, y) > 4) drag.moved = true;
    if (!drag.moved) return;
    if (drag.mode === 'pan') {
      const box = event.currentTarget.getBoundingClientRect();
      onPan?.({
        x: drag.startOffset.x + (x / box.width) * 100,
        y: drag.startOffset.y + (y / box.height) * 100,
      });
    } else {
      setSplit(splitAt(event.clientX));
    }
  }

  function pointerEnd(event: PointerEvent<HTMLDivElement>) {
    if (canvas.current?.hasPointerCapture(event.pointerId)) {
      canvas.current.releasePointerCapture(event.pointerId);
    }
  }

  function click() {
    const drag = gesture.current;
    gesture.current = null;
    if (!drag?.moved) onZoom?.();
  }

  function keyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.shiftKey ? 10 : 2;
    const next = event.key === 'ArrowLeft' ? split - step
      : event.key === 'ArrowRight' ? split + step
      : event.key === 'Home' ? 0
      : event.key === 'End' ? 100
      : null;
    if (next === null) return;
    event.preventDefault();
    event.stopPropagation();
    setSplit(clampSplit(next));
  }

  const transform = `translate(${offset.x}%, ${offset.y}%) scale(${scale})`;

  return (
    <div ref={canvas} className="compare-canvas checker relative h-full min-h-0 w-full overflow-hidden"
      data-zoomed={scale > 1}
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={pointerEnd}
      onPointerCancel={() => { gesture.current = null; }}
      onClick={click}>
      <img ref={beforeImage} className="compare-image" src={before} alt={beforeLabel} draggable={false}
        style={{ transform }}
        onLoad={(event) => {
          const { naturalWidth, naturalHeight } = event.currentTarget;
          setSizes((value) => ({ ...value, before: `${naturalWidth} × ${naturalHeight}` }));
        }}
        onError={() => setFailed('before')} />
      <div className="compare-reveal" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>
        <img ref={afterImage} className="compare-image" src={after} alt={afterLabel} draggable={false}
          style={{ transform }}
          onLoad={(event) => {
            const { naturalWidth, naturalHeight } = event.currentTarget;
            setSizes((value) => ({ ...value, after: `${naturalWidth} × ${naturalHeight}` }));
          }}
          onError={() => setFailed('after')} />
      </div>
      {failed && (
        <p className="compare-missing">
          {failed === 'before' ? 'The original preview is unavailable.' : 'The new preview is unavailable.'}
        </p>
      )}
      <span className="compare-tag compare-tag-before">
        {beforeLabel}{sizes.before ? ` · ${sizes.before}` : ''}
      </span>
      <span className="compare-tag compare-tag-after">
        {afterLabel}{sizes.after ? ` · ${sizes.after}` : ''}
      </span>
      <div className="compare-divider" style={{ left: `${split}%` }}>
        <div className="compare-handle" role="slider" tabIndex={0}
          aria-label="Comparison position" aria-valuemin={0} aria-valuemax={100}
          aria-valuenow={Math.round(split)}
          aria-valuetext={`${Math.round(split)}% ${beforeLabel}, ${Math.round(100 - split)}% ${afterLabel}`}
          onPointerDown={handleDown} onKeyDown={keyDown}>
          <span className="compare-knob" aria-hidden="true"><CaretLeft size={14} weight="bold" /><CaretRight size={14} weight="bold" /></span>
        </div>
      </div>
    </div>
  );
}
