"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { command, request, ProductRequestError } from "./product-work-api";
import type { Definition } from "./definitions";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

type Comparison = {
  base_definition_id: string; target_definition_id: string; target_release_id: string;
  target_revision: number; comparison_digest: string;
  changes: { path: string; base: unknown; local: unknown; incoming: unknown; conflict: boolean }[];
};
const labels: Record<string, string> = {
  target_users: "目标用户", scenarios: "使用场景", included_features: "包含功能", excluded_features: "排除功能",
  region_constraints: "地区约束", target_cost: "目标成本", price_position: "价格定位", launch_window: "上市窗口",
  service_requirements: "服务要求", success_criteria: "成功判据",
};

type Props = {
  item: Definition; base: string; canDerive: boolean; canMerge: boolean;
  renderValue: (value: unknown) => ReactNode; onChanged: () => void;
  onAccessDenied?: (failure: ProductRequestError) => void;
  captureAccess?: () => () => boolean;
  onPendingChange?: (pending: boolean) => void;
};
type Pending = { kind: "derive" | "merge"; body: Record<string, unknown> };
export function DefinitionInheritance(props: Props) {
  return <InheritancePanel key={JSON.stringify([props.base, props.item.id])} {...props}/>;
}
function InheritancePanel({ item, base, canDerive, canMerge, renderValue, onChanged, onAccessDenied, captureAccess, onPendingChange }: Props) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState(""); const [name, setName] = useState(""); const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Definition | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [pending, setPending] = useState<Pending | null>(null), [denied, setDenied] = useState(false), [notice, setNotice] = useState("");
  const attempt = useRef<Pending | null>(null), live = useRef(true), inFlight = useRef(false), revision = useRef(0);
  useEffect(() => { live.current = true; return () => { live.current = false; revision.current += 1; }; }, []);
  function clearPending() { attempt.current = null; setPending(null); onPendingChange?.(false); }
  async function run(work: (current: () => boolean) => Promise<void>) {
    if (inFlight.current || !live.current) return;
    inFlight.current = true; setBusy(true); setError(null);
    const version = revision.current, parentCurrent = captureAccess?.() ?? (() => true);
    const current = () => live.current && revision.current === version && parentCurrent();
    try { await work(current); }
    catch (failure) {
      if (!current()) return;
      if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) {
        revision.current += 1; inFlight.current = false;
        clearPending(); setOpen(false); setCode(""); setName(""); setReason(""); setCreated(null); setComparison(null); setSelected([]); setNotice(""); setDenied(true); setBusy(false);
        setError(failure.message); onAccessDenied?.(failure);
      } else setError(failure instanceof Error ? failure.message : "派生或父版办理暂不可用");
    } finally { if (current()) { inFlight.current = false; setBusy(false); } }
  }
  const href = (id: string) => `/product-work?space=${base.split("/")[1]}&tab=definitions#definition-${id}`;
  async function send(current: () => boolean, original: Pending) {
    let saved: Definition;
    try {
      saved = await request<Definition>(`${base}/definitions/${item.id}/${original.kind === "derive" ? "derive" : "parent-merge"}`, "POST", original.body);
    } catch (failure) {
      if (!current()) return;
      if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) throw failure;
      if (failure instanceof ProductRequestError && failure.status < 500 && ![408, 429].includes(failure.status)) { clearPending(); throw failure; }
      setError(`${failure instanceof Error ? failure.message : "请求中断"}；保存结果尚未确认，请按原请求重试核对，原输入与编号保持。`);
      return;
    }
    if (!current()) return;
    clearPending(); setReason("");
    if (original.kind === "derive") { setCreated(saved); setOpen(false); }
    else {
      setComparison(null); setSelected([]); setNotice("所选父版变更已接受到定义草稿，原发布版保持；规格及专业协审仍须办理。");
      try { onChanged(); } catch { setError("父版变更已保存，页面暂未刷新。请刷新定义列表，无需再次接受。"); }
    }
  }
  function submit(kind: Pending["kind"], body: Record<string, unknown>) {
    if (attempt.current || (kind === "derive" ? !canDerive : !canMerge)) return;
    void run(async current => {
      const original: Pending = { kind, body: JSON.parse(JSON.stringify({ ...command(item), ...body })) as Record<string, unknown> };
      attempt.current = original; setPending(original); setNotice(""); onPendingChange?.(true);
      await send(current, original);
    });
  }
  const derive = () => submit("derive", { code, name, reason });
  const compare = () => run(async current => {
    setComparison(null); setSelected([]);
    const value = await request<Comparison>(`${base}/definitions/${item.id}/parent-comparison`);
    if (current()) { setComparison(value); setDenied(false); }
  });
  const merge = () => { if (comparison) submit("merge", { target_definition_id: comparison.target_definition_id, target_release_id: comparison.target_release_id, comparison_digest: comparison.comparison_digest, accept_paths: selected, reason }); };
  const restore = () => run(async current => {
    const value = await request<Definition>(`${base}/definitions/${item.id}`);
    if (!current()) return;
    if (value.payload_digest !== item.payload_digest) { setError("原定义已有更新，请刷新定义列表后继续。"); return; }
    setDenied(false);
  });
  if (!item.base_definition_id && !canDerive) return null;
  if (denied) return <section className="space-y-3 rounded-md border p-3"><h5 className="font-medium">产品派生与父版更新</h5><p role="alert" className="text-sm text-destructive">{error}</p><Button variant="outline" size="sm" disabled={busy} onClick={() => void restore()}>重新核对读取范围</Button></section>;
  return <section className="space-y-3 rounded-md border p-3">
    <h5 className="font-medium">产品派生与父版更新</h5>
    {notice && <p role="status" className="text-sm">{notice}</p>}
    {pending && <div className="space-y-2 rounded-md border p-3 text-sm"><p>本次保存尚待核对，原产品输入、父版选择和请求编号保持；核对完成前不能开始新的写入。</p><Button variant="outline" disabled={busy || (pending.kind === "derive" ? !canDerive : !canMerge)} onClick={() => void run(async current => { const original = attempt.current; if (original) await send(current, original); })}>{pending.kind === "derive" ? "按原请求重试核对派生" : "按原请求重试核对父版变更"}</Button></div>}
    {item.base_definition_id && <>
      <p className="text-sm">锁定父版：<a className="underline" href={href(item.base_definition_id)}>查看父产品原发布定义</a>。本产品保留自己的差异和发布流程，父版更新不会自动覆盖。</p>
      <Button variant="outline" size="sm" disabled={busy} onClick={compare}>比较父产品最新发布版</Button>
      {!!item.parent_updates?.length && <details><summary className="cursor-pointer text-sm">已接受的父版变更（{item.parent_updates.length}次）</summary>
        {item.parent_updates.map((update, index) => <p className="text-sm" key={index}><a className="underline" href={href(update.source.ref_id)}>父版来源</a> · {update.accepted_paths.map(path => labels[path.split("/")[1]] ?? path.split("/")[1]).join("、")} · {update.reason}</p>)}
      </details>}
    </>}
    {comparison && <div className="space-y-3">
      <p className="text-sm">与父产品第 {comparison.target_revision} 版比较。仅接受勾选项，未选项保持本地内容；变更的规格仍需在本产品确认。</p>
      {!comparison.changes.length && <p className="text-sm text-muted-foreground">父产品没有新的内容差异。</p>}
      {comparison.changes.map(change => <section className="space-y-2 border-t pt-3" key={change.path}>
        <label className="flex items-center gap-2 text-sm font-medium"><input type="checkbox" disabled={!canMerge || busy || !!pending || change.incoming === null} checked={selected.includes(change.path)} onChange={event => setSelected(values => event.target.checked ? [...values, change.path] : values.filter(value => value !== change.path))}/>{labels[change.path.split("/")[1]] ?? `规格 ${change.path.split("/")[1]}`}{change.conflict && <span className="text-destructive">本地也有修改，请核对冲突</span>}</label>
        <div className="grid gap-3 lg:grid-cols-3">{([["原锁定父版", change.base], ["本地当前内容", change.local], ["父产品新版", change.incoming]] as const).map(([title, value]) => <div className="space-y-2 text-sm" key={title}><h6 className="font-medium">{title}</h6>{value === null ? <p className="text-muted-foreground">无此项</p> : renderValue(value)}</div>)}</div>
      </section>)}
      {comparison.changes.length > 0 && (canMerge ? <><label className="block text-sm">接受变更的原因<textarea disabled={busy || !!pending} className={field} maxLength={2048} value={reason} onChange={event => setReason(event.target.value)}/></label><Button disabled={busy || !!pending || !selected.length || !reason.trim()} onClick={merge}>接受所选父版变更</Button></> : <p className="text-sm text-muted-foreground">已发布定义请先创建修订；审核中的定义请先退回草稿。仅负责人或管理人可接受变更。</p>)}
    </div>}
    {canDerive && !created && <Button variant="outline" size="sm" disabled={busy || !!pending} onClick={() => setOpen(value => !value)}>{open ? "取消派生" : "派生为新产品"}</Button>}
    {open && canDerive && !created && <form className="space-y-3" onSubmit={event => { event.preventDefault(); derive(); }}><fieldset disabled={busy || !!pending} className="space-y-3">
      <p className="text-sm text-muted-foreground">在同产品线和层级创建独立产品，引用此发布版。规格先待确认，专业协审人需重新指定。</p>
      <label className="block text-sm">新产品编号<input required pattern={"[a-zA-Z0-9_.:\\-]+"} maxLength={128} className={field} value={code} onChange={event => setCode(event.target.value)}/></label>
      <label className="block text-sm">新产品名称<input required maxLength={2048} className={field} value={name} onChange={event => setName(event.target.value)}/></label>
      <label className="block text-sm">派生原因<textarea required maxLength={2048} className={field} value={reason} onChange={event => setReason(event.target.value)}/></label>
      <Button disabled={busy || !code.trim() || !name.trim() || !reason.trim()} type="submit">创建派生产品与定义草稿</Button>
    </fieldset></form>}
    {created && <p role="status" className="text-sm">已创建 {created.product_name}。<a className="underline" href={href(created.id)}>打开新产品定义，核对差异与规格</a></p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </section>;
}
