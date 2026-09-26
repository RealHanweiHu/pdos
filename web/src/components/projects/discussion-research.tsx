"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";

const date = (v: unknown) => typeof v === "string" ? new Date(v).toLocaleString("zh-CN") : "未记录";

export function DiscussionResearch({ projectId, run, canAdd, onAdded }: { projectId: string; run: Row; canAdd: boolean; onAdded: () => Promise<void> }) {
  const [options, setOptions] = useState<Row | null>(null), [selected, setSelected] = useState("");
  const [offset, setOffset] = useState(0), [length, setLength] = useState(4000), [note, setNote] = useState("");
  const [preview, setPreview] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const attempt = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/projects/${projectId}/changes/discussion-runs/${run.run_id}/research`;
  async function request(path: string, body?: Row): Promise<Row> {
    const response = await fetch(base + path, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const value: unknown = await response.json();
    if (!response.ok) throw new Error(text(obj(obj(value).detail).message) || "研究快照操作未完成，请核对权限或重试");
    return obj(value);
  }
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "操作未完成"); }
    finally { setBusy(false); }
  }
  const additions = rows(run.research_inputs);
  return <details className="space-y-2 rounded-md border p-3"><summary className="cursor-pointer font-medium">公开研究依据与执行记录 · {additions.length} 份片段</summary>
    <p>使用已有正文的公开来源快照；原内部对象范围保持固定。后续尚未固定输入的调用可读取新片段，旧发言和已固定调用不会改写。原文及追加说明仍需核对。</p>
    {run.research_current === false && <p className="text-primary">追加来源的版本或有效性已变化；请核对历史快照，继续时需按当前资料关联新讨论。</p>}
    {rows(run.research_choices).length > 0 && <details><summary className="cursor-pointer">各专业实际研究判断 · {rows(run.research_choices).length} 次</summary><div className="mt-2 space-y-2">{rows(run.research_choices).map(v => { const decision = obj(obj(v.body).output), tool = rows(run.research_tools).find(t => obj(t.input_body).checkpoint_id === v.id), result = obj(tool?.output_body); return <div key={text(v.id)} className="rounded-md bg-muted/40 p-2"><p>{text(v.seat_label)} · 第 {String(v.round_number)} 轮 · 研究第 {String(v.step)} 步：{decision.action === "finish" ? "结束研究，进入发言" : decision.action === "search" ? "搜索公开线索" : "读取公开原文"}</p><p>{text(decision.reason)}</p>{decision.target != null && <p className="break-all">查询目标：{text(decision.target)}</p>}{decision.action !== "finish" && <><p>{tool ? ({ completed: "读取完成", partial: "已读取部分内容", no_results: "搜索返回零结果", unavailable: "暂不可用", denied: "地址政策拒绝" }[text(result.status)] ?? "执行状态待核对") : "尚无可用工具结果，不能据此引用"}。{text(result.notice)}</p>{result.error_code != null && <p>原因：{text(result.error_code)}</p>}{rows(result.hits).map((hit, i) => <p key={i} className="break-all">线索：{text(hit.title)} · {text(hit.url)}（尚未读取原文）</p>)}</>}</div>; })}</div></details>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {canAdd && <div className="space-y-2">
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => setOptions(await request("/sources")))}>加载已有研究快照</Button>
      {options && <fieldset disabled={busy} className="space-y-2">
        <p>{text(options.notice)}</p>
        <label className="block">研究快照<select className={field} value={selected} onChange={e => { setSelected(e.target.value); setPreview(null); }}><option value="">选择已有快照</option>{rows(options.items).map(v => <option value={text(v.id)} key={text(v.id)}>{text(v.name)} · {date(v.captured_at)} · {text(v.url)}</option>)}</select></label>
        <div className="grid gap-2 sm:grid-cols-2"><label>片段起点（字符，从0开始）<input type="number" min={0} max={2000000} className={field} value={offset} onChange={e => { setOffset(Number(e.target.value)); setPreview(null); }}/></label><label>片段长度（最多6000字符）<input type="number" min={1} max={6000} className={field} value={length} onChange={e => { setLength(Number(e.target.value)); setPreview(null); }}/></label></div>
        <Button type="button" size="sm" variant="outline" disabled={!selected || !Number.isInteger(offset) || !Number.isInteger(length) || length < 1 || length > 6000 || offset < 0} onClick={() => void act(async () => setPreview(await request("/preview", { snapshot_id: selected, offset, length })))}>预览原文片段</Button>
        {preview && <div className="space-y-2"><p>已保存正文共 {String(preview.total_characters)} 字符，本次只追加以下片段：</p><p className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2">{text(obj(obj(preview.reference).fields).excerpt)}</p>
          {obj(obj(preview.reference).fields).stale === true && <p className="text-primary">已到建议复查时间，作为历史观察保留。</p>}
          {obj(obj(preview.reference).fields).superseded_by_id != null && <p className="text-primary">此快照已有新版，请核对是否需要引用历史版本。</p>}
          {obj(obj(preview.reference).fields).conflicts_with_id != null && <p className="text-primary">此快照记录了冲突，须保留并核对。</p>}
          <label className="block">为什么追加、需要核对什么<textarea maxLength={2000} className={field} value={note} onChange={e => setNote(e.target.value)}/></label>
          <Button type="button" size="sm" disabled={!note.trim()} onClick={() => void act(async () => {
            const body = { snapshot_id: selected, offset, length, note: note.trim(), expected_digest: preview.digest };
            const signature = JSON.stringify(body);
            if (attempt.current?.signature !== signature) attempt.current = { signature, id: crypto.randomUUID() };
            await request("", { ...body, request_id: attempt.current.id });
            attempt.current = null; setPreview(null); setNote(""); await onAdded();
          })}>具名追加至本场讨论</Button>
        </div>}
      </fieldset>}
    </div>}
    {additions.map(item => { const ref = obj(item.reference), f = obj(ref.fields), cited = rows(run.receipts).filter(r => [...rows(obj(r.output).statements), ...rows(obj(r.output).responses).map(v => obj(v.basis))].some(s => rows(s.citations).some(c => c.reference_id === ref.reference_id))); return <details className="rounded-md bg-muted/40 p-2" key={text(item.id)}><summary className="cursor-pointer">{text(ref.label)} · {item.origin === "agent_research" ? "专业研究采集" : "具名人工追加"} · {date(item.created_at)}</summary><div className="mt-2 space-y-1">
      <p>原文采集：{date(f.captured_at)}；片段起点：{String(f.excerpt_offset)}。{f.stale === true ? "追加时已过建议复查期。" : ""}{f.superseded_by_id ? "追加时已有新版。" : ""}{f.conflicts_with_id ? "追加时有冲突记录。" : ""}</p>
      <p className="break-all">来源：{text(f.url)}</p><p>{item.origin === "agent_research" ? "专业研究目的" : "人工追加说明"}：{text(obj(item.request).note)}</p>
      <p>已有 {cited.length} 条专业发言明确引用此片段；未引用不代表已采纳。</p>
      <p className="whitespace-pre-wrap">{text(f.excerpt)}</p>
      <p>此处保留追加时的原值；新的有效性以当前核对提示为准。</p>
    </div></details>; })}
  </details>;
}
