import { NextResponse } from 'next/server';
import { loadProgress } from '@/lib/progress';

export const dynamic = 'force-dynamic';

export async function GET() {
  const data = loadProgress();

  if (!data.ok) {
    return NextResponse.json(
      { error: data.reason, detail: data.detail, expected: data.expected },
      { status: 503 },
    );
  }

  return NextResponse.json(
    {
      schema: 'smr-decomp-progress/1',
      project: data.game.title,
      image: data.game.image,
      compiler: data.game.compiler,
      clVersion: data.game.clVersion,
      dataBuiltAt: data.dataBuiltAt,
      matched: {
        functions: data.totals.matched,
        bytes: data.totals.matchedBytes,
        percent: Number(data.totals.matchedPct.toFixed(4)),
        bytePercent: Number(data.totals.matchedBytesPct.toFixed(4)),
        banks: data.totals.matchedBanks,
      },
      total: {
        functions: data.totals.functions,
        bytes: data.totals.bytes,
        banks: data.totals.banks,
      },
      named: {
        functions: data.totals.named,
        percent: Number(data.totals.namedPct.toFixed(4)),
        unnamed: data.totals.unnamed,
      },
      decompiled: {
        functions: data.totals.decompiled,
        failed: data.totals.failed,
      },
      agent: {
        attached: data.agent.attached,
        state: data.agent.state,
        task: data.agent.task,
        updatedAt: data.agent.updatedAt,
      },
      kinds: data.kinds,
    },
    { headers: { 'Cache-Control': 'no-store' } },
  );
}
