import { createReadStream } from 'node:fs';
import { Readable } from 'node:stream';
import { getSplash } from '../../../../lib/splash';

export async function GET(_request, { params }) {
  const { version } = await params;
  const file = await getSplash(version);
  if (!file) return new Response(null, { status: 404 });

  return new Response(Readable.toWeb(createReadStream(file.actual)), {
    headers: {
      'Content-Type': file.type,
      'Content-Length': String(file.size),
      'X-Content-Type-Options': 'nosniff',
    },
  });
}
