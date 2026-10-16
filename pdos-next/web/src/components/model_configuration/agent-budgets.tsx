"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { budgetIntegerMax, budgetPendingKey, dollars, matchBudgetReceipt, microDollars, parseBudgetPending, validLimits, type AgentBudget, type BudgetCommand, type BudgetLimits, type BudgetPreview, type BudgetReading, type BudgetReceipt } from "@/lib/agent-budgets";
import { proofClockCurrent } from "@/lib/proof-clock";
import type { WorkspaceTransport } from "@/lib/workspace-api";

function Usage({ row }: { row: AgentBudget }) {
  return <div className="space-y-1 text-sm"><p>费用：已计 {dollars(row.spent_micro_usd)} · 占用 {dollars(row.held_micro_usd)} · 额度 {dollars(row.limit_micro_usd)} USD</p><p>调用 {row.calls} / {row.call_limit} 次</p><p>输入：已用 {row.used_input_tokens} · 占用 {row.held_input_tokens} / {row.input_token_limit} tokens</p><p>输出：已用 {row.used_output_tokens} · 占用 {row.held_output_tokens} / {row.output_token_limit} tokens</p></div>;
}

export function ConnectedAgentBudgets({ api, principalId, categoryId }: { api: WorkspaceTransport; principalId: string; categoryId: string }) {
  const prefix = useId(), epoch = useRef(0), locked = useRef(false), focus = useRef<HTMLElement>(null), noticeFocus = useRef<HTMLParagraphElement>(null);
  const key = budgetPendingKey(principalId, categoryId);
  const [reading, setReading] = useState<BudgetReading | null>(null), [preview, setPreview] = useState<BudgetPreview | null>(null);
  const [pending, setPending] = useState<BudgetCommand | null>(null), [busy, setBusy] = useState(true), [broken, setBroken] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [form, setForm] = useState({ amount: "", input: "", output: "", calls: "" });
  useEffect(() => { if (preview || pending) focus.current?.focus(); }, [preview, pending]);
  useEffect(() => { if (notice) noticeFocus.current?.focus(); }, [notice]);

  async function load(current: number, cursor?: string) {
    const value = await api<BudgetReading>(`v1/agent-budgets?page_size=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
    if (value.requester_id !== principalId) throw new Error("预算读取范围与当前身份不一致。");
    if (epoch.current === current) setReading(previous => cursor && previous ? { ...value, items: [...previous.items, ...value.items] } : value);
    return value;
  }
  function accept(original: BudgetCommand, receipt: BudgetReceipt, current: number) {
    if (!matchBudgetReceipt(receipt, original, principalId, categoryId)) throw new Error("回执与原预算请求不一致，请保留原请求继续核对。");
    if (epoch.current !== current) return;
    setPending(null); setPreview(null);
    setNotice(`${original.payload.action === "allocate" ? "新预算已建立" : "活动预算已停用"} · 回执 ${receipt.id}`);
    try { localStorage.removeItem(key); }
    catch { setError("已取得回执；本地恢复记录未清除，重新打开时会再次只读核对。"); }
  }
  useEffect(() => {
    const current = ++epoch.current; locked.current = true;
    async function open() {
      try {
        const raw = localStorage.getItem(key);
        if (raw) {
          let original: BudgetCommand;
          try { original = parseBudgetPending(raw, categoryId); }
          catch (failure) { setBroken(true); throw failure; }
          if (epoch.current !== current) return;
          setPending(original);
          const value = await api<{ receipt: BudgetReceipt | null }>("v1/agent-budgets/recover", original);
          if (value.receipt) accept(original, value.receipt, current);
        }
      } catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
      try { await load(current); }
      catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
      finally { if (epoch.current === current) { locked.current = false; setBusy(false); } }
    }
    void open();
    return () => { epoch.current = current + 1; };
    // The workspace remounts this component on person/category changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, key, categoryId]);
  async function run(action: (current: number) => Promise<void>) {
    if (locked.current) return;
    const current = epoch.current; locked.current = true; setBusy(true); setError("");
    try { await action(current); }
    catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
    finally { if (epoch.current === current) { locked.current = false; setBusy(false); } }
  }
  async function prepare(action: "allocate" | "stop", limits: BudgetLimits | null, current: number) {
    const value = await load(current);
    if (!value.can_edit) throw new Error("当前身份已无预算变更权限。");
    if (action === "stop" && !value.active_budgets.length) { if (epoch.current === current) setNotice("当前已没有活动预算。"); return; }
    const result = await api<BudgetPreview>("v1/commands/preview", { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(),
      category_id: categoryId, product_id: null, operation: "ai.budget.configure", expected_revision: value.category_revision, source_read_set: [],
      payload: { action, expected_active_digest: value.active_digest, limits } });
    if (epoch.current === current) { setPreview(result); setNotice(""); }
  }
  function allocate(event: FormEvent) {
    event.preventDefault();
    void run(async current => {
      const limits = { limit_micro_usd: microDollars(form.amount), input_token_limit: Number(form.input), output_token_limit: Number(form.output), call_limit: Number(form.calls) };
      if (!validLimits(limits)) throw new Error("请填写可记录的费用额度，以及正整数调用次数和 token 额度。");
      await prepare("allocate", limits, current);
    });
  }
  async function save(original: BudgetCommand, current: number) {
    localStorage.setItem(key, JSON.stringify(original));
    if (epoch.current === current) { setPending(original); setPreview(null); }
    let receipt: BudgetReceipt;
    try { receipt = await api<BudgetReceipt>("v1/commands", original); }
    catch (failure) {
      const status = (failure as { status?: number }).status;
      if (epoch.current === current && status !== undefined && status >= 400 && status < 500) { localStorage.removeItem(key); setPending(null); }
      throw failure;
    }
    accept(original, receipt, current);
    try { await load(current); }
    catch { if (epoch.current === current) setError("预算变更已取得回执，列表读取失败，请刷新。"); }
  }
  const disabled = busy || !reading?.can_edit || !!pending || !!preview || broken;
  return <section aria-label="我的模型预算" className="space-y-4 rounded-lg border border-border p-4 sm:p-5">
    <div className="flex flex-wrap justify-between gap-3"><h2 className="font-semibold">我的模型预算</h2><Button variant="outline" disabled={busy} onClick={() => void run(async current => { await load(current); })}>刷新预算与用量</Button></div>
    <p className="text-sm text-muted-foreground">本人预算在当前租户跨品类、跨运行累计。配置额度不会充值或发起模型调用；实际调用仍核对协议、资格与当前权限。</p>
    {error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}
    {notice && <p ref={noticeFocus} tabIndex={-1} role="status" className="break-all text-sm">{notice}</p>}
    {busy && <p role="status" className="text-sm">正在核对预算与回执…</p>}
    {reading && <div className="space-y-3">
      <p className="text-sm text-muted-foreground">本人预算配置 · 第 {reading.control_revision} 版</p>
      {!reading.active_budgets.length && <p className="text-sm">当前没有可供新调用使用的活动预算。</p>}
      {reading.active_budgets.map(row => <article key={row.id} className="space-y-2 rounded-lg border border-border p-3"><h3 className="font-medium">{row.id === reading.selected_budget_id ? "新工作将绑定此预算" : "其他活动预算"} · 第 {row.revision} 版</h3><Usage row={row} /><p className="break-all text-xs text-muted-foreground">预算 {row.id}</p></article>)}
      <Button variant="outline" className="h-auto whitespace-normal" disabled={disabled || !reading.active_budgets.length} onClick={() => void run(current => prepare("stop", null, current))}>核对并停用全部活动预算</Button>
      {!reading.can_edit && <p className="text-sm text-muted-foreground">当前可查询本人预算；变更额度须本人具有当前租户管理员和品类写入权限。</p>}
    </div>}
    <form onSubmit={allocate} className="space-y-3"><h3 className="font-medium">建立新预算</h3><p className="text-sm text-muted-foreground">确认后更换本人活动预算，旧用量和占用保留。已发出的调用继续归原预算结算。</p>
      <fieldset disabled={disabled} className="grid gap-3 sm:grid-cols-2">
        <label htmlFor={`${prefix}-amount`}>费用额度（USD）<input id={`${prefix}-amount`} inputMode="decimal" required autoComplete="off" value={form.amount} onChange={event => setForm({ ...form, amount: event.target.value })} /></label>
        {([{ key: "calls", label: "调用次数额度" }, { key: "input", label: "输入 tokens 额度" }, { key: "output", label: "输出 tokens 额度" }] as const).map(field => <label htmlFor={`${prefix}-${field.key}`} key={field.key}>{field.label}<input id={`${prefix}-${field.key}`} type="number" min={1} max={budgetIntegerMax} step={1} required value={form[field.key]} onChange={event => setForm({ ...form, [field.key]: event.target.value })} /></label>)}
      </fieldset><Button disabled={disabled} type="submit">核对新预算并预览</Button>
    </form>
    {preview && <section ref={focus} tabIndex={-1} aria-label="确认预算变更" className="space-y-3 rounded-lg border border-primary/40 p-3 text-sm">
      <h3 className="font-medium">{preview.review.action === "allocate" ? "确认建立新预算" : "确认停用活动预算"}</h3>
      {preview.review.limits && <p>新额度 {dollars(preview.review.limits.limit_micro_usd)} USD · 调用 {preview.review.limits.call_limit} 次 · 输入 {preview.review.limits.input_token_limit} / 输出 {preview.review.limits.output_token_limit} tokens</p>}
      <p>预算配置将保存为第 {preview.review.next_revision} 版，停用本人 {preview.review.retired_budgets.length} 份活动预算。已有用量和占用保留，进行中的调用继续归原预算结算。</p>
      {!!preview.review.retired_budgets.length && <details><summary className="cursor-pointer">查看受影响预算</summary>{preview.review.retired_budgets.map(row => <p key={row.id} className="break-all">{row.id} · 第 {row.previous_revision} → {row.next_revision} 版</p>)}</details>}
      <div className="flex flex-wrap gap-2"><Button disabled={busy || !reading?.can_edit || !proofClockCurrent("T1", preview.expires_at)} onClick={() => void run(current => save(preview.command, current))}>确认此预算变更</Button><Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></div>
    </section>}
    {pending && <section ref={focus} tabIndex={-1} aria-label="恢复原预算请求" className="space-y-3 rounded-lg border border-primary/40 p-3 text-sm"><h3 className="font-medium">原预算{pending.payload.action === "allocate" ? "建立" : "停用"}结果待核对</h3><p>重新打开先查询原回执；原请求未完成时，由本人明确重试同一请求。确认过期则重新预览。</p><Button disabled={busy} onClick={() => void run(async current => {
      const result = await api<{ receipt: BudgetReceipt | null }>("v1/agent-budgets/recover", pending);
      if (result.receipt) { accept(pending, result.receipt, current); await load(current); }
      else { const value = await load(current); if (!value.can_edit) throw new Error("当前已无预算变更权限，请先核对原回执。"); await save(pending, current); }
    })}>核对并重试原预算请求</Button></section>}
    {reading && <details className="space-y-3"><summary className="cursor-pointer text-sm">查看本人预算历史</summary><div className="mt-3 space-y-3">{reading.items.map(row => <article key={row.id} className="space-y-2 rounded-lg border border-border p-3 text-sm"><p>{row.active ? "活动" : "已停用"} · {new Date(row.created_at).toLocaleString("zh-CN")} · 第 {row.revision} 版</p><Usage row={row} /><p className="break-all text-xs text-muted-foreground">预算 {row.id}<br />变更回执：{row.receipt_id ?? "尚无管理回执"}</p></article>)}{reading.next_cursor && <Button variant="outline" disabled={busy} onClick={() => void run(async current => { await load(current, reading.next_cursor!); })}>读取更多预算历史</Button>}</div></details>}
    {broken && <Button variant="outline" className="h-auto whitespace-normal" disabled={busy || !reading} onClick={() => { try { localStorage.removeItem(key); setBroken(false); setError(""); } catch { setError("本地恢复记录暂时无法移除。"); } }}>已核对当前预算，移除损坏的恢复记录</Button>}
  </section>;
}
