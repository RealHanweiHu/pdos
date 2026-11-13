"use client";
// D312 (P120 第 4–6 项): interface contracts under an engineering configuration.
// Create/revise by an engineering-role person; each discipline confirms separately.
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowsClockwise, Plugs } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { NamedCommandReview } from "@/features/projects/named-command-review";
import { makeCommand } from "@/lib/named-command";
import type { ProjectApi } from "@/lib/project-plan-view";
import { actionNames, confirmationNames, splitLines, timeText, type HistoryRow } from "@/lib/d47-records";
import { useNamedAction } from "./use-named-action";

type Confirmation = { discipline: string; state: string; actor_id: string | null; note: string | null; at_revision: number | null; superseded_at_revision?: number };
type Content = {
  name: string; kind: string; modules: { key: string; label: string }[]; disciplines: string[]; constraints: { text: string; unit: string | null }[];
  units: string[]; verification_method: string | null; responsible_id: string;
  affected: { kind: string; id: string; revision: number; key: string | null; label?: string }[]; leads: { text: string }[];
};
type Item = { id: string; revision: number; state: string; configuration: { id: string; revision: number }; content: Content; confirmations: Confirmation[]; superseded: Confirmation[]; recorded_at: string; history?: HistoryRow[] };
type Configuration = { id: string; revision: number; name: string };
type Props = { projectId: string; product: { id: string; revision: number }; api: ProjectApi; configurations: Configuration[]; principalId: string };
type Draft = { name: string; kind: string; modules: string; disciplines: string; constraints: string; units: string; method: string; responsible: string; affected: string; leads: string; configuration: string };
const stateNames: Record<string, string> = { pending: "待各专业确认", confirmed: "各专业已确认", disputed: "有专业提出异议" };
const blank = (configuration = ""): Draft => ({ name: "", kind: "", modules: "", disciplines: "", constraints: "", units: "", method: "", responsible: "", affected: "", leads: "", configuration });

export function parseContent(draft: Draft) {
  const modules = splitLines(draft.modules).map(line => { const [key, ...rest] = line.split(/\s+/); return { key, label: rest.join(" ") || key }; });
  const constraints = splitLines(draft.constraints).map(line => { const [text, unit] = line.split("|").map(part => part.trim()); return { text, unit: unit || null }; });
  const affected = splitLines(draft.affected).map(line => {
    const [kind, id, revision, key] = line.split(/\s+/);
    if (!kind || !id || !Number(revision)) throw new Error("受影响项每行写：类型 标识 版本 [行或工序key]");
    return { kind, id, revision: Number(revision), key: key || null };
  });
  if (!draft.responsible) throw new Error("请指定接口负责人。");
  return {
    name: draft.name.trim(), kind: draft.kind.trim(), modules, disciplines: draft.disciplines.split(/[,，\s]+/).map(v => v.trim()).filter(Boolean),
    constraints, units: draft.units.split(/[,，\s]+/).map(v => v.trim()).filter(Boolean), verification_method: draft.method.trim() || null,
    responsible_id: draft.responsible, affected, leads: splitLines(draft.leads).map(text => ({ text })),
  };
}

function toDraft(item: Item): Draft {
  const c = item.content;
  return {
    name: c.name, kind: c.kind, modules: c.modules.map(m => `${m.key} ${m.label}`).join("\n"), disciplines: c.disciplines.join(", "),
    constraints: c.constraints.map(v => v.unit ? `${v.text} | ${v.unit}` : v.text).join("\n"), units: c.units.join(", "), method: c.verification_method ?? "",
    responsible: c.responsible_id, affected: c.affected.map(a => [a.kind, a.id, a.revision, a.key ?? ""].join(" ").trim()).join("\n"),
    leads: c.leads.map(l => l.text).join("\n"), configuration: item.configuration.id,
  };
}

