export const KIND_META: Record<string, { label: string; short: string; color: string }> = {
  tail_thunk: {
    label: 'Tail-call thunk',
    short: 'THUNK',
    color: '#4f7325',
  },
  accessor: {
    label: 'Field accessor',
    short: 'ACCESSOR',
    color: '#a8740f',
  },
  reloc: {
    label: 'Relocated function',
    short: 'RELOC',
    color: '#2b6f7d',
  },
  thiscall: {
    label: 'This-call thunk',
    short: 'THISCALL',
    color: '#5b6f2c',
  },
  setter: {
    label: 'Field setter',
    short: 'SETTER',
    color: '#8d5b1c',
  },
  float_copy: {
    label: 'Float copy',
    short: 'FLOAT',
    color: '#2f6570',
  },
  wrapper: {
    label: 'Wrapper',
    short: 'WRAPPER',
    color: '#7a3d2c',
  },
  call_copy: {
    label: 'Call copy',
    short: 'CALL COPY',
    color: '#5b6f2c',
  },
  dtor_wrapper: {
    label: 'Destructor wrapper',
    short: 'DTOR',
    color: '#8a5a1f',
  },
  leaf: {
    label: 'Leaf sanity check',
    short: 'LEAF',
    color: '#8c3b2a',
  },
  unknown: {
    label: 'Unclassified',
    short: 'UNKNOWN',
    color: '#6b5e49',
  },
};

export function kindMeta(kind: string) {
  return (
    KIND_META[kind] ?? {
      label: kind.replaceAll('_', ' '),
      short: kind.replaceAll('_', ' ').toUpperCase(),
      color: '#8a9c7d',
    }
  );
}

export function formatInt(value: number): string {
  return new Intl.NumberFormat('en-US').format(value);
}

export function formatPercent(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return '—';
  if (value > 0 && value < 0.01) return '<0.01%';
  return `${value.toFixed(digits)}%`;
}

export function formatBytes(value: number): string {
  if (value < 1000) return `${formatInt(value)} B`;
  if (value < 1_000_000) return `${(value / 1000).toFixed(1)} KB`;
  return `${(value / 1_000_000).toFixed(2)} MB`;
}

export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'UNKNOWN';
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  })
    .format(date)
    .toUpperCase()
    .replace(',', '');
}

export function formatAge(iso: string, now = Date.now()): string {
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return 'UNKNOWN';
  const seconds = Math.max(0, Math.floor((now - time) / 1000));
  if (seconds < 45) return 'JUST NOW';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 1) return 'JUST NOW';
  if (minutes < 60) return `${minutes}M AGO`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}H AGO`;
  return `${Math.floor(hours / 24)}D AGO`;
}
