"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
export type Residual = { kind: string; id: string; expected_digest: string; note: string; snapshot: Record<string, unknown>; changed?: boolean };
const text = (v: unknown) => v == null ? "" : String(v);
const kinds: Record<string, string> = { task: "任务", issue: "问题", risk: "已确认风险" };
export function TaskTakeoverResiduals({ base, values, onChange, disabled }: { base: string; values: Residual[]; onChange: (values: Residual[]) => void; disabled: boolean }) {
  const [kind, setKind] = useState("task"), [search, setSearch] = useState("");
  const [items, setItems] = useState<Record<string, unknown>[]>([]), [next, setNext] = useState<string | null>(null), [applied, setApplied] = useState({ kind: "task", search: "" });
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function load(after?: string) {
    setBusy(true); setError("");
    const scope = after ? applied : { kind, search: search.trim() };
    try {
      const query = new URLSearchParams({ ...scope, ...(after ? { after_id: after } : {}) });
      const response = await fetch(`${base}/residuals?${query}`, { cache: "no-store" });
      const value = await responseBody(response);
      if (!response.ok || !isRecord(value) || !Array.isArray(value.items) || !value.items.every(item => isRecord(item) && ["id", "title", "status", "digest", "href"].every(key => typeof item[key] === "string") && item.kind === scope.kind && String(item.href).startsWith("/projects?")) || !(value.next_after_id === null || typeof value.next_after_id === "string")) throw new Error("遗留项列表暂不可读取，请重试");
      setItems(value.items); setApplied(scope); setNext(value.next_after_id);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-2 rounded-md border p-3" aria-label="关联实际遗留工作">
    <p className="font-medium">关联实际遗留工作（最多30项）</p><p className="text-muted-foreground">选择原任务、问题或已确认风险，保留其具名负责人、期限和版本。未完成项缺少有效负责人或期限时，请先在原记录补齐；交接不会另建或关闭这些工作。</p>
    <div className="flex flex-wrap gap-2"><select aria-label="遗留对象类型" className="rounded-md border bg-background p-2" disabled={disabled || busy} value={kind} onChange={e => setKind(e.target.value)}>{Object.entries(kinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><input aria-label="搜索遗留工作标题" className="min-w-0 flex-1 rounded-md border bg-background p-2" maxLength={200} value={search} disabled={disabled || busy} onChange={e => setSearch(e.target.value)}/><Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void load()}>查找原工作</Button></div>
    {error ? <p role="alert" className="text-destructive">{error}</p> : null}
    <ul className="max-h-64 space-y-2 overflow-auto">{items.map(item => { const selected = values.some(value => value.kind === item.kind && value.id === item.id); return <li className="flex flex-wrap items-center gap-2" key={`${item.kind}:${item.id}`}><div className="min-w-0 flex-1"><Link className="text-primary underline" href={text(item.href)}>{text(item.title)}</Link><p>{text(item.owner_name) || "负责人待补齐"} · {text(item.due_date) || "期限待补齐"} · {text(item.status)}</p></div><Button type="button" size="sm" variant="outline" disabled={disabled || selected || values.length >= 30} onClick={() => onChange([...values, { kind: text(item.kind), id: text(item.id), expected_digest: text(item.digest), note: "", snapshot: item }])}>{selected ? "已关联" : "关联此项"}</Button></li>; })}</ul>
    {next ? <Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void load(next)}>下一批匹配项</Button> : null}
    {values.map((item, index) => <div className="space-y-2 rounded-md border p-2" key={`${item.kind}:${item.id}`}><p>{kinds[item.kind]} · {text(item.snapshot.title)} · {text(item.snapshot.owner_name) || "未指定"} · {text(item.snapshot.due_date) || "未设期限"}</p>{item.changed ? <p className="text-destructive">原对象已变化，请移除后重新核对并选择。</p> : null}<label className="block">与本次交接的关系／仍需办理事项<textarea className="mt-1 w-full rounded-md border bg-background p-2" required maxLength={4000} disabled={disabled} value={item.note} onChange={e => onChange(values.map((value, i) => i === index ? { ...value, note: e.target.value } : value))}/></label><Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => onChange(values.filter((_, i) => i !== index))}>移除此关联</Button></div>)}
  </section>;
}
