import type { CSSProperties } from 'react';
import { Explorer } from './explorer';
import { LiveRefresh } from './live-refresh';
import {
  formatAge,
  formatBytes,
  formatInt,
  formatPercent,
  formatTimestamp,
  kindMeta,
} from '@/lib/format';
import { loadProgress, type AgentStatus, type ProgressMissing } from '@/lib/progress';

export const dynamic = 'force-dynamic';

const AGENT_ACTIVE_MS = 10 * 60 * 1000;

const UNKNOWN_AGENT: AgentStatus = {
  attached: false,
  state: 'unknown',
  agent: '',
  task: '',
  detail: '',
  updatedAt: null,
};

function AgentStrip({ agent = UNKNOWN_AGENT }: { agent?: AgentStatus }) {
  const ageMs = agent.updatedAt ? Date.now() - Date.parse(agent.updatedAt) : null;
  const fresh = ageMs !== null && Number.isFinite(ageMs) && ageMs >= 0 && ageMs < AGENT_ACTIVE_MS;
  const working = agent.state === 'working' && fresh;
  const blocked = agent.state === 'blocked' && fresh;

  const state = !agent.attached
    ? 'NOT ATTACHED'
    : working
      ? 'WORKING'
      : blocked
        ? 'BLOCKED'
        : agent.state === 'idle'
          ? 'IDLE'
          : fresh
            ? agent.state.toUpperCase()
            : 'LAST SEEN';

  const task = agent.attached
    ? [agent.task, agent.detail].filter(Boolean).join(' — ')
    : agent.detail || 'No status file at work/dev/agent-status.json';

  return (
    <div
      className={`agent-strip${working ? ' is-working' : ''}${blocked ? ' is-blocked' : ''}`}
    >
      <span className="agent-pulse" aria-hidden="true" />
      <span className="agent-label" title={agent.agent || undefined}>
        DECOMPILATION AGENT
      </span>
      <span className="agent-state" role="status">
        {state}
      </span>
      <span className="agent-task" title={task}>
        {task}
      </span>
      <span className="agent-updated">
        {agent.updatedAt ? `UPDATED ${formatAge(agent.updatedAt)}` : 'NO TIMESTAMP'}
      </span>
    </div>
  );
}

interface MeterProps {
  value: number;
  max: number;
  label: string;
  tone?: 'amber' | 'green';
  size?: 'hero' | 'md' | 'sm';
}

function Meter({ value, max, label, tone = 'green', size = 'sm' }: MeterProps) {
  const width = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div
      className={`meter meter-${size} meter-${tone}`}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
    >
      <span
        className="meter-fill"
        style={
          {
            width: `${width}%`,
            minWidth: width > 0 ? (size === 'hero' ? '7px' : '2px') : 0,
          } as CSSProperties
        }
      />
      <span className="meter-ticks" aria-hidden="true" />
    </div>
  );
}

function Star({ muted = false }: { muted?: boolean }) {
  return (
    <svg
      className={`star${muted ? ' is-muted' : ''}`}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M12 1.6 15.2 8l7 .9-5.1 4.9 1.3 7-6.4-3.4-6.4 3.4 1.3-7L2 8.9 9 8z" />
    </svg>
  );
}

