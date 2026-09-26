"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { ProcessTemplateSuggestions } from "@/components/organization/process-template-suggestions";

type Row = Record<string, unknown>;
export type BriefSource = {
  template_id: string;
  base_template_id: string;
  base_version: number;
  base_digest: string;
  expected_release_id: string | null;
};
const text = (value: unknown) => value == null ? "" : String(value);
const object = (value: unknown): Row => isRecord(value) ? value : {};
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const path = "/api/admin/organization/process-templates/briefs";
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

async function api(url: string, body?: unknown): Promise<Row> {
  const response = await fetch(url, { cache: "no-store", ...(body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : {}) });
  const value: unknown = await responseBody(response);
  if (!response.ok || !isRecord(value)) throw new Error(text(object(object(value).detail).message) || "管理要求暂不可用，请保留输入后重试");
  return value;
}

export function ProcessTemplateBriefs({ source, onConfigure, onOpenRevision }: {
  source: BriefSource | null;
  onConfigure: (brief: Row) => void;
  onOpenRevision: (id: string) => Promise<void>;
}) {
  const [instruction, setInstruction] = useState("");
  const [criteria, setCriteria] = useState("");
  const [previous, setPrevious] = useState<Row | null>(null);
  const [list, setList] = useState<Row | null>(null);
  const [detail, setDetail] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const attempt = useRef({ signature: "", id: "" });
  const detailEpoch = useRef(0);
  const current = object(detail?.brief);
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "办理失败"); }
    finally { setBusy(false); }
  }
  const load = async () => setList(await api(path));
  const open = async (id: string) => { const epoch=++detailEpoch.current; const value=await api(`${path}/${id}`); if (epoch === detailEpoch.current) setDetail(value); };
  async function save() {
    if (!source) return;
    const payload = { ...source, previous_brief_id: previous?.id ?? null, instruction, acceptance_criteria: criteria };
    const signature = JSON.stringify(payload);
    if (signature !== attempt.current.signature) attempt.current = { signature, id: crypto.randomUUID() };
    const value = await api(path, { ...payload, request_id: attempt.current.id });
    await open(text(value.id)); await load();
    setNotice("原始要求和模板依据已保存，本次没有自动发起生成。");
  }
  return <details className="rounded-md border p-3" onToggle={event => {
    if (event.currentTarget.open && !list && !busy) void act(load);
  }}>
    <summary className="cursor-pointer font-medium">管理要求原文与来源记录</summary>
    <fieldset disabled={busy} className="mt-3 space-y-3">
      <p className="text-sm text-muted-foreground">先保存管理要求、验收预期及当前模板版本。补充要求形成新记录，保留原文；之后可关联人工配置候选，或在智能建议开放后单独请求生成。</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {notice && <p role="status" className="text-sm">{notice}</p>}
      <p className="text-sm">{source ? `保存目标：${source.template_id}；依据 ${source.base_template_id} v${source.base_version}` : "请先选择配置依据及目标模板短码。"}</p>
      {previous && <div className="rounded-md bg-muted p-2 text-sm">
        本次补充自 {text(previous.template_id)} 的原要求，保存后保留两份记录。
        {previous.template_id !== source?.template_id && <p className="text-destructive">目标模板不同，请选择原目标模板或取消补充关系。</p>}
        <Button size="sm" variant="ghost" type="button" onClick={() => setPrevious(null)}>改为独立要求</Button>
      </div>}
      <label className="block text-sm">希望怎样管理流程<textarea className={field} rows={4} maxLength={16000} value={instruction} onChange={event => setInstruction(event.target.value)} placeholder="写明适用团队或产品、要改变的规则，以及希望保留的做法。"/></label>
      <label className="block text-sm">怎样判断配置符合要求<textarea className={field} rows={3} maxLength={8000} value={criteria} onChange={event => setCriteria(event.target.value)} placeholder="说明一个应允许的场景、一个应拒绝的场景，以及预期结果。"/></label>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" type="button" disabled={!source || !instruction.trim() || !criteria.trim() || Boolean(previous && previous.template_id !== source?.template_id)} onClick={() => void act(save)}>保存要求与来源</Button>
        <Button size="sm" variant="outline" type="button" onClick={() => void act(load)}>刷新要求记录</Button>
      </div>
      <div className="max-h-60 space-y-2 overflow-auto">{rows(list?.items).map(item => <Button key={text(item.id)} size="sm" variant="outline" type="button" className="block h-auto whitespace-normal text-left" onClick={() => void act(() => open(text(item.id)))}>
        {text(item.template_id)} · 来源 v{text(item.base_version)} · {new Date(text(item.created_at)).toLocaleString("zh-CN")}{item.previous_brief_id ? " · 补充要求" : ""}
      </Button>)}</div>
      {!!list?.next_before_id && <Button size="sm" variant="ghost" type="button" onClick={() => void act(async () => {
        const next = await api(`${path}?before_id=${encodeURIComponent(text(list.next_before_id))}`);
        setList({ ...next, items: [...rows(list.items), ...rows(next.items)] });
      })}>加载更早要求</Button>}
      {detail && <section className="space-y-3 border-t pt-3">
        <h4 className="font-medium">{text(current.template_id)} · 原始管理要求</h4>
        <p className="text-xs text-muted-foreground">保存于 {new Date(text(current.created_at)).toLocaleString("zh-CN")}；模板依据 {text(current.base_template_id)} v{text(current.base_version)}</p>
        <p className="whitespace-pre-wrap break-words text-sm">{text(current.instruction)}</p>
        <p className="font-medium text-sm">验收预期</p><p className="whitespace-pre-wrap break-words text-sm">{text(current.acceptance_criteria)}</p>
        <ProcessTemplateSuggestions key={text(current.id)} detail={detail} onRefresh={() => open(text(current.id))} onOpenRevision={onOpenRevision} onBusyChange={setBusy}/>
        {!detail.source_current && <p className="text-sm text-destructive">依据或目标发布版已变化。请先选择当前模板，载入此要求补充，再保存为新记录。</p>}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" type="button" variant="outline" disabled={!detail.source_current} onClick={() => void act(async () => {
            const refreshed = await api(`${path}/${text(current.id)}`); setDetail(refreshed);
            if (!refreshed.source_current) throw new Error("模板来源已变化，请读取当前版后保存新要求。");
            onConfigure(object(refreshed.brief));
          })}>按此要求重新载入配置依据</Button>
          <Button size="sm" type="button" variant="outline" onClick={() => { setInstruction(text(current.instruction)); setCriteria(text(current.acceptance_criteria)); setPrevious(current); setNotice("已载入原文。保存将采用上方当前选择的模板依据，并生成新记录。"); }}>载入原文补充</Button>
          {!!current.previous_brief_id && <Button size="sm" type="button" variant="ghost" onClick={() => void act(() => open(text(current.previous_brief_id)))}>查看上一份原始要求</Button>}
        </div>
        <p className="text-xs text-muted-foreground">重新载入会替换尚未保存的配置编辑内容。以下是基于此要求保存的候选，候选尚需独立演练和发布。</p>
        {rows(detail.revisions).map(item => <Button key={text(item.id)} size="sm" variant="ghost" type="button" className="block h-auto whitespace-normal text-left" onClick={() => void act(() => onOpenRevision(text(item.id)))}>候选 v{text(item.version)} · {text(item.reason)}</Button>)}
        {detail.revisions_truncated === true && <p className="text-xs text-muted-foreground">仅显示最近50个关联候选。</p>}
      </section>}
    </fieldset>
  </details>;
}
