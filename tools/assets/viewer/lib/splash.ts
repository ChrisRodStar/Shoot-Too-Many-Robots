import { stat } from 'node:fs/promises';
import { resolve } from 'node:path';
import { resolveAsset } from './catalog';

export const splashPath = 'Loose/splashscreen.bmp';
const generated = new Map([
  ['new', { filename: 'shoot-many-robots-remaster-4k.bmp', type: 'image/bmp' }],
  ['master', { filename: 'shoot-many-robots-remaster-4k.png', type: 'image/png' }],
]);

export async function getSplash(version: string) {
  try {
    if (version === 'original') {
      const file = await resolveAsset(splashPath);
      return file && { ...file, type: 'image/bmp', filename: 'splashscreen.bmp' };
    }
    const variant = generated.get(version);
    if (!variant) return null;

    const actual = resolve(process.cwd(), '../../../work/assets/upgrades', variant.filename);
    const info = await stat(actual);
    return info.isFile() ? { ...variant, actual, size: info.size } : null;
  } catch (error) {
    if (error instanceof Error && 'code' in error && error.code === 'ENOENT') return null;
    throw error;
  }
}
