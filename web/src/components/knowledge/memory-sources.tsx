"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

const states: Record<string, string> = { current: "按当前登记的依据核对，未发现失效项", manual: "已人工审核，未登记外部版本依据", unverified: "知识尚未审核或已归档", stale: "部分依据已失效或不可用，暂停复用", needs_review: "部分来源版本无法核对，需先复核" };
const sourceStates: Record<string, string> = { current: "当前依据有效", historical: "历史出处，保留原记录", stale: "已变化、过期或存在冲突", unavailable: "来源不可用", needs_review: "缺少可核对的版本依据" };
const kinds: Record<string, string> = { fmea_publication: "已发布 FMEA 与原质量证据", event: "业务事件", root_cause: "已批准根因版本", effectiveness_review: "有效性复核版本", test_run: "逐次测试依据", decision: "决策依据", meeting_retrospective: "已确认复盘结论", issue: "问题闭环", ncr: "NCR闭环", closure_evidence: "关闭证据", memory_correction: "知识修正历史", evidence_snapshot: "证据快照", document: "文档版本", specification: "产品规格" };
type Assessment = { state: string; sources: { kind: string; reference: string; state: string }[] };
function parse(value: unknown): Assessment {
  if (!isRecord(value) || typeof value.state !== "string" || !Object.hasOwn(states, value.state) || !Array.isArray(value.sources)) throw new Error("来源核对记录不完整");
  return { state: value.state, sources: value.sources.map(source => {
    if (!isRecord(source) || typeof source.state !== "string" || !Object.hasOwn(sourceStates, source.state)) throw new Error("来源状态不完整");
    return { kind: typeof source.kind === "string" ? source.kind : "unknown", reference: typeof source.reference === "string" ? source.reference : "未登记", state: source.state };
  }) };
}
export function MemorySources({ projectId, memoryId }: { projectId: string; memoryId: string }) {
  const [data, setData] = useState<Assessment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function load() {
    setBusy(true); setData(null); setError(null);
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/memories/${encodeURIComponent(memoryId)}/sources`, { cache: "no-store" });
      const value: unknown = await responseBody(response).catch(() => null);
      if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "来源核对暂不可用");
      setData(parse(value));
    } catch (error) { setError(error instanceof Error ? error.message : "来源核对暂不可用"); }
    finally { setBusy(false); }
  }
  return <div className="mt-2 space-y-2">
    <Button size="sm" variant="outline" disabled={busy} onClick={load}>{busy ? "正在核对来源…" : "核对来源与当前版本"}</Button>
    {data && <div className="space-y-2 rounded-lg border p-3 text-xs"><p>{states[data.state]}</p><ul className="space-y-2">{data.sources.map((source, index) => <li key={index} className="break-words"><p>{kinds[source.kind] ?? "其他来源"} · {sourceStates[source.state]}</p><p className="mt-1 text-muted-foreground">{source.reference}</p></li>)}</ul></div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </div>;
}
