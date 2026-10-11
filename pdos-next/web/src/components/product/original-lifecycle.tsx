"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowClockwise, Archive, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import { Button } from "@/components/ui/button";
import { awareTimestamp, dispositionNames, intentStateNames, isRecord, lifecycleActionNames, lifecycleCommand, lifecycleFailure, lifecycleParseNames, lifecycleReason, lifecycleScope, lifecycleTime, lifecycleUploadNames, normalizeInventory, validLifecycleCandidate, validLifecyclePreview, validLifecycleReceipt, type LifecycleAction, type LifecycleCandidate, type LifecycleCommand, type LifecycleInventory, type LifecycleItem, type LifecyclePending, type LifecyclePreview } from "@/lib/original-lifecycle";

type Props = { productId: string; productRevision: number; onCommitted: () => Promise<void>; api: WorkspaceTransport };
type Selection = { itemId: string; action: LifecycleAction | "cancel" | "protection" | "abandon"; intentId?: string };
type PreviewState = { value: LifecyclePreview; item: LifecycleItem; scope: string };
const fieldNames: Record<string, string> = {
  action: "本次动作", status: "意图状态", state: "意图状态", revision: "当前版本", object_version: "固定字节版本", lifecycle_revision: "保护事实版本", protection_revision: "人工保留事实版本",
  registered: "是否已登记", manual_hold: "人工暂缓处理", retention_until: "保留至", reasons: "当前保护依据", eligible: "服务器候选结论", not_before: "最早允许时点", expires_at: "候选有效至", captured_at: "事实核对时点",
  reason: "本次具名原因", disposition: "字节访问位置", upload_state: "上传状态", parse_state: "解析状态", reference_count: "当前引用数量", formal_history: "是否涉及正式历史", coverage_complete: "完整引用范围已核实",
  policy_version: "当前保留政策版本", physical_effect_applied: "本次预览是否已执行字节动作", attempted: "是否已尝试执行", size_bytes: "原件字节数", media_type: "原件格式", title: "原件标题", filename: "文件名",
  upload_attempt_revision: "上传登记版本", registration_state: "登记状态", byte_status: "字节核对状态", upload_terminal_at: "上传终态时点", pending_intent_id: "待核对意图", object_id: "固定原件", id: "固定原件与上传登记", intent_id: "固定意图", candidate_id: "固定候选", attempt_id: "固定上传登记", upload_attempt_id: "固定上传登记",
};
const hiddenReviewFields = new Set(["digest", "content_sha256", "policy_digest", "inventory_revision", "reference_read_version", "storage_key", "server_storage_key", "confirmation_token"]);
function ReviewFields({ value, item, field = "" }: { value: unknown; item: LifecycleItem; field?: string }) {
  if (value === null || value === undefined) return <span>尚未核实 · 保持保护</span>;
  if (Array.isArray(value)) return value.length ? <ul className="space-y-1">{value.map((entry, index) => <li key={index}><ReviewFields value={entry} item={item} field={field}/></li>)}</ul> : <span>服务器未列出此项</span>;
  if (isRecord(value)) return <dl className="space-y-3">{Object.entries(value).filter(([key]) => !hiddenReviewFields.has(key) && Object.hasOwn(fieldNames, key)).map(([key, entry]) => <div key={key}><dt className="subtle">{fieldNames[key]}</dt><dd className="mt-1 whitespace-pre-wrap [overflow-wrap:anywhere]"><ReviewFields value={entry} item={item} field={key}/></dd></div>)}</dl>;
  if (typeof value === "boolean") {
    const names: Record<string, [string, string]> = { registered: ["尚未登记，继续按真实保护事实核对", "已登记 · 受保护"], manual_hold: ["已具名核对无暂缓要求", "暂缓处理 · 保持保护"], eligible: ["当前候选不适用", "候选符合当前服务器规则，仍须一次确认"], physical_effect_applied: ["未执行；保存意图后另行核对实际结果", "服务器报告已执行，仍以实际核对为准"], coverage_complete: ["范围未完整核实 · 保持保护", "本次完整范围已核实"], formal_history: ["本次核对未发现正式历史", "涉及正式历史 · 保持保护"], attempted: ["尚未尝试", "已有执行尝试，不能盲目重发"] };
    return <span>{names[field]?.[value ? 1 : 0] ?? (value ? "是" : "否")}</span>;
  }
  if (["object_id", "id", "candidate_id", "intent_id", "attempt_id", "upload_attempt_id", "pending_intent_id"].includes(field)) return <span>{field === "object_id" || field === "id" ? item.title : "已绑定本次原件的固定记录（系统核验）"}</span>;
  if (typeof value === "string") {
    if (field === "reasons") return <span>{lifecycleReason(value)}</span>;
    if (["retention_until", "not_before", "expires_at", "captured_at", "upload_terminal_at"].includes(field)) return <span>{lifecycleTime(value)}<span className="subtle block">{value}</span></span>;
    if (field === "action") return <span>{lifecycleActionNames[value] ?? "动作待核对"}</span>;
    if (field === "state" || field === "status") return <span>{value === "reserved" ? "上传登记保留 · 尚未完成" : intentStateNames[value] ?? lifecycleUploadNames[value] ?? "状态待核对"}</span>;
    if (field === "disposition") return <span>{dispositionNames[value] ?? dispositionNames.unknown}</span>;
    if (field === "upload_state") return <span>{lifecycleUploadNames[value] ?? lifecycleUploadNames.unknown}</span>;
    if (field === "parse_state") return <span>{lifecycleParseNames[value] ?? lifecycleParseNames.unknown}</span>;
    if (field === "registration_state" || field === "byte_status") return <span>{statusLabel(value)}</span>;
    return <span>{value}</span>;
  }
  return <span>{String(value)}</span>;
}
function statusLabel(value: string): string { return ({ registered: "已登记", unregistered: "尚未登记", unknown: "尚未知", intact: "已核实字节完整 · 扫描安全另行核对", corrupt: "字节校验不符 · 不可视为完整", present: "已核实字节存在", verified: "本次字节已核实", missing: "本次未取得字节 · 不推定删除", available: "本次字节可核对", unavailable: "本次字节核对不可用", written: "字节写入已记", inaccessible: "当前位置不可访问", active: "正常访问位置", quarantined: "隔离访问位置", prepared: "登记准备已记", bytes_written: "字节写入已记", aborted: "上传终止已记", not_registered: "尚未登记" } as Record<string, string>)[value] ?? "状态待核对"; }

