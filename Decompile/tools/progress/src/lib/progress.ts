import { existsSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

export interface MatchedFunction {
  address: string;
  name: string;
  size: number;
  bank: string;
  kind: string;
  source: string;
  note: string;
}

export interface BankProgress {
  name: string;
  index: number;
  total: number;
  matched: number;
  bytes: number;
  matchedBytes: number;
}

export interface KindProgress {
  kind: string;
  count: number;
  bytes: number;
}

export interface NamespaceCount {
  name: string;
  count: number;
}

export type AgentState = 'working' | 'idle' | 'blocked' | 'unknown';

export interface AgentStatus {
  attached: boolean;
  state: AgentState;
  agent: string;
  task: string;
  detail: string;
  updatedAt: string | null;
}

export interface ProgressTotals {
  functions: number;
  bytes: number;
  matched: number;
  matchedBytes: number;
  matchedPct: number;
  matchedBytesPct: number;
  named: number;
  namedPct: number;
  unnamed: number;
  unnamedPct: number;
  decompiled: number;
  failed: number;
  decompiledPct: number;
  strings: number;
  calls: number;
  banks: number;
  matchedBanks: number;
  sourceBytes: number;
  sourceFiles: number;
  vtables: number;
  classes: number;
  slots: number;
  labels: number;
  suggestions: number;
  exportsNamed: number;
}

export interface ProgressData {
  ok: true;
  game: {
    title: string;
    developer: string;
    engine: string;
    release: string;
    compiler: string;
    clVersion: string;
    image: string;
    sha256: string;
  };
  dataBuiltAt: string;
  sourceLabel: string;
  totals: ProgressTotals;
  kinds: KindProgress[];
  banks: BankProgress[];
  matchedFunctions: MatchedFunction[];
  namespaces: NamespaceCount[];
  agent: AgentStatus;
}

export interface ProgressMissing {
  ok: false;
  reason: string;
  detail: string;
  root: string | null;
  expected: string[];
}

export type ProgressResult = ProgressData | ProgressMissing;

interface FunctionRecord {
  addr: string;
  name: string;
  size: number;
  bank: string;
  decompiled: boolean;
  signature?: string;
  calls?: string[];
  strings?: string[];
}

interface MatchedRecord {
  address: string;
  size: number;
  symbol?: string;
  source?: string;
  note?: string;
  kind?: string;
}

interface ProgressCache {
  version: number;
  key: string;
  value: ProgressResult;
}

const PROGRESS_CACHE_VERSION = 2;

const globalForCache = globalThis as typeof globalThis & {
  __smrProgressCache?: ProgressCache;
};

export function findDecompileRoot(): string | null {
  const override = process.env.SMR_DECOMPILE_ROOT;
  if (override && existsSync(path.join(override, 'config', 'matched.json'))) {
    return path.resolve(override);
  }

  const seen = new Set<string>();
  let dir = process.cwd();
  for (let depth = 0; depth < 8; depth += 1) {
    for (const candidate of [dir, path.join(dir, 'Decompile')]) {
      if (seen.has(candidate)) continue;
      seen.add(candidate);
      if (existsSync(path.join(candidate, 'config', 'matched.json'))) {
        return candidate;
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function normalizeAddress(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/^0x/, '')
    .replace(/[^0-9a-f]/g, '')
    .padStart(8, '0')
    .slice(-8);
}

function readJson<T>(file: string): T {
  return JSON.parse(readFileSync(file, 'utf8')) as T;
}

function countCsvRows(file: string): number {
  if (!existsSync(file)) return 0;
  const text = readFileSync(file, 'utf8').trim();
  if (!text) return 0;
  return Math.max(0, text.split('\n').length - 1);
}

function readVtableFacts(file: string): { vtables: number; classes: number; slots: number } {
  const text = readFileSync(file, 'utf8').trim();
  if (!text) return { vtables: 0, classes: 0, slots: 0 };
  const lines = text.split('\n').slice(1);
  const classes = new Set<string>();
  let slots = 0;
  for (const line of lines) {
    const cells = line.split(',');
    if (cells[1]) classes.add(cells[1]);
    const count = Number(cells[2]);
    if (Number.isFinite(count)) slots += count;
  }
  return { vtables: lines.length, classes: classes.size, slots };
}

function pct(part: number, whole: number): number {
  return whole > 0 ? (part / whole) * 100 : 0;
}

export function agentStatusPath(root: string): string {
  return path.join(path.dirname(root), 'work', 'dev', 'agent-status.json');
}

function readAgentStatus(root: string): AgentStatus {
  const file = agentStatusPath(root);
  const empty: AgentStatus = {
    attached: false,
    state: 'unknown',
    agent: '',
    task: '',
    detail: '',
    updatedAt: null,
  };

  if (!existsSync(file)) return empty;

  try {
    const raw = JSON.parse(readFileSync(file, 'utf8')) as Record<string, unknown>;
    const stateValue = typeof raw.state === 'string' ? raw.state.toLowerCase() : '';
    const state: AgentState =
      stateValue === 'working' || stateValue === 'idle' || stateValue === 'blocked'
        ? stateValue
        : 'unknown';
    const updatedValue = typeof raw.updatedAt === 'string' ? Date.parse(raw.updatedAt) : NaN;

    return {
      attached: true,
      state,
      agent: typeof raw.agent === 'string' ? raw.agent : '',
      task: typeof raw.task === 'string' ? raw.task : '',
      detail: typeof raw.detail === 'string' ? raw.detail : '',
      updatedAt: Number.isNaN(updatedValue) ? null : new Date(updatedValue).toISOString(),
    };
  } catch {
    return {
      ...empty,
      detail: 'Agent status file is not valid JSON.',
    };
  }
}

function buildProgress(root: string): ProgressResult {
  const buildDir = path.join(root, 'build', 'game');
  const configDir = path.join(root, 'config');
  const required = {
    functions: path.join(buildDir, 'functions.jsonl'),
    matched: path.join(configDir, 'matched.json'),
    project: path.join(configDir, 'project.json'),
    vtables: path.join(buildDir, 'vtables.csv'),
  };

  const missing = Object.entries(required)
    .filter(([, file]) => !existsSync(file))
    .map(([name, file]) => `${name}: ${path.relative(root, file)}`);

  if (missing.length > 0) {
    return {
      ok: false,
      reason: 'INDEX TREE INCOMPLETE',
      detail:
        'The dashboard reads the generated decompilation indexes directly. Regenerate them with the export pipeline, then refresh this page.',
      root,
      expected: missing,
    };
  }

  const functionsRaw = readFileSync(/* turbopackIgnore: true */ required.functions, 'utf8');
  const functions: FunctionRecord[] = [];
  for (const line of functionsRaw.split('\n')) {
    if (line.trim()) functions.push(JSON.parse(line) as FunctionRecord);
  }

  const registry = readJson<{ functions?: MatchedRecord[]; cl_version?: string }>(required.matched);
  const matchedRecords = registry.functions ?? [];
  const project = readJson<{
    game?: string;
    developer?: string;
    engine?: string;
    release?: string;
    toolchain?: { compiler?: string };
    pe?: { exports?: number };
    sha256?: string;
  }>(required.project);

  const byAddress = new Map<string, FunctionRecord>();
  const byBank = new Map<string, BankProgress>();
  let totalBytes = 0;
  let named = 0;
  let decompiled = 0;
  let strings = 0;
  let calls = 0;
  const namespaces = new Map<string, number>();

  for (const fn of functions) {
    byAddress.set(normalizeAddress(fn.addr), fn);
    totalBytes += fn.size;
    if (!fn.name.startsWith('FUN_') && !fn.name.startsWith('thunk_')) {
      named += 1;
      const scope = fn.name.split('::')[0];
      if (scope && scope !== fn.name && !scope.toUpperCase().endsWith('.DLL')) {
        namespaces.set(scope, (namespaces.get(scope) ?? 0) + 1);
      }
    }
    if (fn.decompiled) decompiled += 1;
    if ((fn.strings?.length ?? 0) > 0) strings += 1;
    calls += fn.calls?.length ?? 0;

    const bank =
      byBank.get(fn.bank) ??
      ({
        name: fn.bank,
        index: Number(fn.bank.replace(/\D/g, '')) || 0,
        total: 0,
        matched: 0,
        bytes: 0,
        matchedBytes: 0,
      } satisfies BankProgress);
    bank.total += 1;
    bank.bytes += fn.size;
    byBank.set(fn.bank, bank);
  }

  const kinds = new Map<string, KindProgress>();
  const matchedFunctions: MatchedFunction[] = [];

  for (const record of matchedRecords) {
    const address = normalizeAddress(record.address);
    const fn = byAddress.get(address);
    const kind = record.kind ?? 'unknown';
    const size = Number(record.size) || fn?.size || 0;

    const kindEntry = kinds.get(kind) ?? { kind, count: 0, bytes: 0 };
    kindEntry.count += 1;
    kindEntry.bytes += size;
    kinds.set(kind, kindEntry);

    const bankName = fn?.bank ?? 'unknown';
    const bank = byBank.get(bankName);
    if (bank) {
      bank.matched += 1;
      bank.matchedBytes += size;
    }

    matchedFunctions.push({
      address: `0x${address}`,
      name: fn?.name ?? `FUN_${address}`,
      size,
      bank: bankName,
      kind,
      source: record.source ?? '',
      note: record.note ?? '',
    });
  }

  matchedFunctions.sort((a, b) => a.address.localeCompare(b.address));

  const banks = [...byBank.values()].sort((a, b) => a.index - b.index);
  const matchedBytes = matchedFunctions.reduce((sum, fn) => sum + fn.size, 0);
  const matchedBanks = banks.filter((bank) => bank.matched > 0).length;

  const vtableFacts = readVtableFacts(required.vtables);
  const labels = countCsvRows(path.join(buildDir, 'names_applied.csv'));
  const suggestions = countCsvRows(path.join(buildDir, 'suggested_names.csv'));

  let sourceBytes = 0;
  let sourceFiles = 0;
  for (const bank of banks) {
    try {
      sourceBytes += statSync(path.join(root, 'src', 'game', `${bank.name}.c`)).size;
      sourceFiles += 1;
    } catch {
      // Generated source is optional; indexes alone are enough for the dashboard.
    }
  }

  const totals: ProgressTotals = {
    functions: functions.length,
    bytes: totalBytes,
    matched: matchedFunctions.length,
    matchedBytes,
    matchedPct: pct(matchedFunctions.length, functions.length),
    matchedBytesPct: pct(matchedBytes, totalBytes),
    named,
    namedPct: pct(named, functions.length),
    unnamed: functions.length - named,
    unnamedPct: pct(functions.length - named, functions.length),
    decompiled,
    failed: functions.length - decompiled,
    decompiledPct: pct(decompiled, functions.length),
    strings,
    calls,
    banks: banks.length,
    matchedBanks,
    sourceBytes,
    sourceFiles,
    vtables: vtableFacts.vtables,
    classes: vtableFacts.classes,
    slots: vtableFacts.slots,
    labels,
    suggestions,
    exportsNamed: Math.max(0, named - labels),
  };

  const builtAt = Math.max(
    statSync(/* turbopackIgnore: true */ required.functions).mtimeMs,
    statSync(/* turbopackIgnore: true */ required.matched).mtimeMs,
  );

  return {
    ok: true,
    game: {
      title: project.game ?? 'Shoot Many Robots',
      developer: project.developer ?? 'Demiurge Studios',
      engine: project.engine ?? 'Seoul Engine',
      release: project.release ?? 'Windows PC (Steam), 2012',
      compiler: project.toolchain?.compiler ?? 'Microsoft Visual C++ 2008 (cl 15.00, VC9)',
      clVersion: registry.cl_version ?? '15.00.30729.01',
      image: 'ShootManyRobots.exe',
      sha256: project.sha256 ?? '',
    },
    dataBuiltAt: new Date(builtAt).toISOString(),
    sourceLabel:
      path.basename(root) === 'Decompile'
        ? 'Decompile'
        : path.relative(process.cwd(), root) || '.',
    totals,
    kinds: [...kinds.values()].sort((a, b) => b.count - a.count),
    banks,
    matchedFunctions,
    namespaces: [...namespaces.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8),
    agent: readAgentStatus(root),
  };
}

export function loadProgress(): ProgressResult {
  const root = findDecompileRoot();
  if (!root) {
    return {
      ok: false,
      reason: 'NO DECOMPILE ROOT',
      detail:
        'Could not find Decompile/config/matched.json from the dashboard working directory. Set SMR_DECOMPILE_ROOT to the Decompile folder.',
      root: null,
      expected: ['config/matched.json', 'build/game/functions.jsonl'],
    };
  }

  const watched = [
    path.join(root, 'config', 'matched.json'),
    path.join(root, 'build', 'game', 'functions.jsonl'),
    path.join(root, 'build', 'game', 'vtables.csv'),
    path.join(root, 'build', 'game', 'names_applied.csv'),
    path.join(root, 'build', 'game', 'suggested_names.csv'),
    path.join(root, 'config', 'project.json'),
  ];

  const statusFile = agentStatusPath(root);
  if (existsSync(statusFile)) watched.push(statusFile);

  let key: string;
  try {
    key = watched.map((file) => `${file}:${statSync(file).mtimeMs}`).join('|');
  } catch {
    return buildProgress(root);
  }

  if (
    globalForCache.__smrProgressCache?.version === PROGRESS_CACHE_VERSION &&
    globalForCache.__smrProgressCache.key === key
  ) {
    return globalForCache.__smrProgressCache.value;
  }

  const value = buildProgress(root);
  globalForCache.__smrProgressCache = { version: PROGRESS_CACHE_VERSION, key, value };
  return value;
}
