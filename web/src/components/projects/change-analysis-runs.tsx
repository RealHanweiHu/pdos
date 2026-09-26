"use client";

import { useRef, useState } from "react";
import { ConversationFinding } from "@/components/ai/conversation-finding";
import { ChangeToolReceipts } from "@/components/ai/change-tool-receipts";
import { ChangeAssessmentView } from "@/components/ai/change-work-package-proposal";
import { ChangeDiscussionContinuation } from "@/components/ai/change-discussion-continuation";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const obj = (value: unknown): Row => isRecord(value) ? value : {};
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const text = (value: unknown) => value == null ? "未记录" : String(value);
const statuses: Record<string, string> = { queued: "等待处理", running: "处理中", succeeded: "处理完成", degraded: "未完成", failed: "已停止" };
export function ChangeAnalysisRuns({ projectId, ecrId, sourceDigest, depth, includeSupplierNotices = false }: { projectId: string; ecrId: string; sourceDigest: string; depth: number; includeSupplierNotices?: boolean }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [allowDiscussion, setAllowDiscussion] = useState(false);
  const attempt = useRef<{ id: string; signature: string } | null>(null);
  const base = `/api/projects/${projectId}/changes/ecrs/${ecrId}/analysis-runs`;
  async function request(path = "", body?: unknown): Promise<Row> {
    const response = await fetch(base + path, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const value: unknown = await response.json();
    if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "分析请求未完成，请读取原记录");
    return value;
  }
  async function act(fn: () => Promise<void>) { setBusy(true); setError(null); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); } }
  async function read(more = false) {
    const value = await request(more && data?.next_before_id ? `?before_id=${text(data.next_before_id)}` : "");
    setData(old => more && old ? { ...value, items: [...rows(old.items), ...rows(value.items)] } : value);
  }
  const ordinaryLive = data?.rollout === "live";
  const live = ordinaryLive && (!includeSupplierNotices || data?.notice_rollout === "live");
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(() => read()); }}>
    <summary className="cursor-pointer font-medium">分析建议与运行记录</summary>
    <div className="mt-3 space-y-3">
      <p>按上方已读取的 {depth} 层资料准备带引用的逐对象建议。建议需要人工核对，接受与应用分别办理。</p>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {data && !live && <p className="text-muted-foreground">此项能力尚待阶段评测，目前未开放生成。</p>}
      {data?.can_request === true && <form className="space-y-2" onSubmit={e => { e.preventDefault(); void act(async () => {
        const payload = { expected_digest: sourceDigest, depth, user_instruction: instruction.trim(), allow_discussion: allowDiscussion, include_supplier_notices: includeSupplierNotices };
        const signature = JSON.stringify(payload);
        if (attempt.current?.signature !== signature) attempt.current = { id: crypto.randomUUID(), signature };
        await request("", { ...payload, request_id: attempt.current.id });
        await read();
      }); }}><label className="block">本次重点核对什么<textarea maxLength={10000} disabled={busy || !live} className="mt-1 w-full rounded-md border bg-background p-2" value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="例如：替代物料涉及哪些规格、当次配置和复验要求"/></label><label className="flex items-center gap-2"><input type="checkbox" checked={allowDiscussion} disabled={busy || (includeSupplierNotices ? data.notice_discussion_available : data.discussion_available) !== true} onChange={e => setAllowDiscussion(e.target.checked)}/>允许 Agent 发起专业讨论，并在完成后继续分析</label>{includeSupplierNotices && <p>通告版使用固定原文与具名人审；专业讨论及后续分析须通过对应阶段评测后启用。</p>}<p>发起判断、讨论和讨论后的分析共用本请求累计预算。讨论完整结束且原资料仍有效时，后台生成单独的新候选供人工核对；未完成、资料变化或预算不足时保留停止原因。</p><Button type="submit" size="sm" disabled={busy || !live}>按本次资料准备待审建议</Button></form>}
      <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void act(() => read())}>读取最新运行记录</Button>
      {rows(data?.items).map(item => {
        const assessment = obj(item.assessment), labels=obj(item.reference_labels);
        return <details className="space-y-2 rounded-md border p-2" key={text(item.run_id)}><summary className="cursor-pointer">{text(item.created_at)} · {item.include_supplier_notices === true ? "含厂商通告 · " : ""}{statuses[text(item.status)] ?? text(item.status)} · {item.discussion_input != null ? "讨论后的分析 · " : ""}{item.finding_id ? "已形成候选，展开查看当前裁决" : item.disposition === "insufficient_evidence" ? "资料不足" : "尚无待审建议"}</summary>
          <p className="mt-2">{item.sources_current ? "原分析资料当前仍一致" : "原分析资料已变化 / 不可用，请重新准备"}</p>
          {item.error_code != null && <p className="text-primary">本次未完成。请核对来源、可用模型和预算；原记录已保留。</p>}
          <ChangeToolReceipts value={item.tool_receipts}/>
          {<ChangeDiscussionContinuation projectId={projectId} ecrId={ecrId} sourceDigest={sourceDigest} value={item} disabled={busy} onRefresh={() => read()}/>}
          {Array.isArray(item.missing) && item.missing.length > 0 && <p className="whitespace-pre-wrap">待补资料：{item.missing.map(String).join("；")}</p>}
          {item.finding_id != null && item.convened_discussion != null && <p className="font-medium">讨论前的原分析候选</p>}
          {item.finding_id != null ? <ConversationFinding findingId={text(item.finding_id)} /> : item.assessment != null ? <ChangeAssessmentView assessment={assessment} labels={labels}/> : null}

          {item.requested_by_me === true && ordinaryLive && (item.include_supplier_notices !== true || data?.notice_rollout === "live") && (item.status === "running" || item.error_code === "APPLICATION_RUN_LEASE_EXPIRED") && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { await request("", { request_id: item.request_id, expected_digest: item.source_digest, depth: item.depth, user_instruction: item.user_instruction, allow_discussion: item.allow_discussion === true, include_supplier_notices: item.include_supplier_notices === true }); await read(); })}>读取 / 恢复原请求</Button>}
        </details>;
      })}
      {data?.next_before_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => read(true))}>更早运行记录</Button>}
    </div>
  </details>;
}
