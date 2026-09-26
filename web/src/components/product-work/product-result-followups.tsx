"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { request } from "./product-work-api";

type Response = { original_path: string; revision_path: string | null; treatment: string; explanation: string };
const actions: Record<string, string> = { link_revision: "关联实际后续修订", no_change: "保留原定义", needs_evidence: "补充依据后再办理", withdrawn: "撤回此次落实记录" };
const treatments: Record<string, string> = { changed: "修订已调整", retained: "保留", removed: "修订已移除此项", needs_evidence: "尚待补证" };
const states: Record<string, string> = { draft: "草稿", in_review: "协审中", published: "已发布", withdrawn: "已撤回", rejected: "已退回" };

export function ProductResultFollowupInbox({ base, revisionId }: { base: string; revisionId: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function read(before?: string) {
    setBusy(true); setError("");
    try {
      const value = await request<Row>(base + "/result-followup-inbox", "POST", { revision_id: revisionId, before_id: before ?? null });
      setData(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "反馈关联暂不可用"); }
    finally { setBusy(false); }
  }
  return <details className="space-y-3 rounded-md border p-3 text-sm" onToggle={event => { if (event.currentTarget.open && !data && !busy) void read(); }}><summary className="cursor-pointer font-medium">本修订承接的实测、质量与服务反馈</summary><p className="text-muted-foreground">只展示当前有权读取的项目反馈。历史关联、后来撤回或新回应替代需展开原落实记录核对。</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void read()}>刷新关联</Button>{error && <p role="alert" className="text-destructive">{error}</p>}{data && rows(data.items).length === 0 && <p>本页暂无可读取的关联反馈。</p>}{rows(data?.items).map(value => <article key={text(value.id)} className="space-y-2 border-t pt-3"><h6 className="font-medium">{({test_run:"实测",complaint:"质量 / 服务投诉",ncr:"NCR 根因与整改"} as Record<string,string>)[text(value.source_kind)]} · 落实 v{text(value.version)}</h6>{value.is_latest !== true && <p className="text-primary">此关联已有更新处置，请展开查看最新记录。</p>}{value.feedback_is_latest !== true && <p className="text-primary">原反馈已有更新回应，此处保留历史关联。</p>}<p className="whitespace-pre-wrap">{text(value.finding)}</p><p className="whitespace-pre-wrap">原落实说明：{text(value.reason)}</p><a className="inline-flex min-h-11 items-center underline" href={"/product-work?space=" + base.split("/")[1] + "&tab=definitions#definition-" + text(value.definition_id)}>回查原定义与反馈</a><ProductResultFollowups base={base} feedbackId={text(value.feedback_id)}/></article>)}{data?.next_before_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void read(text(data.next_before_id))}>更多关联历史</Button>}</details>;
}

function Responses({ values }: { values: unknown }) {
  return <div className="space-y-2">{rows(values).map(value => {
    const response = obj(value.response);
    return <section key={text(response.original_path)} className="space-y-1 rounded-md border p-2"><p className="break-all">原字段：{text(response.original_path)} · {treatments[text(response.treatment)]}</p><p className="whitespace-pre-wrap">{text(response.explanation)}</p>{response.revision_path != null && <p className="break-all">对应修订字段：{text(response.revision_path)} · {value.values_equal === true ? "字段值相同" : "字段值不同"}</p>}<div className="grid gap-2 md:grid-cols-2"><div><p className="text-muted-foreground">原反馈字段</p><pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(obj(value.original).value, null, 2)}</pre></div><div><p className="text-muted-foreground">本次修订字段</p>{value.revision_field == null ? <p>未对应现有字段</p> : <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(obj(value.revision_field).value, null, 2)}</pre>}</div></div></section>;
  })}</div>;
}

