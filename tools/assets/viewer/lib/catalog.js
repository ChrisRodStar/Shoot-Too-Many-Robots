import { createHash } from 'node:crypto';
import { readFile, realpath, stat } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
import { classify, inlineTypes } from './asset-types';

const root = resolve(process.cwd(), '../../../work/assets-extracted');
const manifestPath = resolve(root, 'manifest.json');
let cached;

function isRelativePath(value) {
  return typeof value === 'string' && value.split('/').every(
    (part) => part && part !== '..' && part !== '.' && !/[\\:\x00-\x1f]/.test(part),
  );
}

export async function getCatalog() {
  const info = await stat(manifestPath);
  if (cached?.ino === info.ino && cached?.mtime === info.mtimeMs && cached?.size === info.size) {
    return cached.catalog;
  }

  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
  const entries = new Map();
  for (const record of manifest.files) {
    const archive = record.archive.replace(/\.sar$/i, '');
    if (!isRelativePath(archive) || archive.includes('/') || !isRelativePath(record.path)) continue;

    const path = `${archive}/${record.path}`;
    const id = createHash('sha256').update(path).digest('hex').slice(0, 24);
    const type = classify(archive, record.path);
    const preview = `__previews__/${path}.png`;
    const converted = record.preview === preview;
    const native = Object.hasOwn(inlineTypes, type.extension);
    const asset = {
      id, path, archive, ...type,
      size: record.size,
      sha256: record.sha256,
      image: record.image ?? null,
      preview: converted ? 'png' : native ? 'original' : null,
    };
    entries.set(id, { asset, converted });
  }

  const assets = [...entries.values()].map(({ asset }) => asset);
  const catalog = { assets, entries };
  cached = { ino: info.ino, mtime: info.mtimeMs, size: info.size, catalog };
  return catalog;
}

export async function resolveAsset(path) {
  const [directory, actual] = await Promise.all([realpath(root), realpath(resolve(root, path))]);
  if (!actual.startsWith(directory + sep)) return null;
  const info = await stat(actual);
  return info.isFile() ? { actual, size: info.size } : null;
}
