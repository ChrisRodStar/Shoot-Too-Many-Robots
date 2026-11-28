import type { NextRequest } from 'next/server';
import { createReadStream } from 'node:fs';
import { Readable } from 'node:stream';
import { getCatalog, resolveAsset } from '../../../../lib/catalog';
import { inlineTypes } from '../../../../lib/asset-types';
import { resolveUpscale } from '../../../../lib/upscales';

export async function GET(request: NextRequest, { params }: RouteContext<'/api/asset/[id]'>) {
  const { id } = await params;
  const mode = request.nextUrl.searchParams.get('view') ?? 'download';
  if (!['download', 'preview', 'text', 'before', 'after'].includes(mode)) return new Response(null, { status: 400 });

  try {
    const { entries } = await getCatalog();
    const entry = entries.get(id);
    if (!entry) return new Response(null, { status: 404 });

    const { asset, converted } = entry;
    if (mode === 'preview' && !asset.preview) return new Response(null, { status: 404 });
    if (mode === 'text' && asset.kind !== 'text') return new Response(null, { status: 404 });

    const compare = mode === 'before' || mode === 'after';
    const showPng = compare || (mode === 'preview' && converted);
    const path = showPng ? `__previews__/${asset.path}.png` : asset.path;
    const file = compare
      ? await resolveUpscale(request.nextUrl.searchParams.get('batch'), asset, mode === 'before')
      : await resolveAsset(path);
    if (!file) return new Response(null, { status: 404 });

    const headers = new Headers({ 'X-Content-Type-Options': 'nosniff' });
    let length = file.size;
    if (mode === 'download') {
      const filename = encodeURIComponent(asset.name).replace(/[!'()*]/g,
        (char) => '%' + char.charCodeAt(0).toString(16).toUpperCase());
      headers.set('Content-Disposition', `attachment; filename*=UTF-8''${filename}`);
      headers.set('Content-Type', 'application/octet-stream');
    } else if (mode === 'text') {
      length = Math.min(file.size, 65536);
      headers.set('Content-Type', 'text/plain; charset=utf-8');
    } else {
      headers.set('Content-Type', showPng ? 'image/png' : inlineTypes[asset.extension] ?? 'application/octet-stream');
      headers.set('Cache-Control', compare ? 'no-cache' : 'private, max-age=300');
    }
    headers.set('Content-Length', String(length));

    const stream = length ? createReadStream(file.actual, { end: length - 1 }) : null;
    return new Response(stream ? Readable.toWeb(stream) as ReadableStream<Uint8Array> : null, { headers });
  } catch (error) {
    if (error instanceof Error && 'code' in error && error.code === 'ENOENT') return new Response(null, { status: 404 });
    console.error('Asset read failed', error);
    return new Response(null, { status: 500 });
  }
}
