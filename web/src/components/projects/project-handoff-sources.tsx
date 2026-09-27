"use client";

import Link from "next/link";

export type HandoffSourceCheck = {
  key: string;
  label: string;
  tab: string;
  count: number;
  digest: string;
  accepted_count: number | null;
  changed: boolean | null;
};

export function ProjectHandoffSources({ projectId, sources, reasons }: {
  projectId: string;
  sources: HandoffSourceCheck[];
  reasons: string[];
}) {
  return <div className="space-y-2 border-t pt-3">
    {reasons.length > 0 && <ul className="space-y-1 text-xs text-muted-foreground" aria-label="接收待办原因">
      {reasons.map(reason => <li key={reason}>{reason}</li>)}
    </ul>}
    {sources.length > 0 && <details>
      <summary className="cursor-pointer text-xs font-medium">核对业务依据 · {sources.length} 类</summary>
      <p className="my-2 text-xs text-muted-foreground">核对本项目已登记记录及修订。数量包含历史记录；没有记录仍须按适用要求补证，数量不代表合格或交接完整。</p>
      <ul className="divide-y text-xs">
        {sources.map(source => <li key={source.key} className="space-y-1 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Link prefetch={false} href={`/projects?project=${projectId}&tab=${source.tab}`} className="text-primary underline underline-offset-4">{source.label}</Link>
            <span className="font-mono tabular-nums">{source.count} 条</span>
          </div>
          <p className={source.changed ? "text-primary" : "text-muted-foreground"}>
            {source.changed === null ? "尚无本版接收依据，待核对" : source.changed ? `与原接收依据不同（原 ${source.accepted_count} 条）` : "与原接收依据一致"}
          </p>
          <details className="text-muted-foreground"><summary className="cursor-pointer">查看当前校验摘要</summary><p className="mt-1 break-all font-mono">{source.digest}</p></details>
        </li>)}
      </ul>
    </details>}
  </div>;
}
