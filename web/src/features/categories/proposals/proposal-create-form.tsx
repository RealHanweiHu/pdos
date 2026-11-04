"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { categoryTransport } from "@/lib/category-transport";
import type { WorkspaceTransport } from "@/lib/workspace-api";

// D53 (AT-45, F06): proposals can be created by hand, so the work goes on when 小Pai is unavailable.
type EntryKind = "new_product" | "customer_request";
const entryKinds: Record<EntryKind, string> = { new_product: "新品", customer_request: "客户需求" };
type Command = {
  command_id: string; idempotency_key: string; operation: "proposal.create"; product_id: null;
  expected_revision: number; source_read_set: []; payload: Record<string, unknown>; category_id?: string;
};
type Preview = { command: Command; confirmation_token: string; expires_at: string | null };
type Receipt = { id?: string; subject_id?: string };

export function ProposalCreateForm({ categoryId, api, onCreated }: {
  categoryId: string; api: WorkspaceTransport; onCreated: (proposalId: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<EntryKind>("new_product");
  const [brief, setBrief] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const scoped = categoryTransport(categoryId, api);

  async function review() {
    if (lock.current || !title.trim()) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const category = (await api<{ id: string; revision: number }[]>("v1/categories")).find(item => item.id === categoryId);
      if (!category || !Number.isInteger(category.revision)) throw new Error("当前品类不可见或版本未知，请刷新后重试。");
      const command: Command = {
        command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation: "proposal.create",
        product_id: null, expected_revision: category.revision, source_read_set: [],
        payload: { title: title.trim(), entry_kind: kind, brief: brief.trim() },
      };
      const result = await scoped<Preview>("v1/commands/preview", command);
      if (!result.command || result.command.operation !== "proposal.create" || !result.confirmation_token) {
        throw new Error("服务器未返回完整的确认预览，尚未创建，请重试。");
      }
      if (alive.current) setPreview(result);
    } catch (failure) { if (alive.current) setError(failure instanceof Error ? failure.message : "预览暂不可用。"); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }

  async function create() {
    if (lock.current || !preview) return;
    lock.current = true; setBusy(true); setError(""); setAttempted(true);
    try {
      const receipt = await scoped<Receipt>("v1/commands", preview.command);
      if (!receipt.subject_id) throw new Error("创建结果尚未确认，请使用原请求重试。");
      if (alive.current) onCreated(receipt.subject_id);
    } catch (failure) {
      if (!alive.current) return;
      const failed = failure as Error & { status?: number };
      // A refused request is final; an unknown outcome keeps the original request for a safe retry.
      if (failed.status && failed.status < 500) { setPreview(null); setAttempted(false); }
      setError(failed.message || "创建未完成，请使用原请求重试。");
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }

  return <section className="space-y-4" aria-label="手动创建提案">
    <h3 className="font-semibold">手动创建</h3>
    <fieldset disabled={busy || !!preview} className="space-y-3">
      <legend className="sr-only">提案基本信息</legend>
      <label className="block text-sm">提案标题<input required maxLength={200} value={title} onChange={event => setTitle(event.target.value)} /></label>
      <label className="block text-sm">来源<select value={kind} onChange={event => setKind(event.target.value as EntryKind)}>
        {(Object.keys(entryKinds) as EntryKind[]).map(value => <option key={value} value={value}>{entryKinds[value]}</option>)}
      </select></label>
      <p className="text-xs text-muted-foreground">派生提案需要先固定父型号，请从该型号的派生入口发起。</p>
      <label className="block text-sm">简述（可选）<textarea rows={3} maxLength={4000} value={brief} onChange={event => setBrief(event.target.value)} /></label>
    </fieldset>
    {error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}
    {preview ? <div className="space-y-3 rounded-lg border border-border p-4">
      <h4 className="font-medium">服务器确认预览</h4>
      <p className="break-words">{String(preview.command.payload.title)} · {entryKinds[preview.command.payload.entry_kind as EntryKind] ?? "未知来源"}</p>
      {!!preview.command.payload.brief && <p className="whitespace-pre-wrap break-words text-sm">{String(preview.command.payload.brief)}</p>}
      <p className="text-sm text-muted-foreground">新提案默认私有，只有你可见。方案、规格与来源可在提案页继续补充，也可以之后让小Pai补全。</p>
      {preview.expires_at && <p className="text-xs text-muted-foreground">确认有效期至 {new Date(preview.expires_at).toLocaleString()}，提交时再次核对权限。</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={busy} onClick={() => void create()}>{busy ? "正在创建…" : attempted ? "使用原请求重试创建" : "本人确认并创建提案"}</Button>
        {!attempted && <Button type="button" variant="ghost" disabled={busy} onClick={() => { setPreview(null); setError(""); }}>返回修改</Button>}
      </div>
    </div> : <Button type="button" disabled={busy || !title.trim()} onClick={() => void review()}>{busy ? "正在核对…" : "查看创建预览"}</Button>}
  </section>;
}
