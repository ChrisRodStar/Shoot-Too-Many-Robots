'use client';

import {
  Archive, ArrowDown, ArrowLeft, ArrowRight, Cube, File, FileText, FilmReel,
  FolderOpen, Image as ImageIcon, MagnifyingGlass, MusicNote, X,
} from '@phosphor-icons/react';
import { useDeferredValue, useEffect, useRef, useState } from 'react';
import { categories, formatSize, kinds } from '../lib/asset-types';

const PAGE_SIZE = 48;
const number = new Intl.NumberFormat('en-US');
const kindIcons = {
  image: ImageIcon, text: FileText, audio: MusicNote, video: FilmReel, movie: FilmReel,
  model: Cube, physics: Cube,
};
const notes = {
  model: 'Cooked Seoul Engine model. Download the original for use in a format-aware tool.',
  animation: 'Cooked character or object animation data.',
  physics: 'PhysX collision and rig data.',
  effect: 'Compiled shader or effect data.',
  movie: 'Cooked interface movie.',
  audio: 'FMOD sound banks and event data require an FMOD-compatible tool.',
  image: 'No image preview is available. Run the extractor with Pillow to decode supported textures.',
};

function assetUrl(asset, mode) {
  return `/api/asset/${asset.id}?view=${mode}`;
}

function TextPreview({ asset }) {
  const [result, setResult] = useState(null);
  const url = assetUrl(asset, 'text');

  useEffect(() => {
    const controller = new AbortController();
    fetch(url, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('Text preview is unavailable.');
        return response.text();
      })
      .then((text) => setResult({ text }))
      .catch((error) => {
        if (!controller.signal.aborted) setResult({ error: error.message });
      });
    return () => controller.abort();
  }, [url]);

  if (!result) return <p>Loading text preview…</p>;
  if (result.error) return <p>{result.error}</p>;
  return <pre>{result.text}{asset.size > 65536 && '\n\n… Preview limited to 64 KiB'}</pre>;
}

function AssetImage({ asset, thumbnail = false }) {
  const [failed, setFailed] = useState(false);
  if (failed) return thumbnail ? <ImageIcon size={28} /> : <p>Image preview could not be loaded.</p>;
  return <img src={assetUrl(asset, 'preview')} alt={thumbnail ? '' : asset.name}
    loading={thumbnail ? 'lazy' : 'eager'} onError={() => setFailed(true)} />;
}

function Preview({ asset }) {
  if (asset.kind === 'text') return <TextPreview asset={asset} />;
  if (asset.kind === 'image' && asset.preview) return <AssetImage asset={asset} />;
  if (asset.kind === 'audio' && asset.preview) {
    return <audio aria-label={asset.name} controls preload="metadata" src={assetUrl(asset, 'preview')} />;
  }
  if (asset.kind === 'video' && asset.preview) {
    return <video aria-label={asset.name} controls preload="metadata" src={assetUrl(asset, 'preview')} />;
  }
  return <p>{notes[asset.kind] ?? 'No inline preview for this file type.'}</p>;
}

function Inspector({ asset, onClose, panelRef }) {
  return (
    <aside className={asset ? 'inspector has-asset' : 'inspector'} ref={panelRef} aria-label="Asset inspector" tabIndex={-1}>
      <div className="inspector-header">
        <span className="eyebrow">Inspector</span>
        {asset && <button type="button" className="icon-button" aria-label="Close inspector" onClick={onClose}><X size={17} /></button>}
      </div>
      {!asset ? (
        <div className="inspector-empty"><FolderOpen size={34} weight="thin" /><p>Select an asset to inspect it.</p></div>
      ) : (
        <>
          <div className={`preview ${asset.kind === 'image' && asset.preview ? 'checker' : ''}`}>
            <Preview key={asset.id} asset={asset} />
          </div>
          {asset.preview === 'png' && <p className="preview-caption">PNG preview · up to 512 px per side</p>}
          <h2 className="inspector-name">{asset.name}</h2>
          <div className="asset-label">{categories[asset.category]} / {asset.group}</div>
          <dl className="details">
            <div><dt>Type</dt><dd>{kinds[asset.kind]}</dd></div>
            <div><dt>File size</dt><dd>{formatSize(asset.size)}</dd></div>
            {asset.image && <div><dt>Source size</dt><dd>{asset.image.width} × {asset.image.height} px</dd></div>}
            {asset.image?.format && <div><dt>Encoding</dt><dd>{asset.image.format}</dd></div>}
            <div className="asset-path"><dt>Extracted path</dt><dd>{asset.path}</dd></div>
          </dl>
          <div className="actions">
            {asset.path === 'Loose/splashscreen.bmp' && (
              <a className="download" href="/compare/splash">Compare startup splash</a>
            )}
            <a className="download" href={assetUrl(asset, 'download')} download={asset.name}>
              <ArrowDown size={17} /> Save original
            </a>
            {asset.kind === 'image' && asset.preview === 'png' && (
              <a className="secondary" href={assetUrl(asset, 'preview')} download={asset.name + '.png'}>
                Save PNG preview
              </a>
            )}
          </div>
        </>
      )}
    </aside>
  );
}

