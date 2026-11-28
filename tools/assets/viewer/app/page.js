import { connection } from 'next/server';
import { getCatalog } from '../lib/catalog';
import { AssetViewer } from './viewer';

export default async function Home() {
  await connection();
  try {
    const { assets } = await getCatalog();
    return <AssetViewer assets={assets} />;
  } catch (error) {
    if (error.code !== 'ENOENT') console.error('Could not load asset manifest', error);
    return (
      <main className="catalog-error">
        <h1>Asset catalog unavailable</h1>
        <p>{error.code === 'ENOENT' ? 'The extraction manifest is missing.' : 'The extraction manifest could not be read.'}</p>
        <p>From the project root, run <code>python3 tools/assets/extract_sar.py</code>, then reload.</p>
      </main>
    );
  }
}
