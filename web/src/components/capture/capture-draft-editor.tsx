"use client";

import { useEffect, useRef, useState } from "react";
import { CaptureRecognition } from "./capture-recognition";
import { Button } from "@/components/ui/button";
import { TestRunConfigurationPicker } from "@/components/projects/test-run-configuration-picker";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const txt = (v: unknown) => v == null ? "" : String(v);
const obj = (v: unknown): Row => isRecord(v) ? v : {};
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
async function api(path: string, body?: unknown): Promise<Row> {
  const response = await fetch(path, { cache: "no-store", ...(body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
  const value: unknown = await responseBody(response);
  if (!response.ok || !isRecord(value)) throw new Error(txt(obj(obj(value).detail).message) || "办理失败，请保留当前输入后重试");
  return value;
}
function initial(record: Row): Row {
  return { kind: "issue", title: "", description: txt(record.original_text), recognition_id: null, recognition_note: "", issue_type: "engineering", severity: "medium", sample_id: null, sample_reason: "", test_case_id: null, test_case_digest: null, status: "in_progress", conditions: "", equipment: "", environment: "", metrics: [], expected_completion_at: null, executed_at: null, execution_time_precision: "unknown", execution_time_reason: "", configuration_mode: "unknown", configuration_revision_id: null, configuration_reason: "", evidence_document_id: null, ...obj(obj(record.draft).body) };
}
function localTime(value: unknown) { if (!value) return ""; const date = new Date(txt(value)); if (!Number.isFinite(date.getTime())) return ""; return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
function timestamp(value: string) { return value ? new Date(value).toISOString() : null; }

export function CaptureDraftEditor({ base, record, submitted }: { base: string; record: Row; submitted: (r: Row) => void }) {
  const [draft, setDraft] = useState<Row>(() => initial(record));
  const [version, setVersion] = useState(Number(obj(record.draft).version) || 0);
  const [savedText, setSavedText] = useState(() => record.draft ? JSON.stringify(initial(record)) : "");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState(""), [confirmed, setConfirmed] = useState(false);
  const [query, setQuery] = useState(""), [samples, setSamples] = useState<Row[]>([]), [sampleName, setSampleName] = useState("");
  const [caseQuery, setCaseQuery] = useState(""), [cases, setCases] = useState<Row[]>([]), [caseInfo, setCaseInfo] = useState<Row | null>(null);
  const [history, setHistory] = useState<Row[]>([]), [before, setBefore] = useState<number | null>(null), [documents, setDocuments] = useState<Row[]>([]);
  const request = useRef({ signature: "", id: "" });
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const path = `${base}/${txt(record.id)}`, project = txt(record.project_id);
  const dirty = JSON.stringify(draft) !== savedText, isTest = draft.kind === "test";
  function update(change: Row) { setDraft(current => ({ ...current, ...change })); setConfirmed(false); setNotice(""); }
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "办理失败"); } finally { setBusy(false); } }
  async function save() {
    const signature = JSON.stringify([version, draft]);
    if (request.current.signature !== signature) request.current = { signature, id: crypto.randomUUID() };
    const result = await api(`${path}/drafts`, { request_id: request.current.id, expected_version: version, draft });
    setVersion(Number(result.version)); setDraft(obj(result.body)); setSavedText(JSON.stringify(obj(result.body))); setConfirmed(false); setNotice(`草稿第 ${String(result.version)} 版已保存，可稍后继续。`);
  }
  async function loadHistory(next?: number) { const result = await api(`${path}/drafts${next ? `?before=${next}` : ""}`); setHistory(current => next ? [...current, ...rows(result.items)] : rows(result.items)); setBefore(typeof result.next_before === "number" ? result.next_before : null); }
  const textField = (key: string, label: string, maxLength: number, multiline = false) => <label className="block text-sm">{label}{multiline ? <textarea rows={3} maxLength={maxLength} className={field} value={txt(draft[key])} onChange={e => update({ [key]: e.target.value })}/> : <input maxLength={maxLength} className={field} value={txt(draft[key])} onChange={e => update({ [key]: e.target.value })}/>}</label>;
  return <section className="space-y-3 border-t pt-4">
    <h3 className="font-medium">人工办理草稿{version > 0 ? ` · 第 ${version} 版` : " · 尚未保存"}{dirty ? "（有未保存内容）" : ""}</h3>
    <p className="text-xs text-muted-foreground">草稿可缺项保存，确认提交前须补齐。识别文字须对照原件核对，不代表已批准结论。</p>
    {record.uploaded_at != null && <CaptureRecognition path={path} media={txt(record.media_type)} editable disabled={busy} selectedId={txt(draft.recognition_id)} adopt={(id, text) => {
      const description = text ? [txt(draft.description), text].filter(Boolean).join("\n\n") : txt(draft.description);
      if (description.length > 16000) { setError("合并后说明超过16000字，请手动整理，或仅关联识别来源。"); return; }
      update({ description, recognition_id: id, recognition_note: "" }); setError(""); setNotice("识别来源已加入本地草稿，请对照原件修正文字、填写核对情况并保存。");
    }}/>} 
    <fieldset disabled={busy} className="space-y-3">
      <label className="block text-sm">办理类型<select className={field} value={txt(draft.kind)} onChange={e => update({ kind: e.target.value })}><option value="issue">登记问题</option><option value="test">登记一次测试</option></select></label>
      {!isTest && <>{textField("title", "问题标题", 512)}<div className="grid gap-3 sm:grid-cols-2"><label className="block text-sm">问题类型<select className={field} value={txt(draft.issue_type)} onChange={e => update({ issue_type: e.target.value })}>{Object.entries({ engineering: "工程", quality: "品质", supplier: "供应商", test_failure: "测试失败", certification: "认证" }).map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label><label className="block text-sm">严重程度<select className={field} value={txt(draft.severity)} onChange={e => update({ severity: e.target.value })}>{Object.entries({ low: "低", medium: "中", high: "高", critical: "严重" }).map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label></div></>}
      {draft.recognition_id != null && <div className="space-y-2 rounded-md border p-3">{textField("recognition_note", "识别核对情况、修正内容及仍不确定之处（提交前必填）", 2000, true)}<Button type="button" size="sm" variant="ghost" onClick={() => update({ recognition_id: null, recognition_note: "" })}>解除识别来源关联（保留当前说明文字）</Button></div>}
      {textField("description", isTest ? "测试现象、结果说明与不确定内容" : "问题现象与待核对内容", 16000, true)}
      <div className="space-y-2 rounded-md border p-3"><label className="block text-sm">查找样机编号<input className={field} maxLength={200} value={query} onChange={e => setQuery(e.target.value)}/></label><Button type="button" variant="outline" size="sm" onClick={() => void act(async () => setSamples(rows((await api(`${base}/samples?q=${encodeURIComponent(query)}`)).items)))}>查询项目样机</Button>
        <p className="text-xs text-muted-foreground">最多显示50条，请缩小编号查找。出现相近或多个编号时须明确选择，系统不会自动关联。</p>
        <div className="max-h-40 space-y-2 overflow-auto">{samples.map(s => <label key={txt(s.id)} className="flex items-center gap-2 break-all text-sm"><input type="radio" name={`sample-${txt(record.id)}`} checked={draft.sample_id === s.id} onChange={() => { update({ sample_id: s.id, configuration_mode: "unknown", configuration_revision_id: null, configuration_reason: "", evidence_document_id: null }); setSampleName(txt(s.serial_number)); }}/>{txt(s.serial_number)}</label>)}</div>
        {draft.sample_id ? <p className="break-all text-sm">已选样机：{sampleName || txt(draft.sample_id)} <Button type="button" size="sm" variant="ghost" onClick={() => { update({ sample_id: null, configuration_mode: "unknown", configuration_revision_id: null, evidence_document_id: null }); setSampleName(""); }}>清除关联</Button></p> : textField("sample_reason", "未关联原因 / 待确认内容", 2000, true)}
      </div>
      {isTest && <>
        <div className="space-y-2 rounded-md border p-3"><label className="block text-sm">查找测试用例<input className={field} maxLength={200} value={caseQuery} onChange={e => setCaseQuery(e.target.value)}/></label><Button type="button" variant="outline" size="sm" onClick={() => void act(async () => setCases(rows((await api(`${base}/test-cases?q=${encodeURIComponent(caseQuery)}`)).items)))}>读取测试方法与判据</Button><p className="text-xs text-muted-foreground">最多显示50条。必须选中实际用例；提交时会重核测试方法与判据是否变化。</p><div className="max-h-48 space-y-2 overflow-auto">{cases.map(c => <label className="flex gap-2 text-sm" key={txt(c.id)}><input type="radio" name={`case-${txt(record.id)}`} checked={draft.test_case_id === c.id} onChange={() => { update({ test_case_id: c.id, test_case_digest: c.digest }); setCaseInfo(c); }}/>{txt(c.title)}</label>)}</div>{caseInfo ? <div className="whitespace-pre-wrap text-sm"><p>方法：{txt(caseInfo.method) || "未填写"}</p><p>验收判据：{txt(caseInfo.acceptance_criteria)}</p></div> : draft.test_case_id != null && <p className="break-all text-xs">草稿已保存用例选择。可重新读取并选中，核对当前方法与判据。</p>}</div>
        <label className="block text-sm">实际测试状态<select className={field} value={txt(draft.status)} onChange={e => update({ status: e.target.value, executed_at: null, execution_time_precision: "unknown", execution_time_reason: "", configuration_mode: "unknown", configuration_revision_id: null })}>{Object.entries({ in_progress: "正在进行", passed: "已通过", failed: "已失败", aborted: "已终止" }).map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        {draft.status === "in_progress" ? <label className="block text-sm">预计完成时间<input type="datetime-local" className={field} value={localTime(draft.expected_completion_at)} onChange={e => update({ expected_completion_at: timestamp(e.target.value) })}/></label> : <div className="space-y-2"><label className="block text-sm">实际测试时间精度<select className={field} value={txt(draft.execution_time_precision)} onChange={e => update({ execution_time_precision: e.target.value, executed_at: null })}><option value="unknown">尚待确认（不能提交）</option><option value="day">仅确认日期</option><option value="instant">确认具体时间</option></select></label>{draft.execution_time_precision === "day" && <label className="block text-sm">实际测试日期<input type="date" className={field} value={txt(draft.executed_at).slice(0,10)} onChange={e => update({ executed_at: e.target.value ? `${e.target.value}T00:00:00Z` : null })}/></label>}{draft.execution_time_precision === "instant" && <label className="block text-sm">实际测试时间（本机时区）<input type="datetime-local" className={field} value={localTime(draft.executed_at)} onChange={e => update({ executed_at: timestamp(e.target.value) })}/></label>}{textField("execution_time_reason", "实际时间的登记依据", 2000)}<p className="text-xs text-muted-foreground">照片拍摄、上传与登记时间不能代替实际测试时间。</p></div>}
        <label className="block text-sm">当次样机配置<select className={field} value={txt(draft.configuration_mode)} onChange={e => update({ configuration_mode: e.target.value, configuration_revision_id: null })}><option value="unknown">配置未知，保留原因</option>{draft.status === "in_progress" && <option value="current">开始登记时固定当前已确认配置</option>}<option value="revision" disabled={!draft.sample_id}>明确选择已保存版本</option></select></label>
        {draft.configuration_mode !== "current" && textField("configuration_reason", "配置选择依据 / 未知原因", 2000)}
        {draft.configuration_mode === "revision" && draft.sample_id != null && <TestRunConfigurationPicker projectId={project} sampleId={txt(draft.sample_id)} value={txt(draft.configuration_revision_id)} busy={busy} onSelect={revision => update({ configuration_revision_id: revision?.id ?? null, evidence_document_id: revision?.source_document_id ?? null })}/>}
        <div className="grid gap-3 sm:grid-cols-2">{textField("equipment", "测试设备", 256)}{textField("environment", "测试环境", 256)}</div>{textField("conditions", "测试条件", 10000, true)}
        <div className="space-y-2"><p className="text-sm font-medium">实际测量值</p>{rows(draft.metrics).map((m,i) => <div key={i} className="space-y-2 rounded-md border p-3"><div className="grid gap-2 sm:grid-cols-2">{[["name","指标名称",128],["value","实测值",2000],["unit","单位",32],["target","目标值",2000]].map(([key,label,max]) => <label className="text-sm" key={txt(key)}>{txt(label)}<input className={field} maxLength={Number(max)} value={txt(m[txt(key)])} onChange={e => update({ metrics: rows(draft.metrics).map((r,n) => n === i ? { ...r, [txt(key)]: e.target.value } : r) })}/></label>)}</div><label className="block text-sm">本项结论<select className={field} value={txt(m.verdict)} onChange={e => update({ metrics: rows(draft.metrics).map((r,n) => n === i ? { ...r, verdict: e.target.value } : r) })}><option value="info">仅记录</option><option value="pass">通过</option><option value="fail">失败</option></select></label><Button type="button" variant="ghost" size="sm" onClick={() => update({ metrics: rows(draft.metrics).filter((_,n) => n !== i) })}>移除此测量项</Button></div>)}<Button type="button" variant="outline" size="sm" disabled={rows(draft.metrics).length>=100} onClick={() => update({ metrics: [...rows(draft.metrics), { name: "", value: "", unit: "", target: "", verdict: "info" }] })}>增加测量项</Button></div>
        <div className="space-y-2"><Button type="button" variant="outline" size="sm" onClick={() => void act(async () => setDocuments(rows((await api(`/api/projects/${project}/documents`)).items)))}>读取已有证据文档</Button><label className="block text-sm">关联报告 / 证据文档<select className={field} value={txt(draft.evidence_document_id)} onChange={e => update({ evidence_document_id: e.target.value || null })}><option value="">未关联报告</option>{draft.evidence_document_id != null && !documents.some(d => d.id === draft.evidence_document_id) && <option value={txt(draft.evidence_document_id)}>已保存的配置来源报告 / 证据</option>}{documents.map(d => <option key={txt(d.id)} value={txt(d.id)}>{txt(d.filename)}</option>)}</select></label><p className="text-xs text-muted-foreground">现场原件单独保留并可回查；采用报告提取的配置时必须绑定同一报告。</p></div>
      </>}
      <div className="flex flex-wrap gap-2"><Button type="button" disabled={!dirty} onClick={() => void act(save)}>保存草稿</Button><Button type="button" variant="outline" size="sm" onClick={() => void act(() => loadHistory())}>查看草稿历史</Button><Button type="button" variant="ghost" size="sm" onClick={() => void act(async () => { const latest = await api(path); if (latest.submitted_at) { submitted(latest); return; } const body = initial(latest); setDraft(body); setVersion(Number(obj(latest.draft).version) || 0); setSavedText(latest.draft ? JSON.stringify(body) : ""); setConfirmed(false); setCaseInfo(null); setSampleName(""); setNotice("已载入服务器最新草稿，本地未保存修改已放弃。"); })}>放弃本地修改，载入最新</Button></div>
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {history.length>0 && <div className="max-h-80 space-y-2 overflow-auto rounded-md border p-3">{history.map(h => <details key={txt(h.id)} className="text-sm"><summary>第 {String(h.version)} 版 · {new Date(txt(h.created_at)).toLocaleString("zh-CN")} · {obj(h.body).kind === "test" ? "测试" : "问题"}</summary><p className="whitespace-pre-wrap py-2">{txt(obj(h.body).title)}{txt(obj(h.body).description)}</p><Button type="button" size="sm" variant="outline" onClick={() => { setDraft(obj(h.body)); setConfirmed(false); setNotice("已载入历史内容，保存时会生成新版本。请重新核对样机、测试方法和时间。"); setCaseInfo(null); setSampleName(""); }}>载入为新草稿</Button></details>)}{before != null && <Button type="button" size="sm" variant="ghost" onClick={() => void act(() => loadHistory(before))}>更早版本</Button>}</div>}
      <label className="flex items-start gap-2 text-sm"><input className="mt-1" type="checkbox" checked={confirmed} disabled={dirty || !version || record.status === "awaiting_upload"} onChange={e => setConfirmed(e.target.checked)}/>我已核对已保存的第 {version || "—"} 版内容、样机及{isTest ? "实际测试状态与依据" : "问题事实"}。提交后原件与核对记录对有权办理项目的人员可见。</label>
      <p className="text-xs text-muted-foreground">{dirty ? "请先保存草稿，再确认提交。" : ""}{record.status === "awaiting_upload" ? "原件仍待补传，草稿可保存，暂不能提交。" : ""}每条现场记录只转入一个业务记录，后续在原记录中办理。</p>
      <Button type="button" disabled={!confirmed || dirty || !version || record.status === "awaiting_upload"} onClick={() => void act(async () => { const result = await api(`${path}/submit`, { expected_version: version, confirmed: true }); if (mounted.current) submitted(result); })}>{busy ? "正在办理…" : isTest ? "确认并登记测试" : "确认并登记问题"}</Button>
    </fieldset>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </section>;
}
