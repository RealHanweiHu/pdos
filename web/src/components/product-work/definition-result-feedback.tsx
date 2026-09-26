"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { obj, rows, text, field, type Row } from "@/components/quality/fmea-sources";
import { request } from "./product-work-api";
import { ProductResultFollowups } from "./product-result-followups";
import { ProductMetricCalculations } from "./product-metric-calculations";
import { NcrWorkspace } from "@/components/quality/ncr-workspace";

const kinds = { test_run: "逐次实测结果", complaint: "质量 / 服务投诉", ncr: "NCR 根因与整改闭环" };
const verdicts: Record<string, string> = { adopt_for_followup: "采用为后续调整依据", reject_application: "不采用到本次字段", needs_evidence: "要求补充证据", withdrawn: "撤回原反馈" };
const states: Record<string, string> = { passed: "通过", failed: "失败", aborted: "中止", open: "待处理", triaged: "已分诊", investigating: "调查中", resolved: "已解决", closed: "已关闭", containment: "遏制中", root_cause: "根因分析", action: "整改中", verification: "有效性验证" };

export function DefinitionResultFeedback({ base, definitionId }: { base: string; definitionId: string }) {
  const [projects, setProjects] = useState<Row | null>(null), [project, setProject] = useState("");
  const [kind, setKind] = useState<keyof typeof kinds>("test_run"), [options, setOptions] = useState<Row | null>(null), [sourceId, setSourceId] = useState("");
  const [search, setSearch] = useState(""), [loadedSearch, setLoadedSearch] = useState(""), [data, setData] = useState<Row | null>(null);
  const [showNcr, setShowNcr] = useState(false);
  const [history, setHistory] = useState<Row | null>(null);
  const [paths, setPaths] = useState<string[]>([]), [verdict, setVerdict] = useState("needs_evidence");
  const [finding, setFinding] = useState(""), [change, setChange] = useState(""), [limits, setLimits] = useState(""), [applicability, setApplicability] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const attempt = useRef<{ key: string; id: string } | null>(null);
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "实际结果反馈暂不可用"); } finally { setBusy(false); } }
  async function loadProjects(before?: string) { const value = await request<Row>(`${base}/result-feedback-options`, "POST", { definition_id: definitionId, before_id: before ?? null }); setProjects(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
  async function loadSources(before?: string) { const query = before ? loadedSearch : search; const value = await request<Row>(`${base}/result-feedback-options`, "POST", { definition_id: definitionId, project_id: project, source_kind: kind, search: query, before_id: before ?? null }); setOptions(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); setLoadedSearch(query); }
  async function read(before?: number) { const value = await request<Row>(`${base}/result-feedback`, "POST", { definition_id: definitionId, project_id: project, source_kind: kind, source_id: sourceId, before_version: before ?? null }); setData(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
  async function loadHistory(before?: string) { const value = await request<Row>(`${base}/result-feedback-history`, "POST", { definition_id: definitionId, before_id: before ?? null }); setHistory(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
  function clearSource() { setShowNcr(false); setOptions(null); setSourceId(""); setData(null); setPaths([]); setNotice(""); }
  const source = obj(data?.source), actual = obj(source.source), record = obj(actual.record), testCase = obj(actual.test_case);
  async function save() {
    const body = { definition_id: definitionId, project_id: project, source_kind: kind, source_id: sourceId, expected_version: data?.version, expected_digest: source.digest, field_paths: paths, verdict, finding, proposed_change: change, limitations: limits, applicability_basis: applicability };
    const key = JSON.stringify(body); if (attempt.current?.key !== key) attempt.current = { key, id: crypto.randomUUID() };
    await request(`${base}/result-feedback-save`, "POST", { ...body, request_id: attempt.current.id });
    attempt.current = null; setNotice("具名反馈已保存，可沿原定义创建修订；原发布内容和业务结果保持留档。"); setFinding(""); setChange(""); setLimits(""); setApplicability(""); await read(); await loadHistory();
  }
  return <details className="space-y-3 rounded-md border p-3 text-sm" onToggle={event => { if (event.currentTarget.open && !projects && !busy) void act(async () => { await loadProjects(); await loadHistory(); }); }}>
    <summary className="cursor-pointer font-medium">实测、质量与服务结果反馈</summary>
    <p className="text-muted-foreground">选择实际继承本定义的项目，对照真实结果与原定义字段，记录适用范围和后续安排。失败、中止与未结案记录均按原状态保留。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <details className="space-y-2"><summary className="cursor-pointer">本定义已收到的反馈与历史</summary><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => loadHistory())}>刷新历史</Button>{history && rows(history.items).length === 0 && <p>此页暂无当前有权读取的反馈。</p>}{rows(history?.items).map(value => <article key={text(value.id)} className="space-y-2 rounded-md border p-3"><p className="font-medium">{kinds[text(value.source_kind) as keyof typeof kinds]} · v{text(value.version)} · {verdicts[text(value.verdict)]} · {value.is_latest ? "该来源最新回应" : "历史回应"}</p><p>{text(value.actor_name)} · {new Date(text(value.created_at)).toLocaleString()}</p><p className="whitespace-pre-wrap">{text(value.finding)}</p><p className="whitespace-pre-wrap">后续：{text(value.proposed_change)}</p>{value.sources_current !== true && <p className="text-primary">当前资料或继承关系已变化，以下保留原时点判断。</p>}<ProductResultFollowups base={base} feedbackId={text(value.id)}/><details><summary className="cursor-pointer">适用范围、原字段与完整原依据</summary><p>{text(value.applicability_basis)}</p><p>{text(value.limitations)}</p><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({ fields: value.selected_fields, source: value.source_snapshot }, null, 2)}</pre></details><a className="inline-flex min-h-11 items-center underline" href={`/projects/${text(value.project_id)}`}>回查原项目</a></article>)}{history?.next_before_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => loadHistory(text(history.next_before_id)))}>更多历史反馈</Button>}</details>
    <fieldset disabled={busy} className="space-y-3">
      <label className="block">实际项目<select className={field} value={project} onChange={event => { setProject(event.target.value); clearSource(); }}><option value="">请选择有权读取的实际关联项目</option>{rows(projects?.items).map(value => <option key={text(value.id)} value={text(value.id)}>{text(value.title)}</option>)}</select></label>
      <Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadProjects())}>刷新关联项目</Button>{projects?.next_before_id != null && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadProjects(text(projects.next_before_id)))}>继续查找关联项目</Button>}
      <label className="block">结果类型<select className={field} value={kind} onChange={event => { setKind(event.target.value as keyof typeof kinds); clearSource(); }}>{Object.entries(kinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="block">原测试项、投诉或 NCR 描述<input className={field} value={search} maxLength={128} onChange={event => setSearch(event.target.value)}/></label><Button type="button" size="sm" variant="outline" disabled={!project} onClick={() => void act(() => loadSources())}>查找实际来源</Button>
      <label className="block">选择原记录<select className={field} value={sourceId} onChange={event => { setSourceId(event.target.value); setData(null); setPaths([]); setNotice(""); }}><option value="">请选择</option>{rows(options?.items).map(value => <option key={text(value.id)} value={text(value.id)}>{text(value.title)}{value.run_number != null ? ` · 第 ${text(value.run_number)} 次` : ""} · {states[text(value.status)] ?? text(value.status)} · {text(value.time) || "时点未登记"}</option>)}</select></label>
      {options && rows(options.items).length === 0 && <p>此页暂无匹配来源；可修改搜索或继续翻页。</p>}{options?.next_before_id != null && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadSources(text(options.next_before_id)))}>更多原记录</Button>}
      <Button type="button" disabled={!sourceId || !project} onClick={() => void act(() => read())}>读取原结果与定义对照</Button>
    </fieldset>
    {data && <>
      {source.inheritance_current !== true && <p className="text-primary">当前项目已不再继承此定义，保留原反馈供回查。</p>}
      <section className="space-y-2 rounded-md bg-muted/30 p-3"><h6 className="font-medium">{text(testCase.title) || text(record.title) || text(record.code)} · {states[text(record.status)] ?? text(record.status)}</h6>
        {kind === "test_run" ? <><p className="whitespace-pre-wrap">原测试判据：{text(testCase.acceptance_criteria)}</p><p className="whitespace-pre-wrap">方法：{text(testCase.method) || "未登记"}</p><p className="whitespace-pre-wrap">实际说明：{text(record.result_notes) || "未登记"}</p><p>原规格继承条目 {rows(actual.inherited_specifications).length} 项；实测指标 {rows(record.metrics).length} 项</p></> : kind === "ncr" ? <>
          <p className="whitespace-pre-wrap">不符合项：{text(record.nonconformity)}</p><p className="whitespace-pre-wrap">原要求：{text(record.requirement_reference)}</p><p>受影响范围：{text(record.affected_scope) || "未登记"} · 数量 {record.affected_quantity == null ? "未知" : text(record.affected_quantity)}</p>
          <div className="space-y-2 rounded-md border p-3"><h6 className="font-medium">当前已批准根因</h6>{actual.current_approved_root ? <><p>版本 {text(obj(actual.current_approved_root).version)} · {text(obj(actual.current_approved_root).approved_at)}</p><p className="whitespace-pre-wrap">{text(obj(actual.current_approved_root).root_cause)}</p><details><summary className="cursor-pointer">原分析过程</summary><p className="whitespace-pre-wrap">{text(obj(actual.current_approved_root).analysis)}</p></details></> : <p>尚无当前有效的已批准根因。</p>}</div>
          <div className="space-y-2 rounded-md border p-3"><h6 className="font-medium">最近一次实际复核</h6>{actual.latest_review ? <><p>第 {text(obj(actual.latest_review).review_number)} 次 · {obj(actual.latest_review).result === "effective" ? "有效" : "无效"}</p><p className="whitespace-pre-wrap">原判据：{text(obj(actual.latest_review).criteria)}</p><p className="whitespace-pre-wrap">实际结果：{text(obj(actual.latest_review).actual_result)}</p><p>观察到期：{text(obj(actual.latest_review).observation_due_at)} · 复核时点：{text(obj(actual.latest_review).reviewed_at)}</p></> : <p>尚无实际复核，未推定整改有效。</p>}</div>
          <details className="space-y-2"><summary className="cursor-pointer">实际整改行动（{rows(obj(actual.quality_chain).actions).length}）</summary>{rows(obj(actual.quality_chain).actions).map(action => <div className="space-y-1 rounded-md border p-2" key={text(action.id)}><p>{action.action_type === "corrective" ? "纠正措施" : "预防措施"} · {({planned:"待开始",in_progress:"执行中",completed:"已完成",cancelled:"已取消"} as Record<string,string>)[text(action.status)] ?? text(action.status)}</p><p className="whitespace-pre-wrap">{text(action.description)}</p><p className="whitespace-pre-wrap">完成结果：{text(action.completion_summary) || "尚未登记"}</p></div>)}</details>
          <p className="text-muted-foreground">{text(actual.interpretation)}</p>
          <details onToggle={event => setShowNcr(event.currentTarget.open)}><summary className="cursor-pointer">打开原质量工作区，回查或继续办理</summary>{showNcr && <NcrWorkspace key={`${project}:${sourceId}`} projectId={project} ncrId={sourceId}/>}</details>
        </> : <><p className="whitespace-pre-wrap">原投诉：{text(record.description)}</p><p className="whitespace-pre-wrap">影响范围：{text(record.affected_scope) || "未登记"}</p><p className="whitespace-pre-wrap">处理结论：{text(record.resolution_summary) || "尚未形成结论"}</p></>}
        <p>实际依据 {rows(actual.evidence).length} 份</p>{Array.isArray(actual.warnings) && actual.warnings.map((warning, index) => <p key={index} className="text-primary">{String(warning)}</p>)}
        <a className="inline-flex min-h-11 items-center underline" href={`/projects/${project}`}>打开原项目办理</a>
        <details><summary className="cursor-pointer">核对完整结果、根因历史、条件、样机配置与定义原文</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(source, null, 2)}</pre></details>
      </section>
      {kind === "test_run" && <ProductMetricCalculations key={project + ":" + sourceId} base={base} definitionId={definitionId} projectId={project} testRunId={sourceId}/>}
      {data.can_respond === true && <form className="space-y-3 rounded-md border p-3" onSubmit={event => { event.preventDefault(); void act(save); }}><fieldset className="space-y-3" disabled={busy}>
        <h6 className="font-medium">产品经理具名回应</h6><p>选择本次实际核对的定义字段（最多 20 项）；未选字段保持未回应。</p>
        <div className="max-h-80 space-y-2 overflow-auto">{rows(source.fields).map(value => <label key={text(value.path)} className="block rounded-md border p-2"><span className="flex gap-2"><input type="checkbox" checked={paths.includes(text(value.path))} disabled={!paths.includes(text(value.path)) && paths.length >= 20} onChange={event => setPaths(old => event.target.checked ? [...old, text(value.path)] : old.filter(p => p !== value.path))}/><span className="break-all text-xs">{text(value.path)}</span></span><pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(value.value, null, 2)}</pre></label>)}</div>
        <label className="block">回应<select className={field} value={verdict} onChange={event => setVerdict(event.target.value)}>{Object.entries(verdicts).filter(([key]) => key !== "withdrawn" || Number(data.version) > 0).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label className="block">实际结果与原字段的差异<textarea className={field} required maxLength={2048} value={finding} onChange={event => setFinding(event.target.value)}/></label>
        <label className="block">适用关系与依据（样机、版本、市场或使用条件）<textarea className={field} required maxLength={2048} value={applicability} onChange={event => setApplicability(event.target.value)}/></label>
        <label className="block">调整、保留或补证安排<textarea className={field} required maxLength={2048} value={change} onChange={event => setChange(event.target.value)}/></label>
        <label className="block">样本、方法和结论限制<textarea className={field} required maxLength={2048} value={limits} onChange={event => setLimits(event.target.value)}/></label>
        <label className="flex items-start gap-2"><input key={`${text(source.digest)}:${text(data.version)}`} type="checkbox" required/>已核对实际来源及适用范围；采用意见不代表已经修订、发布或验证有效。</label>
        <Button disabled={!paths.length}>保存具名反馈</Button>
      </fieldset></form>}
      {rows(data.items).map(value => <article className="space-y-2 border-t pt-3" key={text(value.id)}><h6 className="font-medium">反馈 v{text(value.version)} · {verdicts[text(value.verdict)]} · {value.version === data.version ? "最新回应" : "历史回应"}</h6><p className="text-xs text-muted-foreground">记录人 {text(value.actor_name) || text(value.actor_user_id)} · {new Date(text(value.created_at)).toLocaleString()}</p><p className="whitespace-pre-wrap">{text(value.finding)}</p><p className="whitespace-pre-wrap">适用依据：{text(value.applicability_basis)}</p><p className="whitespace-pre-wrap">后续：{text(value.proposed_change)}</p><p className="whitespace-pre-wrap">限制：{text(value.limitations)}</p>{value.sources_current !== true && <p className="text-primary">原来源或定义已变化，历史判断需重新核对。</p>}<ProductResultFollowups base={base} feedbackId={text(value.id)}/><details><summary className="cursor-pointer">当时字段与原始依据</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({ fields: value.selected_fields, source: value.source_snapshot }, null, 2)}</pre></details></article>)}
      {data.next_before_version != null && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => read(Number(data.next_before_version)))}>更早反馈</Button>}
    </>}
  </details>;
}
