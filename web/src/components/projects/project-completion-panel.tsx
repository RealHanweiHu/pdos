"use client";

import { ProjectHandoffHistory } from "./project-handoff-history";
import { ProjectHandoffSources, type HandoffSourceCheck } from "./project-handoff-sources";
import Link from "next/link";
import { isRecord, responseBody } from "@/components/workspace-api";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";

type Handoff = { acceptance_reasons?: string[]; source_checks?: HandoffSourceCheck[]; review_digest: string; item_key: string; label: string; status: string; acceptance_current: boolean; note?: string; document_id?: string; receiver_user_id?: string };
type Completion = { ready: boolean; blockers: { key: string; label: string }[]; handoff_items: Handoff[];
  documents: { id: string; filename: string }[]; members: { id: string; display_name: string }[];
  issue_policy: { low: boolean; medium: boolean } };
const statusLabels: Record<string, string> = { missing: "待准备", pending: "待接收", accepted: "已接收", returned: "已退回" };
type Command = { suffix: string; method: "PUT" | "POST"; body: Record<string, unknown>; label: string; summary: string };
const inputClass = "w-full rounded-md border bg-background p-2 text-sm";
async function read(response: Response) {
  if (response.status === 204) return null;
  const body = await response.json();
  if (!response.ok) throw new Error(body?.detail?.message ?? "结项清单暂不可用");
  return body;
}

