"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { TestImportPreview, importRequest } from "@/components/projects/test-import-preview";
import { attachmentRequest, parseAttachment, type ConversationAttachment } from "./conversation-files";
import { cancelAgentRun } from "./ai-api";

type Receipt = { id: string; attachmentId: string; planId: string; status: string; batchId: string | null; runId: string | null; reused: boolean | null; error: string | null };
function receipt(v: unknown): Receipt {
  if (!isRecord(v) || typeof v.id !== "string" || typeof v.attachment_id !== "string" || typeof v.plan_id !== "string" || typeof v.status !== "string") throw new Error("导入回执不完整");
  return { id: v.id, attachmentId: v.attachment_id, planId: v.plan_id, status: v.status, batchId: typeof v.batch_id === "string" ? v.batch_id : null, runId: typeof v.run_id === "string" ? v.run_id : null, reused: typeof v.reused_existing === "boolean" ? v.reused_existing : null, error: typeof v.error_code === "string" ? v.error_code : null };
}
const labels: Record<string, string> = { pending: "请求已保存，待准备", queued: "等待字段映射", running: "正在准备报告", succeeded: "映射完成，待核对导入结果", parsed: "测试草稿已准备，待核对确认", confirmed: "正式结果已确认", failed: "导入准备未完成", degraded: "本次准备已停止", cancelled: "已取消准备" };
export function ConversationReportImports({ projectId, conversationId, messageId, attachmentIds, archived }: {
  projectId: string; conversationId: string; messageId: string; attachmentIds: string[]; archived: boolean;
}) {
  const [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<Receipt[]>([]), [attachments, setAttachments] = useState<ConversationAttachment[]>([]);
  const [plans, setPlans] = useState<{ id: string; title: string; status: string }[]>([]);
  const [attachmentId, setAttachmentId] = useState(""), [planId, setPlanId] = useState("");
  const pending = useRef<{ signature: string; requestId: string } | null>(null);
  const base = `/api/conversations/${conversationId}`;
  async function refresh() {
    const value = await importRequest(`${base}/messages/${messageId}/report-imports`);
    if (!isRecord(value) || !Array.isArray(value.items) || !Array.isArray(value.plans)) throw new Error("导入清单不可用");
    setItems(value.items.map(receipt));
    setPlans(value.plans.map(p => { if (!isRecord(p) || typeof p.id !== "string" || typeof p.title !== "string" || typeof p.status !== "string") throw new Error("计划资料不完整"); return { id: p.id, title: p.title, status: p.status }; }));
    const sources = await Promise.all(attachmentIds.map(id => attachmentRequest(`${base}/attachments/${id}`)));
    setAttachments(sources.map(parseAttachment)); setLoaded(true);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "报告办理未完成"); } finally { setBusy(false); } }
  async function prepare() {
    const signature = JSON.stringify([attachmentId, planId]); if (pending.current?.signature !== signature) pending.current = { signature, requestId: crypto.randomUUID() };
    try { await importRequest(`${base}/messages/${messageId}/report-imports`, { request_id: pending.current.requestId, attachment_id: attachmentId, plan_id: planId, publish_to_project: true }); pending.current = null; }
    finally { await refresh(); }
  }
  const eligible = attachments.filter(a => a.filename.toLowerCase().endsWith(".xlsx") && a.status === "extracted" && a.classification === "internal" && !a.revoked_at);
  return <details className="rounded-lg border bg-background p-3" onToggle={e => { if (e.currentTarget.open && !loaded && !busy) void act(refresh); }}>
    <summary className="cursor-pointer text-sm font-medium">将这条消息的测试报告录入项目</summary>
    <div className="mt-3 space-y-4">
      <p className="text-xs text-muted-foreground">选择一个已保存的XLSX及本项目测试计划。准备导入会把报告原件登记为项目证据，供有权限的项目成员核对；会话仍仅本人可见。停止会话附件引用不会撤销已经登记的项目证据。待补充记录会单独标出，核对原值及映射后一次确认整批正式结果。</p>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(refresh)}>刷新原请求与批次</Button>
      {!archived && <div className="space-y-2"><div className="flex flex-wrap gap-2"><select aria-label="本次导入的消息附件" className="max-w-full rounded-md border bg-background p-2 text-xs" disabled={busy} value={attachmentId} onChange={e => setAttachmentId(e.target.value)}><option value="">选择原报告</option>{eligible.map(a => <option key={a.id} value={a.id}>{a.filename}</option>)}</select><select aria-label="报告目标测试计划" className="max-w-full rounded-md border bg-background p-2 text-xs" disabled={busy} value={planId} onChange={e => setPlanId(e.target.value)}><option value="">选择目标计划</option>{plans.map(p => <option key={p.id} value={p.id}>{p.title} · {p.status}</option>)}</select></div><Button size="sm" disabled={busy || !eligible.some(a => a.id === attachmentId) || !plans.some(p => p.id === planId)} onClick={() => void act(prepare)}>登记项目报告并准备草稿</Button>{loaded && !eligible.length && <p className="text-xs text-muted-foreground">本条暂没有可用于报告导入的内部XLSX；PDF可在会话中阅读，尚不用于实测值正式录入。</p>}</div>}
      {items.map(item => <article key={item.id} className="space-y-3 rounded-md border p-3"><p className="text-sm font-medium">{attachments.find(a => a.id === item.attachmentId)?.filename ?? "原消息报告"} → {plans.find(p => p.id === item.planId)?.title ?? "原测试计划"}</p><p className="text-xs">{labels[item.status] ?? item.status}{item.reused ? " · 复用已有批次，未重复创建记录" : ""}</p>
        {item.batchId && <TestImportPreview key={item.batchId} projectId={projectId} batchId={item.batchId} onConfirmed={refresh} />}
        {!item.batchId && !archived && !["cancelled"].includes(item.status) && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { try { await importRequest(`${base}/report-imports/${item.id}/prepare`, {}); } finally { await refresh(); } })}>查询或继续原导入请求</Button>}
        {item.runId && ["queued", "running"].includes(item.status) && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { await cancelAgentRun(item.runId!); await refresh(); })}>停止本次准备</Button>}
        {item.error && <p className="text-xs text-destructive">准备尚未完成，原请求与文件保留。请刷新回执，核对文件格式或运行条件。</p>}
      </article>)}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
  </details>;
}
