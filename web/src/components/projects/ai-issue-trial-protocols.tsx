"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { AiIssueTrialCollections } from "./ai-issue-trial-collections";
import { AiIssueTrialCurrent } from "./ai-issue-trial-current";

const inputClass = "mt-1 min-h-10 w-full min-w-0 rounded-lg border bg-background px-3 py-2 text-sm disabled:opacity-50";
const evidenceLabels: Record<string, string> = { real_business: "真实业务", controlled_replay: "受控重放", synthetic: "模拟场景" };
const confirmationLabels: Record<string, string> = { ever_confirmed: "曾确认采用", retained_original: "确认后保持原稿，未修改或撤回" };
const blockerLabels: Record<string, string> = { policy_missing: "尚未登记写入政策", write_policy_missing: "尚未登记写入政策", policy_not_tiered: "当前未采用分级写入政策", operation_not_enabled: "当前政策尚未启用此操作", scope_not_enabled: "当前项目授权尚未就绪", no_candidates: "尚无可登记的独立问题评测版本", no_trusted_evaluations: "尚无受信的独立问题评测发布记录", evaluation_missing: "尚无可用于登记的独立问题评测", evaluation_expired: "评测已到期，请核对新的有效版本", model_version_unknown: "评测模型版本尚未核实", publication_not_configured: "尚未配置受信独立评测发布记录" };
type Candidate = { key: string; label: string; binding: Record<string, unknown>; evaluation_id: string; published_at: string; expires_at: string };
type Preparation = { can_register: boolean; policy_revision: number; candidates: Candidate[]; blockers: string[] };
type Configuration = { minimum_handled_runs: number; minimum_followup_seconds: number; sampling_basis_points: number; confirmation_basis: string; recovery_protocol_version: string; recovery_conditions: string; minimum_confirmation_basis_points: number; maximum_retraction_basis_points: number };
type Protocol = { id: string; created_at: string; actor_name: string; window_start: string; window_end: string; evidence_kind: string; binding_label: string; configuration: Configuration; reason: string; notice: string };
type History = { items: Protocol[]; next_before_id: string | null };
type Form = { candidate: string; evidence: string; start: string; end: string; minimum: string; followup: string; sampling: string; confirmation: string; recoveryVersion: string; recoveryConditions: string; reason: string };
function emptyForm(): Form { return { candidate: "", evidence: "real_business", start: "", end: "", minimum: "", followup: "", sampling: "", confirmation: "", recoveryVersion: "", recoveryConditions: "", reason: "" }; }
function record(value: unknown): Record<string, unknown> { if (!isRecord(value)) throw new Error("试运行登记资料不完整，请刷新核对"); return value; }
function text(value: unknown): string { if (typeof value !== "string") throw new Error("试运行登记资料不完整，请刷新核对"); return value; }
function stamp(value: unknown): string { const result = text(value); if (!Number.isFinite(Date.parse(result))) throw new Error("试运行登记时间不完整，请刷新核对"); return result; }
function integer(value: unknown, minimum = 0): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) throw new Error("试运行配置数值不完整，请刷新核对"); return value; }
function preparation(value: unknown): Preparation {
  const row = record(value);
  if (typeof row.can_register !== "boolean" || !Array.isArray(row.candidates) || !Array.isArray(row.blockers)) throw new Error("试运行准备资料不完整，请刷新核对");
  return { can_register: row.can_register, policy_revision: integer(row.policy_revision), blockers: row.blockers.map(text), candidates: row.candidates.map(value => { const item = record(value); return { key: text(item.key), label: text(item.label), binding: record(item.binding), evaluation_id: text(item.evaluation_id), published_at: stamp(item.published_at), expires_at: stamp(item.expires_at) }; }) };
}
function protocol(value: unknown): Protocol {
  const row = record(value), config = record(row.configuration);
  const evidence = text(row.evidence_kind), confirmation = text(config.confirmation_basis);
  if (!evidenceLabels[evidence] || !confirmationLabels[confirmation]) throw new Error("试运行场景或确认口径不完整");
  const basisPoints = (value: unknown) => { const result = integer(value); if (result > 10000) throw new Error("试运行比例不完整"); return result; };
  return { id: text(row.id), created_at: stamp(row.created_at), actor_name: text(row.actor_name), window_start: stamp(row.window_start), window_end: stamp(row.window_end), evidence_kind: evidence, binding_label: typeof row.binding_label === "string" && row.binding_label.trim() ? row.binding_label : "原登记评测版本（已固定）", configuration: { minimum_handled_runs: integer(config.minimum_handled_runs, 1), minimum_followup_seconds: integer(config.minimum_followup_seconds, 1), sampling_basis_points: basisPoints(config.sampling_basis_points), confirmation_basis: confirmation, recovery_protocol_version: text(config.recovery_protocol_version), recovery_conditions: text(config.recovery_conditions), minimum_confirmation_basis_points: basisPoints(config.minimum_confirmation_basis_points), maximum_retraction_basis_points: basisPoints(config.maximum_retraction_basis_points) }, reason: text(row.reason), notice: text(row.notice) };
}
function history(value: unknown): History { const row = record(value); if (!Array.isArray(row.items)) throw new Error("试运行登记历史不完整"); return { items: row.items.map(protocol), next_before_id: row.next_before_id === null ? null : text(row.next_before_id) }; }
function positive(value: string, label: string): number { if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)) || Number(value) < 1) throw new Error(`请填写${label}的正整数`); return Number(value); }
function localDate(value: string): Date {
  const fields = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value), date = new Date(value);
  if (!fields || !Number.isFinite(date.getTime())) throw new Error("请填写完整的本地开始与结束时间");
  const actual = [date.getFullYear(), date.getMonth() + 1, date.getDate(), date.getHours(), date.getMinutes(), date.getSeconds()];
  if (fields.slice(1).some((value, index) => Number(value ?? 0) !== actual[index])) throw new Error("所填时间在当前时区不存在，请核对日期或夏令时");
  return date;
}
function commandFor(form: Form, prepared: Preparation) {
  const candidate = prepared.candidates.find(item => item.key === form.candidate);
  if (!prepared.can_register || !candidate) throw new Error("请选择当前可登记的独立问题评测版本");
  if (Date.parse(candidate.expires_at) <= Date.now()) throw new Error("所选评测已到期，请刷新登记资料");
  const start = localDate(form.start), end = localDate(form.end);
  if (end <= start || end.getTime() - start.getTime() > 366 * 86400000) throw new Error("结束时间须晚于开始时间，窗口不能超过 366 天");
  if (form.evidence === "real_business" && start.getTime() <= Date.now()) throw new Error("真实业务须提前登记，请选择未来的开始时间");
  if (!evidenceLabels[form.evidence] || !confirmationLabels[form.confirmation]) throw new Error("请选择观察场景与确认口径");
  if (!/^\d+(?:\.\d{1,2})?$/.test(form.sampling)) throw new Error("请填写抽检百分比，最多两位小数");
  const sampling = Math.round(Number(form.sampling) * 100);
  if (sampling < 1 || sampling > 10000) throw new Error("抽检比例须在 0.01% 至 100% 之间");
  if (!/^[a-zA-Z0-9_.:-]{1,128}$/.test(form.recoveryVersion.trim())) throw new Error("恢复政策版本名称请使用字母、数字、点或短横线");
  if (!form.recoveryVersion.trim() || !form.recoveryConditions.trim() || !form.reason.trim()) throw new Error("请填写恢复政策版本、恢复条件与登记说明");
  return { request_id: crypto.randomUUID(), preparation_digest: candidate.key, binding: candidate.binding, window_start: start.toISOString(), window_end: end.toISOString(), evidence_kind: form.evidence, configuration: { minimum_handled_runs: positive(form.minimum, "最小办理数"), minimum_followup_seconds: positive(form.followup, "最短跟踪时长"), sampling_basis_points: sampling, confirmation_basis: form.confirmation, recovery_protocol_version: form.recoveryVersion.trim(), recovery_conditions: form.recoveryConditions.trim() }, reason: form.reason.trim() };
}
type Command = ReturnType<typeof commandFor>;
class RequestFailure extends Error { constructor(message: string, readonly status: number, readonly code: string | null) { super(message); } }
async function request(path: string, body?: Command): Promise<unknown> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new RequestFailure(isRecord(value) && typeof value.detail === "string" ? value.detail : isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "试运行登记暂不可用，请重新核对", response.status, isRecord(value) && isRecord(value.detail) && typeof value.detail.code === "string" ? value.detail.code : null);
  return value;
}
function time(value: string) { return new Date(value).toLocaleString("zh-CN"); }
function reasonLabel(code: string) { return blockerLabels[code] ?? (/[\u3400-\u9fff]/.test(code) ? code : "当前政策或独立问题评测尚未就绪，请核对后刷新。"); }

