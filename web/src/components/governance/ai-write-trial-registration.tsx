"use client";

import { useEffect, useRef, useState } from "react";
import { ClipboardTextIcon } from "@phosphor-icons/react";
import { isRecord } from "@/components/workspace-api";

const endpoint = "/api/ai/governance/write-policy/trials";
const inputClass = "mt-1 min-h-9 w-full rounded-md border bg-background px-2.5 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
const buttonClass = "inline-flex min-h-9 items-center justify-center rounded-md border bg-background px-3 text-xs outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
const blockerLabels: Record<string, string> = {
  policy_missing: "尚未登记分级写入政策", write_policy_missing: "尚未登记分级写入政策",
  policy_not_tiered: "请先启用分级写入政策", trial_disabled: "当前政策尚未启用会议草稿试运行",
  evaluation_missing: "尚无可用于登记的独立评测", no_trusted_evaluations: "尚无受信的独立评测发布记录",
  no_candidates: "当前没有符合政策的独立评测候选", no_projects: "当前没有可登记的项目范围",
  evaluation_expired: "已有评测已到期，需重新核对有效版本", model_version_unknown: "模型版本尚未核实",
};
type Candidate = { key: string; label: string; binding: Record<string, unknown>; evaluation_id: string; published_at: string; expires_at: string };
type Preparation = { as_of: string; candidates: Candidate[]; projects: { id: string; code: string; name: string }[]; policy_revision: number; blockers: string[] };
type Form = { candidate: string; projects: string[]; evidence: string; start: string; end: string; minimum: string; followup: string; sampling: string; confirmation: string; recoveryVersion: string; recoveryConditions: string; reason: string };
const emptyForm = (): Form => ({ candidate: "", projects: [], evidence: "real_business", start: "", end: "", minimum: "", followup: "", sampling: "", confirmation: "", recoveryVersion: "", recoveryConditions: "", reason: "" });
function text(value: unknown): string { if (typeof value !== "string") throw new Error("登记准备资料不完整，请重新读取。"); return value; }
function stamp(value: unknown): string { const result = text(value); if (!Number.isFinite(Date.parse(result))) throw new Error("评测有效时间不完整，请重新读取。"); return result; }
function preparation(value: unknown): Preparation {
  if (!isRecord(value) || !Array.isArray(value.candidates) || !Array.isArray(value.projects) || !Array.isArray(value.blockers) || !Number.isSafeInteger(value.policy_revision) || Number(value.policy_revision) < 0) throw new Error("登记准备资料不完整，请重新读取。");
  return { as_of: stamp(value.as_of), policy_revision: Number(value.policy_revision), blockers: value.blockers.map(text),
    candidates: value.candidates.map(row => { if (!isRecord(row) || !isRecord(row.binding)) throw new Error("独立评测候选资料不完整，请重新读取。"); return { key: text(row.key), label: text(row.label), binding: row.binding, evaluation_id: text(row.evaluation_id), published_at: stamp(row.published_at), expires_at: stamp(row.expires_at) }; }),
    projects: value.projects.map(row => { if (!isRecord(row)) throw new Error("项目范围不完整，请重新读取。"); return { id: text(row.id), code: text(row.code), name: text(row.name) }; }),
  };
}
class RequestFailure extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function request(body?: string): Promise<unknown> {
  const response = await fetch(endpoint + (body ? "" : "/preparation"), { method: body ? "POST" : "GET", cache: "no-store", credentials: "same-origin", ...(body ? { headers: { "Content-Type": "application/json" }, body } : {}) });
  if (!response.ok) {
    const message = response.status === 401 ? "登录已失效，请重新登录。" : response.status === 403 ? "当前账号无权登记该试运行范围。" : response.status === 409 ? "政策、评测或开始时间已变化，请刷新登记资料后重新核对。" : response.status === 422 || response.status === 400 ? "登记内容未通过核对，请检查窗口、范围及配置。" : "登记服务暂不可用，请重试。";
    throw new RequestFailure(message, response.status);
  }
  return response.json();
}
function message(error: unknown) { return error instanceof TypeError ? "网络连接中断。" : error instanceof Error ? error.message : "登记尚未完成。"; }
function positive(value: string, label: string, decimals = false): number {
  if (!(decimals ? /^\d+(?:\.\d{1,2})?$/ : /^\d+$/).test(value)) throw new Error(`请填写${label}${decimals ? "（最多两位小数）" : "的正整数"}。`);
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0 || !Number.isSafeInteger(Math.round(number * 100))) throw new Error(`请核对${label}。`);
  return number;
}
function localDate(value: string): Date {
  const fields = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value);
  const parsed = new Date(value);
  if (!fields || !Number.isFinite(parsed.getTime())) throw new Error("请填写完整的本地开始与结束时间。");
  const expected = fields.slice(1).map(part => Number(part ?? 0));
  const actual = [parsed.getFullYear(), parsed.getMonth() + 1, parsed.getDate(), parsed.getHours(), parsed.getMinutes(), parsed.getSeconds()];
  if (actual.some((part, index) => part !== expected[index])) throw new Error("所填时间在当前时区不存在，请核对日期或夏令时切换时间。");
  return parsed;
}
function bodyFor(form: Form, prepared: Preparation, requestId: string) {
  const candidate = prepared.candidates.find(item => item.key === form.candidate);
  if (!candidate) throw new Error("请选择已核实的独立评测候选。");
  if (Date.parse(candidate.expires_at) <= Date.now()) throw new Error("所选独立评测已到期，请刷新登记资料。");
  if (!form.projects.length || form.projects.length > 100 || form.projects.some(id => !prepared.projects.some(project => project.id === id))) throw new Error("请选择 1 至 100 个当前有权项目。");
  const start = localDate(form.start), end = localDate(form.end);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || end <= start) throw new Error("请填写有效的开始与结束时间，结束须晚于开始。");
  if (form.evidence === "real_business" && start.getTime() <= Math.max(Date.now(), Date.parse(prepared.as_of))) throw new Error("真实业务须提前登记，请选择未来的开始时间。");
  const seconds = (end.getTime() - start.getTime()) / 1000;
  if (!Number.isSafeInteger(seconds)) throw new Error("观察窗口请精确到秒。");
  const minimum = positive(form.minimum, "最小办理数"), followup = Math.round(positive(form.followup, "后续观察时长", true) * 3600);
  const sampling = Math.round(positive(form.sampling, "抽检比例", true) * 100);
  if (!Number.isSafeInteger(followup)) throw new Error("后续观察时长过大，请核对。");
  if (sampling > 10000) throw new Error("抽检比例不能超过 100%。");
  if (!["ever_confirmed", "retained_original"].includes(form.confirmation)) throw new Error("请选择确认口径。");
  if (!/^[a-zA-Z0-9_.:-]{1,128}$/.test(form.recoveryVersion.trim())) throw new Error("请填写恢复政策的版本名称，使用字母、数字、点或短横线。");
  if (!form.recoveryConditions.trim() || !form.reason.trim()) throw new Error("请填写恢复条件与登记说明。");
  return { request_id: requestId, preparation_digest: candidate.key, project_ids: form.projects, binding: candidate.binding, evidence_kind: form.evidence, window_start: start.toISOString(), window_end: end.toISOString(), configuration: { minimum_handled_drafts: minimum, cohort_window_seconds: seconds, minimum_followup_seconds: followup, sampling_basis_points: sampling, confirmation_basis: form.confirmation, recovery_protocol_version: form.recoveryVersion.trim(), recovery_conditions: form.recoveryConditions.trim() }, reason: form.reason.trim() };
}

