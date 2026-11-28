export const categories = {
  all: 'All assets',
  ui: 'Interface',
  characters: 'Characters',
  weapons: 'Weapons',
  environment: 'Environment',
  maps: 'Maps & levels',
  items: 'Items & pickups',
  effects: 'Effects',
  textures: 'Shared textures',
  audio: 'Audio',
  config: 'Game data',
  other: 'Other assets',
};

export const kinds = {
  image: 'Image / texture',
  model: 'Model',
  animation: 'Animation',
  physics: 'Physics',
  effect: 'Shader / effect',
  movie: 'Interface movie',
  audio: 'Audio',
  video: 'Video',
  text: 'Text / data',
  other: 'Other',
};

export type Category = keyof typeof categories;
export type AssetKind = keyof typeof kinds;

const groups: Partial<Record<string, Category>> = {
  ui: 'ui',
  char: 'characters',
  weapons: 'weapons',
  environment: 'environment',
  maps: 'maps',
  rpg: 'items',
  fx: 'effects',
  effects: 'effects',
  fxstudio: 'effects',
  textures: 'textures',
  sound: 'audio',
};

const extensions: Partial<Record<AssetKind, string[]>> = {
  image: ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'dds', 'sif', 'tga'],
  model: ['sol'],
  animation: ['nsa', 'mor'],
  physics: ['nxa'],
  effect: ['fxb'],
  movie: ['gfx'],
  audio: ['wav', 'mp3', 'ogg', 'm4a', 'aac', 'flac', 'opus', 'fsb', 'fev'],
  video: ['mp4', 'webm', 'mov', 'm4v', 'ogv'],
  text: ['txt', 'ini', 'csv', 'json', 'xml', 'html', 'cfg', 'lua', 'md'],
};

export const inlineTypes: Partial<Record<string, string>> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  webp: 'image/webp',
  gif: 'image/gif',
  bmp: 'image/bmp',
  wav: 'audio/wav',
  mp3: 'audio/mpeg',
  ogg: 'audio/ogg',
  m4a: 'audio/mp4',
  aac: 'audio/aac',
  flac: 'audio/flac',
  opus: 'audio/ogg',
  mp4: 'video/mp4',
  webm: 'video/webm',
  mov: 'video/quicktime',
  m4v: 'video/mp4',
  ogv: 'video/ogg',
};

export function classify(archive: string, path: string) {
  const parts = path.split('/');
  const name = parts.at(-1) ?? '';
  const extension = name.includes('.') ? (name.split('.').at(-1) ?? '').toLowerCase() : '';
  const kind = (Object.keys(extensions) as AssetKind[]).find((key) => extensions[key]?.includes(extension)) ?? 'other';
  const folder = parts.length > 1 ? parts[0] : '';
  const folderKey = folder.toLowerCase();
  let category: Category = Object.hasOwn(groups, folderKey)
    ? groups[folderKey] ?? 'other' : kind === 'audio' ? 'audio' : 'other';
  if (archive === 'PC_Config') category = 'config';

  let group = parts.length > 2 ? parts[1] : 'General';
  if (category === 'config') group = folder || 'General';
  if (category === 'ui' && parts.length === 2) {
    group = name.replace(/\.[^.]+$/, '').replace(/_I[0-9a-f]+$/i, '');
  }

  return { name, extension, category, group, kind };
}

export function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
}

export type ImageInfo = { width: number; height: number; format: string | null };

export type Asset = ReturnType<typeof classify> & {
  id: string;
  path: string;
  archive: string;
  size: number;
  sha256: string;
  image: ImageInfo | null;
  preview: 'png' | 'original' | null;
};