function ProtocolDetail({ value }: { value: Protocol }) {
  const config = value.configuration;
  return <section aria-label="原试运行登记" className="space-y-3 border-t pt-3"><p className="font-medium">{value.actor_name} · {time(value.created_at)}</p><p>{value.binding_label} · {evidenceLabels[value.evidence_kind]}</p><p className="text-muted-foreground">原窗口：{time(value.window_start)} 至 {time(value.window_end)}</p><p className="leading-5 text-muted-foreground">{value.notice}</p>{value.evidence_kind !== "real_business" && <p className="text-primary">此登记属于模拟或受控重放，不能取得真实业务资格。</p>}<dl className="grid gap-3 sm:grid-cols-2"><div><dt className="text-muted-foreground">最小办理数</dt><dd>{config.minimum_handled_runs} 个原请求</dd></div><div><dt className="text-muted-foreground">最短跟踪时长</dt><dd>{config.minimum_followup_seconds} 秒</dd></div><div><dt className="text-muted-foreground">抽检比例</dt><dd>{config.sampling_basis_points / 100}%</dd></div><div><dt className="text-muted-foreground">确认口径</dt><dd>{confirmationLabels[config.confirmation_basis]}</dd></div><div><dt className="text-muted-foreground">原政策确认率门槛</dt><dd>不低于 {config.minimum_confirmation_basis_points / 100}%</dd></div><div><dt className="text-muted-foreground">原政策撤回率门槛</dt><dd>不高于 {config.maximum_retraction_basis_points / 100}%</dd></div><div><dt className="text-muted-foreground">恢复政策版本</dt><dd className="break-words">{config.recovery_protocol_version}</dd></div></dl><div><p className="text-muted-foreground">恢复条件</p><p className="mt-1 whitespace-pre-wrap break-words leading-5">{config.recovery_conditions}</p></div><div><p className="text-muted-foreground">登记说明</p><p className="mt-1 whitespace-pre-wrap break-words leading-5">{value.reason}</p></div></section>;
}

