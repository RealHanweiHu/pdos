"use client";

import { useEffect, useRef, useState } from "react";
import { ConnectedSkillQualification } from "./skill-qualification";
import { Button } from "@/components/ui/button";
import { matchSkillReceipt, parseSkillPending, skillPendingKey, skillTitle, type AgentSkill, type SkillCommand, type SkillPreview, type SkillReading, type SkillReceipt } from "@/lib/agent-skills";
import { proofClockCurrent } from "@/lib/proof-clock";
import type { WorkspaceTransport } from "@/lib/workspace-api";

export function ConnectedAgentSkills({ api, principalId, categoryId }: { api: WorkspaceTransport; principalId: string; categoryId: string }) {
  const epoch = useRef(0), locked = useRef(false), key = skillPendingKey(principalId, categoryId);
  const reviewFocus = useRef<HTMLElement>(null);
  const noticeFocus = useRef<HTMLParagraphElement>(null);
  const [reading, setReading] = useState<SkillReading | null>(null);
  const [preview, setPreview] = useState<SkillPreview | null>(null);
  const [pending, setPending] = useState<SkillCommand | null>(null);
  const [busy, setBusy] = useState(true), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [broken, setBroken] = useState(false);
  useEffect(() => { if (preview || pending) reviewFocus.current?.focus(); }, [preview, pending]);
  useEffect(() => { if (notice) noticeFocus.current?.focus(); }, [notice]);

  async function load(current: number) {
    const value = await api<SkillReading>("v1/agent-skills");
    if (epoch.current === current) setReading(value);
    return value;
  }
  function accept(original: SkillCommand, receipt: SkillReceipt, current: number) {
    if (!matchSkillReceipt(receipt, original, principalId, categoryId)) throw new Error("回执与原技能请求不一致，请保留原请求继续核对。");
    if (epoch.current !== current) return;
    setPending(null); setPreview(null);
    setNotice(`${skillTitle(original.payload.skill_key)}已${original.payload.enabled ? "启用" : "停用"} · 第 ${receipt.subject_revision} 版 · 回执 ${receipt.id}`);
    try { localStorage.removeItem(key); }
    catch { setError("已取得原回执，本地恢复记录未清除，重新打开时会再次只读核对。"); }
  }
  useEffect(() => {
    const current = ++epoch.current;
    locked.current = true;
    async function open() {
      try {
        const raw = localStorage.getItem(key);
        if (raw) {
          let original: SkillCommand;
          try { original = parseSkillPending(raw, categoryId); }
          catch (failure) { setBroken(true); throw failure; }
          if (epoch.current !== current) return;
          setPending(original);
          const result = await api<{ receipt: SkillReceipt | null }>("v1/agent-skills/recover", original);
          if (result.receipt) accept(original, result.receipt, current);
        }
      } catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
      try { await load(current); }
      catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
      finally { if (epoch.current === current) { locked.current = false; setBusy(false); } }
    }
    void open();
    return () => { epoch.current = current + 1; };
    // A scope-owned component remounts on person/category changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, key, categoryId]);

  async function run(action: (current: number) => Promise<void>) {
    if (locked.current) return;
    const current = epoch.current;
    locked.current = true; setBusy(true); setError("");
    try { await action(current); }
    catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
    finally { if (epoch.current === current) { locked.current = false; setBusy(false); } }
  }
  function prepare(item: AgentSkill, enabled: boolean) {
    void run(async current => {
      const value = await load(current), actual = value.items.find(row => row.skill_key === item.skill_key);
      if (!value.can_edit || !actual) throw new Error("当前身份或技能配置已变化，请刷新核对。");
      if (actual.enabled === enabled) { if (epoch.current === current) setNotice("当前已是所选状态，无需重复办理。"); return; }
      const result = await api<SkillPreview>("v1/commands/preview", {
        command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), category_id: categoryId,
        product_id: null, operation: "ai.skill.enable", expected_revision: value.category_revision,
        source_read_set: [], payload: { skill_key: actual.skill_key, expected_revision: actual.revision,
          enabled, skill_version: actual.skill_version, skill_digest: actual.skill_digest },
      });
      if (epoch.current === current) { setPreview(result); setNotice(""); }
    });
  }
  async function save(original: SkillCommand, current: number) {
    localStorage.setItem(key, JSON.stringify(original));
    if (epoch.current === current) { setPending(original); setPreview(null); }
    let receipt: SkillReceipt;
    try { receipt = await api<SkillReceipt>("v1/commands", original); }
    catch (failure) {
      const status = (failure as { status?: number }).status;
      if (epoch.current === current && status !== undefined && status >= 400 && status < 500) {
        localStorage.removeItem(key); setPending(null);
      }
      throw failure;
    }
    accept(original, receipt, current);
    try { await load(current); }
    catch { if (epoch.current === current) setError("已取得技能变更回执，当前列表读取失败，请刷新。"); }
  }
  const disabled = busy || !reading?.can_edit || !!preview || !!pending || broken;
  return <><section aria-label="租户技能包" className="space-y-4 rounded-lg border border-border p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">租户技能包</h2><Button variant="outline" disabled={busy} onClick={() => void run(async current => { await load(current); })}>刷新技能状态</Button></div>
    <p className="text-sm text-muted-foreground">技能启用状态在当前租户所有品类共用，由管理员核对后一次确认。启用只开放该能力，不授予自动写入资格；实际调用仍核对当前权限、协议、资格和预算。</p>
    {error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}
    {notice && <p ref={noticeFocus} tabIndex={-1} role="status" className="break-all text-sm">{notice}</p>}
    {busy && <p role="status" className="text-sm">正在核对技能状态与回执…</p>}
    {reading && !reading.can_edit && <p className="text-sm text-muted-foreground">当前可读取；启用或停用须由有当前品类写入权限的租户管理员办理。</p>}
    {reading && <ul className="grid gap-3 lg:grid-cols-2">{reading.items.map(item => <li key={item.skill_key} className="space-y-2 rounded-lg border border-border p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="break-all font-medium">{skillTitle(item.skill_key)}</h3><span>{item.enabled ? "已启用" : "未启用"}</span></div>
      <p className="break-words text-muted-foreground">{item.purpose}</p><p className="break-all">配置 {item.skill_version ?? "已移除"} · 状态第 {item.revision} 版</p>
      <p className="text-muted-foreground">{item.qualification_record === "recorded" ? "已有审阅记录，实际 T0 资格由运行核对。" : item.qualification_record === "revoked" ? "T0 审阅资格已撤销。" : "尚无 T0 审阅记录。"}</p>
      <details><summary className="cursor-pointer">查看领域动作与回执</summary><div className="mt-2 space-y-1 break-all text-xs"><p>技能标识：{item.skill_key}</p>{item.operations.map(operation => <p key={operation}>{operation}</p>)}<p>最近回执：{item.receipt_id ?? "尚无变更回执"}</p></div></details>
      <Button variant={item.enabled ? "outline" : "default"} disabled={disabled || !item.available && !item.enabled} aria-label={`${item.enabled ? "停用" : "启用"}${skillTitle(item.skill_key)}`} onClick={() => prepare(item, !item.enabled)}>{item.enabled ? "停用" : "启用"}</Button>
    </li>)}</ul>}
    {preview && <section ref={reviewFocus} tabIndex={-1} aria-label="确认技能状态变更" className="space-y-3 rounded-lg border border-primary/40 p-3 text-sm">
      <h3 className="font-medium">确认{preview.review.enabled ? "启用" : "停用"}{skillTitle(preview.review.skill_key)}</h3>
      <p className="break-words">配置 {preview.review.skill_version ?? "已移除"} · 状态第 {preview.review.next_revision} 版。适用于当前租户的所有品类，既有审阅记录保持原样。</p>
      <div className="flex flex-wrap gap-2"><Button disabled={busy || !reading?.can_edit || !proofClockCurrent("T1", preview.expires_at)} onClick={() => void run(current => save(preview.command, current))}>确认{preview.review.enabled ? "启用" : "停用"}此技能</Button><Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>返回</Button></div>
    </section>}
    {pending && <section ref={reviewFocus} tabIndex={-1} aria-label="恢复原技能请求" className="space-y-3 rounded-lg border border-primary/40 p-3 text-sm">
      <p className="font-medium">{skillTitle(pending.payload.skill_key)}的{pending.payload.enabled ? "启用" : "停用"}结果待核对</p><p>重新打开先查询原回执；手动核对仍未取得时，沿用同一份已确认请求重试。确认已过期则重新预览。</p>
      <Button disabled={busy} onClick={() => void run(async current => {
        const result = await api<{ receipt: SkillReceipt | null }>("v1/agent-skills/recover", pending);
        if (result.receipt) { accept(pending, result.receipt, current); await load(current); }
        else { const value = await load(current); if (!value.can_edit) throw new Error("当前已无技能变更权限，请先核对原回执。"); await save(pending, current); }
      })}>核对并重试原技能请求</Button>
    </section>}
    {broken && <Button variant="outline" className="h-auto whitespace-normal" disabled={busy || !reading} onClick={() => { try { localStorage.removeItem(key); setBroken(false); setError(""); } catch { setError("本地恢复记录暂时无法移除。"); } }}>已核对当前状态，移除损坏的恢复记录</Button>}
  </section>
    {reading && <ConnectedSkillQualification api={api} principalId={principalId} categoryId={categoryId} catalog={reading} onUpdated={() => load(epoch.current)} />}
  </>;
}