export function AssetViewer({ assets }) {
  const [category, setCategory] = useState('all');
  const [kind, setKind] = useState('all');
  const [group, setGroup] = useState('all');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('preview');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState(null);
  const panelRef = useRef(null);
  const galleryRef = useRef(null);
  const resultsRef = useRef(null);
  const selectedButton = useRef(null);
  const search = useDeferredValue(query);
  const tokens = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const counts = { all: assets.length };
  const groups = new Set();
  const availableKinds = new Set();
  const visible = [];

  for (const asset of assets) {
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

  const pages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const current = Math.min(page, pages);
  const start = (current - 1) * PAGE_SIZE;
  const end = Math.min(start + PAGE_SIZE, visible.length);

  function changeCategory(next) {
    setCategory(next);
    setKind('all');
    setGroup('all');
    setPage(1);
    galleryRef.current?.scrollTo(0, 0);
  }

  function changePage(next) {
    setPage(next);
    resultsRef.current?.scrollIntoView({ block: 'start' });
  }

  function selectAsset(asset, button) {
    selectedButton.current = button;
    setSelected(asset);
    if (window.matchMedia('(max-width: 850px)').matches) {
      requestAnimationFrame(() => {
        panelRef.current?.focus({ preventScroll: true });
        panelRef.current?.scrollIntoView({ block: 'start' });
      });
    } else {
      panelRef.current?.scrollTo(0, 0);
    }
  }

  function closeInspector() {
    setSelected(null);
    requestAnimationFrame(() => {
      const button = selectedButton.current;
      if (button?.isConnected) button.focus();
      else resultsRef.current?.querySelector('select')?.focus();
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
            onChange={(event) => { setQuery(event.target.value); setPage(1); galleryRef.current?.scrollTo(0, 0); }} />
        </label>
        <div className="source-label"><span /> Local extraction</div>
      </header>

      <div className="workspace">
        <nav className="sidebar" aria-label="Asset categories">
          <div className="eyebrow">Categories</div>
          {Object.entries(categories).map(([key, label]) => (
            <button key={key} type="button" className="category" aria-pressed={key === category} onClick={() => changeCategory(key)}>
              <span>{label}</span><span className="category-count">{number.format(counts[key] ?? 0)}</span>
            </button>
          ))}
          <div className="source-path"><FolderOpen size={15} /> work/assets/extracted</div>
        </nav>

        <main className="gallery" ref={galleryRef}>
          <div className="gallery-header" ref={resultsRef}>
            <div><h2>{categories[category]}</h2><p role="status">{number.format(visible.length)} {visible.length === 1 ? 'asset' : 'assets'}</p></div>
            <div className="filters">
              {category !== 'all' && groups.size > 1 && (
                <select aria-label="Asset group" value={group} onChange={(event) => { setGroup(event.target.value); setPage(1); }}>
                  <option value="all">All groups</option>
                  {[...groups].sort().map((name) => <option key={name}>{name}</option>)}
                </select>
              )}
              <select aria-label="File type" value={kind} onChange={(event) => { setKind(event.target.value); setPage(1); }}>
                <option value="all">All types</option>
                {Object.entries(kinds).filter(([key]) => availableKinds.has(key)).map(([key, label]) => (
                  <option value={key} key={key}>{label}</option>
                ))}
              </select>
              <select aria-label="Sort by" value={sort} onChange={(event) => { setSort(event.target.value); setPage(1); }}>
                <option value="preview">Images first</option>
                <option value="path">Path</option>
                <option value="name">Name</option>
                <option value="size">Largest first</option>
              </select>
            </div>
          </div>
          <div className="results-bar">
            <span>{visible.length ? `${number.format(start + 1)}–${number.format(end)} of ${number.format(visible.length)}` : 'No results'}</span>
            <div className="pagination">
              <button type="button" className="icon-button" aria-label="Previous page" disabled={current <= 1} onClick={() => changePage(current - 1)}><ArrowLeft size={16} /></button>
              <span>{current} / {pages}</span>
              <button type="button" className="icon-button" aria-label="Next page" disabled={current >= pages} onClick={() => changePage(current + 1)}><ArrowRight size={16} /></button>
            </div>
          </div>
          {visible.length === 0 ? (
            <div className="empty">
              <MagnifyingGlass size={30} weight="thin" />
              <p>No assets match your filters.</p>
              <button className="secondary" type="button" onClick={() => { setQuery(''); changeCategory('all'); }}>Reset filters</button>
            </div>
          ) : (
            <ul className="grid">
              {visible.slice(start, end).map((asset) => {
                const Icon = kindIcons[asset.kind] ?? File;
                return (
                  <li key={asset.id}>
                    <button className="tile" type="button" aria-pressed={asset.id === selected?.id}
                      onClick={(event) => selectAsset(asset, event.currentTarget)} title={asset.path}>
                      <span className={`tile-image ${asset.kind === 'image' && asset.preview ? 'checker' : ''}`}>
                        {asset.kind === 'image' && asset.preview ? <AssetImage asset={asset} thumbnail /> : <Icon size={29} weight="thin" />}
                      </span>
                      <span className="tile-name">{asset.name}</span>
                      <span className="tile-meta"><span>{asset.extension || kinds[asset.kind]}</span>
                        <span>{asset.image ? `${asset.image.width} × ${asset.image.height}` : formatSize(asset.size)}</span></span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </main>

        <Inspector asset={selected} onClose={closeInspector} panelRef={panelRef} />
      </div>
    </div>
  );
}
