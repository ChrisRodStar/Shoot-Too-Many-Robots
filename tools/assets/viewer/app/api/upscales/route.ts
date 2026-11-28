import { getUpscales } from '../../../lib/upscales';

export async function GET() {
  return Response.json(Object.fromEntries(await getUpscales()), {
    headers: { 'Cache-Control': 'no-store' },
  });
}