export function ProjectCompletionPanel({ projectId, userId, canManage }: { projectId: string; userId: string; canManage: boolean }) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const search = useSearchParams();
  const rawFocus = search.get("completion_item");
  const focus = rawFocus && ["configuration", "bom", "manufacturing", "test_certification", "training", "residuals", "quality_follow_up"].includes(rawFocus) ? rawFocus : null;
  useEffect(() => { if (focus && detailsRef.current) detailsRef.current.open = true; }, [focus]);
  const base = `/api/projects/${projectId}/completion`;
  const [data, setData] = useState<Completion | null>(null);
  useEffect(() => { if (focus && data) document.getElementById(`completion-${projectId}-${focus}`)?.scrollIntoView({ block: "center" }); }, [focus, projectId, data]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<{ key: string; document: string; receiver: string; note: string; digest: string; receiverOnly: boolean; changeReason: string } | null>(null);
  const [preview, setPreview] = useState<Command | null>(null), [pending, setPending] = useState<Command | null>(null), [notice, setNotice] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const load = async () => setData(await read(await fetch(base, { cache: "no-store" })));
  const act = async (work: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "操作失败"); }
    finally { setBusy(false); }
  };
  const mutate = async (suffix: string, method: "PUT" | "POST", body: unknown) => {
    await read(await fetch(`${base}/${suffix}`, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
    await load();
  };
  const stage = (suffix: string, method: "PUT" | "POST", body: Record<string, unknown>, label: string, summary: string) => {
    setError(null); setNotice(""); setPreview({ suffix, method, body: { ...body, request_id: crypto.randomUUID() }, label, summary });
  };
  async function send(command: Command) {
    setPending(command); setBusy(true); setError(null);
    try {
      const response = await fetch(`${base}/${command.suffix}`, { method: command.method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(command.body) });
      const result = await responseBody(response);
      if (!response.ok) {
        if ([400, 401, 403, 404, 409, 422].includes(response.status)) { setPending(null); setPreview(null); }
        throw new Error(isRecord(result) && isRecord(result.detail) && typeof result.detail.message === "string" ? result.detail.message : "办理结果尚未确认，请按原请求重试");
      }
      if (!isRecord(result) || result.request_id !== command.body.request_id) throw new Error("办理回执不完整，请按原请求重试");
      setPending(null); setPreview(null); setDraft(null); setNotes({});
      setNotice(`${command.label}已留档，原请求 ${String(command.body.request_id)}。`);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "办理失败"); }
    finally { setBusy(false); }
  }
  return <details ref={detailsRef} className="mt-6 rounded-lg border p-4" onToggle={(event) => { if (event.currentTarget.open && data === null && !busy) void act(load); }}>
    <summary className="cursor-pointer font-semibold">结项与交接清单</summary>
    <div className="mt-4 space-y-4">
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {notice && <p role="status" className="break-all text-sm">{notice}</p>}
      <fieldset disabled={busy || !!preview || !!pending} className="space-y-4">
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新结项条件</Button>
      {data && <>
        <p className="text-sm">{data.ready ? "当前条件已满足，可在项目状态中完成结项。" : `还有 ${data.blockers.length} 项条件需要处理。`}</p>
        {data.blockers.length > 0 && <ul className="list-disc space-y-1 pl-5 text-sm">{data.blockers.map((blocker) => <li key={blocker.key}>{blocker.label}</li>)}</ul>}
        <section className="space-y-3"><h3 className="text-sm font-semibold">交付与接收</h3>
          {data.handoff_items.map((item) => <article id={`completion-${projectId}-${item.item_key}`} key={item.item_key} className="space-y-2 rounded-md border p-3">
            <p className="text-sm font-medium">{item.label} · {item.status === "accepted" && !item.acceptance_current ? "接收需复核" : statusLabels[item.status]}</p>
            {item.document_id && <p className="text-sm">文档：{data.documents.find((doc) => doc.id === item.document_id)?.filename ?? "文档已不可用"} · 接收人：{data.members.find((member) => member.id === item.receiver_user_id)?.display_name ?? "需重新指定"}</p>}
            {item.note && <p className="whitespace-pre-wrap text-sm text-muted-foreground">{item.note}</p>}
            {item.document_id && <Link prefetch={false} className="inline-block text-xs text-primary underline underline-offset-4" href={`/projects?project=${projectId}&tab=documents&entity_id=${item.document_id}`}>查看交接原文档</Link>}
            <ProjectHandoffSources projectId={projectId} sources={item.source_checks ?? []} reasons={item.acceptance_reasons ?? []} />
            {canManage && <Button size="sm" variant="outline" disabled={busy} onClick={() => setDraft({ key: item.item_key, document: item.document_id ?? "", receiver: item.receiver_user_id ?? "", note: item.note ?? "", digest: item.review_digest, receiverOnly: false, changeReason: "" })}>{item.status === "missing" ? "准备交接" : "更新交接"}</Button>}
            {canManage && item.document_id && item.receiver_user_id && <Button size="sm" variant="outline" disabled={busy} onClick={() => setDraft({ key: item.item_key, document: item.document_id!, receiver: "", note: item.note ?? "", digest: item.review_digest, receiverOnly: true, changeReason: "" })}>保留原资料更换接收人</Button>}
            <ProjectHandoffHistory key={`${item.item_key}:${item.review_digest}`} projectId={projectId} itemKey={item.item_key}/>
            {item.receiver_user_id === userId && <div className="space-y-2"><label className="block text-sm">接收或退回说明<textarea className={inputClass} value={notes[item.item_key] ?? ""} onChange={(event) => setNotes({ ...notes, [item.item_key]: event.target.value })} /></label><div className="flex gap-2">{[true, false].map((accept) => <Button key={String(accept)} size="sm" variant={accept ? "default" : "outline"} disabled={busy || !(notes[item.item_key] ?? "").trim()} onClick={() => stage(`handoff/${item.item_key}/response`, "POST", { accept, note: notes[item.item_key], expected_digest: item.review_digest }, accept ? "确认接收" : "退回补充", `${item.label} · ${data.documents.find(doc => doc.id === item.document_id)?.filename ?? item.document_id}\n${notes[item.item_key]}`)}>{accept ? "确认接收" : "退回补充"}</Button>)}</div></div>}
          </article>)}
          {draft && canManage && <form className="space-y-3 rounded-md border p-3" onSubmit={(event) => { event.preventDefault(); stage(`handoff/${draft.key}`, "PUT", { document_id: draft.document, receiver_user_id: draft.receiver, note: draft.note, expected_digest: draft.digest, ...(draft.receiverOnly ? { receiver_change_reason: draft.changeReason.trim() } : {}) }, draft.receiverOnly ? "更换接收人" : "提交交接", `${data.handoff_items.find(item => item.item_key === draft.key)?.label} · ${data.documents.find(doc => doc.id === draft.document)?.filename ?? draft.document}\n接收人：${data.members.find(member => member.id === draft.receiver)?.display_name ?? draft.receiver}\n${draft.note}${draft.receiverOnly ? `\n换人原因：${draft.changeReason.trim()}` : ""}`); }}>
            <p className="font-medium">准备：{data.handoff_items.find((item) => item.item_key === draft.key)?.label}</p>
            <label className="block text-sm">项目证据文档<select required disabled={draft.receiverOnly} className={inputClass} value={draft.document} onChange={(event) => setDraft({ ...draft, document: event.target.value })}><option value="">选择已上传文档</option>{data.documents.map((doc) => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}</select></label>
            <label className="block text-sm">接收人<select required className={inputClass} value={draft.receiver} onChange={(event) => setDraft({ ...draft, receiver: event.target.value })}><option value="">选择项目成员</option>{data.members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
            <label className="block text-sm">交接范围、版本与责任说明<textarea required disabled={draft.receiverOnly} maxLength={10000} className={inputClass} value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} /></label>
            {draft.receiverOnly && <label className="block text-sm">更换接收人的原因<textarea required maxLength={2048} className={inputClass} value={draft.changeReason} onChange={event => setDraft({ ...draft, changeReason: event.target.value })}/></label>}
            <p className="text-xs text-muted-foreground">提交后本项回到待接收，原接收记录保留，新接收人须重新核对；已结项项目会重新打开。</p>
            <div className="flex gap-2"><Button size="sm" disabled={busy || !draft.note.trim() || (draft.receiverOnly && (!draft.changeReason.trim() || draft.receiver === data.handoff_items.find(item => item.item_key === draft.key)?.receiver_user_id))}>预览交接办理</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setDraft(null)}>取消</Button></div>
          </form>}
        </section>
        <section className="space-y-2 border-t pt-3"><h3 className="text-sm font-semibold">问题关闭政策</h3><p className="text-xs text-muted-foreground">high / critical 始终要求 Owner 与 Verifier 分离、指定 Verifier 关闭及关闭证据。</p>
          {(["low", "medium"] as const).map((severity) => <label key={severity} className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!canManage || busy} checked={data.issue_policy[severity]} onChange={(event) => { const enabled = event.target.checked; void act(() => mutate("issue-policy", "PUT", { ...data.issue_policy, [severity]: enabled })); }} />{severity} 问题同样要求独立验证与证据</label>)}
        </section>
      </>}
      </fieldset>
      {preview && !pending && <section className="space-y-2 rounded-md border p-3" aria-label="交接办理预览"><p className="font-medium">{preview.label}</p><p className="whitespace-pre-wrap text-sm">{preview.summary}</p><p className="text-xs text-muted-foreground">确认时会重新核对原交接记录与业务依据。</p><Button size="sm" disabled={busy} onClick={() => void send(preview)}>确认{preview.label}</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></section>}
      {pending && <section className="space-y-2 rounded-md border p-3"><p className="break-all text-sm">原请求 {String(pending.body.request_id)} 的结果待确认，请保留本页并重试取得回执。</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void send(pending)}>按原请求重试</Button></section>}
    </div>
  </details>;
}
