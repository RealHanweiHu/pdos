"use client";

import { useRef, useState } from "react";
import { cancelAgentRun } from "@/components/ai/ai-api";
import { AgentRunProgressPanel } from "@/components/ai/agent-run-progress";
import { ConversationFinding } from "@/components/ai/conversation-finding";
import { ChangeToolReceipts } from "@/components/ai/change-tool-receipts";
import { Button } from "@/components/ui/button";
import { field, rows, text, type Row } from "./fmea-sources";
import { OperationEvidence, evidenceBody, qualityRequest, type Evidence } from "./quality-operation-evidence";

const statuses: Record<string, string> = { running: "处理中", succeeded: "处理完成", degraded: "未完成", failed: "已停止", cancelled: "已取消" };

export function QualityPreparationRuns({ projectId, ncrId, phaseAvailable }: { projectId: string; ncrId: string; phaseAvailable: boolean }) {
  const [data, setData] = useState<Row | null>(null), [snapshot, setSnapshot] = useState<Row | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]), [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false), [generating, setGenerating] = useState(false), [error, setError] = useState("");
  const attempt = useRef<{ id: string; signature: string } | null>(null);
  async function read(more = false) {
    const result = await qualityRequest(projectId, ncrId, `/preparation-runs${more && data?.next_before_id ? `?before_id=${text(data.next_before_id)}` : ""}`);
    setData(old => more && old ? { ...result, items: [...rows(old.items), ...rows(result.items)] } : result);
  }
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError("");
    try { await fn(); } catch(e) { setError(e instanceof Error ? e.message : "办理未完成，请读取原记录"); } finally { setBusy(false); }
  }
  async function generate(original?: Row) {
    setGenerating(true); setError("");
    try {
      const payload = original ? { expected_digest: original.source_digest, selections: original.selections, user_instruction: original.user_instruction } : { expected_digest: snapshot?.digest, selections: evidenceBody(evidence), user_instruction: instruction.trim() };
      const signature = JSON.stringify(payload);
      if (!original && attempt.current?.signature !== signature) attempt.current = { id: crypto.randomUUID(), signature };
      await qualityRequest(projectId, ncrId, "/preparation-runs", { ...payload, request_id: original?.request_id ?? attempt.current?.id });
      await read();
    } catch(e) { setError(e instanceof Error ? e.message : "生成未完成，请读取原运行记录"); } finally { setGenerating(false); }
  }
  const live = data?.rollout === "live";
  return <details className="space-y-3 rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(() => read()); }}>
    <summary className="cursor-pointer font-medium">准备调查或整改建议</summary>
    <p className="text-sm text-muted-foreground">按实际 NCR 阶段读取原问题、根因版本、整改进展及选定证据。建议逐项人审，接受后再单独应用。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {data && !live && <p className="text-sm text-muted-foreground">此项能力尚待阶段评测，目前可核对资料，尚未开放生成。</p>}
    {phaseAvailable ? <>
      <OperationEvidence projectId={projectId} ncrId={ncrId} value={evidence} onChange={v => { setEvidence(v); setSnapshot(null); }} disabled={busy || generating}/>
      <Button type="button" variant="outline" size="sm" disabled={busy || generating} onClick={() => void act(async () => { setSnapshot(null); setSnapshot(await qualityRequest(projectId, ncrId, "/preparation-context", { selections: evidenceBody(evidence) })); })}>读取本次准备资料</Button>
      {snapshot && <div className="space-y-2 rounded-md border p-3 text-sm">
        <p>{snapshot.phase === "investigation" ? "当前准备根因调查任务；假设须通过实际调查核实。" : "当前准备纠正与预防措施；须依据实际获批根因。"}</p>
        <p>已读取 {rows(snapshot.references).length} 项原资料。生成时会再次核对是否变化。</p>
        {rows(snapshot.references).map(ref => <details key={text(ref.reference_id)}><summary className="cursor-pointer">{text(ref.label)} · {text(ref.reference_id).split(":")[0]}</summary><pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(ref.fields, null, 2)}</pre>{Array.isArray(ref.omitted_fields) && ref.omitted_fields.length > 0 && <p>本次未纳入字段：{ref.omitted_fields.map(String).join("、")}</p>}</details>)}
        {Array.isArray(snapshot.omitted_references) && snapshot.omitted_references.length > 0 && <p>资料较多，本次有 {snapshot.omitted_references.length} 项未纳入，建议缩小证据范围。</p>}
        {data?.can_request === true && <form className="space-y-2" onSubmit={e => { e.preventDefault(); void generate(); }}><label className="block">本次重点核对什么<textarea maxLength={10000} className={field} value={instruction} disabled={busy || generating} onChange={e => setInstruction(e.target.value)}/></label><Button type="submit" size="sm" disabled={busy || generating || !live}>{generating ? "正在准备…" : "按本次资料准备待审建议"}</Button></form>}
      </div>}
    </> : <p className="text-sm">进入根因调查或措施执行阶段后，可准备新的建议。</p>}
    <div><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void act(() => read())}>读取最新运行记录</Button></div>
    {generating && <p role="status" className="text-sm">生成中仍可读取运行记录、查看进度或取消本次请求。</p>}
    {rows(data?.items).map(item => {
      const controllable = item.requested_by_me === true && (item.status === "running" || item.error_code === "APPLICATION_RUN_LEASE_EXPIRED");
      return <details className="space-y-2 rounded-md border p-3 text-sm" key={text(item.run_id)}><summary className="cursor-pointer">{text(item.created_at)} · {statuses[text(item.status)] ?? text(item.status)} · {item.finding_id ? "已有待审建议" : item.disposition === "insufficient_evidence" ? "资料不足" : "尚无待审建议"}</summary>
        <p>{item.sources_current === true ? "本次原资料当前仍一致" : "原资料已变化或当前不可用，重新准备前请读取最新资料"}</p>
        {item.error_code != null && <p className="text-primary">本次未完成，请核对来源、可用模型与预算。原运行记录已保留。</p>}
        {Array.isArray(item.missing) && item.missing.length > 0 && <p>待补资料：{item.missing.map(String).join("；")}</p>}
        <ChangeToolReceipts value={item.tool_receipts}/>
        <AgentRunProgressPanel projectId={projectId} runId={text(item.run_id)}/>
        {item.finding_id != null && <ConversationFinding findingId={text(item.finding_id)}/>}
        {controllable && <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void act(async () => { await cancelAgentRun(text(item.run_id)); await read(); })}>取消本次请求</Button>{live && <Button type="button" variant="outline" size="sm" disabled={busy || generating} onClick={() => void generate(item)}>读取 / 恢复原请求</Button>}</div>}
      </details>;
    })}
    {data?.next_before_id != null && <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void act(() => read(true))}>更早运行记录</Button>}
  </details>;
}
