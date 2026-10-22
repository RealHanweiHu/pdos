"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowClockwise, Package, Plus } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { mpRecord, mpRevision, mpSame, mpStatus, mpUuid } from "@/components/manufacturing-preparation/manufacturing-preparation-contract";
import {
  approvalDraft, blankReleaseLocal, newReleaseCommand, parseReleasePayload, releaseAssessments, releaseAuthorityReady, releaseDetail, releaseDiscipline, releaseDraftKey, releaseHeader, releaseOperations, restoreReleaseLocal, runReleaseRequest,
  type ReleaseApi, type ReleaseAssessment, type ReleaseDetail, type ReleaseHeader, type ReleaseInputs, type ReleaseLocal, type ReleaseOperation, type ReleasePending, type ReleasePrepared, type ReleaseScope,
} from "@/lib/releases";
import styles from "./release-packages.module.css";

export type ReleasePackagesProps = { categoryId: string; projectId: string; product: { id: string; revision: number }; principalId: string; api: ReleaseApi; onSaved: () => void | Promise<void>; onPendingChange?: (busy: boolean) => void; blocked?: boolean };
const names = { engineering: "工程", manufacturing: "制造" };
const states = { BLOCKED: "阻塞", UNKNOWN: "未知", READY_WITH_CONDITIONS: "满足已声明条件", READY: "已满足本范围检查" };
const operationNames: Record<ReleaseOperation, string> = { "release.package.assemble": "固定包", "release.engineering.approve": "工程具名决定", "release.manufacturing.approve": "制造具名决定" };
const diagnosticNames: Record<string, string> = {
  RELEASE_POLICY_MISSING: "尚无适用的放行政策",
  RELEASE_POLICY_OWNER_UNCONNECTED: "放行政策依据尚未接通",
  DOCUMENT_CONFIGURATION_APPLICABILITY_UNKNOWN: "文档与配置的适用关系待核对",
  PUBLICATION_RECHECK_REQUIRED: "制造发布依据待复核",
  RESOURCE_QUALIFICATION_OWNER_UNCONNECTED: "资源资格依据尚未接通",
};
function Diagnostic({ value, prefix = "" }: { value: unknown; prefix?: string }) {
  const raw = mpRecord(value) ? value.code ?? value.key : value;
  const code = typeof raw === "string" && /^[A-Z][A-Z0-9_]+$/.test(raw) ? raw : null;
  const detail = mpRecord(value) && typeof value.detail === "string" ? value.detail : typeof value === "string" && !code ? value : null;
  const message = code && diagnosticNames[code] ? diagnosticNames[code] : detail ?? "此项依据仍待核对";
  return <div><p>{prefix}{message}</p>{code && <details><summary>查看诊断代码</summary><code>{code}</code>{detail && detail !== message && <p>{detail}</p>}</details>}</div>;
}
function FixedContent({ plan }: { plan: Record<string, unknown> }) {
  const declaration = mpRecord(plan.declaration) ? plan.declaration : plan, configuration = mpRecord(declaration.subject_config) ? declaration.subject_config : {}, range = mpRecord(declaration.release_scope) ? declaration.release_scope : {}, reason = declaration.reason ?? (mpRecord(plan.input_snapshot) ? plan.input_snapshot.reason : undefined);
  const basedOnPackage = !mpRecord(declaration.subject_config) && mpRecord(declaration.package) && mpUuid(declaration.package.id) && mpRevision(declaration.package.revision) ? declaration.package : null;
  return <div className={styles.stack}><p>用途：{String(declaration.purpose ?? "未知")}</p>{basedOnPackage && <p>基于固定包 {String(basedOnPackage.id)} · v{String(basedOnPackage.revision)}</p>}<dl className={styles.facts}>{!basedOnPackage && [["definition", "产品定义"], ["engineering_configuration", "工程配置"], ["manufacturing_configuration", "制造配置"]].map(([key, name]) => <div key={key}><dt>{name}</dt><dd>{mpRecord(configuration[key]) ? `${String(configuration[key].id)} · v${String(configuration[key].revision)}` : "未知"}</dd></div>)}{[["quantity", "数量"], ["unit", "单位"], ["site", "场地"], ["lots", "批次"], ["lines", "产线"], ["regions", "地区"]].map(([key, name]) => <div key={key}><dt>{name}</dt><dd>{range[key] == null ? "未知／未覆盖" : Array.isArray(range[key]) ? range[key].length ? range[key].map(v => mpRecord(v) ? `${String(v.id)} · v${String(v.revision)}` : String(v)).join("；") : "明确为空，不代表全部" : String(range[key])}</dd></div>)}</dl>{Array.isArray(declaration.limits) && declaration.limits.map((v, i) => <p key={i}>限制：{mpRecord(v) ? String(v.text) : "待核"}</p>)}{typeof reason === "string" && <p>办理说明：{reason}</p>}{["verifications", "pilots", "residuals", "documents", "exceptions"].map(key => Array.isArray(declaration[key]) && declaration[key].length > 0 && <details key={key}><summary>{({ verifications: "固定测试", pilots: "固定试产", residuals: "遗留问题与变更", documents: "固定文档", exceptions: "独立例外决定" } as Record<string, string>)[key]}（{declaration[key].length}）</summary><pre>{JSON.stringify(declaration[key], null, 2)}</pre></details>)}<details><summary>固定原件引用及完整内容</summary><pre>{JSON.stringify(plan, null, 2)}</pre></details></div>;
}
export function ReleaseAssessmentReading({ assessments }: { assessments: ReleaseAssessment[] }) {
  return <div className={styles.grid}>{(["engineering", "manufacturing"] as const).map(discipline => { const row = assessments.find(v => v.discipline === discipline); return <section className={styles.card} key={discipline} aria-label={`${names[discipline]}范围检查`}><h4>{names[discipline]}：{row ? states[row.state] : "未知"}</h4>{row?.checks.map((v, i) => <div key={i}><Diagnostic value={v}/>{v.non_waivable === true && <p>不可豁免</p>}</div>)}{row?.blocked.map((v, i) => <Diagnostic key={`b${i}`} value={v} prefix="阻塞："/>)}{row?.unknown.map((v, i) => <Diagnostic key={`u${i}`} value={v} prefix="待核："/>)}{row?.conditions.map(v => <p key={v.id}>固定条件决定：{v.id} · v{v.revision}</p>)}</section>; })}</div>;
}
export function ReleasePackageReading({ detail }: { detail: ReleaseDetail }) {
  const assessments = releaseAssessments(detail.assessments) ?? [];
  return <section className={styles.card} aria-label="已保存固定发布包"><h3>固定发布包 v{detail.revision}</h3><p>{mpSame(detail.current.version, { id: detail.id, revision: detail.revision }) ? "当前包版本" : "历史固定包版本"} · {detail.applicability === "current" ? "当前来源可核" : "适用依据待复核"}</p><FixedContent plan={detail.package}/>{detail.package.policy == null && <p>尚无适用政策，工程和制造决定均须保留未知。</p>}<ReleaseAssessmentReading assessments={assessments}/>{(["engineering", "manufacturing"] as const).map(discipline => <div key={discipline}><h4>{names[discipline]}已记录决定</h4>{detail.decisions.filter(d => d.discipline === discipline).length ? detail.decisions.filter(d => d.discipline === discipline).map(d => <details key={String(d.id)}><summary>决定 v{String(d.revision)} · {d.applicability === "current" ? "适用依据当前" : "待复核，历史决定仍保留"}</summary>{mpRecord(d.decision) && <><FixedContent plan={d.decision}/><p>具名签署人：{Array.isArray(d.decision.signers) ? d.decision.signers.join("、") : "待核"}；明确期限：{d.decision.expiry == null ? "未另设期限" : String(d.decision.expiry)}</p></>}<p>原回执：{String(d.receipt_id)}</p></details>) : <p>尚无具名决定。</p>}</div>)}<p className="subtle">工程与制造分别负责其范围。客户承认、外部接收和实际生效须分别记录，固定包与内部决定不代替这些事实。</p></section>;
}
export function ReleasePackages(props: ReleasePackagesProps) { return <ReleasePanel key={`${props.categoryId}:${props.principalId}:${props.product.id}:${props.projectId}`} {...props}/>; }
function ReleasePanel({ categoryId, projectId, product, principalId, api, onSaved, onPendingChange, blocked = false }: ReleasePackagesProps) {
  const scope = useMemo<ReleaseScope>(() => ({ categoryId, productId: product.id, projectId, principalId }), [categoryId, product.id, projectId, principalId]);
  const key = `pdos-release-v1:${categoryId}:${principalId}:${product.id}:${projectId}`;
  const [local, setLocal] = useState<ReleaseLocal>(() => blankReleaseLocal(scope)), state = useRef(local);
  const [items, setItems] = useState<ReleaseHeader[]>([]), [detail, setDetail] = useState<ReleaseDetail | null>(null), [cursor, setCursor] = useState<string | null>(null);
  const [reading, setReading] = useState(true), [failed, setFailed] = useState(true), [busy, setBusy] = useState(false), [denied, setDenied] = useState(false), [notice, setNotice] = useState("");
  const [material, setMaterial] = useState<ReleaseInputs | null>(null), [prepared, setPrepared] = useState<ReleasePrepared | null>(null);
  const alive = useRef(false), lock = useRef(false), sequence = useRef(0), dialog = useRef<HTMLDialogElement>(null);
  const invalidate = useCallback(() => { sequence.current++; }, []);
  const persist = useCallback((next: ReleaseLocal) => { try { localStorage.setItem(key, JSON.stringify(next)); } catch { throw new Error("本机未能保留原请求，请恢复存储后继续；本次尚未提交。"); } state.current = next; setLocal(next); }, [key]);
  function save(next: ReleaseLocal) { try { persist(next); return true; } catch (e) { setNotice(e instanceof Error ? e.message : "本机存储不可用。"); return false; } }
  const failure = useCallback((error: unknown) => { if ([401, 403].includes(mpStatus(error) ?? 0)) { sequence.current++; state.current = blankReleaseLocal(scope); setLocal(state.current); setItems([]); setDetail(null); setMaterial(null); setPrepared(null); setDenied(true); setNotice("当前访问不可用，页面材料已隐藏；原请求仅在本范围重新授权后可恢复。"); } else setNotice(error instanceof Error ? error.message : "读取或办理失败，请重试。"); }, [scope]);
  const refresh = useCallback(async () => {
    const epoch = ++sequence.current; setReading(true); setFailed(true); setMaterial(null); setPrepared(null);
    try { const raw = await api<unknown>(`v1/products/${product.id}/release-packages?project_id=${projectId}`); if (!alive.current || epoch !== sequence.current) return;
      if (!mpRecord(raw) || !Array.isArray(raw.items) || !raw.items.every(v => releaseHeader(v, projectId)) || !(raw.next_cursor === null || typeof raw.next_cursor === "string")) throw new Error("本项目发布包读取不完整，请重试。");
      setItems(raw.items); setCursor(raw.next_cursor); const selected = state.current.selected;
      if (selected) { const fixed = await api<unknown>(`v1/products/${product.id}/release-packages/${selected.id}`); if (!alive.current || epoch !== sequence.current) return; if (!releaseDetail(fixed, scope) || fixed.id !== selected.id || fixed.revision !== selected.revision) throw new Error("固定包回读身份或版本不一致。"); setDetail(fixed); } else setDetail(null);
      setFailed(false);
    } catch (error) { if (alive.current && epoch === sequence.current) failure(error); }
    finally { if (alive.current && epoch === sequence.current) setReading(false); }
  }, [api, product.id, projectId, scope, failure]);
  useEffect(() => { alive.current = true; void Promise.resolve().then(async () => { if (!alive.current) return; try { const restored = restoreReleaseLocal(JSON.parse(localStorage.getItem(key) ?? "null"), scope); if (restored) persist(restored); } catch { /* Invalid local content cannot authorize a submission. */ } await refresh(); }); return () => { alive.current = false; invalidate(); }; }, [key, scope, persist, refresh, invalidate]);
  useEffect(() => { if (material || prepared) dialog.current?.showModal(); else dialog.current?.close(); }, [material, prepared]);
  useEffect(() => { onPendingChange?.(busy || !!local.pending || !!material || !!prepared); return () => onPendingChange?.(false); }, [busy, local.pending, material, prepared, onPendingChange]);
  const disabled = busy || reading || denied || blocked, editable = !disabled && !failed && !local.pending && !material && !prepared;
  const draftKey = releaseDraftKey(local.operation, local.selected), rawDraft = local.drafts[draftKey] ?? "";
  let draftError = "", parsed: ReturnType<typeof parseReleasePayload> | null = null;
  if (rawDraft) { try { parsed = parseReleasePayload(rawDraft, local.operation, scope, local.selected); } catch (error) { draftError = error instanceof Error ? error.message : "材料格式待核。"; } }
  const discipline = releaseDiscipline(local.operation), assessment = detail && discipline ? (releaseAssessments(detail.assessments) ?? []).find(v => v.discipline === discipline) : undefined;
  const canDecide = !discipline || !!detail && detail.applicability === "current" && mpRecord(detail.package.policy) && typeof detail.package.policy.version === "string" && !!detail.package.policy.version;
  function edit(next: ReleaseLocal) { if (!editable) return; setMaterial(null); setPrepared(null); save({ ...next, receipt: null, completed: null }); }
  async function selectPackage(identity: string) {
    if (!editable) return; const selected = items.find(v => v.id === identity); if (!selected) return;
    if (!save({ ...local, selected: { id: selected.id, revision: selected.revision }, receipt: null, completed: null })) return;
    const epoch = ++sequence.current; setBusy(true); setDetail(null);
    try { const fixed = await api<unknown>(`v1/products/${product.id}/release-packages/${identity}`); if (!alive.current || epoch !== sequence.current) return; if (!releaseDetail(fixed, scope) || fixed.id !== identity || fixed.revision !== selected.revision) throw new Error("所选固定包版本回读不一致。"); setDetail(fixed); }
    catch (error) { if (alive.current && epoch === sequence.current) failure(error); }
    finally { if (alive.current && epoch === sequence.current) setBusy(false); }
  }
  function chooseOperation(operation: ReleaseOperation) {
    if (!editable) return; const next = { ...local, operation, drafts: { ...local.drafts }, receipt: null, completed: null };
    const slot = releaseDraftKey(operation, next.selected); if (operation !== releaseOperations[0] && detail && next.drafts[slot] === undefined) next.drafts[slot] = approvalDraft(detail); edit(next);
  }
  async function run(waiting: ReleasePending) {
    if (lock.current || denied || blocked) return; lock.current = true; setBusy(true); setNotice("");
    try { const answer = await runReleaseRequest(api, waiting, scope, next => persist({ ...state.current, pending: next }), () => alive.current);
      if (!answer || !alive.current) return;
      if (answer.stage === "review") { setMaterial(answer.inputs); return; }
      if (answer.stage === "preview") { setPrepared(answer.prepared); return; }
      const command = waiting.command, selected = command.operation === releaseOperations[0] ? { id: answer.receipt.subject_id, revision: answer.receipt.subject_revision } : state.current.selected;
      persist({ ...state.current, selected, pending: null, receipt: answer.receipt, completed: command }); setMaterial(null); setPrepared(null); setNotice("已保存并取得原回执；工程、制造及外部接收生效仍分别读取。"); await refresh();
      try { await onSaved(); } catch { if (alive.current) setNotice("本次已保存并取得回执，关联视图刷新失败，请重新读取。"); }
    } catch (error) { if (alive.current) { if (waiting.stage === "execute" && ![401, 403].includes(mpStatus(error) ?? 0)) setNotice("提交结果尚未核实。请保留原请求，明确重放并核对同一原提交。"); else failure(error); } }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function start() {
    if (!editable || !parsed || !canDecide || local.receipt) return;
    try { const command = newReleaseCommand(scope, product.revision, local.operation, parsed), pending = { stage: "inputs" as const, command }; if (save({ ...local, pending, receipt: null, completed: null })) void run(pending); } catch (error) { failure(error); }
  }
  function confirm() {
    if (disabled || !local.pending) return;
    const command = prepared?.command ?? local.pending.command;
    if (command.operation !== releaseOperations[0] && (!prepared || (prepared.expires_at !== null && Date.parse(prepared.expires_at) <= Date.now()))) { setPrepared(null); setNotice("本次预览已到期，请继续核对原请求。"); return; }
    if (command.operation === releaseOperations[0] && (!material || local.pending.stage !== "review")) return;
    const pending = { ...local.pending, stage: "execute" as const, command }; if (!save({ ...local, pending })) return; setMaterial(null); setPrepared(null); void run(pending);
  }
  async function more() {
    if (disabled || !cursor || local.pending) return; const original = cursor, epoch = sequence.current; setBusy(true);
    try { const raw = await api<unknown>(`v1/products/${product.id}/release-packages?project_id=${projectId}&history_cursor=${encodeURIComponent(original)}`); if (!alive.current || epoch !== sequence.current) return; if (!mpRecord(raw) || !Array.isArray(raw.items) || !raw.items.every(v => releaseHeader(v, projectId)) || !(raw.next_cursor === null || typeof raw.next_cursor === "string") || raw.next_cursor === original) throw new Error("发布包分页不完整，请重试。"); const rows = raw.items; setItems(old => [...old, ...rows.filter(v => !old.some(a => a.id === v.id))]); setCursor(raw.next_cursor); } catch (error) { if (alive.current && epoch === sequence.current) failure(error); } finally { if (alive.current) setBusy(false); }
  }
  const shown = prepared?.inputs ?? material;
  return <section className={styles.panel} aria-label="固定发布包与分别决定">
    <header className={styles.row}><div><h2><Package size={20}/>固定发布包与分别决定</h2><p className="subtle">固定资料与用途，分别办理工程、制造决定；客户承认、外部接收和实际生效继续保留独立事实。</p></div><Button variant="outline" disabled={disabled || !!material || !!prepared} onClick={() => void refresh()}><ArrowClockwise/>刷新发布包</Button></header>
    {notice && <p role="status">{notice}</p>}{reading && <p>正在读取本项目固定发布包。</p>}{failed && !reading && !denied && <p role="alert">本项目发布包读取未完成，暂不能开始新办理。</p>}
    {!denied && !failed && !reading && <>
      {local.receipt && <p role="status">已保存本次{operationNames[local.receipt.operation]}，回执 {local.receipt.id}。继续办理须明确选择新草稿。</p>}
      <div className={styles.row}><Button variant="outline" disabled={!editable} onClick={() => { edit({ ...local, operation: releaseOperations[0], selected: null }); setDetail(null); }}><Plus/>新建固定包草稿</Button><label>已保存固定包<select disabled={!editable} value={local.selected?.id ?? ""} onChange={e => void selectPackage(e.target.value)}><option value="">选择一份固定包按需回读</option>{items.map(v => <option key={v.id} value={v.id}>v{v.revision} · {v.purpose ?? v.id} · {v.applicability === "current" ? "可核" : v.applicability === "not_checked" ? "未核对" : "待复核"}</option>)}</select></label></div>
      {detail && <ReleasePackageReading detail={detail}/>}
      <fieldset className={styles.card} disabled={!editable}><legend>本次明确办理</legend><label>办理内容<select value={local.operation} onChange={e => chooseOperation(e.target.value as ReleaseOperation)}><option value={releaseOperations[0]}>保存固定包（不作放行决定）</option><option value={releaseOperations[1]} disabled={!detail}>工程具名决定</option><option value={releaseOperations[2]} disabled={!detail}>制造具名决定</option></select></label>{discipline && <p role="status">{!canDecide ? `${names[discipline]}政策或适用依据未知，不能办理具名批准。` : `${names[discipline]}包整体检查：${assessment ? states[assessment.state] : "未知"}；可读取核对本次选定范围，是否可决定仍由实际检查判断。`}</p>}<label>高级材料 JSON<textarea rows={12} spellCheck={false} value={rawDraft} onChange={e => edit({ ...local, drafts: { ...local.drafts, [draftKey]: e.target.value } })} placeholder="粘贴本项目精确固定版本、范围、用途及真实原件引用"/></label>{draftError && <p role="alert">{draftError}</p>}<details><summary>材料填写说明</summary><p>固定包使用 project_id、subject_config（definition／engineering_configuration／manufacturing_configuration）、release_scope、purpose、sources、reason；可列固定制造发布、测试、试产、文档、问题／变更、独立例外和有原文的限制。续版须显式填写 previous 的真实 ID 与版本。</p><p>决定使用所选 package、release_scope、purpose、limits、expiry、sources 和具名理由。原件引用须为真实 artifact 的 ID、revision 与完整行 position（line:行号;quote_sha256:原文摘要）。未知数量、场地或范围留 null，不代表无限制。不要粘贴密钥或运行、权限、政策资格字段。</p></details></fieldset>
      {parsed && !local.pending && <section className={styles.card} aria-label="本次声明材料"><h3>本次声明，待服务器核对</h3><FixedContent plan={parsed}/></section>}
      {local.pending ? <section className={styles.card}><p>{local.pending.stage === "execute" ? "同一已确认提交仍待核对。若此前未到达，显式重放可能继续原授权保存。" : "原材料请求已保留；刷新或切换范围不会自动派发。"}</p><div className={styles.row}><Button disabled={disabled || !!material || !!prepared} onClick={() => void run(local.pending!)}>{local.pending.stage === "execute" ? "重放并核对同一原提交" : "继续核对原请求"}</Button>{local.pending.stage !== "execute" && <Button variant="outline" disabled={disabled} onClick={() => { if (save({ ...local, pending: null })) { setMaterial(null); setPrepared(null); } }}>取消本次核对</Button>}</div></section> : <Button disabled={!editable || !parsed || !canDecide || !!local.receipt} onClick={start}>读取并核对本次材料</Button>}
      {cursor && <Button variant="outline" disabled={disabled || !!local.pending} onClick={() => void more()}>读取更多固定包</Button>}
    </>}
    <dialog ref={dialog} className={styles.dialog} onCancel={() => { setMaterial(null); setPrepared(null); }}>{shown && <div className={styles.stack}><h3>{local.operation === releaseOperations[0] ? "核对固定内容，本人保存" : "核对真实范围，具名一次决定"}</h3><FixedContent plan={shown.candidate}/><p className="subtle">以下为固定包整体两专业检查。</p><ReleaseAssessmentReading assessments={shown.assessments}/>{mpRecord(shown.candidate.assessment) && <section className={styles.card}><h4>本次{names[shown.candidate.discipline as keyof typeof names]}选定范围：{states[shown.candidate.assessment.state as keyof typeof states] ?? "未知"}</h4>{Array.isArray(shown.candidate.assessment.checks) && shown.candidate.assessment.checks.map((v, i) => <Diagnostic key={i} value={v}/>)}</section>}{shown.diagnostics.map((v, i) => <Diagnostic key={i} value={v}/>)}{local.pending && local.operation !== releaseOperations[0] && !releaseAuthorityReady(shown.authority, local.pending.command, scope) && <div><p>本人的本次专业授权或资格尚未明确，不能作出具名决定。</p>{Array.isArray(shown.authority.reason_codes) && shown.authority.reason_codes.map((v, i) => <Diagnostic key={i} value={v}/>)}</div>}<p>包内容和专业检查不代表客户承认、外部接收或实际生效。</p><div className={styles.row}><Button disabled={disabled || (local.operation !== releaseOperations[0] && !prepared)} onClick={confirm}>{local.operation === releaseOperations[0] ? "本人保存固定包" : "本人具名确认决定"}</Button><Button variant="outline" disabled={busy} onClick={() => { setMaterial(null); setPrepared(null); }}>返回核对</Button></div></div>}</dialog>
  </section>;
}
