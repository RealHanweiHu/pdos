"use client";
// D309 (P97 第 5–8 项, C11): customer acceptance from the signed sample sheet, five scopes.
// It shows what is accepted and what is not; it never replaces release or stage decisions.
import { useCallback, useEffect, useRef, useState } from "react";
import { Handshake } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { NamedCommandReview } from "@/features/projects/named-command-review";
import { makeCommand } from "@/lib/named-command";
import type { ProjectApi } from "@/lib/project-plan-view";
import { acceptanceStateNames, exactSource, isoFromLocal, scopeNames, scopeStateNames, splitLines, timeText } from "@/lib/d47-records";
import { useNamedAction } from "./use-named-action";

type Scope = { scope: string; state: string; conditions: string[]; expires_at: string | null };
type Acceptance = { id: string; revision: number; state: string; customer: { label: string; goodjob_id: string | null }; scopes: Scope[]; recorded_at: string };
type Source = { id: string; title: string; content: string; revision: number };
type Props = { api: ProjectApi; product: { id: string; revision: number }; build: { id: string; revision: number }; sources: Source[]; originals: { artifact_id: string | null }[] };
type Row = { state: string; conditions: string; expires: string };
const SCOPES = Object.keys(scopeNames);

export function CustomerAcceptances({ api, product, build, sources, originals }: Props) {
  const action = useNamedAction(api);
  const { setError } = action;
  const [items, setItems] = useState<Acceptance[] | null>(null), [editing, setEditing] = useState<Acceptance | null>(null);
  const [label, setLabel] = useState(""), [goodjob, setGoodjob] = useState(""), [sheet, setSheet] = useState(""), [line, setLine] = useState("1"), [reason, setReason] = useState("");
  const [rows, setRows] = useState<Record<string, Row>>(() => Object.fromEntries(SCOPES.map(key => [key, { state: "not_applicable", conditions: "", expires: "" }])));
  const alive = useRef(true);
  const refresh = useCallback(async () => { const value = await api<{ items: Acceptance[] }>(`v1/products/${product.id}/builds/${build.id}/customer-acceptances`); if (alive.current) setItems(value.items); }, [api, product.id, build.id]);
  useEffect(() => { alive.current = true; void Promise.resolve().then(() => alive.current ? refresh() : undefined).catch(failure => setError((failure as Error).message)); return () => { alive.current = false; }; }, [refresh, setError]);
  const sheets = sources.filter(source => originals.some(row => row.artifact_id === source.id));
  function save() {
    void action.start(async () => {
      const source = sheets.find(row => row.id === sheet);
      if (!source) throw new Error("请选择已上传的客户签样单原件。");
      const signed = await exactSource(source, Number(line) || 1);
      const scopes = SCOPES.map(key => ({ scope: key, state: rows[key].state, conditions: splitLines(rows[key].conditions), expires_at: isoFromLocal(rows[key].expires) }));
      const target = editing ? { acceptance: { id: editing.id, revision: editing.revision } } : { build_id: build.id, expected_build_revision: build.revision };
      return makeCommand(product, "customer.acceptance.record", { ...target, customer: { label: label.trim(), goodjob_id: goodjob.trim() || null }, scopes, signed_sheet: signed, reason: reason.trim() || "按客户签样单登记" }, [{ artifact_id: source.id, expected_revision: source.revision }]);
    }, "T2");
  }
  return <section className="min-w-0 space-y-3 rounded-lg border border-border p-3" aria-label="客户承认">
    <h3 className="flex items-center gap-2 font-semibold"><Handshake aria-hidden size={16}/>客户承认（签样单）</h3>
    <p className="subtle text-xs">按外观、尺寸、性能、包装标识、认证资料逐类登记。承认只覆盖登记的范围，不代表工程发布、制造放行或阶段通过；阶段评审只列出它。</p>
    {action.error && <p role="alert" className="text-sm text-destructive [overflow-wrap:anywhere]">{action.error}</p>}
    {action.notice && <p role="status" className="text-sm">{action.notice}</p>}
    {items === null ? <p className="subtle text-sm">正在读取…</p> : items.length === 0 ? <p className="subtle text-sm">本轮尚无客户承认记录。</p> : <ul className="space-y-2">{items.map(item => <li key={item.id} className="border-t border-border pt-2 text-sm">
      <p className="font-medium">{item.customer.label} · {acceptanceStateNames[item.state]} · v{item.revision} · {timeText(item.recorded_at)}</p>
      <ul className="mt-1 flex flex-wrap gap-2">{item.scopes.map(scope => <li key={scope.scope} className="rounded-full border border-border px-2 py-0.5 text-xs">{scopeNames[scope.scope]}：{scopeStateNames[scope.state]}{scope.conditions.length ? `（${scope.conditions.join("；")}）` : ""}{scope.expires_at ? ` 至 ${timeText(scope.expires_at)}` : ""}</li>)}</ul>
      <Button size="sm" variant="ghost" className="mt-1" onClick={() => { setEditing(item); setLabel(item.customer.label); setGoodjob(item.customer.goodjob_id ?? ""); setRows(Object.fromEntries(item.scopes.map(s => [s.scope, { state: s.state, conditions: s.conditions.join("\n"), expires: "" }]))); }}>续登</Button>
    </li>)}</ul>}
    <details className="space-y-2" open={!!editing}><summary className="cursor-pointer text-sm font-medium">{editing ? `续登：${editing.customer.label}` : "登记客户承认"}</summary>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block text-xs">客户（外部名称）<input value={label} onChange={e => setLabel(e.target.value)}/></label>
        <label className="block text-xs">GoodJob 客户编号（可选）<input value={goodjob} onChange={e => setGoodjob(e.target.value)}/></label>
        <label className="block text-xs">签样单原件<select value={sheet} onChange={e => setSheet(e.target.value)}><option value="">选择已上传的原件</option>{sheets.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label>
        <label className="block text-xs">引用原文第几行<input value={line} inputMode="numeric" onChange={e => setLine(e.target.value)}/></label>
      </div>
      <table className="w-full text-xs"><tbody>{SCOPES.map(key => <tr key={key} className="border-t border-border align-top"><td className="py-1 pr-2">{scopeNames[key]}</td>
        <td className="py-1 pr-2"><select value={rows[key].state} onChange={e => setRows({ ...rows, [key]: { ...rows[key], state: e.target.value } })}>{Object.entries(scopeStateNames).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></td>
        <td className="py-1 pr-2"><textarea aria-label={`${scopeNames[key]}条件`} placeholder="条件（每行一条）" value={rows[key].conditions} onChange={e => setRows({ ...rows, [key]: { ...rows[key], conditions: e.target.value } })}/></td>
        <td className="py-1"><input aria-label={`${scopeNames[key]}到期`} type="datetime-local" value={rows[key].expires} onChange={e => setRows({ ...rows, [key]: { ...rows[key], expires: e.target.value } })}/></td></tr>)}</tbody></table>
      <label className="block text-xs">说明<input value={reason} onChange={e => setReason(e.target.value)}/></label>
      {!action.prepared && <div className="flex gap-2"><Button size="sm" variant="outline" disabled={action.busy || !label.trim()} onClick={save}>预览具名登记</Button>{editing && <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>取消续登</Button>}</div>}
    </details>
    {action.prepared && <NamedCommandReview prepared={action.prepared} busy={action.busy} onCancel={action.cancel} onConfirm={() => void action.confirm("customer_acceptance", "客户承认已登记。", async () => { setEditing(null); await refresh(); })}>
      <p className="text-xs">覆盖：{((action.prepared.review.covered ?? []) as string[]).join("、") || "无"} · 未覆盖：{((action.prepared.review.not_covered ?? []) as string[]).join("、") || "无"}</p>
    </NamedCommandReview>}
  </section>;
}
