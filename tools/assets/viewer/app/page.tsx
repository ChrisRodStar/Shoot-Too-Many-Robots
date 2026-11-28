import { connection } from 'next/server';
import { getCatalog } from '../lib/catalog';
import { getUpscales } from '../lib/upscales';
import { getSplash } from '../lib/splash';
import { AssetViewer } from './viewer';

export default async function Home({ searchParams }: PageProps<'/'>) {
  await connection();
  try {
    const [{ assets }, upscales, query, splash] = await Promise.all([getCatalog(), getUpscales(), searchParams, getSplash('master')]);
    return <AssetViewer assets={assets} upscales={Object.fromEntries(upscales)} initiallyUpscaled={query.upscaled === '1'}
      initialAsset={typeof query.asset === 'string' ? query.asset : undefined} splashAvailable={Boolean(splash)} />;
  } catch (error) {
    const missing = error instanceof Error && 'code' in error && error.code === 'ENOENT';
    if (!missing) console.error('Could not load asset manifest', error);
    return (
      <main className="catalog-error">
        <h1>Asset catalog unavailable</h1>
        <p>{missing ? 'The extraction manifest is missing.' : 'The extraction manifest could not be read.'}</p>
        <p>From the project root, run <code>python3 tools/assets/extract_sar.py</code>, then reload.</p>
      </main>
    );
  }
}
