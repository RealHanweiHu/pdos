"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { field, obj, request, rows, text, type Row } from "./fmea-sources";

export function FmeaDesignRules(props: { projectId: string; entryId: string }) {
  return <Panel key={`${props.projectId}:${props.entryId}`} {...props}/>;
}
function Panel({ projectId, entryId }: { projectId: string; entryId: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [saved, setSaved] = useState<Row | null>(null);
  const [title, setTitle] = useState(""), [content, setContent] = useState(""), [applicability, setApplicability] = useState("");
  const active = useRef(true), loading = useRef(false), attempted = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function load() {
    if (loading.current) return;
    loading.current = true; attempted.current = true; setBusy(true); setError(""); setData(null); setSaved(null);
    try {
      const value = await request(projectId, `/${entryId}/design-rules`);
      if (!Array.isArray(value.items) || typeof value.digest !== "string") throw new Error("候选依据返回不完整");
      if (active.current) { setData(value); setTitle(`设计规则候选：${text(obj(obj(value.version).body).title)}`); setContent(""); setApplicability(""); }
    } catch (e) { if (active.current) setError(e instanceof Error ? e.message : "读取失败"); }
    finally { loading.current = false; if (active.current) setBusy(false); }
  }
  const version = obj(data?.version), body = obj(version.body), pub = obj(data?.publication);
  const ready = !!pub.id && !!data?.basis && Array.isArray(data?.source_gaps) && data.source_gaps.length === 0;
  return <details className="rounded-md border p-3" onToggle={e => { if (e.target === e.currentTarget && e.currentTarget.open && !attempted.current) void load(); }}>
    <summary className="cursor-pointer font-medium">转为设计规则候选与专业审核</summary>
    <div className="mt-3 space-y-3 text-sm">
      <p className="text-xs text-muted-foreground">依据当前已发布 FMEA 整理可复用约束，明确适用与不适用条件。保存后仍为知识草稿，由另一位有权限的人员审核；不会修改项目规格或 FMEA 评分。</p>
      <Button variant="outline" size="sm" disabled={busy} onClick={() => void load()}>读取发布依据与原候选</Button>
      {busy && <p role="status">正在办理…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
      {data && <>
        {!pub.id ? <p>尚无已发布 FMEA，请先完成原版本的专业核对与发布。</p> : <div className="space-y-1 rounded-md border p-3"><p>采用已发布 v{text(version.version)}：{text(body.title)}</p><p className="whitespace-pre-wrap">设计功能：{text(body.design_function)}</p><p className="whitespace-pre-wrap">失效模式：{text(body.failure_mode)}</p>{rows(body.controls).map(control => <p key={text(control.key)} className="whitespace-pre-wrap">{control.kind === "prevention" ? "预防" : "探测"}控制：{text(control.description)}；验证要求：{text(control.verification)}</p>)}<p className="whitespace-pre-wrap">未覆盖范围：{text(body.control_gaps)}</p></div>}
        {pub.id != null && !ready && <p role="alert" className="text-destructive">发布依据或其质量证据已变化或不可用，请先核对、修订并发布 FMEA。</p>}
        {rows(data.items).map(memory => <Candidate key={text(memory.id)} projectId={projectId} memory={memory}/>)}
        {data.has_more === true && <a href={`/knowledge?project=${projectId}`} className="text-primary underline">查看完整知识历史</a>}
        {data.can_draft === true && ready && !saved && !rows(data.items).some(memory => memory.publication_id === pub.id) && <form className="space-y-3" onSubmit={e => { e.preventDefault(); if (loading.current) return; loading.current = true; setBusy(true); setError(""); void request(projectId, `/${entryId}/design-rules`, { publication_id: pub.id, expected_digest: data.digest, title: title.trim(), content: content.trim(), applicability: applicability.trim() }).then(result => { if (active.current) setSaved(obj(result.memory)); }, e => { if (active.current) setError(e instanceof Error ? e.message : "保存失败，请保留原内容重试"); }).finally(() => { loading.current = false; if (active.current) setBusy(false); }); }}>
          <fieldset disabled={busy} className="space-y-2"><label className="block">候选名称<input required maxLength={512} value={title} onChange={e => setTitle(e.target.value)} className={field}/></label>
          <label className="block">设计约束、方法与对应依据<textarea required maxLength={20000} value={content} onChange={e => setContent(e.target.value)} className={field}/></label>
          <label className="block">适用产品、工况与不适用边界<textarea required maxLength={5000} value={applicability} onChange={e => setApplicability(e.target.value)} className={field}/></label>
          <Button type="submit" size="sm" disabled={!title.trim() || !content.trim() || !applicability.trim()}>保存设计规则候选</Button></fieldset>
        </form>}
      </>}
      {saved && <div role="status"><p>已保存原候选，请继续具名编辑或独立审核。</p><Candidate projectId={projectId} memory={saved}/></div>}
    </div>
  </details>;
}
function Candidate({ projectId, memory }: { projectId: string; memory: Row }) {
  return <div className="rounded-md border p-2"><p>{text(memory.title)} · {({ draft: "待独立审核", verified: "已有审核记录，复用前仍核对来源", archived: "已归档" } as Record<string, string>)[text(memory.status)] ?? "读取原记录"}</p><a className="text-primary underline" href={`/knowledge?project=${projectId}&memory=${memory.id}`}>打开原知识候选与审核记录</a></div>;
}