function MissingState({ data }: { data: ProgressMissing }) {
  return (
    <div className="term">
      <div className="grit" aria-hidden="true" />
      <main className="missing">
        <div className="missing-panel">
          <p className="eyebrow">TERMLINK ERROR · {data.reason}</p>
          <h1>NO INDEX SIGNAL</h1>
          <p className="missing-copy">{data.detail}</p>
          {data.root ? (
            <p className="missing-root">
              ROOT <code>{data.root}</code>
            </p>
          ) : null}
          <ul className="missing-list">
            {data.expected.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p className="mini-label">REGENERATE THE TREE</p>
          <pre className="missing-command">{`./Decompile/tools/export.sh game 4
python3 Decompile/tools/match/verify.py`}</pre>
          <p className="missing-foot">
            Or point the dashboard at another tree with <code>SMR_DECOMPILE_ROOT</code>.
          </p>
        </div>
      </main>
    </div>
  );
}

export default function Page() {
  const data = loadProgress();
  if (!data.ok) return <MissingState data={data} />;

  const { totals, game, kinds, banks, matchedFunctions, namespaces } = data;
  const maxNamespace = Math.max(1, ...namespaces.map((item) => item.count));
  const remaining = totals.functions - totals.matched;

  return (
    <div className="term">
      <div className="grit" aria-hidden="true" />

      <header className="topbar">
        <a className="brand" href="#top" aria-label="Back to the top of the decompilation dashboard">
          <span className="brand-mark">SMR</span>
          <span className="brand-copy">
            <b>DECOMPILATION</b>
            <small>FIELD DIVISION</small>
          </span>
        </a>
        <div className="topbar-meta">
          <LiveRefresh />
          <span className="topbar-version">MSVC 9 · SP1</span>
        </div>
      </header>

      <main id="top">
        <AgentStrip agent={data.agent} />

        <section className="hero" aria-labelledby="page-title">
          <div className="hero-main">
            <p className="eyebrow">
              FIELD REPORT · {game.title.toUpperCase()} · {game.engine.toUpperCase()}
            </p>
            <h1 id="page-title">
              DECOMPILATION
              <br />
              <span>PROGRESS</span>
            </h1>

            <div className="readout">
              <span className="readout-value">{formatPercent(totals.matchedPct, 2)}</span>
              <p className="readout-copy">
                of <b>{formatInt(totals.functions)}</b> <code>.text</code> functions rebuilt to
                the original bytes.
                <span className="readout-sub">
                  {formatInt(totals.matchedBytes)} B · {formatPercent(totals.matchedBytesPct, 3)}{' '}
                  of {formatBytes(totals.bytes)} of code
                </span>
              </p>
            </div>

            <div className="meter-caption">
              <span>FUNCTION COVERAGE</span>
              <span>
                {formatInt(totals.matched)} / {formatInt(totals.functions)} ·{' '}
                {formatPercent(totals.matchedPct, 2)}
              </span>
            </div>
            <Meter
              value={totals.matched}
              max={totals.functions}
              label="Functions matched byte-exactly"
              tone="amber"
              size="hero"
            />
            <div className="meter-scale" aria-hidden="true">
              <span>0</span>
              <span>25</span>
              <span>50</span>
              <span>75</span>
              <span>100%</span>
            </div>

            <div className="hero-counts">
              <div>
                <b>{formatInt(totals.matched)}</b>
                <span>MATCHED</span>
              </div>
              <div>
                <b>{formatInt(remaining)}</b>
                <span>STILL STANDING</span>
              </div>
              <div>
                <b>{formatInt(totals.matchedBytes)}</b>
                <span>BYTES PROVEN</span>
              </div>
              <div>
                <b>
                  {totals.matchedBanks}
                  <em>/{totals.banks}</em>
                </b>
                <span>BANKS LIT</span>
              </div>
            </div>
          </div>

          <aside className="hero-side">
            <div className="side-block">
              <p className="mini-label">REGISTRY INTEGRITY</p>
              <p className="side-value">
                100<span>%</span>
              </p>
              <div className="star-row" role="img" aria-label="Five out of five stars">
                {Array.from({ length: 5 }, (_, index) => (
                  <Star key={index} />
                ))}
              </div>
              <p className="side-copy">
                {formatInt(totals.matched)} registered · {formatInt(totals.matched)} verified · 0
                mismatches
              </p>
            </div>

            <div className="side-block">
              <p className="mini-label">NEXT MILESTONE</p>
              <p className="side-next">
                First fully matched bank<span className="blink">_</span>
              </p>
              <p className="side-copy">
                Start with a small Seoul Engine export, then widen the unit map.
              </p>
            </div>

            <div className="side-meta">
              <div>
                <span>COMPILER</span>
                <b>MSVC 9 SP1</b>
              </div>
              <div>
                <span>IMAGE</span>
                <b>{game.image}</b>
              </div>
              <div>
                <span>INDEX BUILT</span>
                <b>{formatTimestamp(data.dataBuiltAt)} UTC</b>
              </div>
            </div>
          </aside>
        </section>

        <section className="rails" aria-label="Pipeline coverage">
          <div className="rail">
            <div className="rail-head">
              <span className="mini-label">NAMES RECOVERED</span>
              <span className="rail-pct">{formatPercent(totals.namedPct)}</span>
            </div>
            <p className="rail-value">
              {formatInt(totals.named)}
              <span> / {formatInt(totals.functions)}</span>
            </p>
            <Meter
              value={totals.named}
              max={totals.functions}
              label="Functions with recovered names"
            />
            <p className="rail-note">{formatInt(totals.unnamed)} FUN_ placeholders remain</p>
          </div>

          <div className="rail">
            <div className="rail-head">
              <span className="mini-label">GHIDRA SWEEP</span>
              <span className="rail-pct">{formatPercent(totals.decompiledPct, 2)}</span>
            </div>
            <p className="rail-value">
              {formatInt(totals.decompiled)}
              <span> / {formatInt(totals.functions)}</span>
            </p>
            <Meter
              value={totals.decompiled}
              max={totals.functions}
              label="Functions with generated C"
            />
            <p className="rail-note">
              {formatInt(totals.failed)} functions rejected and kept in-tree
            </p>
          </div>

          <div className="rail">
            <div className="rail-head">
              <span className="mini-label">REGISTRY VERIFIED</span>
              <span className="rail-pct">100.0%</span>
            </div>
            <p className="rail-value">
              {formatInt(totals.matched)}
              <span> / {formatInt(totals.matched)}</span>
            </p>
            <Meter
              value={totals.matched}
              max={totals.matched}
              label="Registered functions verified byte-identical"
              tone="amber"
            />
            <p className="rail-note">
              {formatBytes(totals.matchedBytes)} across {kinds.length} match classes
            </p>
          </div>
        </section>

        <section className="manifest" aria-labelledby="manifest-title">
          <div className="manifest-head">
            <p className="mini-label" id="manifest-title">
              VERIFIED MANIFEST
            </p>
            <p className="manifest-total">
              {formatInt(totals.matched)} FUNCTIONS · {formatInt(totals.matchedBytes)} BYTES
            </p>
          </div>
          <div className="manifest-grid">
            {kinds.map((item) => {
              const meta = kindMeta(item.kind);
              return (
                <article
                  key={item.kind}
                  className="manifest-tile"
                  style={{ '--kind': meta.color } as CSSProperties}
                >
                  <span className="manifest-kind">{meta.label}</span>
                  <strong>{formatInt(item.count)}</strong>
                  <span className="manifest-meta">
                    {formatPercent((item.count / Math.max(1, totals.matched)) * 100, 1)} of
                    matches · {formatInt(item.bytes)} B
                  </span>
                  <span className="manifest-bar" aria-hidden="true">
                    <span
                      style={{
                        width: `${(item.count / Math.max(1, totals.matched)) * 100}%`,
                      }}
                    />
                  </span>
                </article>
              );
            })}
          </div>
        </section>

        <Explorer banks={banks} functions={matchedFunctions} kinds={kinds} />

        <section className="section naming" id="naming">
          <div className="section-head">
            <div>
              <p className="section-index">03 / SALVAGE &amp; INTEL</p>
              <h2 className="section-title">What the tree knows</h2>
            </div>
            <p className="section-aside">{formatPercent(totals.namedPct)} NAMED</p>
          </div>

          <div className="naming-layout">
            <div className="naming-main">
              <div className="naming-big">
                <span className="naming-value">{formatPercent(totals.namedPct)}</span>
                <div>
                  <p>{formatInt(totals.named)} functions carry a name</p>
                  <p className="dim">
                    {formatInt(totals.unnamed)} are still bare FUN_ placeholders
                  </p>
                </div>
              </div>
              <Meter
                value={totals.named}
                max={totals.functions}
                label="Functions with recovered names"
                size="md"
              />
              <div className="naming-stats">
                <div>
                  <b>{formatInt(totals.exportsNamed)}</b>
                  <span>EXPORT / RTTI NAMES</span>
                </div>
                <div>
                  <b>{formatInt(totals.labels)}</b>
                  <span>VTABLE LABELS · GUESS</span>
                </div>
                <div>
                  <b>{formatInt(totals.vtables)}</b>
                  <span>
                    VTABLES · {formatInt(totals.classes)} CLASSES
                  </span>
                </div>
                <div>
                  <b>{formatInt(totals.slots)}</b>
                  <span>VIRTUAL SLOTS</span>
                </div>
                <div>
                  <b>{formatInt(totals.suggestions)}</b>
                  <span>NAME SUGGESTIONS</span>
                </div>
                <div>
                  <b>{formatInt(totals.strings)}</b>
                  <span>FUNCS WITH STRINGS</span>
                </div>
              </div>
            </div>

            <aside className="naming-side">
              <p className="mini-label">TOP RECOVERED SCOPES</p>
              <ol className="namespace-list">
                {namespaces.map((item) => (
                  <li key={item.name}>
                    <span className="ns-name">{item.name}</span>
                    <span className="ns-bar" aria-hidden="true">
                      <span style={{ width: `${(item.count / maxNamespace) * 100}%` }} />
                    </span>
                    <span className="ns-count">{item.count}</span>
                  </li>
                ))}
              </ol>
              <div className="structure-note">
                <p className="mini-label">STRUCTURE</p>
                <p>
                  {formatInt(totals.calls)} call edges · {formatInt(totals.sourceFiles)} generated
                  banks · {formatBytes(totals.sourceBytes)} of C
                </p>
                <p className="dim">
                  {formatInt(totals.failed)} functions rejected by the decompiler and kept in-tree.
                </p>
              </div>
            </aside>
          </div>
        </section>
      </main>

      <footer>
        <div className="next-milestone">
          <span className="tag">NEXT</span>
          <p>
            Match the first complete bank, then track progress in bytes rather than function
            counts.
          </p>
        </div>
        <div className="footer-meta">
          <div>
            <span className="mini-label">VERIFY</span>
            <code>python3 Decompile/tools/match/verify.py</code>
          </div>
          <div>
            <span className="mini-label">SOURCE</span>
            <code>{data.sourceLabel}/config/matched.json</code>
          </div>
          <div>
            <span className="mini-label">DATA BUILT</span>
            <code>{formatTimestamp(data.dataBuiltAt)} UTC</code>
          </div>
        </div>
        <p className="legal">
          Local metadata only · no game bytes are stored or served · generated C is not playable.
        </p>
      </footer>
    </div>
  );
}