export function AiIssueTrialProtocols({ projectId }: { projectId: string }) { return <Protocols key={projectId} projectId={projectId} />; }
function Protocols({ projectId }: { projectId: string }) {
  const base = `/api/projects/${encodeURIComponent(projectId)}/ai-issue-trials`;
  const [prepared, setPrepared] = useState<Preparation | null>(null), [data, setData] = useState<History | null>(null), [selected, setSelected] = useState<Protocol | null>(null), [form, setForm] = useState<Form>(emptyForm), [pending, setPending] = useState<Command | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const active = useRef(true), locked = useRef(false), selection = useRef(0);
  useEffect(() => { active.current = true; return () => { active.current = false; selection.current += 1; }; }, []);
  function fail(error: unknown) { setError(error instanceof Error ? error.message : "试运行登记读取失败"); if (error instanceof RequestFailure && [401, 403].includes(error.status)) { setPrepared(null); setData(null); setSelected(null); } }
  async function load() {
    if (locked.current) return; locked.current = true; setBusy(true); setError(null);
    const results = await Promise.allSettled([request(`${base}/preparation`).then(preparation), request(`${base}?limit=20`).then(history)]);
    if (active.current) { setPrepared(results[0].status === "fulfilled" ? results[0].value : null); setData(results[1].status === "fulfilled" ? results[1].value : null); for (const result of results) if (result.status === "rejected") fail(result.reason); setBusy(false); }
    locked.current = false;
  }
  async function older() {
    if (locked.current || !data?.next_before_id) return; locked.current = true; setBusy(true); setError(null);
    try { const page = history(await request(`${base}?limit=20&before_id=${encodeURIComponent(data.next_before_id)}`)); if (active.current) setData(current => current ? { ...page, items: [...current.items, ...page.items.filter(item => !current.items.some(old => old.id === item.id))] } : page); }
    catch (error) { if (active.current) fail(error); }
    finally { locked.current = false; if (active.current) setBusy(false); }
  }
  async function open(id: string) {
    const current = ++selection.current; setSelected(null); setError(null); setBusy(true);
    try { const value = protocol(await request(`${base}/${encodeURIComponent(id)}`)); if (value.id !== id) throw new Error("原登记记录不匹配，请重新读取"); if (active.current && current === selection.current) setSelected(value); }
    catch (error) { if (active.current && current === selection.current) fail(error); }
    finally { if (active.current && current === selection.current) setBusy(false); }
  }
  async function save(original?: Command) {
    if (locked.current || (!original && !prepared?.can_register)) return;
    let command = original;
    if (!command) { try { command = commandFor(form, prepared!); } catch (error) { fail(error); return; } }
    locked.current = true; setPending(command); setBusy(true); setError(null); setNotice(null);
    try {
      const result = record(await request(base, command)), saved = protocol(result.protocol);
      if (typeof result.replayed !== "boolean" || saved.evidence_kind !== command.evidence_kind || Date.parse(saved.window_start) !== Date.parse(command.window_start) || Date.parse(saved.window_end) !== Date.parse(command.window_end)) throw new Error("原登记回执尚未完整核对，请沿原请求重试");
      if (active.current) { setSelected(saved); setPending(null); setForm(emptyForm()); setNotice(result.replayed ? "已核对原登记回执，没有重复登记。" : "试运行已登记，原窗口与配置已固定。登记不会开放模型或自动写入。"); setData(current => ({ items: [saved, ...(current?.items ?? []).filter(item => item.id !== saved.id)], next_before_id: current?.next_before_id ?? null })); }
    } catch (error) {
      if (active.current) { fail(error); if (error instanceof RequestFailure && error.status >= 400 && error.status < 500 && !error.code?.endsWith("_RETRY")) { setPending(null); if (error.status === 409) { setPrepared(null); setForm(current => ({ ...current, candidate: "" })); } } }
    } finally { locked.current = false; if (active.current) setBusy(false); }
  }
  function change(key: keyof Form, value: string) { setForm(current => ({ ...current, [key]: value })); }
  const candidate = prepared?.candidates.find(item => item.key === form.candidate), lockedForm = busy || !!pending;
  return <details className="min-w-0 border-t pt-3" onToggle={event => { if (event.target === event.currentTarget && event.currentTarget.open && !prepared && !data && !busy && !pending) void load(); }}><summary className="cursor-pointer text-sm font-medium text-primary">项目问题正式试运行登记</summary><div className="mt-3 space-y-3 text-xs"><p className="leading-5 text-muted-foreground">先固定独立评测版本、窗口与办理口径；在原登记下按窗口采集并回查原件。登记和采集不开放模型，也不授予自动写入资格。</p><Button size="sm" variant="outline" disabled={lockedForm} onClick={() => void load()}>刷新试运行登记资料</Button>{busy && <p role="status">正在核对试运行登记…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status" className="text-muted-foreground">{notice}</p>}
    {prepared && !prepared.can_register && <p className="text-muted-foreground">当前账号仅可回查登记，不能登记新的试运行。</p>}
    {prepared?.blockers.length ? <ul className="space-y-1 text-primary">{[...new Set(prepared.blockers.map(reasonLabel))].map(reason => <li key={reason}>{reason}</li>)}</ul> : null}
    {prepared && prepared.candidates.length === 0 && <p className="text-muted-foreground">尚无可登记的独立问题评测版本，请先核对受信评测发布记录。</p>}
    {prepared?.can_register && prepared.candidates.length > 0 && <form className="space-y-3" onSubmit={event => { event.preventDefault(); void save(); }}><fieldset disabled={lockedForm} className="space-y-3">
      <label className="block">独立问题评测版本<select className={inputClass} value={form.candidate} onChange={event => change("candidate", event.target.value)} required><option value="">请选择已通过的评测版本</option>{prepared.candidates.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
      {candidate && <p className="text-muted-foreground">发布于 {time(candidate.published_at)}；有效至 {time(candidate.expires_at)}。</p>}
      <label className="block">观察场景<select className={inputClass} value={form.evidence} onChange={event => change("evidence", event.target.value)}>{Object.entries(evidenceLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {form.evidence !== "real_business" && <p className="text-primary">模拟或受控重放不能取得真实业务资格。</p>}
      <p className="leading-5 text-muted-foreground">时间按本地时区 {Intl.DateTimeFormat().resolvedOptions().timeZone} 填写；真实业务必须在窗口开始前登记。</p>
      <div className="grid gap-3 sm:grid-cols-2"><label className="min-w-0">试运行开始<input required type="datetime-local" step="1" className={inputClass} value={form.start} onChange={event => change("start", event.target.value)} /></label><label className="min-w-0">试运行结束<input required type="datetime-local" step="1" className={inputClass} value={form.end} onChange={event => change("end", event.target.value)} /></label></div>
      <div className="grid gap-3 sm:grid-cols-3"><label>最小办理数（个原请求）<input required type="number" min="1" step="1" className={inputClass} value={form.minimum} onChange={event => change("minimum", event.target.value)} /></label><label>最短跟踪时长（秒）<input required type="number" min="1" step="1" className={inputClass} value={form.followup} onChange={event => change("followup", event.target.value)} /></label><label>抽检比例（%）<input required type="number" min="0.01" max="100" step="0.01" className={inputClass} value={form.sampling} onChange={event => change("sampling", event.target.value)} /></label></div>
      <label className="block">确认口径<select required className={inputClass} value={form.confirmation} onChange={event => change("confirmation", event.target.value)}><option value="">请选择确认口径</option>{Object.entries(confirmationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <p className="text-muted-foreground">确认率与撤回率门槛由服务端按第 {prepared.policy_revision} 版政策固定，原值随登记回执保留。</p>
      <label className="block">恢复政策版本名称<input required maxLength={128} className={inputClass} value={form.recoveryVersion} onChange={event => change("recoveryVersion", event.target.value)} /></label>
      <label className="block">恢复条件<textarea required maxLength={2048} rows={2} className={inputClass} value={form.recoveryConditions} onChange={event => change("recoveryConditions", event.target.value)} /></label>
      <label className="block">登记说明<textarea required maxLength={2048} rows={2} className={inputClass} value={form.reason} onChange={event => change("reason", event.target.value)} /></label>
    </fieldset><Button size="sm" type="submit" disabled={lockedForm}>登记本次项目试运行</Button></form>}
    {pending && !busy && <div className="space-y-2"><p className="text-primary">登记结果尚未明确，已保留原版本、窗口和请求；继续核对不会另起登记。</p><Button size="sm" onClick={() => void save(pending)}>重试原试运行登记</Button></div>}
    {data?.items.length === 0 && <p className="text-muted-foreground">尚无项目试运行登记。</p>}
    {data?.items.map(item => <div className="flex flex-wrap items-center justify-between gap-2 border-b py-2" key={item.id}><div className="min-w-0 space-y-1"><p>{time(item.created_at)} · {item.actor_name} · {evidenceLabels[item.evidence_kind]}</p><p className="break-words text-muted-foreground">{item.binding_label}</p></div><Button size="sm" variant="outline" disabled={lockedForm} onClick={() => void open(item.id)}>查看原登记</Button></div>)}
    {data?.next_before_id && <Button size="sm" variant="outline" disabled={lockedForm} onClick={() => void older()}>更早的试运行登记</Button>}
    {selected && <><ProtocolDetail value={selected} /><AiIssueTrialCollections projectId={projectId} protocolId={selected.id} /><AiIssueTrialCurrent projectId={projectId} protocolId={selected.id} /></>}
  </div></details>;
}
