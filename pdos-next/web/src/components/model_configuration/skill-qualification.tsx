"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { skillTitle, type SkillReading } from "@/lib/agent-skills";
import { assessments, blankReview, dimensions, matchesQualificationReceipt, parseQualificationPending, qualificationPendingKey, severities, type CaseReference, type QualificationCommand, type QualificationPreview, type QualificationReading, type QualificationReceipt, type ReviewCase } from "@/lib/skill-qualification";
import { proofClockCurrent } from "@/lib/proof-clock";
import type { WorkspaceTransport } from "@/lib/workspace-api";

const states: Record<string, string> = { not_recorded: "尚无资格", revoked: "已撤销", paused: "发现严重错误，已暂停", stale: "版本已变化，须重新审阅", inactive: "当前停用", qualified: "当前版本已有试点资格" };
const fieldClass = "w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm";
export function ConnectedSkillQualification({ api, principalId, categoryId, catalog, onUpdated }: { api: WorkspaceTransport; principalId: string; categoryId: string; catalog: SkillReading; onUpdated: () => Promise<unknown> }) {
  const epoch = useRef(0), locked = useRef(false), focus = useRef<HTMLElement>(null);
  const key = qualificationPendingKey(principalId, categoryId);
  const [skill, setSkill] = useState(""), [reading, setReading] = useState<QualificationReading | null>(null);
  const [cases, setCases] = useState<ReviewCase[]>([blankReview()]), [attested, setAttested] = useState(false), [refs, setRefs] = useState<CaseReference[]>([]), [reason, setReason] = useState("");
  const [preview, setPreview] = useState<QualificationPreview | null>(null), [pending, setPending] = useState<QualificationCommand | null>(null);
  const [busy, setBusy] = useState(false), [broken, setBroken] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  useEffect(() => { if (preview || pending) focus.current?.focus(); }, [preview, pending]);
  async function load(selected: string, current: number, cursor?: string) {
    const result = await api<QualificationReading>(`v1/agent-skill-qualification?skill_key=${encodeURIComponent(selected)}${cursor ? `&cursor=${cursor}` : ""}`);
    if (epoch.current === current) setReading(previous => cursor && previous?.skill_key === selected ? { ...result, reviews: [...previous.reviews, ...result.reviews.filter(batch => !previous.reviews.some(old => old.id === batch.id))] } : result);
    return result;
  }
  function accept(original: QualificationCommand, receipt: QualificationReceipt, current: number) {
    if (!matchesQualificationReceipt(receipt, original, principalId, categoryId)) throw new Error("回执与原审阅请求不一致，请保留原请求继续核对。");
    if (epoch.current !== current) return;
    setPending(null); setPreview(null); setRefs([]); setAttested(false); setCases([blankReview()]); setReason("");
    setNotice(`${skillTitle(original.payload.skill_key)}${original.operation === "ai.skill.review.record" ? "案例审阅已保存" : original.payload.decision === "批准" ? "试点资格已具名批准" : "试点资格已撤销"} · 回执 ${receipt.id}`);
    try { localStorage.removeItem(key); } catch { setError("已取得回执，本地恢复记录未清除，再次打开将只读核对。"); }
  }
  useEffect(() => {
    const current = ++epoch.current;
    async function restore() {
      locked.current = true; setBusy(true);
      try {
        const raw = localStorage.getItem(key);
        if (!raw) return;
        let original: QualificationCommand;
        try { original = parseQualificationPending(raw, categoryId); } catch (failure) { setBroken(true); throw failure; }
        if (epoch.current !== current) return;
        setPending(original); setSkill(original.payload.skill_key);
        const result = await api<{ receipt: QualificationReceipt | null }>("v1/agent-skill-qualification/recover", original);
        if (result.receipt) accept(original, result.receipt, current);
        await load(original.payload.skill_key, current);
      } catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
      finally { if (epoch.current === current) { locked.current = false; setBusy(false); } }
    }
    void restore();
    return () => { epoch.current = current + 1; };
    // Scope-owned component remounts when the current person/category changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, key, categoryId]);
  async function run(action: (current: number) => Promise<void>) {
    if (locked.current) return;
    const current = epoch.current;
    locked.current = true; setBusy(true); setError("");
    try { await action(current); } catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
    finally { if (epoch.current === current) { locked.current = false; setBusy(false); } }
  }
  async function save(original: QualificationCommand, current: number) {
    localStorage.setItem(key, JSON.stringify(original));
    if (epoch.current === current) { setPending(original); setPreview(null); }
    let receipt: QualificationReceipt;
    try { receipt = await api<QualificationReceipt>("v1/commands", original); }
    catch (failure) {
      const status = (failure as { status?: number }).status;
      if (epoch.current === current && status !== undefined && status >= 400 && status < 500) { localStorage.removeItem(key); setPending(null); }
      throw failure;
    }
    accept(original, receipt, current);
    await Promise.all([load(original.payload.skill_key, current), onUpdated()]);
  }
  function prepare(operation: QualificationCommand["operation"], decision?: "批准" | "撤销") {
    void run(async current => {
      const actual = await load(skill, current);
      if (!actual.can_edit) throw new Error("当前已无办理权限，请核对当前身份。");
      const binding = { skill_key: skill, skill_digest: actual.skill_digest, tool_digest: actual.tool_digest, model_digest: actual.model_digest };
      const payload = operation === "ai.skill.review.record" ? { ...binding, cases, personally_reviewed: attested } : { skill_key: skill, expected_revision: actual.revision, decision, reason, case_refs: decision === "批准" ? refs : [], ...(decision === "批准" ? binding : {}) };
      const result = await api<QualificationPreview>("v1/commands/preview", { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), category_id: categoryId, product_id: null, operation, expected_revision: actual.category_revision, source_read_set: [], payload });
      if (epoch.current === current) { setPreview(result); setNotice(""); }
    });
  }
  const frozen = busy || !!pending || !!preview || broken, canEdit = !!reading?.can_edit && !frozen;
  const canReview = canEdit && !!reading?.skill_digest && !!reading.model_digest && reading.model_enabled;
  function changeCase(index: number, patch: Partial<ReviewCase>) { setCases(previous => previous.map((item, n) => n === index ? { ...item, ...patch } : item)); setAttested(false); }
  return <section aria-label="案例审阅与试点资格" className="space-y-4 rounded-lg border border-border p-4 sm:p-5">
    <h2 className="font-semibold">案例审阅与试点资格</h2>
    <p className="text-sm text-muted-foreground">本人审阅自有或合成案例后登记材料定位与结论。试点租户可选取 10–20 个不同案例，具名批准当前技能和模型的草稿自动写入资格。未知和问题如实保留，严重错误暂停 T0。</p>
    <label className="block space-y-1 text-sm"><span>选择审阅技能</span><select className={fieldClass} value={skill} disabled={frozen} onChange={event => { const value = event.target.value; setSkill(value); setReading(null); setRefs([]); setCases([blankReview()]); setAttested(false); setNotice(""); if (value) void run(current => load(value, current).then(() => undefined)); }}><option value="">请选择技能</option>{catalog.items.map(item => <option key={item.skill_key} value={item.skill_key}>{skillTitle(item.skill_key)}</option>)}</select></label>
    {error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}{notice && <p role="status" className="break-all text-sm">{notice}</p>}{busy && <p role="status" className="text-sm">正在核对审阅与资格…</p>}
    {skill && <Button variant="outline" disabled={frozen} onClick={() => void run(current => load(skill, current).then(() => undefined))}>刷新审阅与资格</Button>}
    {reading && <>
      <div className="space-y-2 rounded-lg bg-muted/40 p-3 text-sm"><p className="font-medium">{states[reading.qualification.state] ?? reading.qualification.state}</p><p className="break-all">技能 {reading.skill_version ?? "已移除"} · 模型 {reading.model_label ?? "未登记"} / {reading.model_version ?? "未登记"}</p><p>{reading.pilot ? "已登记试点租户" : "当前租户未登记为试点"} · {reading.enabled ? "技能已启用" : "技能未启用"} · 状态第 {reading.revision} 版</p>{reading.qualification.reviewed_by_name && <p>最近资格审阅人：{reading.qualification.reviewed_by_name} · {reading.qualification.case_count} 个案例</p>}<p>自动写入仍逐次核对当前权限、来源、协议及预算；正式批准与发布保留具名办理。</p></div>
      <details open className="space-y-3"><summary className="cursor-pointer font-medium text-sm">登记本人案例审阅</summary>
        {cases.map((item, index) => <fieldset key={index} disabled={!canReview} className="mt-3 space-y-3 rounded-lg border border-border p-3"><legend className="px-1 text-sm">案例 {index + 1}</legend>
          <div className="grid gap-3 sm:grid-cols-[1fr_10rem]"><label className="space-y-1 text-sm"><span>案例 {index + 1} 材料定位</span><input className={fieldClass} maxLength={1000} value={item.source_ref} onChange={event => changeCase(index, { source_ref: event.target.value })} placeholder="已审阅材料的名称、编号或位置" /></label><label className="space-y-1 text-sm"><span>案例 {index + 1} 材料类型</span><select className={fieldClass} value={item.material_kind} onChange={event => changeCase(index, { material_kind: event.target.value as ReviewCase["material_kind"] })}><option value="own">本人自有材料</option><option value="synthetic">合成案例</option></select></label></div>
          <label className="block space-y-1 text-sm"><span>案例 {index + 1} 审阅结论</span><textarea className={fieldClass} rows={2} maxLength={2000} value={item.conclusion} onChange={event => changeCase(index, { conclusion: event.target.value })} /></label>
          <label className="block space-y-1 text-sm"><span>案例 {index + 1} 错误程度</span><select className={fieldClass} value={item.severity} onChange={event => changeCase(index, { severity: event.target.value as ReviewCase["severity"] })}>{Object.entries(severities).map(([value, title]) => <option key={value} value={value}>{title}</option>)}</select></label>
          <details><summary className="cursor-pointer text-sm">六项审阅维度（默认尚未评价）</summary><div className="mt-3 grid gap-3 sm:grid-cols-2">{Object.entries(dimensions).map(([name, title]) => <label key={name} className="space-y-1 text-sm"><span>案例 {index + 1} {title}</span><select className={fieldClass} value={item.criteria[name as keyof typeof dimensions]} onChange={event => changeCase(index, { criteria: { ...item.criteria, [name]: event.target.value } })}>{Object.entries(assessments).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>)}</div></details>
          {cases.length > 1 && <Button variant="outline" onClick={() => { setCases(old => old.filter((_, n) => n !== index)); setAttested(false); }}>移除案例 {index + 1}</Button>}
        </fieldset>)}
        <Button variant="outline" disabled={!canReview || cases.length >= 20} onClick={() => { setCases(old => [...old, blankReview()]); setAttested(false); }}>添加一个案例</Button>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={attested} disabled={!canReview} onChange={event => setAttested(event.target.checked)} /><span>我已亲自审阅以上材料，并如实记录结论和未知项。</span></label>
        <Button disabled={!canReview || !attested || cases.some(item => !item.source_ref.trim() || !item.conclusion.trim())} onClick={() => prepare("ai.skill.review.record")}>预览保存本批审阅</Button>
      </details>
      <section aria-label="本人已登记审阅" className="space-y-3 text-sm"><h3 className="font-medium">本人已登记审阅 · 已选 {refs.length} / 20</h3>{!reading.reviews.length && <p className="text-muted-foreground">尚无本人登记记录。</p>}{reading.reviews.map(batch => <div key={batch.id} className="space-y-2 rounded-lg border border-border p-3"><p className="break-all text-xs text-muted-foreground">{batch.skill_version} · {batch.model_version} · {batch.current ? "当前版本" : "历史版本，须重新审阅"}</p>{batch.cases.map((item, index) => { const selected = refs.some(ref => ref.batch_id === batch.id && ref.index === index); return <label key={index} className="flex items-start gap-2 border-t border-border pt-2"><input type="checkbox" className="mt-1" checked={selected} disabled={!canEdit || !batch.current || item.severity === "critical" || !selected && refs.length >= 20} onChange={event => setRefs(old => event.target.checked ? [...old, { batch_id: batch.id, index }] : old.filter(ref => ref.batch_id !== batch.id || ref.index !== index))} /><span className="min-w-0 break-words"><span className="font-medium">{item.source_ref}</span><span className="block">{item.conclusion}</span><span className="block text-muted-foreground">{item.material_kind === "synthetic" ? "合成案例" : "自有材料"} · {severities[item.severity]}</span></span></label>; })}</div>)}{reading.next_cursor && <Button variant="outline" disabled={frozen} onClick={() => void run(current => load(skill, current, reading.next_cursor!).then(() => undefined))}>读取更早的本人审阅</Button>}</section>
      <label className="block space-y-1 text-sm"><span>本人资格决定理由</span><textarea className={fieldClass} rows={2} maxLength={4000} value={reason} disabled={!canEdit} onChange={event => setReason(event.target.value)} /></label>
      <div className="flex flex-wrap gap-2"><Button disabled={!canEdit || !reading.pilot || !reading.enabled || !reading.model_enabled || !reading.draft_operations.length || refs.length < 10 || !reason.trim()} onClick={() => prepare("ai.skill.qualify", "批准")}>预览具名批准试点资格</Button><Button variant="outline" disabled={!canEdit || !reading.qualification.reviewed_by_name || !reason.trim()} onClick={() => prepare("ai.skill.qualify", "撤销")}>预览撤销试点资格</Button></div>
    </>}
    {preview && <section ref={focus} tabIndex={-1} aria-label="确认审阅或资格决定" className="space-y-3 rounded-lg border border-primary/40 p-3 text-sm"><h3 className="font-medium">{preview.command.operation === "ai.skill.qualify" ? `具名${preview.review.decision}试点资格` : "确认本批案例审阅"} · {skillTitle(preview.review.skill_key)}</h3><p className="break-all">{preview.review.skill_version} · {preview.review.model_label} / {preview.review.model_version} · {preview.review.case_count} 个案例</p><p>{preview.review.effect}</p>{preview.review.reason && <p className="break-words">决定理由：{preview.review.reason}</p>}<details><summary className="cursor-pointer">核对案例材料与结论</summary><ul className="mt-2 space-y-2">{preview.review.cases?.map((item, index) => <li key={index} className="break-words">{item.source_ref}：{item.conclusion}（{severities[item.severity]}）</li>)}</ul></details><div className="flex flex-wrap gap-2"><Button disabled={busy || !reading?.can_edit || !proofClockCurrent(preview.write_tier ?? "T1", preview.expires_at)} onClick={() => void run(current => save(preview.command, current))}>{preview.command.operation === "ai.skill.qualify" ? `本人具名${preview.review.decision}` : "确认保存审阅"}</Button><Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>返回</Button></div></section>}
    {pending && <section ref={focus} tabIndex={-1} aria-label="恢复原审阅请求" className="space-y-3 rounded-lg border border-primary/40 p-3 text-sm"><p>原{pending.operation === "ai.skill.qualify" ? "资格决定" : "案例审阅"}结果待核对。重新打开先只读查询回执；只有本人点击才沿用原请求重试。</p><Button disabled={busy} onClick={() => void run(async current => { const result = await api<{ receipt: QualificationReceipt | null }>("v1/agent-skill-qualification/recover", pending); if (result.receipt) { accept(pending, result.receipt, current); await Promise.all([load(pending.payload.skill_key, current), onUpdated()]); } else { await load(pending.payload.skill_key, current); await save(pending, current); } })}>核对并重试原审阅请求</Button></section>}
    {broken && <Button variant="outline" disabled={busy} onClick={() => { localStorage.removeItem(key); setBroken(false); setError(""); }}>已核对当前状态，清除损坏的本地记录</Button>}
  </section>;
}
