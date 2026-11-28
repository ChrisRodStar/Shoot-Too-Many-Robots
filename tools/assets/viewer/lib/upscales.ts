import { readdir, realpath, stat } from 'node:fs/promises';
import { join, relative, resolve, sep } from 'node:path';

import type { Asset } from './asset-types';

const root = resolve(process.cwd(), '../../../work/assets/upgrades');
const batchPattern = /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/;

async function list(directory: string, recursive = false) {
  try {
    return await readdir(directory, { withFileTypes: true, recursive });
  } catch (error) {
    if (!(error instanceof Error && 'code' in error && (error.code === 'ENOENT' || error.code === 'ENOTDIR'))) throw error;
    return [];
  }
}

export async function getUpscales() {
  const paths = new Map<string, string[]>();
  const batches = (await list(root)).filter((entry) => entry.isDirectory() && batchPattern.test(entry.name));
  await Promise.all(batches.map(async ({ name }) => {
    const previews = join(root, name, 'previews');
    for (const file of await list(previews, true)) {
      if (!file.isFile() || !file.name.endsWith('.png')) continue;
      const path = relative(previews, join(file.parentPath, file.name)).split(sep).join('/').slice(0, -4);
      const batches = paths.get(path) ?? [];
      batches.push(name);
      paths.set(path, batches);
    }
  }));
  for (const names of paths.values()) names.sort();
  return new Map([...paths].sort(([a], [b]) => a.localeCompare(b)));
}

export async function resolveUpscale(batch: string | null, asset: Asset, before = false) {
  if (!batch || !batchPattern.test(batch)) return null;
  try {
    const directory = await realpath(root);
    const file = await realpath(join(directory, batch, before ? 'originals' : 'previews', asset.path + '.png'));
    if (!file.startsWith(directory + sep)) return null;
    const info = await stat(file);
    return info.isFile() ? { actual: file, size: info.size } : null;
  } catch (error) {
    if (error instanceof Error && 'code' in error && (error.code === 'ENOENT' || error.code === 'ENOTDIR')) return null;
    throw error;
  }
}