export function EngineeringInterfaces({ projectId, product, api, configurations, principalId }: Props) {
  const action = useNamedAction(api);
  const { setError } = action;
  const [items, setItems] = useState<Item[] | null>(null), [members, setMembers] = useState<{ principal_id: string; name: string; roles: { key: string }[] }[]>([]);
  const [draft, setDraft] = useState<Draft>(() => blank(configurations[0]?.id ?? "")), [editing, setEditing] = useState<Item | null>(null), [note, setNote] = useState("");
  const alive = useRef(true);
  const refresh = useCallback(async () => {
    const [list, team] = await Promise.all([
      api<{ items: Item[] }>(`v1/products/${product.id}/projects/${projectId}/interfaces`),
      api<{ members?: { principal_id: string; name: string; roles: { key: string }[] }[] }>(`v1/products/${product.id}/projects/${projectId}/team`).catch(() => ({ members: [] })),
    ]);
    if (alive.current) { setItems(list.items); setMembers(team.members ?? []); }
  }, [api, product.id, projectId]);
  useEffect(() => { alive.current = true; void Promise.resolve().then(() => alive.current ? refresh() : undefined).catch(failure => setError((failure as Error).message)); return () => { alive.current = false; }; }, [refresh, setError]);
  const myRoles = new Set(members.find(m => m.principal_id === principalId)?.roles.map(r => r.key) ?? []);
  const configuration = configurations.find(c => c.id === draft.configuration);
  function save() {
    void action.start(() => {
      if (!configuration) throw new Error("请选择接口挂接的工程配置当前版本。");
      const record = { action: editing ? "revise" : "create", ...(editing ? {} : { project_id: projectId }), configuration: { id: configuration.id, revision: configuration.revision }, ...parseContent(draft) };
      return makeCommand(product, "engineering.interface.update", { ...(editing ? { interface: { id: editing.id, revision: editing.revision } } : {}), record, reason: note.trim() || (editing ? "修订接口合同" : "登记接口合同") });
    }, "T1");
  }
  function respond(item: Item, discipline: string, kind: "confirm" | "dispute") {
    void action.start(() => makeCommand(product, "engineering.interface.update", { interface: { id: item.id, revision: item.revision }, record: { action: kind, discipline, note: note.trim() || null }, reason: note.trim() || (kind === "confirm" ? "本专业确认接口" : "本专业对接口有异议") }), "T1");
  }
  return <section className="min-w-0 space-y-3 rounded-lg border border-border p-3" aria-label="接口合同">
    <header className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="flex items-center gap-2 font-semibold"><Plugs aria-hidden size={16}/>接口合同</h3><p className="subtle mt-1 text-xs">挂在工程配置下；各参与专业分别确认，负责人不代替确认。影响只沿登记的受影响项传播，待核实线索单列。</p></div>
      <Button size="sm" variant="ghost" disabled={action.busy} onClick={() => void refresh().catch(failure => action.setError((failure as Error).message))}><ArrowsClockwise aria-hidden/>刷新</Button></header>
    {action.error && <p role="alert" className="text-sm text-destructive [overflow-wrap:anywhere]">{action.error}</p>}
    {action.notice && <p role="status" className="text-sm">{action.notice}</p>}
    {items === null ? <p className="subtle text-sm">正在读取接口…</p> : items.length === 0 ? <p className="subtle text-sm">本项目尚无接口合同。</p> : <ul className="space-y-3">{items.map(item => <li key={item.id} className="space-y-2 border-t border-border pt-2 text-sm">
      <p className="font-medium">{item.content.name} · {item.content.kind} · v{item.revision} · {stateNames[item.state] ?? item.state}</p>
      <p className="subtle text-xs">模块：{item.content.modules.map(m => m.label).join("、")} · 约束：{item.content.constraints.map(c => c.unit ? `${c.text}（${c.unit}）` : c.text).join("；") || "无"} · 验证：{item.content.verification_method ?? "未定"}</p>
      <ul className="flex flex-wrap gap-2">{item.confirmations.map(row => <li key={row.discipline} className="rounded-full border border-border px-2 py-0.5 text-xs">{row.discipline}：{confirmationNames[row.state]}{row.note ? `（${row.note}）` : ""}
        {myRoles.has(row.discipline) && principalId !== item.content.responsible_id && <><button type="button" className="ml-1 underline" disabled={action.busy} onClick={() => respond(item, row.discipline, "confirm")}>确认</button><button type="button" className="ml-1 underline" disabled={action.busy} onClick={() => respond(item, row.discipline, "dispute")}>异议</button></>}</li>)}</ul>
      {item.superseded.length > 0 && <p className="subtle text-xs">已取代的确认 {item.superseded.length} 条（内容修订后需重新确认）。</p>}
      <p className="text-xs">受影响项（确定）：{item.content.affected.map(a => a.label ?? `${a.kind}:${a.id.slice(0, 8)}`).join("、") || "无"}</p>
      {item.content.leads.length > 0 && <p className="subtle text-xs">待核实线索（不作为确定影响）：{item.content.leads.map(l => l.text).join("；")}</p>}
      <Button size="sm" variant="outline" disabled={action.busy} onClick={() => { setEditing(item); setDraft(toDraft(item)); }}>修订此接口</Button>
    </li>)}</ul>}
    <details className="space-y-2" open={!!editing}><summary className="cursor-pointer text-sm font-medium">{editing ? `修订：${editing.content.name}（第 ${editing.revision + 1} 版）` : "登记新接口"}</summary>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block text-sm">名称<input value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })}/></label>
        <label className="block text-sm">接口类型<input value={draft.kind} placeholder="机械尺寸、电源、通信协议…" onChange={e => setDraft({ ...draft, kind: e.target.value })}/></label>
        <label className="block text-sm">工程配置<select value={draft.configuration} onChange={e => setDraft({ ...draft, configuration: e.target.value })}><option value="">选择当前版本</option>{configurations.map(c => <option key={c.id} value={c.id}>{c.name} · v{c.revision}</option>)}</select></label>
        <label className="block text-sm">负责人<select value={draft.responsible} onChange={e => setDraft({ ...draft, responsible: e.target.value })}><option value="">选择项目成员</option>{members.map(m => <option key={m.principal_id} value={m.principal_id}>{m.name}</option>)}</select></label>
        <label className="block text-sm">参与专业（角色标识，逗号分隔）<input value={draft.disciplines} placeholder="mechanical, electronics" onChange={e => setDraft({ ...draft, disciplines: e.target.value })}/></label>
        <label className="block text-sm">单位<input value={draft.units} placeholder="mm, V" onChange={e => setDraft({ ...draft, units: e.target.value })}/></label>
      </div>
      <label className="block text-sm">参与模块（每行：标识 名称）<textarea value={draft.modules} onChange={e => setDraft({ ...draft, modules: e.target.value })}/></label>
      <label className="block text-sm">约束（每行：内容 | 单位）<textarea value={draft.constraints} onChange={e => setDraft({ ...draft, constraints: e.target.value })}/></label>
      <label className="block text-sm">验证方式<input value={draft.method} onChange={e => setDraft({ ...draft, method: e.target.value })}/></label>
      <label className="block text-sm">受影响项（每行：类型 标识 版本 [key]，只填确定的显式依赖）<textarea value={draft.affected} placeholder="bom 3f…a1 1 motor" onChange={e => setDraft({ ...draft, affected: e.target.value })}/></label>
      <label className="block text-sm">待核实线索（每行一条，不进入影响计算）<textarea value={draft.leads} onChange={e => setDraft({ ...draft, leads: e.target.value })}/></label>
      <label className="block text-sm">说明或理由<input value={note} onChange={e => setNote(e.target.value)}/></label>
      {!action.prepared && <div className="flex gap-2"><Button size="sm" variant="outline" disabled={action.busy} onClick={save}>预览</Button>{editing && <Button size="sm" variant="ghost" onClick={() => { setEditing(null); setDraft(blank(configurations[0]?.id ?? "")); }}>取消修订</Button>}</div>}
    </details>
    {action.prepared && <NamedCommandReview prepared={action.prepared} busy={action.busy} onCancel={action.cancel} onConfirm={() => void action.confirm("engineering_interface", "接口合同已保存。", async () => { setEditing(null); await refresh(); })}>
      <p className="text-xs">保存后状态：{stateNames[String((action.prepared.review.after as { state?: string })?.state)] ?? "—"}</p>
    </NamedCommandReview>}
    {items && items.some(i => i.history?.length) && <p className="subtle text-xs">最近保存 {timeText(items[0]?.recorded_at)} · 动作记录见各接口详情（{Object.values(actionNames).length} 种动作）。</p>}
  </section>;
}
