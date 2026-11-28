import { notFound, redirect } from 'next/navigation';
import { getCatalog } from '../../../../lib/catalog';
import { getUpscales } from '../../../../lib/upscales';

export default async function TextureComparison({ params }: PageProps<'/compare/texture/[id]'>) {
  const { id } = await params;
  const [{ entries }, upscales] = await Promise.all([getCatalog(), getUpscales()]);
  const asset = entries.get(id)?.asset;
  if (!asset?.preview || !upscales.has(asset.path)) notFound();
  redirect(`/?upscaled=1&asset=${encodeURIComponent(id)}`);
}