export function ProductResultFollowups({ base, feedbackId }: { base: string; feedbackId: string }) {
  const [data, setData] = useState<Row | null>(null), [options, setOptions] = useState<Row | null>(null), [preview, setPreview] = useState<Row | null>(null);
  const [action, setAction] = useState("needs_evidence"), [revision, setRevision] = useState("");
  const [responses, setResponses] = useState<Response[]>([]), [reason, setReason] = useState(""), [limits, setLimits] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const attempt = useRef<{ key: string; id: string } | null>(null);
  const basis = obj(data?.basis), feedback = obj(basis.feedback), selected = obj(basis.revision);
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "反馈落实暂不可用"); } finally { setBusy(false); } }
  async function load(selectedRevision = revision, before?: number) {
    const value = await request<Row>(base + "/result-followup-read", "POST", { feedback_id: feedbackId, revision_id: selectedRevision || null, before_version: before ?? null });
    setPreview(null); setData(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value);
    if (!data) setResponses(rows(obj(obj(value.basis).feedback).selected_fields).map(v => ({ original_path: text(v.path), revision_path: null, treatment: "needs_evidence", explanation: "" })));
  }
  async function loadOptions(before?: number) {
    const value = await request<Row>(base + "/result-followup-options", "POST", { feedback_id: feedbackId, before_revision: before ?? null });
    setOptions(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value);
  }
  function change(index: number, value: Partial<Response>) { setResponses(old => old.map((r, i) => i === index ? { ...r, ...value } : r)); setPreview(null); }
  function draft() { return { feedback_id: feedbackId, revision_id: action === "link_revision" ? revision || null : null, expected_digest: basis.digest, action, responses, reason, limitations: limits }; }
  async function save() {
    const body = { ...draft(), expected_version: data?.version, expected_preview_digest: preview?.digest };
    const key = JSON.stringify(body); if (attempt.current?.key !== key) attempt.current = { key, id: crypto.randomUUID() };
    await request(base + "/result-followup-save", "POST", { ...body, request_id: attempt.current.id }); attempt.current = null;
    await load(); setNotice("落实记录已保存；修订内容及原审批发布状态保持原流程办理。");
  }
  const href = (identity: unknown) => "/product-work?space=" + base.split("/")[1] + "&tab=definitions#definition-" + text(identity);
  const canLink = basis.feedback_is_latest === true && basis.sources_current === true && feedback.verdict === "adopt_for_followup" && obj(basis.current_source).inheritance_current === true;
  return <details className="space-y-3 rounded-md border p-3 text-sm" onToggle={event => { if (event.currentTarget.open && !data && !busy) void act(() => load()); }}>
    <summary className="cursor-pointer font-medium">后续落实与实际修订</summary><p className="text-muted-foreground">逐项记录本反馈的处理结果，关联同一定义系列的实际后续版本。草稿、协审与发布状态分别显示，关联记录不代表调整已生效或效果已验证。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load())}>刷新实际版本与历史</Button>
    {data && <>
      {basis.feedback_is_latest !== true && <p className="text-primary">此反馈已有更新回应；保留落实历史，可撤回原落实记录，请从最新反馈继续办理。</p>}
      {basis.sources_current !== true && <p className="text-primary">原实际依据或定义已有变化，关联修订前须重新核对并保存最新反馈。</p>}
      {data.can_manage === true && <form className="space-y-3" onSubmit={event => { event.preventDefault(); void act(async () => setPreview(await request<Row>(base + "/result-followup-preview", "POST", draft()))); }}><fieldset className="space-y-3" disabled={busy}>
        <label className="block">本次落实方式<select className={field} value={action} onChange={event => { const next = event.target.value; setAction(next); setRevision(""); setPreview(null); setResponses(old => old.map(v => ({ ...v, revision_path: null, treatment: "needs_evidence" }))); void act(async () => { await load(""); if (next === "link_revision") await loadOptions(); }); }}>{Object.entries(actions).map(([key, label]) => <option key={key} value={key} disabled={(key === "link_revision" && !canLink) || (key === "withdrawn" && !Number(data.version)) || (key !== "withdrawn" && (basis.feedback_is_latest !== true || feedback.verdict === "withdrawn"))}>{label}</option>)}</select></label>
        {action === "link_revision" && <section className="space-y-2"><Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadOptions())}>查找实际后续修订</Button><label className="block">后续修订<select className={field} required value={revision} onChange={event => { const next = event.target.value; setRevision(next); setPreview(null); setResponses(old => old.map(v => ({ ...v, revision_path: null, treatment: "needs_evidence" }))); void act(() => load(next)); }}><option value="">请选择同系列实际版本</option>{rows(options?.items).map(value => <option key={text(value.id)} value={text(value.id)}>{text(value.title)} · 修订 {text(value.revision_number)} · {states[text(value.state)] ?? text(value.state)}</option>)}</select></label>{options?.next_before_revision != null && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadOptions(Number(options.next_before_revision)))}>更早修订</Button>}{selected.id != null && <><a className="inline-flex min-h-11 items-center underline" href={href(selected.id)}>打开所选修订 · {states[text(selected.state)] ?? text(selected.state)}</a><details><summary className="cursor-pointer">核对所选修订完整正文</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(selected.content, null, 2)}</pre></details></>}</section>}
        {responses.map((response, index) => <section key={response.original_path} className="space-y-2 rounded-md border p-3"><h6 className="break-all font-medium">{response.original_path}</h6><pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(rows(feedback.selected_fields).find(v => v.path === response.original_path)?.value, null, 2)}</pre><label className="block">逐项处理<select className={field} value={response.treatment} onChange={event => change(index, { treatment: event.target.value, revision_path: event.target.value === "removed" ? null : response.revision_path })}>{Object.entries(treatments).filter(([key]) => action === "link_revision" || (key !== "changed" && key !== "removed")).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          {action === "link_revision" && response.treatment !== "removed" && <label className="block">明确对应的修订字段<select className={field} value={response.revision_path ?? ""} required={response.treatment === "changed" || response.treatment === "retained"} onChange={event => change(index, { revision_path: event.target.value || null })}><option value="">尚未对应</option>{rows(basis.revision_fields).map(value => <option key={text(value.path)} value={text(value.path)}>{text(value.path)}</option>)}</select></label>}
          <label className="block">处理或待补证说明<textarea className={field} required maxLength={2048} value={response.explanation} onChange={event => change(index, { explanation: event.target.value })}/></label></section>)}
        <label className="block">本次安排及依据<textarea className={field} required maxLength={2048} value={reason} onChange={event => { setReason(event.target.value); setPreview(null); }}/></label><label className="block">未落实范围、验证与适用限制<textarea className={field} required maxLength={2048} value={limits} onChange={event => { setLimits(event.target.value); setPreview(null); }}/></label><Button disabled={!responses.length}>预览逐项落实与原文对照</Button>
      </fieldset></form>}
      {preview && <section className="space-y-3 rounded-md bg-muted/30 p-3"><h6 className="font-medium">落实预览 · {actions[text(preview.action)]}</h6><Responses values={preview.responses}/><form onSubmit={event => { event.preventDefault(); void act(save); }} className="space-y-2"><label className="flex items-start gap-2"><input key={text(preview.digest)} required type="checkbox" disabled={busy}/>已逐项核对原反馈与实际修订；尚待发布、补证和效果验证的范围保留。</label><Button disabled={busy}>保存具名落实版本</Button></form></section>}
      {rows(data.items).map(value => {
        const saved = obj(value.snapshot), original = obj(obj(saved.basis).revision), current = obj(value.current_revision);
        return <article key={text(value.id)} className="space-y-2 border-t pt-3"><h6 className="font-medium">落实 v{text(value.version)} · {actions[text(value.action)]}{Number(value.version) === Number(data.version) ? " · 当前记录" : " · 历史记录"}</h6><p className="text-xs text-muted-foreground">{new Date(text(value.created_at)).toLocaleString()} · 记录人 {text(value.actor_user_id)}</p><p className="whitespace-pre-wrap">{text(saved.reason)}</p><p className="whitespace-pre-wrap">待办与限制：{text(saved.limitations)}</p>{current.id != null && <><a className="inline-flex min-h-11 items-center underline" href={href(current.id)}>实际修订 {text(current.revision_number)} · 当前 {states[text(current.state)] ?? text(current.state)}</a><p>登记时状态：{states[text(original.state)] ?? text(original.state)}{current.published_at != null ? " · 实际发布时间 " + new Date(text(current.published_at)).toLocaleString() : " · 尚无发布时间"}</p>{value.revision_unchanged !== true && <p className="text-primary">修订正文或状态已有变化；原落实对应保持当时版本，需重新核对。</p>}</>}{value.sources_current !== true && <p className="text-primary">实际来源已有变化，原处置保留供回查。</p>}<Responses values={saved.responses}/><details><summary className="cursor-pointer">登记时完整依据与当前修订</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({ saved: saved.basis, current_revision: value.current_revision }, null, 2)}</pre></details></article>;
      })}
      {data.next_before_version != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load(revision, Number(data.next_before_version)))}>更早落实版本</Button>}
    </>}
  </details>;
}
