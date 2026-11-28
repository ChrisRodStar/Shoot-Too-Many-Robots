'use client';

import {
  Archive, ArrowDown, Cube, File, FileText, FilmReel,
  FolderOpen, Image as ImageIcon, MagnifyingGlass, MusicNote,
} from '@phosphor-icons/react';
import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { categories, formatSize, kinds, type Asset, type AssetKind, type Category } from '../lib/asset-types';
import { AssetDetail, assetUrl } from './asset-detail';

const SCROLL_BATCH_SIZE = 64;
const UPSCALE_REFRESH_MS = 5000;
const number = new Intl.NumberFormat('en-US');
const kindIcons: Partial<Record<AssetKind, typeof File>> = {
  image: ImageIcon, text: FileText, audio: MusicNote, video: FilmReel, movie: FilmReel,
  model: Cube, physics: Cube,
};
function AssetImage({ asset }: { asset: Asset }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <ImageIcon size={28} />;
  return <img src={assetUrl(asset, 'preview')} alt="" loading="lazy" onError={() => setFailed(true)} />;
}

export function AssetViewer({ assets, upscales, initiallyUpscaled, splashAvailable, initialAsset }: {
  assets: Asset[];
  upscales: Record<string, string[]>;
  initiallyUpscaled: boolean;
  splashAvailable: boolean;
  initialAsset?: string;
}) {
  const [category, setCategory] = useState<Category>('all');
  const [kind, setKind] = useState<AssetKind | 'all'>('all');
  const [group, setGroup] = useState('all');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('preview');
  const [shown, setShown] = useState(SCROLL_BATCH_SIZE);
  const [onlyUpscaled, setOnlyUpscaled] = useState(initiallyUpscaled);
  const [selected, setSelected] = useState<Asset | null>(() => assets.find((asset) => asset.id === initialAsset) ?? null);
  const [liveUpscales, setLiveUpscales] = useState(upscales);
  const galleryRef = useRef<HTMLElement>(null);
  const moreRef = useRef<HTMLDivElement>(null);
  const selectedButton = useRef<HTMLButtonElement>(null);
  const search = useDeferredValue(query);
  const upscaled = useMemo(() => new Set(Object.keys(liveUpscales)), [liveUpscales]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      if (controller.signal.aborted) return;
      try {
        if (!document.hidden) {
          const response = await fetch('/api/upscales', { signal: controller.signal });
          if (response.ok) {
            const next: Record<string, string[]> = await response.json();
            setLiveUpscales((previous) => JSON.stringify(previous) === JSON.stringify(next) ? previous : next);
          }
        }
      } catch {
        // Keep the current list available while the local server restarts.
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, UPSCALE_REFRESH_MS);
      }
    }
    timer = setTimeout(refresh, UPSCALE_REFRESH_MS);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  const { counts, groups, availableKinds, visible } = useMemo(() => {
    const tokens = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const counts: Partial<Record<Category, number>> = { all: 0 };
    const groups = new Set<string>();
    const availableKinds = new Set<AssetKind>();
    const visible: Asset[] = [];

    for (const asset of assets) {
      if (onlyUpscaled && !upscaled.has(asset.path)) continue;
      counts.all = (counts.all ?? 0) + 1;
      counts[asset.category] = (counts[asset.category] ?? 0) + 1;
      if (category !== 'all' && asset.category !== category) continue;
      groups.add(asset.group);
      availableKinds.add(asset.kind);
      if (group !== 'all' && asset.group !== group) continue;
      if (kind !== 'all' && asset.kind !== kind) continue;

      const searchable = `${asset.path} ${asset.group} ${categories[asset.category]} ${kinds[asset.kind]}`.toLowerCase();
      if (tokens.every((token) => searchable.includes(token))) visible.push(asset);
    }

    visible.sort((a, b) => {
      if (sort === 'size' && a.size !== b.size) return b.size - a.size;
      if (sort === 'name') return a.name.localeCompare(b.name, 'en', { numeric: true }) || a.path.localeCompare(b.path);
      if (sort === 'preview') {
        const aImage = a.kind === 'image' && a.preview;
        const bImage = b.kind === 'image' && b.preview;
        if (Boolean(aImage) !== Boolean(bImage)) return Number(Boolean(bImage)) - Number(Boolean(aImage));
      }
      return a.path.localeCompare(b.path, 'en', { numeric: true });
    });
    return { counts, groups, availableKinds, visible };
  }, [assets, category, group, kind, onlyUpscaled, search, sort, upscaled]);

  const hasMore = shown < visible.length;
  useEffect(() => {
    const target = moreRef.current;
    if (!hasMore || !target) return;
    const root = window.matchMedia('(max-width: 850px)').matches ? null : galleryRef.current;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        observer.disconnect();
        setShown((count) => count + SCROLL_BATCH_SIZE);
      }
    }, { root, rootMargin: '350px' });
    observer.observe(target);
    return () => observer.disconnect();
  }, [shown, visible, hasMore]);

  function resetScroll() {
    setShown(SCROLL_BATCH_SIZE);
    galleryRef.current?.scrollTo(0, 0);
  }
  function changeCategory(next: Category) {
    setCategory(next);
    setKind('all');
    setGroup('all');
    resetScroll();
  }

  function selectAsset(asset: Asset, button: HTMLButtonElement) {
    selectedButton.current = button;
    setSelected(asset);
  }

  function closeDetail() {
    setSelected(null);
    requestAnimationFrame(() => {
      if (selectedButton.current?.isConnected) selectedButton.current.focus({ preventScroll: true });
    });
  }

  return (
    <div className="workbench">
      <header className="app-header">
        <div className="identity">
          <span className="brand-icon"><Archive size={21} weight="bold" /></span>
          <div><p className="project-name">Shoot Many Robots</p><h1>Asset Viewer</h1></div>
        </div>
        <label className="search">
          <MagnifyingGlass size={20} />
          <input type="search" value={query} placeholder="Search names and paths" aria-label="Search assets"
            onChange={(event) => { setQuery(event.target.value); resetScroll(); }} />
        </label>
        <div className="source-label"><span /> Local extraction</div>
      </header>

      <div className="workspace">
        <nav className="sidebar" aria-label="Asset categories">
          <div className="eyebrow">Categories</div>
          <button type="button" className="category" aria-pressed={onlyUpscaled} onClick={() => {
            setOnlyUpscaled(!onlyUpscaled);
            changeCategory('all');
          }}><span>Upscaled only</span><span className="category-count">{number.format(upscaled.size)}</span></button>
          {(Object.entries(categories) as [Category, string][]).map(([key, label]) => (
            <button key={key} type="button" className="category" aria-pressed={key === category} onClick={() => changeCategory(key)}>
              <span>{label}</span><span className="category-count">{number.format(counts[key] ?? 0)}</span>
            </button>
          ))}
          <div className="source-path"><FolderOpen size={15} /> work/assets/extracted</div>
        </nav>

        <main className="gallery" ref={galleryRef}>
          <div className="gallery-header">
            <div><h2>{categories[category]}</h2><p role="status">{number.format(visible.length)} {visible.length === 1 ? 'asset' : 'assets'}</p></div>
            <div className="filters">
              {category !== 'all' && groups.size > 1 && (
                <select aria-label="Asset group" value={group} onChange={(event) => { setGroup(event.target.value); resetScroll(); }}>
                  <option value="all">All groups</option>
                  {[...groups].sort().map((name) => <option key={name}>{name}</option>)}
                </select>
              )}
              <select aria-label="File type" value={kind} onChange={(event) => { setKind(event.target.value as AssetKind | 'all'); resetScroll(); }}>
                <option value="all">All types</option>
                {Object.entries(kinds).filter(([key]) => availableKinds.has(key as AssetKind)).map(([key, label]) => (
                  <option value={key} key={key}>{label}</option>
                ))}
              </select>
              <select aria-label="Sort by" value={sort} onChange={(event) => { setSort(event.target.value); resetScroll(); }}>
                <option value="preview">Images first</option>
                <option value="path">Path</option>
                <option value="name">Name</option>
                <option value="size">Largest first</option>
              </select>
            </div>
          </div>
          {visible.length === 0 ? (
            <div className="empty">
              <MagnifyingGlass size={30} weight="thin" />
              <p>No assets match your filters.</p>
              <button className="secondary" type="button" onClick={() => { setQuery(''); setOnlyUpscaled(false); changeCategory('all'); }}>Reset filters</button>
            </div>
          ) : (
            <ul className="asset-grid">
              {visible.slice(0, shown).map((asset) => {
                const Icon = kindIcons[asset.kind] ?? File;
                return (
                  <li key={asset.id}>
                    <button className="tile" type="button" aria-haspopup="dialog"
                      onClick={(event) => selectAsset(asset, event.currentTarget)} title={asset.path}>
                      <span className={`tile-image ${asset.kind === 'image' && asset.preview ? 'checker' : ''}`}>
                        {asset.kind === 'image' && asset.preview ? <AssetImage asset={asset} /> : <Icon size={29} weight="thin" />}
                      </span>
                      <span className="tile-name">{asset.name}</span>
                      <span className="tile-meta"><span>{asset.extension || kinds[asset.kind]}</span>
                        <span>{upscaled.has(asset.path) ? 'Upscaled' : asset.image ? `${asset.image.width} × ${asset.image.height}` : formatSize(asset.size)}</span></span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {hasMore && <div ref={moreRef} className="scroll-marker" aria-hidden="true" />}
        </main>

        {selected && (
          <AssetDetail key={selected.id} asset={selected} batches={liveUpscales[selected.path] ?? []}
            splash={splashAvailable && selected.path === 'Loose/splashscreen.bmp'} onClose={closeDetail} />
        )}
      </div>
    </div>
  );
}
