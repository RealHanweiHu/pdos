"use client";

import { RiskCandidateReview } from "./risk-candidate-review";
import { FindingArchivePolicy, FindingLifecycle } from "./finding-lifecycle";
import { useState } from "react";

import { cn } from "@/lib/utils";

import {
  archiveStaleFindings,
  restoreFinding,
} from "./ai-api";
import type { AiFinding, ReviewInboxDigest, RiskCandidate } from "./ai-types";

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

export function ReviewInboxExtras({
  actorKey,
  archived,
  candidatesByProject,
  digest,
  onNotice,
  onRefresh,
  projectNames,
  refreshing = false,
}: {
  actorKey?: string;
  archived: AiFinding[];
  candidatesByProject: Record<string, RiskCandidate[]>;
  digest: ReviewInboxDigest | null;
  onNotice: (notice: { status?: string; error?: string }) => void;
  onRefresh: () => Promise<void>;
  projectNames: Record<string, string>;
  refreshing?: boolean;
}) {
  const [submitting, setBusy] = useState(false);
  const busy = submitting || refreshing;
  const [archivesExpanded, setArchivesExpanded] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    onNotice({});
    try {
      await action();
      await onRefresh();
    } catch (error) {
      onNotice({ error: messageFrom(error) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 space-y-4">
      {digest ? (
        <dl
          aria-label="待办摘要"
          className="flex flex-wrap overflow-hidden rounded-lg border bg-card text-center"
        >
          {[
            ["待审 Finding", digest.finding_count],
            ["规则风险候选", digest.risk_candidate_count],
            ["导入待确认", digest.import_batch_count],
            ["已归档", digest.archived_count],
          ].map(([label, count], index) => (
            <div className={cn("min-w-28 px-3 py-2", index > 0 && "border-l")} key={label}>
              <dt className="text-[10px] text-muted-foreground">{label}</dt>
              <dd className="mt-0.5 font-mono text-base font-semibold">{count}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      <RiskCandidateReview actorKey={actorKey} candidatesByProject={candidatesByProject} projectNames={projectNames}
        refreshing={refreshing} onNotice={onNotice} onRefresh={onRefresh} />

      <section aria-label="归档治理" className="rounded-lg border bg-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">确认疲劳治理</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              超过处理期的待审建议可归档并恢复；手动扫描每次最多处理 200 条。
            </p>
          </div>
          {archived.length > 0 ? <button aria-expanded={archivesExpanded} className="min-h-11 rounded-lg border px-3 text-xs font-medium sm:min-h-8" onClick={() => setArchivesExpanded((current) => !current)} type="button">{archivesExpanded ? "收起归档" : `展开归档（${archived.length}）`}</button> : null}
          <button
            className="min-h-11 rounded-lg border px-3 text-xs font-medium sm:min-h-8"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const swept = await archiveStaleFindings();
                onNotice({
                  status:
                    swept.length === 0
                      ? "没有超过 14 天未处理的 Finding"
                      : `已归档 ${swept.length} 条过期 Finding，可随时恢复`,
                });
              })
            }
            type="button"
          >
            归档 14 天以上未处理
          </button>
        </div>
        <FindingArchivePolicy/>
        {archivesExpanded && archived.length > 0 ? (
          <ul className="mt-3 max-h-96 space-y-2 overflow-y-auto" role="list">
            {archived.map((finding) => (
              <li
                className="flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2"
                key={finding.id}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{finding.title}</p>
                  <p className="text-xs text-muted-foreground">已归档 · {finding.agent_key}</p>
                  <FindingLifecycle findingId={finding.id}/>
                </div>
                <button
                  className="min-h-11 rounded-lg border px-3 text-xs sm:min-h-8"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await restoreFinding(finding.id);
                      onNotice({ status: "Finding 已恢复到待审队列" });
                    })
                  }
                  type="button"
                >
                  恢复
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  );
}
