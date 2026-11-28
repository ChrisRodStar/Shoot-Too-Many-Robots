'use client';

import { useDeferredValue, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import type { BankProgress, KindProgress, MatchedFunction } from '@/lib/progress';
import { formatInt, formatPercent, kindMeta } from '@/lib/format';

interface ExplorerProps {
  banks: BankProgress[];
  functions: MatchedFunction[];
  kinds: KindProgress[];
}

function bankLevel(matched: number): number {
  if (matched >= 5) return 3;
  if (matched >= 2) return 2;
  if (matched === 1) return 1;
  return 0;
}

function shortSource(source: string): string {
  return source.split('/').pop() ?? source;
}

export function Explorer({ banks, functions, kinds }: ExplorerProps) {
  const [selectedBank, setSelectedBank] = useState<string | null>(null);
  const [selectedKind, setSelectedKind] = useState('all');
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);

  const bank = selectedBank ? banks.find((item) => item.name === selectedBank) : null;

  const filtered = useMemo(() => {
    const needle = deferredQuery.trim().toLowerCase();
    return functions.filter((fn) => {
      if (selectedBank && fn.bank !== selectedBank) return false;
      if (selectedKind !== 'all' && fn.kind !== selectedKind) return false;
      if (!needle) return true;
      return (
        fn.address.toLowerCase().includes(needle) ||
        fn.name.toLowerCase().includes(needle) ||
        fn.source.toLowerCase().includes(needle) ||
        fn.note.toLowerCase().includes(needle)
      );
    });
  }, [deferredQuery, functions, selectedBank, selectedKind]);

  const hasFilters = Boolean(selectedBank) || selectedKind !== 'all' || query.length > 0;
  const matchedBanks = banks.filter((item) => item.matched > 0).length;
  const maxBankMatched = Math.max(1, ...banks.map((item) => item.matched));

  return (
    <section className="section" id="registry">
      <div className="section-head">
        <div>
          <p className="section-index">02 / SECTOR MAP &amp; SALVAGE LOG</p>
          <h2 className="section-title">Wreckage by sector</h2>
        </div>
        <p className="section-aside">
          {matchedBanks} OF {banks.length} BANKS LIT
        </p>
      </div>

      <div className="bank-layout">
        <div className="bank-panel">
          <div className="bank-map" role="group" aria-label="Function bank map">
            {banks.map((item) => (
              <button
                key={item.name}
                type="button"
                className="bank-cell"
                data-level={bankLevel(item.matched)}
                aria-pressed={selectedBank === item.name}
                aria-label={`${item.name}: ${item.matched} of ${item.total} functions matched`}
                title={`${item.name} · ${item.matched}/${item.total} matched`}
                onClick={() => setSelectedBank((current) => (current === item.name ? null : item.name))}
              />
            ))}
          </div>
          <div className="bank-legend" aria-hidden="true">
            <span className="legend-label">0</span>
            <span className="legend-swatch" data-level="0" />
            <span className="legend-swatch" data-level="1" />
            <span className="legend-swatch" data-level="2" />
            <span className="legend-swatch" data-level="3" />
            <span className="legend-label">5+</span>
          </div>
          <div className="bank-detail" aria-live="polite">
            {bank ? (
              <>
                <span className="bank-detail-name">{bank.name}</span>
                <span>
                  {formatInt(bank.matched)} / {formatInt(bank.total)} functions ·{' '}
                  {formatPercent((bank.matched / bank.total) * 100)} of sector
                </span>
                <span>{formatInt(bank.matchedBytes)} B matched</span>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setSelectedBank(null)}
                >
                  CLEAR SECTOR
                </button>
              </>
            ) : (
              <span className="bank-detail-idle">PICK A SECTOR TO FILTER THE SALVAGE LOG</span>
            )}
          </div>
        </div>

        <aside className="bank-summary">
          <p className="mini-label">HOTTEST SECTORS</p>
          <ol className="bank-ranking">
            {[...banks]
              .filter((item) => item.matched > 0)
              .sort((a, b) => b.matched - a.matched)
              .slice(0, 6)
              .map((item) => (
                <li key={item.name}>
                  <button
                    type="button"
                    className="ranking-row"
                    onClick={() => setSelectedBank(item.name)}
                    aria-pressed={selectedBank === item.name}
                  >
                    <span className="ranking-name">{item.name}</span>
                    <span className="ranking-bar" aria-hidden="true">
                      <span style={{ width: `${(item.matched / maxBankMatched) * 100}%` }} />
                    </span>
                    <span className="ranking-value">{item.matched}</span>
                  </button>
                </li>
              ))}
          </ol>
          <p className="bank-footnote">
            Most sectors hold 250 functions. Matching is tracked at function granularity, then
            verified byte-for-byte by the MSVC 2008 harness.
          </p>
        </aside>
      </div>

      <div className="filter-bar">
        <button
          type="button"
          className="chip"
          aria-pressed={selectedKind === 'all'}
          onClick={() => setSelectedKind('all')}
        >
          ALL KINDS
        </button>
        {kinds.map((item) => (
          <button
            key={item.kind}
            type="button"
            className="chip"
            aria-pressed={selectedKind === item.kind}
            onClick={() => setSelectedKind(item.kind)}
          >
            {kindMeta(item.kind).short} {item.count}
          </button>
        ))}
        <label className="search-field">
          <span className="sr-only">Search verified functions</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="SEARCH ADDRESS, NAME, NOTE…"
            spellCheck={false}
          />
        </label>
        {hasFilters ? (
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setSelectedBank(null);
              setSelectedKind('all');
              setQuery('');
            }}
          >
            RESET
          </button>
        ) : null}
      </div>

      <div className="registry-status" aria-live="polite">
        <span>
          {formatInt(filtered.length)} RECORD{filtered.length === 1 ? '' : 'S'}
        </span>
        <span className="status-sep">/</span>
        <span>{formatInt(functions.length)} VERIFIED</span>
      </div>

      <div className="table-wrap">
        <table>
          <caption className="sr-only">
            Verified byte-exact functions, with address, kind, size, bank, and evidence
          </caption>
          <thead>
            <tr>
              <th scope="col">Address</th>
              <th scope="col">Function</th>
              <th scope="col">Kind</th>
              <th scope="col" className="num">
                Size
              </th>
              <th scope="col">Sector</th>
              <th scope="col">Source</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((fn) => {
              const meta = kindMeta(fn.kind);
              return (
                <tr key={fn.address}>
                  <td className="addr">{fn.address}</td>
                  <td className="fn-cell">
                    <span className="fn-name">{fn.name}</span>
                    {fn.note ? <span className="fn-note">{fn.note}</span> : null}
                  </td>
                  <td>
                    <span className="kind-chip" style={{ '--kind': meta.color } as CSSProperties}>
                      {meta.short}
                    </span>
                  </td>
                  <td className="num">{formatInt(fn.size)} B</td>
                  <td className="bank-code">{fn.bank}</td>
                  <td className="source-cell" title={fn.source}>
                    {shortSource(fn.source)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filtered.length === 0 ? (
          <p className="table-empty">NO SALVAGE MATCHES THE CURRENT FILTER.</p>
        ) : null}
      </div>
    </section>
  );
}
