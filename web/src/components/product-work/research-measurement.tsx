"use client";

import { useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { ResearchWorkpacks } from "./research-workpacks";
import { stateLabels, type ProductCatalog, type Workspace } from "./product-work-api";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";

const roles: Record<string, string> = {
  product_manager: "产品经理", project_manager: "项目经理", industrial_design: "工业设计", mechanical: "结构工程",
  hardware: "硬件工程", firmware: "嵌入式工程", dqe: "设计质量工程", sqe: "供应商质量工程", ie: "工业工程",
  test_quality: "测试与品质", procurement: "采购与供应协调", manufacturing_receiver: "制造与下游接收",
  data_steward: "数据职责", quality_reviewer: "专业质量核对", erp_steward: "ERP 职责", security_steward: "安全职责",
};
const scenarios: Record<string, string> = { pm_research_definition: "立项前研究、专业协作、机会、策略与定义" };
const sourceStates: Record<string, string> = { ...stateLabels, draft: "草稿", in_review: "审阅中", published: "已发布", withdrawn: "已撤回", decided: "已决策", assessed: "已评估", concluded: "已形成结论" };
const subjectKinds: Record<string, string> = { research_task: "研究任务", scoped_work_item: "专业协作工作", opportunity: "机会版本", strategy: "策略版本", definition: "产品定义版本" };
const evidenceKinds: Record<string, string> = { real_business: "真实业务", controlled_replay: "受控历史回放", synthetic: "模拟样本" };
const modes: Record<string, string> = { baseline_without_ai: "未使用 AI 的基线", assisted: "辅助办理" };
const phases: Record<string, string> = { prepare: "准备", learn: "学习", input: "输入", review: "审核", correct: "纠错", clarify: "追问", execute: "业务办理", handoff: "交接", receive: "接收核对", passive_wait: "被动等待" };
const terminals: Record<string, string> = { completed: "已完成", failed: "失败", cancelled: "取消", incomplete: "尚未完成" };
const captureMethods: Record<string, string> = { participant_timer: "本人计时", participant_recollection: "本人回忆核对", authorized_event_reference: "已授权事件依据" };
const arrayText = (value: unknown): string[] => Array.isArray(value) ? value.map(text) : [];
const dateText = (value: unknown) => value ? new Date(text(value)).toLocaleString() : "未登记";
const nullable = (value: string) => value.trim() || null;
const countValue = (value: string) => value === "" ? null : Number(value);
function localDate(value: unknown) { if (!value) return ""; const d = new Date(text(value)); if (Number.isNaN(d.valueOf())) return ""; return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, -1); }
function utc(value: string) { const d = new Date(value); if (Number.isNaN(d.valueOf())) throw new Error("请填写有效的本地日期与时间"); return d.toISOString(); }
const seconds = (value: unknown) => value != null && value !== "" && Number.isFinite(Number(value)) ? `${text(value)} 秒` : "未知";
const missingLabels: Record<string, string> = { all_activity_confirmed: "全部本人活动未核对", review_confirmed: "审核投入未核对", correction_confirmed: "纠错投入未核对", open_activity_segments: "存在未结束活动段", unverified_activity_segments: "存在未经本人核对的活动段", invalid_activity_segments: "活动时间待核对", observation_interval: "观察起止时间待核对", active_passive_overlap: "主动活动与被动等待重叠" };
function Label({ title, children }: { title: string; children: ReactNode }) { return <label className="block space-y-1"><span>{title}</span>{children}</label>; }
function Choice({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) { return <label className="flex items-start gap-2"><input type="checkbox" className="mt-1" checked={checked} onChange={e => onChange(e.target.checked)}/><span>{label}</span></label>; }

interface Segment { segment_id: string; phase: string; start_at: string; end_at: string; capture_method: string; participant_verified: boolean; related_object_ref: string }
interface Observation {
  sample_id: string; expected_version: number; subject_kind: string; subject_id: string; source_locator: string;
  role_id: string; complexity_stratum: string; mode: string; pair_key: string; matching_basis: string; first_use: boolean;
  workflow_version: string; started_at: string; ended_at: string; as_of: string; terminal_state: string; segments: Segment[];
  review_confirmed: boolean; correction_confirmed: boolean; all_activity_confirmed: boolean;
  duplicate_entry_count: string; clarification_round_count: string; omission_rework_count: string; false_block_count: string;
  excluded_rule_id: string; exclusion_reason: string;
}
const emptyObservation = (): Observation => ({
  sample_id: "", expected_version: 0, subject_kind: "research_task", subject_id: "", source_locator: "", role_id: "", complexity_stratum: "",
  mode: "baseline_without_ai", pair_key: "", matching_basis: "", first_use: false, workflow_version: "", started_at: "", ended_at: "", as_of: "", terminal_state: "incomplete", segments: [],
  review_confirmed: false, correction_confirmed: false, all_activity_confirmed: false, duplicate_entry_count: "", clarification_round_count: "", omission_rework_count: "", false_block_count: "", excluded_rule_id: "", exclusion_reason: "",
});

function ActivitySummary({ value }: { value: Row }) {
  return <div className="space-y-2 rounded-md bg-muted/40 p-3">
    <p className="font-medium">本人活动投入 · {value.status === "observed" ? "已登记范围完整" : "尚有缺项"}</p>
    <div className="grid gap-2 sm:grid-cols-2"><p>完整主动投入：{seconds(value.active_seconds)}</p><p>已知主动投入：{seconds(value.known_active_seconds)}</p><p>已知被动等待：{seconds(value.known_passive_seconds)}</p><p>端到端周期：{seconds(value.end_to_end_seconds)}{value.right_censored ? "（未结束）" : ""}</p></div>
    <p className="text-muted-foreground">同一本人的重叠活动先合并；他人投入未纳入，不能视为零或据此声称整个流程节省。</p>
    {Object.keys(obj(value.phase_known_seconds)).length > 0 && <p>{Object.entries(obj(value.phase_known_seconds)).map(([key, v]) => `${phases[key] || key} ${seconds(v)}`).join("；")}</p>}
    {arrayText(value.missing_fields).length > 0 && <p className="text-primary">待补核：{arrayText(value.missing_fields).map(v => missingLabels[v] || v).join("、")}</p>}
  </div>;
}

export function ResearchMeasurement({ spaceId, workspace, catalog }: { spaceId: string; workspace: Workspace; catalog: ProductCatalog }) {
  const [scope, setScope] = useState("");
  const lines = catalog.nodes.filter(v => v.level === "line");
  return <section className="space-y-4"><header><h3 className="font-semibold">立项前个人投入观察</h3><p className="mt-2 text-sm text-muted-foreground">单独观察市场空间共同工作或一条实际产品线中的本人活动。已有业务对象无需挂接项目；个人时间差不代表全团队收益或效果验收。</p></header><label className="block max-w-lg text-sm">选择本次观察范围<select className={field} value={scope} onChange={e => setScope(e.target.value)}><option value="">请选择具体范围</option><option value="market_space">市场空间共同工作 · {workspace.space.title}</option>{lines.map(v => <option key={v.id} value={v.id}>产品线 · {v.name}</option>)}</select></label>{scope && <ResearchMeasurementScope key={scope} spaceId={spaceId} productLineId={scope === "market_space" ? null : scope} scopeLabel={scope === "market_space" ? workspace.space.title + " · 共同工作" : lines.find(v => v.id === scope)?.name || "所选产品线"}/>}</section>;
}

function ResearchMeasurementScope({ spaceId, productLineId, scopeLabel }: { spaceId: string; productLineId: string | null; scopeLabel: string }) {
  const [options, setOptions] = useState<Row | null>(null), [studies, setStudies] = useState<Row | null>(null), [study, setStudy] = useState<Row | null>(null);
  const [samples, setSamples] = useState<Row | null>(null), [selectedSample, setSelectedSample] = useState<Row | null>(null), [sampleHistory, setSampleHistory] = useState<Row | null>(null), [summary, setSummary] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [title, setTitle] = useState(""), [protocolVersion, setProtocolVersion] = useState(""), [windowStart, setWindowStart] = useState(""), [windowEnd, setWindowEnd] = useState("");
  const [timezone, setTimezone] = useState(""), [scenario, setScenario] = useState("pm_research_definition"), [roleIds, setRoleIds] = useState<string[]>([]), [strata, setStrata] = useState("");
  const [inclusionRule, setInclusionRule] = useState(""), [exclusionRules, setExclusionRules] = useState<{ rule_id: string; description: string }[]>([]), [matchingRule, setMatchingRule] = useState("");
  const [evidenceKind, setEvidenceKind] = useState("real_business"), [purpose, setPurpose] = useState(""), [consentReason, setConsentReason] = useState(""), [consentConfirmed, setConsentConfirmed] = useState(false);
  const [observation, setObservation] = useState<Observation>(emptyObservation), [editing, setEditing] = useState(false), [preview, setPreview] = useState<Row | null>(null), [saveReason, setSaveReason] = useState("");
  const ids = useRef(new Map<string, string>());
  const originalStartedAt = useRef<string | null>(null);
  const protocol = obj(study?.protocol ?? study), studyId = text(study?.id), ownConsent = obj(study?.my_consent);
  function requestId(body: unknown) { const key = JSON.stringify(body); let id = ids.current.get(key); if (!id) { id = crypto.randomUUID(); ids.current.set(key, id); } return id; }
  async function request(operation: string, body: unknown = {}): Promise<Row> {
    const response = await fetch(`/api/research-measurement/${spaceId}/${operation}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const value: unknown = await response.json();
    if (!response.ok) throw new Error(text(obj(obj(value).detail).message) || text(obj(value).message) || "测量操作未完成，请重新读取原记录");
    return obj(value);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "测量记录暂不可用"); } finally { setBusy(false); } }
  async function loadStudies(before?: string) {
    const value = await request("study-history", { product_line_id: productLineId, before_id: before ?? null });
    setStudies(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value);
    return value;
  }
  async function loadSamples(id: string, before?: string) {
    const value = await request("sample-history", { study_id: id, before_id: before ?? null });
    setSamples(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value);
  }
  async function selectStudy(value: Row) {
    setStudy(value); setSamples(null); setSelectedSample(null); setSampleHistory(null); setSummary(null); setEditing(false); setPreview(null); setConsentReason(""); setConsentConfirmed(false);
    await loadSamples(text(value.id));
  }
  function patchObservation(patch: Partial<Observation>) { setObservation(old => ({ ...old, ...patch })); setPreview(null); }
  function newSample() {
    void act(async () => { setOptions({ ...await request("options", { product_line_id: productLineId, subject_kind: "research_task" }), _subject_kind: "research_task" }); });
    originalStartedAt.current = null;
    setObservation({ ...emptyObservation(), sample_id: crypto.randomUUID(), role_id: arrayText(protocol.role_ids)[0] || "", complexity_stratum: arrayText(protocol.complexity_strata)[0] || "", as_of: localDate(new Date().toISOString()) });
    setEditing(true); setPreview(null); setSaveReason(""); setSelectedSample(null); setSampleHistory(null);
  }
  function prepareTeamObservation(value: Row) {
    if (busy || editing) { setError("请先保存或取消当前编辑，再切换本人观察。"); return; }
    if (value.existing_sample_id) {
      void act(async () => { const result = await request("sample-read", { sample_id: value.existing_sample_id }); setSelectedSample(obj(result.item)); setSampleHistory(result); setEditing(false); setPreview(null); setNotice(obj(obj(result.item).draft).participant_user_id === options?.participant_user_id ? "已打开本人原观察，可核对并准备修订。" : "已打开当前授权范围内的原观察，仅原记录人可以修订。"); });
      return;
    }
    if (ownConsent.status !== "consented") { setError("请先由本人同意当前协议的活动采集。"); return; }
    originalStartedAt.current = null;
    const subject = obj(value.subject);
    setOptions(old => old ? { ...old, _subject_kind: value.subject_kind, _query: "", items: [{ ...subject, id: value.subject_id, kind: value.subject_kind, title: subject.title || subject.question }], next_before_id: null } : old);
    setObservation({ ...emptyObservation(), sample_id: crypto.randomUUID(), subject_kind: text(value.subject_kind), subject_id: text(value.subject_id), mode: text(value.mode), role_id: text(value.role_id), first_use: value.first_use === true, complexity_stratum: text(value.complexity_stratum), workflow_version: text(value.workflow_version), pair_key: text(value.pair_key), matching_basis: text(value.matching_basis), as_of: localDate(new Date().toISOString()) });
    setEditing(true); setPreview(null); setSaveReason(""); setSelectedSample(null); setSampleHistory(null); setNotice("已按固定团队口径准备本人观察，请在上方填写实际办理位置、时间与活动，核对后再保存。");
  }
  function draft() {
    return {
      ...observation, study_id: studyId,
      pair_key: nullable(observation.pair_key), matching_basis: nullable(observation.matching_basis), started_at: originalStartedAt.current ?? utc(observation.started_at), ended_at: observation.ended_at ? utc(observation.ended_at) : null, as_of: utc(observation.as_of),
      segments: observation.segments.map(v => ({ ...v, start_at: utc(v.start_at), end_at: v.end_at ? utc(v.end_at) : null, related_object_ref: nullable(v.related_object_ref) })),
      duplicate_entry_count: countValue(observation.duplicate_entry_count), clarification_round_count: countValue(observation.clarification_round_count), omission_rework_count: countValue(observation.omission_rework_count), false_block_count: countValue(observation.false_block_count),
      excluded_rule_id: nullable(observation.excluded_rule_id), exclusion_reason: nullable(observation.exclusion_reason),
    };
  }
  function revise(value: Row) {
    const data = obj(value.draft);
    originalStartedAt.current = text(data.started_at);
    setObservation({ ...emptyObservation(), sample_id: text(value.sample_id || data.sample_id), expected_version: Number(value.version), subject_kind: text(data.subject_kind), subject_id: text(data.subject_id), source_locator: text(data.source_locator),
      role_id: text(data.role_id), complexity_stratum: text(data.complexity_stratum), mode: text(data.mode), pair_key: text(data.pair_key), matching_basis: text(data.matching_basis), first_use: data.first_use === true,
      workflow_version: text(data.workflow_version), started_at: localDate(data.started_at), ended_at: localDate(data.ended_at), as_of: localDate(new Date().toISOString()), terminal_state: text(data.terminal_state),
      segments: rows(data.segments).map(v => ({ segment_id: text(v.segment_id), phase: text(v.phase), start_at: localDate(v.start_at), end_at: localDate(v.end_at), capture_method: text(v.capture_method), participant_verified: v.participant_verified === true, related_object_ref: text(v.related_object_ref) })),
      review_confirmed: data.review_confirmed === true, correction_confirmed: data.correction_confirmed === true, all_activity_confirmed: data.all_activity_confirmed === true,
      duplicate_entry_count: text(data.duplicate_entry_count), clarification_round_count: text(data.clarification_round_count), omission_rework_count: text(data.omission_rework_count), false_block_count: text(data.false_block_count), excluded_rule_id: text(data.excluded_rule_id), exclusion_reason: text(data.exclusion_reason),
    });
    setPreview(null); setSaveReason(""); setEditing(true);
  }
  async function createStudy() {
    const body = { product_line_id: productLineId, title, protocol_version: protocolVersion, window_start: utc(windowStart), window_end: utc(windowEnd), timezone, scenario_id: scenario, role_ids: roleIds, complexity_strata: strata.split("\n").map(v => v.trim()).filter(Boolean), inclusion_rule: inclusionRule, exclusion_rules: exclusionRules, matching_rule: matchingRule, evidence_kind: evidenceKind, purpose };
    await request("study-create", { ...body, request_id: requestId(body) });
    await loadStudies(); setNotice("已登记不可变测量协议。请由参与者本人选择协议并同意后登记活动。");
  }
  async function consent(status: string) {
    const body = { study_id: studyId, expected_version: Number(ownConsent.version || 0), status, reason: consentReason, activity_and_aggregate_use_confirmed: status === "consented" && consentConfirmed };
    const updated = await request("consent", { ...body, request_id: requestId(body) }); setStudy(updated); setStudies(old => old ? { ...old, items: rows(old.items).map(v => v.id === updated.id ? updated : v) } : old); setConsentReason(""); setConsentConfirmed(false); setEditing(false); setPreview(null); setSummary(null);
    setNotice(status === "consented" ? "已记录本人同意；只能登记自己的活动。" : "已撤回本人参与。当前披露和汇总将按最新同意状态处理，原记录保留。");
  }
  async function saveSample() {
    if (!preview || ownConsent.status !== "consented") return;
    const body = { ...draft(), expected_digest: text(preview.digest), reason: saveReason };
    const value = await request("sample-save", { ...body, request_id: requestId(body) });
    setSelectedSample(value); setSampleHistory(null); setEditing(false); setPreview(null); setSummary(null); await loadSamples(studyId); setNotice("已保存本次观察版本；修订会保留原记录。");
  }
  const canRecord = ownConsent.status === "consented";
  return <details className="space-y-4 rounded-lg border p-4 text-sm">
    <summary className="cursor-pointer font-semibold">立项前个人投入 · 协议、本人记录与描述汇总</summary>
    <p className="text-muted-foreground">按事先登记的窗口与匹配规则记录实际研究与专业工作。基线、辅助、历史回放与模拟分开查看；失败、未完成和未知投入保留。本入口目前记录立项前实际对象与本人投入。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <Button type="button" variant="outline" disabled={busy} onClick={() => void act(async () => { setOptions({ ...await request("options", { product_line_id: productLineId, subject_kind: "research_task" }), _subject_kind: "research_task" }); await loadStudies(); if (!timezone) setTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone); })}>读取协议与实际研究对象</Button>
    {options && <>
      {options.can_manage === true && <details className="space-y-3 rounded-md border p-3"><summary className="cursor-pointer font-medium">登记新的测量协议</summary>
        <p className="text-muted-foreground">固定场景、专业职责、复杂度与连续纳入规则。真实业务窗口须在登记之后开始；历史资料另建回放协议。修改另建协议，这里不冻结收益阈值，也不作阶段验收。</p>
        <form className="space-y-3" onSubmit={e => { e.preventDefault(); void act(createStudy); }}><fieldset disabled={busy} className="space-y-3">
          <div className="grid gap-3 md:grid-cols-2"><Label title="协议名称"><input required maxLength={160} className={field} value={title} onChange={e => setTitle(e.target.value)}/></Label><Label title="协议版本编号（英文字母、数字或 . _ : -）"><input required maxLength={64} pattern="[a-zA-Z0-9_.:\-]+" className={field} value={protocolVersion} onChange={e => setProtocolVersion(e.target.value)}/></Label></div>
          <div className="grid gap-3 md:grid-cols-3"><Label title="窗口开始（本地时间，含）"><input type="datetime-local" step="0.001" required className={field} value={windowStart} onChange={e => setWindowStart(e.target.value)}/></Label><Label title="窗口结束（本地时间，不含）"><input type="datetime-local" step="0.001" required className={field} value={windowEnd} onChange={e => setWindowEnd(e.target.value)}/></Label><Label title="显示时区"><input required maxLength={64} className={field} value={timezone} onChange={e => setTimezone(e.target.value)} placeholder="例如 Asia/Shanghai"/></Label></div>
          <div className="grid gap-3 md:grid-cols-2"><Label title="业务场景"><select className={field} value={scenario} onChange={e => setScenario(e.target.value)}>{Object.entries(scenarios).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Label><Label title="证据用途"><select className={field} value={evidenceKind} onChange={e => setEvidenceKind(e.target.value)}>{Object.entries(evidenceKinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Label></div>
          <fieldset className="space-y-2 rounded-md border p-3"><legend className="px-1">纳入的实际专业职责</legend><div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{Object.entries(roles).map(([key, label]) => <Choice key={key} label={label} checked={roleIds.includes(key)} onChange={checked => setRoleIds(old => checked ? [...old, key] : old.filter(v => v !== key))}/>)}</div></fieldset>
          <Label title="预先划定的复杂度编号（每行一项，最多 20 项，使用英文字母、数字或 . _ : -）"><textarea required maxLength={2048} className={field} value={strata} onChange={e => setStrata(e.target.value)}/></Label>
          <Label title="连续纳入规则与总体范围"><textarea required maxLength={2048} className={field} value={inclusionRule} onChange={e => setInclusionRule(e.target.value)}/></Label>
          <fieldset className="space-y-2 rounded-md border p-3"><legend className="px-1">事先排除规则（没有则留空）</legend>{exclusionRules.map((v, i) => <div key={i} className="grid gap-2 sm:grid-cols-[1fr_3fr_auto]"><Label title="规则编号"><input required maxLength={64} pattern="[a-zA-Z0-9_.:\-]+" className={field} value={v.rule_id} onChange={e => setExclusionRules(old => old.map((r, n) => n === i ? { ...r, rule_id: e.target.value } : r))}/></Label><Label title="排除条件"><input required maxLength={2048} className={field} value={v.description} onChange={e => setExclusionRules(old => old.map((r, n) => n === i ? { ...r, description: e.target.value } : r))}/></Label><Button type="button" variant="ghost" className="self-end" onClick={() => setExclusionRules(old => old.filter((_, n) => n !== i))}>移除</Button></div>)}<Button type="button" size="sm" variant="outline" disabled={exclusionRules.length >= 20} onClick={() => setExclusionRules(old => [...old, { rule_id: "", description: "" }])}>增加排除规则</Button></fieldset>
          <Label title="基线与辅助任务匹配规则"><textarea required maxLength={2048} className={field} value={matchingRule} onChange={e => setMatchingRule(e.target.value)}/></Label>
          <Label title="活动采集与汇总使用目的"><textarea required maxLength={2048} className={field} value={purpose} onChange={e => setPurpose(e.target.value)}/></Label>
          <Button disabled={roleIds.length === 0}>登记固定协议</Button>
        </fieldset></form>
      </details>}
      <section className="space-y-3"><h4 className="font-medium">协议历史</h4>{rows(studies?.items).length === 0 && <p className="text-muted-foreground">当前没有已登记协议。</p>}{rows(studies?.items).map(v => { const p = obj(v.protocol ?? v); return <article key={text(v.id)} className="space-y-1 rounded-md border p-3"><p className="font-medium">{text(p.title)} · {text(p.protocol_version)}</p><p>{evidenceKinds[text(p.evidence_kind)]} · {scenarios[text(p.scenario_id)] || text(p.scenario_id)} · {dateText(p.window_start)} 至 {dateText(p.window_end)}（结束不含）</p><p>{text(p.purpose)}</p><Button type="button" size="sm" variant={v.id === studyId ? "default" : "outline"} disabled={busy} onClick={() => void act(() => selectStudy(v))}>查看协议与本人活动</Button></article>; })}{studies?.next_before_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { await loadStudies(text(studies.next_before_id)); })}>更多协议</Button>}</section>
    </>}
    {study && <section className="space-y-4 rounded-md border p-3">
      <p className="text-muted-foreground">当前固定范围：{scopeLabel}</p>
      <h4 className="font-semibold">{text(protocol.title)} · {text(protocol.protocol_version)}</h4>
      <p>{evidenceKinds[text(protocol.evidence_kind)]} · {dateText(protocol.window_start)} 至 {dateText(protocol.window_end)}（结束不含）</p>
      <dl className="space-y-2"><div><dt className="font-medium">连续纳入规则</dt><dd className="whitespace-pre-wrap">{text(protocol.inclusion_rule)}</dd></div><div><dt className="font-medium">匹配规则</dt><dd className="whitespace-pre-wrap">{text(protocol.matching_rule)}</dd></div><div><dt className="font-medium">使用目的</dt><dd className="whitespace-pre-wrap">{text(protocol.purpose)}</dd></div></dl>
      {rows(protocol.exclusion_rules).map(v => <p key={text(v.rule_id)}>排除规则 {text(v.rule_id)}：{text(v.description)}</p>)}
      <form className="space-y-3 rounded-md border p-3" onSubmit={e => { e.preventDefault(); void act(() => consent("consented")); }}><fieldset disabled={busy} className="space-y-3"><p className="font-medium">本人参与 · {canRecord ? "已同意" : ownConsent.status === "withdrawn" ? "已撤回" : "尚未同意"} · 版本 {text(ownConsent.version || 0)}</p><p className="text-muted-foreground">仅本人可登记自己的活动。参与同意与本次协议绑定，不代表其他员工同意；撤回后停止继续采集和向他人披露，本人历史仍可按原资料权限回查。</p><Label title="同意或撤回说明"><textarea required maxLength={2048} className={field} value={consentReason} onChange={e => setConsentReason(e.target.value)}/></Label>{!canRecord && <Choice label="本人已阅读本协议，同意按所列目的采集本人活动并用于协议范围内的描述汇总。" checked={consentConfirmed} onChange={setConsentConfirmed}/>}<div className="flex gap-2">{!canRecord && <Button disabled={!consentConfirmed}>记录本人同意</Button>}{canRecord && <Button type="button" variant="outline" disabled={!consentReason.trim()} onClick={() => void act(() => consent("withdrawn"))}>撤回本人参与</Button>}</div></fieldset></form>
      <div className="flex flex-wrap gap-2"><Button type="button" disabled={busy || !canRecord} onClick={newSample}>登记本人的研究活动</Button><Button type="button" variant="outline" disabled={busy} onClick={() => void act(async () => { setSummary(await request("summary", { study_id: studyId })); })}>读取当前描述汇总</Button><Button type="button" variant="outline" disabled={busy} onClick={() => void act(() => loadSamples(studyId))}>刷新可读记录</Button></div>
      {editing && <form className="space-y-4 rounded-md border p-3" onSubmit={e => { e.preventDefault(); void act(async () => { setPreview(await request("sample-preview", draft())); }); }}><fieldset disabled={busy} className="space-y-3">
        <h5 className="font-medium">{observation.expected_version ? `修订本人观察 · 原版本 ${observation.expected_version}` : "新登记本人观察"}</h5>
        <p className="text-muted-foreground">时间按当前浏览器本地时区输入，保存为 UTC。请保留失败、未完成和未知，空白次数按未知保存。修订原样本不会增加独立对象系列数。原对象、职责、分层与配对身份在修订中保留。</p>
        <div className="grid gap-3 md:grid-cols-2"><Label title="实际对象类别"><select required disabled={observation.expected_version > 0} className={field} value={observation.subject_kind} onChange={e => { const kind = e.target.value; patchObservation({ subject_kind: kind, subject_id: "" }); void act(async () => { setOptions({ ...await request("options", { product_line_id: productLineId, subject_kind: kind }), _subject_kind: kind }); }); }}>{Object.entries(subjectKinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Label><Label title="选择实际对象及版本"><select required disabled={observation.expected_version > 0} className={field} value={observation.subject_id} onChange={e => patchObservation({ subject_id: e.target.value })}><option value="">请选择实际记录</option>{(options?._subject_kind === observation.subject_kind ? rows(options.items) : []).map(v => <option key={text(v.id)} value={text(v.id)}>{text(v.title || v.label)}{v.revision_number != null ? ` · 修订 ${text(v.revision_number)}` : v.version != null ? ` · 记录 v${text(v.version)}` : ""}{v.state ? " · " + (sourceStates[text(v.state)] || text(v.state)) : ""}</option>)}{observation.subject_id && !(options?._subject_kind === observation.subject_kind ? rows(options.items) : []).some(v => v.id === observation.subject_id) && <option value={observation.subject_id}>原固定对象 · {sourceTitle(obj(selectedSample?.source))}</option>}</select></Label></div>
        <SourcePicker key={observation.subject_kind} options={options} busy={busy} load={(query, before) => act(async () => { const v = await request("options", { product_line_id: productLineId, subject_kind: observation.subject_kind, query, before_id: before ?? null }); setOptions(old => ({ ...v, _query: query, _subject_kind: observation.subject_kind, items: before ? [...rows(old?.items), ...rows(v.items)] : rows(v.items) })); })}/>
        <Label title="本次研究/办理范围、原文位置与版本依据"><textarea required maxLength={2048} className={field} value={observation.source_locator} onChange={e => patchObservation({ source_locator: e.target.value })}/></Label>
        <div className="grid gap-3 md:grid-cols-3"><Label title="本次实际专业职责"><select required disabled={observation.expected_version > 0} className={field} value={observation.role_id} onChange={e => patchObservation({ role_id: e.target.value })}>{arrayText(protocol.role_ids).map(v => <option key={v} value={v}>{roles[v] || v}</option>)}</select></Label><Label title="预登记复杂度层"><select required disabled={observation.expected_version > 0} className={field} value={observation.complexity_stratum} onChange={e => patchObservation({ complexity_stratum: e.target.value })}>{arrayText(protocol.complexity_strata).map(v => <option key={v} value={v}>{v}</option>)}</select></Label><Label title="办理方式"><select disabled={observation.expected_version > 0} className={field} value={observation.mode} onChange={e => patchObservation({ mode: e.target.value })}>{Object.entries(modes).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Label></div>
        <fieldset disabled={observation.expected_version > 0}><Choice label="本人首次使用这一流程（学习投入仍计入本人主动时间）" checked={observation.first_use} onChange={v => patchObservation({ first_use: v })}/></fieldset>
        <Label title="实际流程版本编号（英文字母、数字或 . _ : -）"><input required maxLength={128} disabled={observation.expected_version > 0} pattern="[a-zA-Z0-9_.:\-]+" className={field} value={observation.workflow_version} onChange={e => patchObservation({ workflow_version: e.target.value })}/></Label>
        <div className="grid gap-3 md:grid-cols-2"><Label title="匹配任务对编号（英文字母、数字或 . _ : -；未配对留空）"><input maxLength={128} disabled={observation.expected_version > 0} pattern="[a-zA-Z0-9_.:\-]+" className={field} value={observation.pair_key} onChange={e => patchObservation({ pair_key: e.target.value })}/></Label><Label title="目标、复杂度、资料和验收口径匹配依据"><textarea maxLength={2048} disabled={observation.expected_version > 0} required={!!observation.pair_key} className={field} value={observation.matching_basis} onChange={e => patchObservation({ matching_basis: e.target.value })}/></Label></div>
        <p className="text-muted-foreground">同一参与者在同一分层下使用同一对编号。真实业务须采用匹配的不同任务，不能为试验重复提交业务。</p>
        <div className="grid gap-3 md:grid-cols-3"><Label title="任务开始时间"><input type="datetime-local" step="0.001" required disabled={observation.expected_version > 0} className={field} value={observation.started_at} onChange={e => patchObservation({ started_at: e.target.value })}/></Label><Label title="终止时间（未结束留空）"><input type="datetime-local" step="0.001" className={field} value={observation.ended_at} onChange={e => patchObservation({ ended_at: e.target.value })}/></Label><Label title="本次观察截至时间"><input type="datetime-local" step="0.001" required className={field} value={observation.as_of} onChange={e => patchObservation({ as_of: e.target.value })}/></Label></div>
        <Label title="本次任务结果"><select className={field} value={observation.terminal_state} onChange={e => patchObservation({ terminal_state: e.target.value })}>{Object.entries(terminals).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Label>
        <fieldset className="space-y-3 rounded-md border p-3"><legend className="px-1 font-medium">本人的活动段</legend>
          <p className="text-muted-foreground">审核、纠错、学习、交接和接收核对均应计入。等待与主动活动分开，事件之间的间隔不能直接当主动投入。</p>
          {observation.segments.map((v, i) => { function update(patch: Partial<Segment>) { patchObservation({ segments: observation.segments.map((s, n) => n === i ? { ...s, ...patch } : s) }); } return <article key={v.segment_id} className="space-y-2 rounded-md border p-3"><div className="grid gap-2 md:grid-cols-3"><Label title={`第 ${i + 1} 段活动`}><select className={field} value={v.phase} onChange={e => update({ phase: e.target.value })}>{Object.entries(phases).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Label><Label title="开始时间"><input type="datetime-local" step="0.001" required className={field} value={v.start_at} onChange={e => update({ start_at: e.target.value })}/></Label><Label title="结束时间（未结束留空）"><input type="datetime-local" step="0.001" className={field} value={v.end_at} onChange={e => update({ end_at: e.target.value })}/></Label></div><div className="grid gap-2 md:grid-cols-2"><Label title="记录方式"><select className={field} value={v.capture_method} onChange={e => update({ capture_method: e.target.value })}>{Object.entries(captureMethods).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Label><Label title="关联任务、轮次或资料位置"><input maxLength={2048} className={field} value={v.related_object_ref} onChange={e => update({ related_object_ref: e.target.value })}/></Label></div><Choice label="本人已核对这段活动及其起止时间" checked={v.participant_verified} onChange={checked => update({ participant_verified: checked })}/><Button type="button" size="sm" variant="ghost" onClick={() => patchObservation({ segments: observation.segments.filter((_, n) => n !== i) })}>移除此活动段</Button></article>; })}
          <Button type="button" size="sm" variant="outline" disabled={observation.segments.length >= 100} onClick={() => patchObservation({ segments: [...observation.segments, { segment_id: crypto.randomUUID(), phase: "execute", start_at: "", end_at: "", capture_method: "participant_timer", participant_verified: false, related_object_ref: "" }] })}>增加本人活动段</Button>
        </fieldset>
        <fieldset className="space-y-2 rounded-md border p-3"><legend className="px-1 font-medium">完整性核对</legend><Choice label="本人已经核对审核活动；已发生的投入均已登记，确无投入时才确认零。" checked={observation.review_confirmed} onChange={v => patchObservation({ review_confirmed: v })}/><Choice label="本人已经核对纠错活动；已发生的投入均已登记，确无投入时才确认零。" checked={observation.correction_confirmed} onChange={v => patchObservation({ correction_confirmed: v })}/><Choice label="截至本次观察时点，本人在此任务中的全部活动均已登记，包含学习与其他必要投入。" checked={observation.all_activity_confirmed} onChange={v => patchObservation({ all_activity_confirmed: v })}/><p className="text-muted-foreground">未确认保留为缺失，仍可保存观察。上述确认只涵盖本人，不代其他参与者确认。</p></fieldset>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{([ ["duplicate_entry_count", "重复录入次数"], ["clarification_round_count", "独立追问轮数"], ["omission_rework_count", "遗漏返工次数"], ["false_block_count", "错误阻塞次数"] ] as const).map(([key, label]) => <Label key={key} title={`${label}（未知留空）`}><input type="number" min={0} step={1} className={field} value={observation[key]} onChange={e => patchObservation({ [key]: e.target.value })}/></Label>)}</div>
        <div className="grid gap-3 md:grid-cols-2"><Label title="是否按事先规则排除"><select className={field} value={observation.excluded_rule_id} onChange={e => patchObservation({ excluded_rule_id: e.target.value, exclusion_reason: e.target.value ? observation.exclusion_reason : "" })}><option value="">纳入，含失败或不完整记录</option>{rows(protocol.exclusion_rules).map(v => <option key={text(v.rule_id)} value={text(v.rule_id)}>{text(v.rule_id)} · {text(v.description)}</option>)}</select></Label>{observation.excluded_rule_id && <Label title="本条符合排除规则的具体理由"><textarea required maxLength={2048} className={field} value={observation.exclusion_reason} onChange={e => patchObservation({ exclusion_reason: e.target.value })}/></Label>}</div>
        <div className="flex gap-2"><Button>预览本次观察与来源</Button><Button type="button" variant="ghost" onClick={() => { setEditing(false); setPreview(null); }}>取消编辑</Button></div>
      </fieldset>
      {preview && <section className="space-y-3 rounded-md border border-primary/30 p-3"><h5 className="font-medium">待保存观察 · 原来源核对</h5><SourceValue spaceId={spaceId} source={obj(preview.source)}/>{observation.expected_version > 0 && preview.initial_source != null && <details className="space-y-2"><summary className="cursor-pointer">对照首次登记的原来源</summary><SourceValue spaceId={spaceId} source={obj(preview.initial_source)}/></details>}<ActivitySummary value={obj(preview.summary)}/><p>办理方式：{modes[observation.mode]} · 结果：{terminals[observation.terminal_state]} · {observation.excluded_rule_id ? `按规则 ${observation.excluded_rule_id} 排除` : "纳入连续样本"}</p><Label title="登记或修订依据"><textarea required maxLength={2048} className={field} value={saveReason} onChange={e => setSaveReason(e.target.value)}/></Label><Button type="button" disabled={busy || !saveReason.trim()} onClick={() => void act(saveSample)}>确认保存观察版本</Button></section>}
      </form>}
      <section className="space-y-3"><h5 className="font-medium">{options?.can_manage ? "当前可读取的观察记录" : "本人观察记录"}</h5>{rows(samples?.items).length === 0 && <p className="text-muted-foreground">当前没有可读取的观察记录。</p>}{rows(samples?.items).map(v => { const d = obj(v.draft), source = obj(v.source); return <article key={text(v.id)} className="space-y-1 rounded-md border p-3"><p className="font-medium">{sourceTitle(source)} · 观察版本 {text(v.version)} · {d.participant_user_id === options?.participant_user_id ? "本人" : "其他已同意参与者"}</p><p>{modes[text(d.mode)]} · {roles[text(d.role_id)] || text(d.role_id)} · {text(d.complexity_stratum)} · {terminals[text(d.terminal_state)]}</p><p>观察至 {dateText(d.as_of)} · 保存 {dateText(v.created_at)}{d.excluded_rule_id ? " · 已按预登记规则排除" : ""}</p>{v.source_changed === true && <p className="text-primary">当前来源已变化；保留当时观察与原始依据，未用当前任务进展改写历史投入。</p>}<Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { const result = await request("sample-read", { sample_id: v.sample_id }); setSelectedSample(obj(result.item)); setSampleHistory(result); setEditing(false); setPreview(null); })}>查看原记录与版本历史</Button></article>; })}{samples?.next_before_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => loadSamples(studyId, text(samples.next_before_id)))}>更多观察记录</Button>}</section>
      {selectedSample && <section className="space-y-3 rounded-md border p-3"><h5 className="font-medium">观察版本 {text(selectedSample.version)} · {obj(selectedSample.draft).participant_user_id === options?.participant_user_id ? "本人原记录" : "已同意参与者原记录"}</h5><SourceValue spaceId={spaceId} source={obj(selectedSample.source)}/>{Number(selectedSample.version) > 1 && selectedSample.initial_source != null && <details className="space-y-2"><summary className="cursor-pointer">首次登记来源保持不变</summary><SourceValue spaceId={spaceId} source={obj(selectedSample.initial_source)}/></details>}<ObservationValue value={obj(selectedSample.draft)}/><ActivitySummary value={obj(selectedSample.summary)}/><p>登记依据：{text(selectedSample.reason)}</p>{selectedSample.source_changed === true && <details className="space-y-2"><summary className="cursor-pointer text-primary">当前原对象内容或版本已变化，展开对照当前来源</summary><p className="text-muted-foreground">原观察和当时资料保持不变。</p><SourceValue spaceId={spaceId} source={obj(selectedSample.current_source)}/></details>}<Button type="button" size="sm" variant="outline" disabled={busy || !canRecord || obj(selectedSample.draft).participant_user_id !== options?.participant_user_id || (sampleHistory != null && selectedSample.version !== obj(sampleHistory.item).version)} onClick={() => revise(selectedSample)}>以此记录准备修订</Button>{rows(sampleHistory?.history).length > 0 && <details className="space-y-2"><summary className="cursor-pointer">历次版本（选择查看）</summary>{rows(sampleHistory?.history).map(v => <Button key={text(v.id)} type="button" size="sm" variant="outline" disabled={busy} onClick={() => { setSelectedSample(v); setEditing(false); setPreview(null); }}>版本 {text(v.version)} · {dateText(v.created_at)}</Button>)}{sampleHistory?.next_before_version != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { const result = await request("sample-read", { sample_id: selectedSample.sample_id, before_version: sampleHistory.next_before_version }); setSampleHistory(old => ({ ...result, history: [...rows(old?.history), ...rows(result.history)] })); })}>更早版本</Button>}</details>}</section>}
      {summary && <StudySummary value={summary}/> }
      <ResearchWorkpacks key={studyId} spaceId={spaceId} study={study} currentUserId={text(options?.participant_user_id)} canManage={options?.can_manage === true} canPrepareObservation={!busy && !editing} onPrepareObservation={prepareTeamObservation}/>
    </section>}
  </details>;
}

function SourcePicker({ options, busy, load }: { options: Row | null; busy: boolean; load: (query: string, before?: string) => Promise<void> }) {
  const [query, setQuery] = useState(text(options?._query));
  return <div className="space-y-2 rounded-md bg-muted/30 p-2"><div className="flex flex-wrap items-end gap-2"><Label title="查找当前类别中的实际对象"><input maxLength={128} className={field} value={query} onChange={e => setQuery(e.target.value)}/></Label><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(query)}>查找</Button></div>{options?.next_before_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(text(options._query), text(options.next_before_id))}>更多实际对象</Button>}</div>;
}
function sourceTitle(source: Row) { return text(obj(source.original).title || obj(source.original).question || source.title || source.label) || "原实际对象"; }
function sourceHref(spaceId: string, kind: string, value: Row) {
  const paths: Record<string, [string, string]> = { research_task: ["", "research"], scoped_work_item: ["", "work"], opportunity: ["opportunities", "opportunity"], strategy: ["strategies", "strategy"], definition: ["definitions", "definition"] };
  const path = paths[kind]; if (!path || !value.id) return null;
  return `/product-work?space=${spaceId}${path[0] ? "&tab=" + path[0] : ""}${value.product_line_id ? "&line=" + encodeURIComponent(text(value.product_line_id)) : ""}#${path[1]}-${encodeURIComponent(text(value.id))}`;
}
function SourceValue({ spaceId, source }: { spaceId: string; source: Row }) {
  const original = obj(source.original), current = obj(source.current), kind = text(source.kind);
  function record(value: Row, label: string) { const href = sourceHref(spaceId, kind, value); return <div className="space-y-2 rounded-md border p-3"><p className="font-medium">{label} · {subjectKinds[kind] || "实际对象"}</p><p>{text(value.title || value.question) || "原记录"} · {value.revision_number != null ? `修订 ${text(value.revision_number)} · ` : ""}记录版本 {text(value.version) || "未提供"} · {sourceStates[text(value.state)] || text(value.state) || "状态未提供"}</p>{([ ["question", "研究问题"], ["expected_output", "预期输出"], ["completion_criteria", "完成判据"], ["expected_decision", "支持的决定"], ["method", "研究方法"], ["time_scope", "资料时段"] ] as const).map(([key, name]) => value[key] != null ? <p key={key} className="whitespace-pre-wrap">{name}：{text(value[key])}</p> : null)}{href && <a className="text-primary underline" href={href}>在原工作区核对完整记录</a>}<p className="text-muted-foreground">更新于 {dateText(value.updated_at || value.created_at)}</p></div>; }
  return <div className="space-y-2">{record(original, "固定选中的原对象")}{source.source_changed === true && record(current, "本次读取时的同系列当前对象")}<p className="text-muted-foreground">{text(source.scope_note) || "这里只固定实际对象身份与工作要求；完整资料沿原对象权限读取。"}</p></div>;
}
function ObservationValue({ value }: { value: Row }) {
  return <div className="space-y-2"><p>{modes[text(value.mode)]} · {roles[text(value.role_id)] || text(value.role_id)} · {text(value.complexity_stratum)} · {value.first_use ? "首次使用" : "后续使用"}</p><p>流程版本：{text(value.workflow_version)} · {terminals[text(value.terminal_state)]}</p><p>开始 {dateText(value.started_at)} · 终止 {value.ended_at ? dateText(value.ended_at) : "未结束"} · 截至 {dateText(value.as_of)}</p><p>匹配任务对：{text(value.pair_key) || "未配对"} · {text(value.matching_basis) || "未登记匹配依据"}</p>{value.source_locator != null && <p>研究/办理范围与位置：{text(value.source_locator)}</p>}<p>重复录入 {value.duplicate_entry_count == null ? "未知" : text(value.duplicate_entry_count)} 次 · 追问 {value.clarification_round_count == null ? "未知" : text(value.clarification_round_count)} 轮 · 遗漏返工 {value.omission_rework_count == null ? "未知" : text(value.omission_rework_count)} 次 · 错误阻塞 {value.false_block_count == null ? "未知" : text(value.false_block_count)} 次</p><div className="space-y-1">{rows(value.segments).map(v => <p key={text(v.segment_id)}>{phases[text(v.phase)]}：{dateText(v.start_at)} 至 {v.end_at ? dateText(v.end_at) : "未结束"} · {captureMethods[text(v.capture_method)]} · {v.participant_verified ? "本人已核对" : "尚未核对"}{v.related_object_ref ? " · " + text(v.related_object_ref) : ""}</p>)}</div>{value.excluded_rule_id != null && <p className="text-primary">排除规则 {text(value.excluded_rule_id)}：{text(value.exclusion_reason)}</p>}</div>;
}
function StudySummary({ value }: { value: Row }) {
  const result = obj(value.summary);
  return <section className="space-y-3 rounded-md border p-3"><h5 className="font-medium">当前描述汇总 · {value.scope === "all_consenting" ? "当前可读且同意的参与者" : "本人范围"}</h5><p className="text-muted-foreground">读取于 {dateText(value.as_of)}。这里只描述已登记且可读取的本人活动，尚未评估完整流程收益、真实下游首次接收率或阈值达标。</p><div className="grid gap-2 sm:grid-cols-3"><p>观察 {text(result.sample_count)} 条</p><p>实际对象系列 {text(result.subject_series_count)} 项</p><p>参与者 {text(result.participant_count)} 人</p><p>缺活动字段 {text(result.missing_activity_count)} 条</p><p>完整配对 {text(result.complete_pair_count)} 对</p><p>不完整配对 {text(result.incomplete_pair_count)} 对</p><p>未登记配对 {text(result.without_pair_key_count)} 条</p><p>按预登记规则排除 {text(value.excluded_count)} 条</p><p>来源或权限不可用 {text(value.unavailable_count)} 条</p><p>当前来源有变化 {text(value.source_changed_count)} 条（仍保留历史观察）</p></div>
    {rows(result.strata).map((v, i) => <article key={i} className="space-y-2 rounded-md border p-3"><p className="font-medium">{evidenceKinds[text(v.evidence_kind)]} · {modes[text(v.mode)]} · {subjectKinds[text(v.subject_kind)] || ""} · {roles[text(v.role_id)] || text(v.role_id)} · {text(v.complexity_stratum)}</p><p>{v.first_use ? "首次使用" : "后续使用"} · 流程 {text(v.workflow_version)} · {text(v.sample_count)} 条 / {text(v.subject_series_count)} 项对象系列 / {text(v.participant_count)} 人</p><p>已知本人主动投入合计 {seconds(v.known_active_seconds)} · 完整记录 {text(v.complete_activity_count)} 条 · 缺失 {text(v.missing_activity_count)} 条 · 未结束 {text(v.right_censored_count)} 条</p><p>完整记录平均投入 {seconds(v.mean_complete_active_seconds)} · 跨样本重叠扣除 {seconds(v.cross_sample_overlap_seconds)}</p><p>{Object.entries(obj(v.outcomes)).map(([key, amount]) => `${terminals[key] || key} ${text(amount)} 条`).join("；")}</p>{Object.entries(obj(v.counts)).map(([key, count]) => <p key={key}>{({ duplicate_entry_count: "重复录入", clarification_round_count: "独立追问", omission_rework_count: "遗漏返工", false_block_count: "错误阻塞" } as Record<string, string>)[key] || key}：已知合计 {text(obj(count).known_sum)}，有记录 {text(obj(count).observed_count)} 条，未知 {text(obj(count).missing_count)} 条</p>)}</article>)}
    {rows(result.pairs).length > 0 && <details className="space-y-2"><summary className="cursor-pointer font-medium">逐对比较本人投入</summary>{rows(result.pairs).map((v, i) => <article key={i} className="space-y-1 rounded-md border p-3"><p className="font-medium">{text(v.pair_key)} · {evidenceKinds[text(v.evidence_kind)]} · {subjectKinds[text(v.subject_kind)] || ""} · {roles[text(v.role_id)] || text(v.role_id)} · {text(v.complexity_stratum)}</p><p className="break-all text-xs">参与者记录编号：{text(v.participant_user_id)}</p><p>基线 {seconds(v.baseline_active_seconds)} · 辅助 {seconds(v.assisted_active_seconds)}</p><p>基线减辅助：{seconds(v.active_seconds_difference)} · 比例 {v.difference_percent == null ? v.difference_percent_status === "not_applicable" ? "不适用（基线为零）" : "未知" : text(v.difference_percent) + "%"}</p>{arrayText(v.reasons).map(reason => <p key={reason} className="text-primary">{reason}</p>)}<p className="text-muted-foreground">正值代表本对记录的本人投入减少，负值表示增加；不推定因果收益或验收通过。</p></article>)}</details>}
  </section>;
}