export function OriginalLifecycle(props: Props) { return <LifecyclePanel key={props.productId} {...props}/>; }
function LifecyclePanel({ productId, productRevision, onCommitted, api }: Props) {
  const [inventory, setInventory] = useState<LifecycleInventory | null>(null), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [selection, setSelection] = useState<Selection | null>(null), [reason, setReason] = useState(""), [hold, setHold] = useState("unknown"), [retention, setRetention] = useState("");
  const [candidate, setCandidate] = useState<{ value: LifecycleCandidate; scope: string } | null>(null), [preview, setPreview] = useState<PreviewState | null>(null), [pending, setPending] = useState<LifecyclePending | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const lock = useRef(false), alive = useRef(true), requestScope = useRef(`${productId}:${productRevision}`), pendingRef = useRef<LifecyclePending | null>(null), dialog = useRef<HTMLDialogElement>(null), trigger = useRef<HTMLElement | null>(null);
  const selected = inventory?.items.find(item => item.id === selection?.itemId), selectedIntent = selected?.intents.find(intent => intent.id === selection?.intentId);
  const previewItem = inventory?.items.find(item => item.id === preview?.item.id);
  const currentPreview = preview && previewItem && preview.scope === lifecycleScope(productId, productRevision, previewItem) ? preview : null;
  const currentCandidate = candidate && selected && candidate.scope === lifecycleScope(productId, productRevision, selected) ? candidate.value : null;
  const editing = !loading && !busy && !pending && !currentPreview && inventory !== null;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    requestScope.current = `${productId}:${productRevision}`;
    const scope = requestScope.current; let active = true;
    lock.current = false; pendingRef.current = null;
    void Promise.resolve().then(() => { if (active && alive.current) { setLoading(true); setBusy(false); setInventory(null); setSelection(null); setCandidate(null); setPreview(null); setPending(null); setReason(""); setHold("unknown"); setRetention(""); } });
    api<unknown>(`v1/products/${productId}/original-lifecycle`).then(value => { const result = normalizeInventory(value); if (active && alive.current && requestScope.current === scope) { setInventory(result); setError(""); } }).catch(failure => { if (active && alive.current) setError(lifecycleFailure(failure).message); }).finally(() => { if (active && alive.current) setLoading(false); });
    return () => { active = false; };
  }, [api, productId, productRevision]);
  useEffect(() => { if (currentPreview) { if (!dialog.current?.open) dialog.current?.showModal(); } else { dialog.current?.close(); if (preview) void Promise.resolve().then(() => { if (alive.current) { setPreview(null); setNotice("库存、保护事实或型号范围已变化；旧预览已废弃，请重新核对。"); } }); } }, [currentPreview, preview]);
  function waiting(value: LifecyclePending | null) { pendingRef.current = value; setPending(value); }
  function closePreview() { if (lock.current || pendingRef.current) return; setPreview(null); dialog.current?.close(); trigger.current?.focus(); }
  async function readInventory() { const scope = `${productId}:${productRevision}`, result = normalizeInventory(await api<unknown>(`v1/products/${productId}/original-lifecycle`)); if (alive.current && requestScope.current === scope) setInventory(result); }
  async function refresh() { if (lock.current) return; lock.current = true; setBusy(true); setError(""); try { await readInventory(); } catch (failure) { if (alive.current) { setInventory(null); setPreview(null); setCandidate(null); setError(lifecycleFailure(failure).message); } } finally { lock.current = false; if (alive.current) setBusy(false); } }
  function choose(item: LifecycleItem, action: Selection["action"], intentId?: string) { if (!editing) return; setSelection({ itemId: item.id, action, intentId }); setReason(""); setCandidate(null); setError(""); setNotice(""); setHold("unknown"); setRetention(item.retention_until ?? ""); }
  async function perform(make: () => LifecyclePending, element?: HTMLElement) {
    if (lock.current) return; lock.current = true; setBusy(true); setError(""); setNotice(""); if (element) trigger.current = element;
    const identity = requestScope.current; let attempted = false, committed = false;
    try {
      const request = make(), item = inventory?.items.find(row => row.id === request.itemId); if (!item) throw new Error("尚未取得当前可读库存，请先刷新核对。");
      if (request.scope !== lifecycleScope(productId, productRevision, item) && pendingRef.current !== request) throw new Error("库存或范围已变化，请重新核对当前事实。");
      waiting(request); attempted = true;
      if (request.stage === "candidate") {
        const result = await api<unknown>(`v1/products/${productId}/original-lifecycle/${item.id}/candidate`, { action: request.action });
        if (!validLifecycleCandidate(result, item, request.action)) throw new Error("尚未取得完整且绑定本原件的候选，请按原请求核对。");
        if (!alive.current || identity !== requestScope.current) return; waiting(null); setCandidate({ value: result, scope: request.scope });
      } else if (request.stage === "preview") {
        const result = await api<unknown>("v1/commands/preview", request.command);
        if (!validLifecyclePreview(result, request.command, item)) throw new Error("尚未取得完整且绑定原请求的实质预览，请按原请求核对。");
        if (!alive.current || identity !== requestScope.current) return; waiting(null); setPreview({ value: result, item, scope: request.scope });
      } else if (request.stage === "execute") {
        const receipt = await api<unknown>("v1/commands", request.command); if (!validLifecycleReceipt(receipt, request.command, item)) throw new Error("尚未完整核对操作回执，请保留原请求。");
        committed = true; if (!alive.current || identity !== requestScope.current) return;
        waiting(null); setPreview(null); dialog.current?.close(); setSelection(null); setCandidate(null); setReason("");
        setNotice(request.command.operation === "evidence.lifecycle.protection.record" ? "人工保留事实已记录；最小保留政策继续生效，其他保护事实仍分别核对。" : request.command.operation === "evidence.lifecycle.upload.abandon" ? "未完成上传的具名终止已记录。字节保留与登记事实另行核对，未执行删除。" : request.command.operation === "evidence.lifecycle.cancel" ? "尚未执行的意图已取消；原件字节未因此删除。" : "生命周期意图已登记，请读取实际动作结果；此回执不等于字节已隔离或已恢复。");
        await readInventory(); await onCommitted();
      } else if (request.stage === "reconcile") {
        await api<unknown>(`v1/products/${productId}/original-lifecycle/intents/${request.intentId}/reconcile`, {});
        committed = true; if (!alive.current || identity !== requestScope.current) return; waiting(null); setNotice("已核对原意图；只读取实际动作结果，没有再次发送隔离或恢复。以刷新后的状态为准。"); await readInventory(); await onCommitted();
      }
    } catch (failure) {
      if (!alive.current || identity !== requestScope.current) return;
      if (committed) setError("操作回执已取得，但最新库存暂未取得。请刷新核对，不必重新提交已登记操作。");
      else if (!attempted) setError(failure instanceof Error ? failure.message : "请核对填写内容与当前库存。");
      else { const failed = lifecycleFailure(failure); setError(failed.message); if ([400, 401, 403, 404, 409, 410, 422].includes(failed.status ?? 0)) { waiting(null); setPreview(null); setCandidate(null); if (failed.status === 401 || failed.status === 403) setInventory(null); } else if (pendingRef.current?.stage === "execute") { setPreview(null); dialog.current?.close(); } }
    } finally { if (identity === requestScope.current) { lock.current = false; if (alive.current) setBusy(false); } }
  }
  function requestCandidate() { if (!selected || !selection || !["quarantine", "restore"].includes(selection.action)) return; void perform(() => ({ stage: "candidate", itemId: selected.id, action: selection.action as LifecycleAction, scope: lifecycleScope(productId, productRevision, selected) })); }
  function prepare(element: HTMLElement) { void perform(() => {
    if (!selected || !selection) throw new Error("请选择当前可读原件。");
    let command: LifecycleCommand;
    const make = (operation: LifecycleCommand["operation"], fields: Parameters<typeof lifecycleCommand>[4]) => lifecycleCommand(productId, productRevision, selected, operation, fields, reason, crypto.randomUUID(), crypto.randomUUID());
    if (selection.action === "quarantine" || selection.action === "restore") {
      if (!currentCandidate?.eligible || currentCandidate.not_before && Date.parse(currentCandidate.not_before) > Date.now()) throw new Error("当前候选不适用，请先核对新的服务器候选。");
      command = make(`evidence.lifecycle.${selection.action}`, { candidate_id: currentCandidate.candidate_id, digest: currentCandidate.digest });
    } else if (selection.action === "cancel") {
      if (!selectedIntent?.can_cancel) throw new Error("服务器当前不允许取消此意图。");
      command = make("evidence.lifecycle.cancel", { intent_id: selectedIntent.id, expected_revision: selectedIntent.revision });
    } else if (selection.action === "protection") {
      if (!["hold", "no_hold"].includes(hold)) throw new Error("请明确选择有暂缓要求或已核对无暂缓要求，未知不能默认取消保留。");
      if (!awareTimestamp(retention.trim())) throw new Error("请填写含时区的完整保留时点，例如 2026-10-10T17:00:00-07:00。");
      command = make("evidence.lifecycle.protection.record", { object_id: selected.id, expected_revision: selected.revision, manual_hold: hold === "hold", retention_until: retention.trim() });
    } else {
      if (!selected.upload_attempt_id || !selected.upload_attempt_revision) throw new Error("上传登记与版本尚未知，不能终止。");
      command = make("evidence.lifecycle.upload.abandon", { object_id: selected.id, expected_revision: selected.upload_attempt_revision });
    }
    return { stage: "preview", command, itemId: selected.id, scope: lifecycleScope(productId, productRevision, selected) };
  }, element); }
  return <section className="panel mb-6 min-w-0 [&_*]:min-w-0">
    <div className="flex flex-wrap items-start justify-between gap-3"><h2 className="flex items-center gap-2 font-semibold"><Archive/>原件保留与访问位置</h2><Button variant="outline" size="sm" disabled={busy || loading} onClick={() => void refresh()}><ArrowClockwise/>刷新库存</Button></div>
    <p className="subtle my-3">已登记原件持续受保护，解析失败不等于孤儿。隔离只调整访问位置，字节与历史仍保留；恢复访问位置也不授予扫描通过、来源有效或下载权限。本页不提供物理删除。</p>
    {loading && <p role="status" className="text-sm">正在读取当前原件与保护事实…</p>}{error && <p role="alert" className="my-3 text-sm text-destructive [overflow-wrap:anywhere]">{error}</p>}{notice && <p role="status" className="my-3 text-sm [overflow-wrap:anywhere]">{notice}</p>}
    {pending && <div className="my-4 space-y-3 rounded-lg border border-primary p-3"><p className="text-sm">原{pending.stage === "candidate" ? "候选核对" : pending.stage === "preview" ? "实质预览" : pending.stage === "reconcile" ? "意图观察" : "操作提交"}的结果待核对。本页保留同一请求；核对前不新增动作，不盲目重发字节操作。请保留此页面。</p><Button variant="outline" disabled={busy} onClick={() => void perform(() => pending)}>核对原请求</Button></div>}
    {inventory && <>
      <div className="my-4 space-y-2 rounded-lg border border-border p-3 text-sm">
        {!inventory.coverage_complete && <p className="flex items-start gap-2"><WarningCircle className="mt-0.5 shrink-0 text-primary"/><span>完整引用范围尚未证实；缺少引用记录不能当作零引用，也不能据此推定孤儿。</span></p>}
        {inventory.policy ? <><p>保留政策：{inventory.policy.version}。失败或终止上传至少保护 {duration(inventory.policy.failed_upload_grace_seconds)}；隔离后至少保护 {duration(inventory.policy.quarantine_grace_seconds)}，实际还须核对人工保留、引用与正式历史。</p><p className="subtle">{inventory.policy.profile === "local-synthetic" ? "当前为本地合成验证配置，未授予生产处置资格。" : "当前为服务器配置的保留口径；配置记录不替代生产资格认定。"}</p></> : <p>保留政策尚未取得；当前保持保护，不以页面默认值替代。</p>}
      </div>
      <div className="space-y-4">{inventory.items.map(item => <article key={item.id} className="space-y-4 rounded-lg border border-border p-3 sm:p-4">
        <div><h3 className="font-medium [overflow-wrap:anywhere]">{item.title}</h3><p className="subtle mt-1 [overflow-wrap:anywhere]">{item.filename} · 保护事实 v{item.revision}</p></div>
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <Fact title="登记与保护" value={item.registered === true ? "已登记 · 原件受保护" : item.registered === false ? "尚未登记 · 仍须核对其他保护事实" : "登记未知 · 保持保护"}/>
          <Fact title="上传状态" value={lifecycleUploadNames[item.upload_state] ?? lifecycleUploadNames.unknown}/><Fact title="文字解析" value={lifecycleParseNames[item.parse_state] ?? lifecycleParseNames.unknown}/>
          <Fact title="字节访问位置" value={dispositionNames[item.disposition] ?? dispositionNames.unknown}/><Fact title="字节核对" value={statusLabel(item.byte_status)}/>
          <Fact title="人工暂缓处理" value={item.manual_hold === true ? "暂缓处理 · 保持保护" : item.manual_hold === false ? "已具名核对无暂缓要求" : "尚未核实 · 保持保护"}/>
          <Fact title="保留至" value={lifecycleTime(item.retention_until)}/><Fact title="业务引用" value={item.reference_count === null ? "引用数量未知 · 保持保护" : `${item.reference_count} 处已记录引用${!item.coverage_complete ? " · 完整范围未核实" : " · 本次范围已核实"}`}/>
          <Fact title="正式历史" value={item.formal_history === null ? "尚未核实 · 保持保护" : item.formal_history ? "涉及正式历史 · 保持保护" : "本次核对未发现正式历史"}/>
        </dl>
        {item.reasons.length > 0 && <ul className="space-y-1 text-sm">{[...new Set(item.reasons)].map(entry => <li key={entry}>{lifecycleReason(entry)}</li>)}</ul>}
        {item.pending_intent_id && <p className="text-sm text-primary">已有待核对意图；先观察原意图，不新增隔离或恢复。</p>}
        <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={!editing || !item.can_record_protection} onClick={() => choose(item, "protection")}><ShieldCheck/>具名核对保留</Button><Button variant="outline" disabled={!editing || !item.can_quarantine} onClick={() => choose(item, "quarantine")}>核对隔离候选</Button><Button variant="outline" disabled={!editing || !item.can_restore} onClick={() => choose(item, "restore")}>核对恢复候选</Button>{item.upload_attempt_id && <Button variant="outline" disabled={!editing || !item.can_abandon_upload || !item.upload_attempt_revision} onClick={() => choose(item, "abandon")}>终止未完成上传 · 先核对</Button>}</div>
        {item.intents.length > 0 && <details><summary className="cursor-pointer text-sm font-medium">生命周期意图与实际结果（{item.intents.length}）</summary><div className="mt-3 space-y-3">{item.intents.map(intent => <div key={intent.id} className="space-y-2 rounded-lg border border-border p-3 text-sm"><p className="font-medium">{lifecycleActionNames[intent.action] ?? "生命周期动作"} · {intentStateNames[intent.state] ?? "实际状态待核对"}</p><p className="whitespace-pre-wrap [overflow-wrap:anywhere]">具名原因：{intent.reason || "尚未取得"}</p><p className="subtle">登记：{lifecycleTime(intent.created_at)} · 最近核对：{lifecycleTime(intent.updated_at)} · v{intent.revision}</p>{intent.recovery_required && <p className="text-primary">需要核对实际结果；未知不能当成已完成，也不能盲目重做。</p>}<div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" disabled={!editing || !intent.can_reconcile} onClick={() => void perform(() => ({ stage: "reconcile", itemId: item.id, intentId: intent.id, scope: lifecycleScope(productId, productRevision, item) }))}>只观察并核对原意图</Button><Button variant="outline" size="sm" disabled={!editing || !intent.can_cancel} onClick={() => choose(item, "cancel", intent.id)}>取消尚未执行意图 · 先核对</Button></div></div>)}</div></details>}
      </article>)}{inventory.items.length === 0 && <p className="subtle">当前没有可读取的库存记录。空列表不构成全库无原件或无引用证明。</p>}</div>
    </>}
    {selected && selection && <form className="mt-5 space-y-3 rounded-lg border border-border p-3 sm:p-4" onSubmit={event => { event.preventDefault(); prepare(event.currentTarget); }}><h3 className="font-semibold [overflow-wrap:anywhere]">{lifecycleActionNames[selection.action]}：{selected.title}</h3><fieldset disabled={!editing} className="space-y-3">
      {selection.action === "protection" && <><label>人工暂缓处理<select required value={hold} onChange={event => setHold(event.target.value)}><option value="unknown">尚未核对 · 请明确选择</option><option value="hold">有暂缓要求，保持保留</option><option value="no_hold">已具名核对，无人工暂缓要求</option></select></label><label>保留至（必须包含时区）<input required type="text" value={retention} maxLength={80} onChange={event => setRetention(event.target.value)} placeholder="2026-10-10T17:00:00-07:00"/><span className="subtle">填写完整日期、时间和时区偏移。输入更早日期也不能绕过服务器最小保留期与其他保护。</span></label></>}
      {selection.action === "abandon" && <p className="text-sm">仅终止尚未登记的未完成上传；服务器将核对迟到上传与当前登记事实。原件字节继续按保留政策保护，不执行删除。</p>}
      {selection.action === "cancel" && <p className="text-sm">仅取消从未尝试执行且服务器当前允许取消的意图，不撤销已执行动作。</p>}
      {(selection.action === "quarantine" || selection.action === "restore") && <div className="space-y-3"><p className="subtle">先取得当前库存、引用与保留政策绑定的服务器候选，再读取完整的一次确认预览。</p><Button type="button" variant="outline" onClick={requestCandidate}>读取{selection.action === "quarantine" ? "隔离" : "恢复"}候选</Button>{currentCandidate && <div className="space-y-2 rounded-lg border border-border p-3 text-sm"><p className="font-medium">{currentCandidate.eligible ? "服务器候选符合当前规则 · 尚未执行" : "当前候选不适用 · 保持保护"}</p>{currentCandidate.reasons.map(entry => <p key={entry}>{lifecycleReason(entry)}</p>)}<p>事实核对时点：{lifecycleTime(currentCandidate.captured_at)}</p>{currentCandidate.not_before && <p>最早允许时点：{lifecycleTime(currentCandidate.not_before)}</p>}<p className="subtle">政策版本：{currentCandidate.policy_version ?? selected.policy_version ?? "尚未取得"}</p></div>}</div>}
      <label>本次具名核对原因<textarea required minLength={selection.action === "abandon" ? 4 : 1} maxLength={2000} value={reason} onChange={event => setReason(event.target.value)}/>{selection.action === "abandon" && <span className="subtle">至少四字，说明为什么终止这次未完成上传。</span>}</label><div className="flex flex-wrap gap-2"><Button type="submit" disabled={(selection.action === "quarantine" || selection.action === "restore") && !currentCandidate?.eligible}>读取一次确认预览</Button><Button type="button" variant="outline" onClick={() => { setSelection(null); setCandidate(null); }}>取消准备</Button></div>
    </fieldset></form>}
    <dialog ref={dialog} aria-label="原件生命周期具名操作的一次确认" className="!w-[min(680px,calc(100vw-32px))] max-h-[90vh] overflow-auto" onCancel={event => { event.preventDefault(); if (!busy) closePreview(); }}>
      {currentPreview && <div className="min-w-0 space-y-4 [&_*]:min-w-0"><h3 className="text-lg font-semibold">一次确认：{currentPreview.item.title}</h3><p className="text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">{currentPreview.value.review.effect}</p><div className="grid gap-4 sm:grid-cols-2"><div className="rounded-lg border border-border p-3 text-sm"><h4 className="mb-3 font-semibold">当前固定事实</h4><ReviewFields value={currentPreview.value.review.before} item={currentPreview.item}/></div><div className="rounded-lg border border-border p-3 text-sm"><h4 className="mb-3 font-semibold">本次将记录</h4><ReviewFields value={currentPreview.value.review.after} item={currentPreview.item}/></div></div><p className="subtle">确认有效至 {lifecycleTime(currentPreview.value.expires_at)}。库存、引用、保留、权限或型号范围变化后，须重新核对。意图回执不等于实际字节动作成功。</p><div className="flex flex-wrap justify-end gap-2"><Button variant="outline" disabled={busy || !!pending} onClick={closePreview}>返回编辑</Button><Button disabled={busy || !!pending} onClick={() => { if (Date.parse(currentPreview.value.expires_at) <= Date.now()) { closePreview(); setError("预览已过期，请读取当前事实后重新核对。"); return; } void perform(() => ({ stage: "execute", command: currentPreview.value.command, itemId: currentPreview.item.id, scope: currentPreview.scope })); }}>确认本次具名记录</Button></div></div>}
    </dialog>
  </section>;
}
function Fact({ title, value }: { title: string; value: string }) { return <div><dt className="subtle">{title}</dt><dd className="mt-1 [overflow-wrap:anywhere]">{value}</dd></div>; }
function duration(seconds: number): string { return seconds >= 86400 && seconds % 86400 === 0 ? `${seconds / 86400} 天` : seconds >= 3600 && seconds % 3600 === 0 ? `${seconds / 3600} 小时` : seconds >= 60 && seconds % 60 === 0 ? `${seconds / 60} 分钟` : `${seconds} 秒`; }