export function AiWriteTrialRegistration({ onRegistered, onPendingChange }: { onRegistered: () => void; onPendingChange?: (pending: boolean) => void }) {
  const [prepared, setPrepared] = useState<Preparation | null>(null);
  const [form, setForm] = useState<Form>(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const generation = useRef(0);
  const pending = useRef<string | null>(null);
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  useEffect(() => {
    const current = ++generation.current;
    void request().then(value => { if (current === generation.current) setPrepared(preparation(value)); }).catch((error: unknown) => { if (current === generation.current) setError(message(error)); }).finally(() => { if (current === generation.current) setLoading(false); });
    return () => { generation.current += 1; };
  }, []);
  async function reload() {
    const current = ++generation.current;
    setLoading(true); setError(null);
    try { const next = preparation(await request()); if (current === generation.current) { setPrepared(next); setForm(emptyForm()); } }
    catch (error) { if (current === generation.current) { setError(message(error)); setPrepared(null); } }
    finally { if (current === generation.current) setLoading(false); }
  }
  async function save() {
    if (!prepared || saving) return;
    const current = generation.current;
    setError(null); setNotice(null);
    try { pending.current ??= JSON.stringify(bodyFor(form, prepared, crypto.randomUUID())); }
    catch (error) { setError(message(error)); return; }
    setSaving(true); onPendingChange?.(true);
    try {
      const result = await request(pending.current);
      if (!isRecord(result) || !isRecord(result.protocol) || typeof result.protocol.id !== "string") throw new Error("登记回执尚未完整读取。");
      if (current !== generation.current) return;
      pending.current = null; setUncertain(false); setForm(emptyForm());
      setNotice("试运行已登记，项目、窗口与配置已固定。登记不授予自动写入资格。");
      onPendingChange?.(false); onRegistered();
    } catch (error) {
      if (current !== generation.current) return;
      const knownRejection = error instanceof RequestFailure && error.status >= 400 && error.status < 500;
      if (knownRejection) { pending.current = null; setUncertain(false); onPendingChange?.(false); if ([401, 403].includes(error.status)) setPrepared(null); }
      else setUncertain(true);
      setError(message(error) + (knownRejection ? "" : " 结果尚未确认，已锁定本次内容；请重试原请求，避免重复登记。"));
    } finally { if (current === generation.current) setSaving(false); }
  }
  const unavailable = !prepared || !prepared.candidates.length || !prepared.projects.length;
  const locked = loading || saving || uncertain || unavailable;
  const candidate = prepared?.candidates.find(item => item.key === form.candidate);
  const blockers = [...new Set(prepared?.blockers.map(code => blockerLabels[code] ?? (/[\u3400-\u9fff]/.test(code) ? code : "当前政策或独立评测尚未就绪，请核对后刷新。")) ?? [])];
  function change<K extends keyof Form>(key: K, value: Form[K]) { setForm(old => ({ ...old, [key]: value })); }
  return <section aria-label="登记固定试运行" className="mt-3 rounded-lg border bg-card p-3 sm:p-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="flex items-center gap-2 text-sm font-semibold"><ClipboardTextIcon size={17} className="text-primary" aria-hidden="true" />登记固定试运行</h3><p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">先选择已有独立评测及项目，再固定观察窗口与办理口径。数字需由你明确填写；登记不会自动启用写入。</p></div><button type="button" className={buttonClass} disabled={loading || saving || uncertain} onClick={() => void reload()}>刷新登记资料</button></div>
    {loading && <p role="status" className="mt-3 text-xs text-muted-foreground">正在核对可用评测与项目…</p>}{error && <p role="alert" className="mt-3 text-xs text-destructive">{error}</p>}{notice && <p role="status" className="mt-3 text-xs text-muted-foreground">{notice}</p>}
    {blockers.length > 0 && <ul className="mt-3 space-y-1 text-xs text-muted-foreground">{blockers.map(item => <li key={item}>· {item}</li>)}</ul>}
    {prepared && unavailable && <p className="mt-3 rounded-md bg-muted/40 p-3 text-xs leading-5">{!prepared.candidates.length ? "尚无可登记的独立评测候选。请先完成并发布受信评测。" : "当前没有可登记的项目范围。"}</p>}
    {prepared && !unavailable && <form className="mt-4 space-y-4" onSubmit={event => { event.preventDefault(); void save(); }}>
      <fieldset disabled={locked} className="space-y-4">
        <label className="block text-xs font-medium">独立评测候选<select required className={inputClass} value={form.candidate} onChange={event => change("candidate", event.target.value)}><option value="">请选择已核实的评测</option>{prepared.candidates.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
        {candidate && <p className="text-xs leading-5 text-muted-foreground">评测发布于 {new Date(candidate.published_at).toLocaleString("zh-CN")}；有效至 {new Date(candidate.expires_at).toLocaleString("zh-CN")}。</p>}
        <fieldset><legend className="text-xs font-medium">项目范围 · 已选 {form.projects.length} 项</legend><div className="mt-2 grid max-h-56 gap-2 overflow-y-auto rounded-md border p-3 sm:grid-cols-2">{prepared.projects.map(project => <label key={project.id} className="flex min-w-0 items-start gap-2 text-xs leading-5"><input type="checkbox" className="mt-1 accent-primary" checked={form.projects.includes(project.id)} onChange={event => change("projects", event.target.checked ? [...form.projects, project.id] : form.projects.filter(id => id !== project.id))} /><span className="break-words">{project.name} <span className="text-muted-foreground">· {project.code}</span></span></label>)}</div></fieldset>
        <label className="block text-xs font-medium">观察场景<select className={inputClass} value={form.evidence} onChange={event => change("evidence", event.target.value)}><option value="real_business">真实业务</option><option value="controlled_replay">受控重放</option><option value="synthetic">模拟场景</option></select></label>
        <div><p className="mb-2 text-xs leading-5 text-muted-foreground">以下时间按本地时区 {zone} 输入，保存时包含时区。真实业务的开始时间须晚于登记时间。</p><div className="grid gap-3 sm:grid-cols-2"><label className="block min-w-0 text-xs font-medium">观察开始时间<input required type="datetime-local" step="1" className={inputClass} value={form.start} onChange={event => change("start", event.target.value)} /></label><label className="block min-w-0 text-xs font-medium">观察结束时间<input required type="datetime-local" step="1" className={inputClass} value={form.end} onChange={event => change("end", event.target.value)} /></label></div></div>
        <div className="grid gap-3 sm:grid-cols-3"><label className="block text-xs font-medium">最小办理数（份）<input required type="number" min="1" step="1" className={inputClass} value={form.minimum} onChange={event => change("minimum", event.target.value)} /></label><label className="block text-xs font-medium">后续观察时长（小时）<input required type="number" min="0.01" step="0.01" className={inputClass} value={form.followup} onChange={event => change("followup", event.target.value)} /></label><label className="block text-xs font-medium">抽检比例（%）<input required type="number" min="0.01" max="100" step="0.01" className={inputClass} value={form.sampling} onChange={event => change("sampling", event.target.value)} /></label></div>
        <label className="block text-xs font-medium">确认口径<select required className={inputClass} value={form.confirmation} onChange={event => change("confirmation", event.target.value)}><option value="">请选择确认口径</option><option value="retained_original">确认后未修改、未撤回</option><option value="ever_confirmed">曾确认采用</option></select></label>
        <p className="text-xs leading-5 text-muted-foreground">确认率与撤回率门槛继承第 {prepared.policy_revision} 版政策，服务端固定；已批准边界为确认率不低于 90%、撤回率不高于 5%，政策可采用更严格门槛。</p>
        <label className="block text-xs font-medium">恢复政策版本名称<input required maxLength={128} className={inputClass} value={form.recoveryVersion} onChange={event => change("recoveryVersion", event.target.value)} /><span className="mt-1 block font-normal text-muted-foreground">填写已约定的版本名称；登记此名称不会自动恢复写入。</span></label>
        <label className="block text-xs font-medium">恢复条件<textarea required maxLength={2048} rows={3} className={inputClass} value={form.recoveryConditions} onChange={event => change("recoveryConditions", event.target.value)} /></label>
        <label className="block text-xs font-medium">登记说明<textarea required maxLength={2048} rows={3} className={inputClass} value={form.reason} onChange={event => change("reason", event.target.value)} /></label>
      </fieldset>
      <button type="submit" className={`${buttonClass} border-primary/30 text-primary`} disabled={loading || saving}>{saving ? "正在登记…" : uncertain ? "重试原登记请求" : "登记本次试运行"}</button>
    </form>}
  </section>;
}
