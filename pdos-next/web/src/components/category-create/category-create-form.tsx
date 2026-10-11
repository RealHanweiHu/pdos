"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { emptyGroups, groupKeys, groupNames, personalApi, RequestRejected, selectedInput } from "./contracts";
import type { Api, CategoryCandidate, CategoryConfirmationDraft, CategoryCreateDTO, CategoryPreview, CreatedCategory, Groups } from "./contracts";

export function CategoryCreateForm({ candidate, runId, disabled = false, api = personalApi, onCreated, draft, onDraftChange }: {
  candidate?: CategoryCandidate; runId?: string; disabled?: boolean; api?: Api;
  onCreated: (category: CreatedCategory) => void;
  draft?: CategoryConfirmationDraft; onDraftChange?: (draft: CategoryConfirmationDraft | null) => void;
}) {
  const restored = draft?.request.prepared_by_run_id === runId && draft?.request.candidate_digest === candidate?.candidate_digest ? draft : undefined;
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [selected, setSelected] = useState<Record<keyof Groups, boolean>>(() => ({
    knowledge: restored ? restored.request.groups.knowledge.length > 0 : true,
    parameters: restored ? restored.request.groups.parameters.length > 0 : true,
    snapshot_refs: restored ? restored.request.groups.snapshot_refs.length > 0 : true,
  }));
  const [deidentified, setDeidentified] = useState(!!restored);
  const [preview, setPreview] = useState<CategoryPreview | null>(restored?.preview ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [attempted, setAttempted] = useState(restored?.attempted ?? false);
  const [hasRequest, setHasRequest] = useState(!!restored);
  const [rejected, setRejected] = useState(restored?.rejected ?? false);
  const [created, setCreated] = useState<CreatedCategory | null>(null);
  const request = useRef<CategoryCreateDTO | null>(restored?.request ?? null);
  const lock = useRef(false);
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const frozen = busy || hasRequest;

  async function review() {
    if (lock.current || disabled || !deidentified) return;
    lock.current = true; setBusy(true); setError("");
    try {
      if (!request.current) {
        if (candidate && !runId) throw new Error("候选缺少实际运行，无法采用。");
        const input = candidate ? selectedInput(candidate, selected) : { key, name, purpose, groups: emptyGroups() };
        request.current = { ...input, deidentified_confirmed: true, idempotency_key: crypto.randomUUID(),
          ...(candidate ? { prepared_by_run_id: runId, candidate_digest: candidate.candidate_digest } : {}) };
        setHasRequest(true);
        onDraftChange?.({ request: request.current, preview: null, attempted: false, rejected: false });
      }
      const result = await api<CategoryPreview>("v1/categories/preview", request.current);
      if (!active.current) return;
      if (!result.confirmation_token || !result.payload || !result.expires_at) throw new Error("服务器未返回完整确认预览，请重试。");
      request.current = { ...request.current, confirmation_token: result.confirmation_token };
      setPreview(result);
      onDraftChange?.({ request: request.current, preview: result, attempted: false, rejected: false });
    } catch (failure) { setError(failure instanceof Error ? failure.message : "预览暂不可用。"); }
    finally { lock.current = false; setBusy(false); }
  }

  async function create() {
    if (lock.current || disabled || !preview || !request.current?.confirmation_token) return;
    lock.current = true; setBusy(true); setError(""); setAttempted(true); setRejected(false);
    onDraftChange?.({ request: request.current, preview, attempted: true, rejected: false });
    try {
      const result = await api<{ subject_id: string; id?: string; continuation_state?: string }>("v1/categories", request.current);
      if (!active.current) return;
      if (!result.subject_id) throw new Error("创建结果不完整，请使用原请求重试。");
      const category = { id: result.subject_id, name: request.current.name, purpose: request.current.purpose,
        ...(result.id ? { receiptId: result.id } : {}), ...(result.continuation_state ? { continuationState: result.continuation_state } : {}) };
      setCreated(category);
      onDraftChange?.(null);
      onCreated(category);
    } catch (failure) {
      setRejected(failure instanceof RequestRejected);
      setError(failure instanceof Error ? failure.message : "创建未完成，请使用原请求重试。");
      if (active.current && request.current) onDraftChange?.({ request: request.current, preview, attempted: true, rejected: failure instanceof RequestRejected });
    }
    finally { lock.current = false; setBusy(false); }
  }

  if (created) return <section className="panel space-y-3">
    <p role="status">品类「{created.name}」已创建。{created.continuationState === "awaiting_delivery" ? "小 Pai 的后续通知等待派送，创建回执已保存。" : ""}</p>
    {created.receiptId && <p className="break-all text-sm">创建回执：{created.receiptId}</p>}
    <Button onClick={() => onCreated(created)}>进入已创建品类</Button>
  </section>;

  return <section className="panel space-y-4">
    <h2 className="font-semibold">{candidate ? "核对并采用品类候选" : "手动建立品类"}</h2>
    {candidate ? <>
      <h3 className="text-lg font-medium">{candidate.input.name}</h3>
      <p className="text-sm text-muted-foreground">品类键：{candidate.input.key}</p>
      <p className="whitespace-pre-wrap">{candidate.input.purpose}</p>
      <p className="text-sm text-muted-foreground">以下内容已由服务器封存。每组可完整采用或取消，不能在页面改写。</p>
      <fieldset disabled={frozen || disabled} className="space-y-3">
        <legend className="sr-only">采用的完整组</legend>
        {groupKeys.map(group => <div key={group} className="rounded-lg border p-3">
          <label className="flex items-center gap-2"><input type="checkbox" checked={selected[group]}
            onChange={e => setSelected(old => ({ ...old, [group]: e.target.checked }))} />
            {groupNames[group]} · {candidate.input.groups[group].length} 项</label>
          <details className="mt-2 text-sm"><summary className="cursor-pointer">查看封存内容</summary>
            <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(candidate.input.groups[group], null, 2)}</pre>
          </details>
        </div>)}
      </fieldset>
      <details className="text-sm text-muted-foreground"><summary className="cursor-pointer">实际运行与来源</summary>
        <p className="break-all">运行：{runId}</p><p className="break-all">服务器候选摘要：{candidate.candidate_digest}</p>
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify({ source: candidate.source, snapshots: candidate.snapshots }, null, 2)}</pre>
      </details>
    </> : <fieldset disabled={frozen || disabled} className="space-y-3">
      <legend className="sr-only">品类基本信息</legend>
      <label className="block">品类键<input required pattern="[a-z0-9]+(-[a-z0-9]+)*" value={key} onChange={e => setKey(e.target.value)} placeholder="例如 bicycle-pump" /></label>
      <p className="text-sm text-muted-foreground">使用小写字母、数字和短横线。</p>
      <label className="block">品类名称<input required maxLength={160} value={name} onChange={e => setName(e.target.value)} /></label>
      <label className="block">用途与范围<textarea required value={purpose} onChange={e => setPurpose(e.target.value)} /></label>
    </fieldset>}
    <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={deidentified} disabled={frozen || disabled}
      onChange={e => setDeidentified(e.target.checked)} />我已核对本次内容，确认已去除客户与个人识别信息，可作为品类共享材料。</label>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {disabled && <p role="status" className="text-sm text-muted-foreground">当前暂不能采用，请核对所选运行状态。</p>}
    {preview ? <div className="space-y-3 rounded-lg border p-4">
      <h3 className="font-medium">服务器确认预览</h3>
      <p>{preview.payload.name} · {preview.payload.key}</p><p className="whitespace-pre-wrap text-sm">{preview.payload.purpose}</p>
      <p className="text-sm">来源：{preview.origin === "ai_draft" ? "AI 草稿，经本人确认" : "人工输入"}</p>
      <p className="break-all text-sm text-muted-foreground">原始写入者：{preview.writer_id}</p>
      {preview.candidate && <details className="text-sm"><summary className="cursor-pointer">查看服务器核对与选中来源</summary>
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(preview.candidate, null, 2)}</pre>
      </details>}
      {groupKeys.map(group => <p key={group} className="text-sm">{groupNames[group]}：{preview.groups[group].selected_count} / {preview.groups[group].available_count} 项</p>)}
      <p className="text-sm text-muted-foreground">确认有效期至 {new Date(preview.expires_at).toLocaleString()}，提交时再次核对权限与来源。</p>
      <Button type="button" disabled={busy || disabled} onClick={() => void create()}>{busy ? "正在提交…" : attempted ? "使用原请求重试创建" : "本人确认并创建品类"}</Button>
    </div> : <Button type="button" disabled={busy || disabled || !deidentified || (!candidate && (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(key) || !name.trim() || !purpose.trim()))}
      onClick={() => void review()}>{busy ? "正在核对…" : hasRequest ? "重试原预览请求" : "查看创建预览"}</Button>}
    {hasRequest && !busy && (!attempted || rejected) && <Button type="button" variant="ghost" onClick={() => {
      request.current = null; setHasRequest(false); setPreview(null); setError(""); setAttempted(false); setRejected(false);
      onDraftChange?.(null);
    }}>返回修改并重新预览</Button>}
  </section>;
}
