"use client";
// D305 (P95 第 1–4 项与补充确认): one T1 confirmation records a tool trial, registers or
// versions the tooling, and creates the verification request from this Build's preparation.
// Engineering or manufacturing named people; acceptance follows the test's named disposition.
import { useCallback, useEffect, useRef, useState } from "react";
import { Hammer } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { NamedCommandReview } from "@/features/projects/named-command-review";
import { makeCommand } from "@/lib/named-command";
import type { ProjectApi, SourceRead } from "@/lib/project-plan-view";
import { splitLines, timeText, trialCavities, trialParameters } from "@/lib/d47-records";
import { useNamedAction } from "./use-named-action";

type Tooling = { id: string; revision: number; part: string; version: string; supplier_ref: string; cavities: number; resource_id: string | null };
type TrialRow = { id: string; trial: { round: string; purpose: string; issues: string[]; corrective_actions: string[] }; tooling: { id: string; revision: number; part?: string | null; version?: string | null }; request_id: string; recorded_at: string };
type Preparation = { id: string; revision: number; sha256: string; build_id: string; title: string; is_current: boolean; required_source_read_set: SourceRead[]; authority?: { request_create?: { required_source_read_set?: SourceRead[] } } };
type Props = { api: ProjectApi; product: { id: string; revision: number }; build: { id: string; revision: number } };

function reads(...sets: SourceRead[][]): SourceRead[] {
  const out = new Map<string, SourceRead>();
  for (const set of sets) for (const read of set) out.set(JSON.stringify(read), read);
  return [...out.values()];
}

export function ToolTrials({ api, product, build }: Props) {
  const action = useNamedAction(api);
  const { setError } = action;
  const [tooling, setTooling] = useState<Tooling[]>([]), [items, setItems] = useState<TrialRow[] | null>(null), [preparations, setPreparations] = useState<Preparation[]>([]);
  const [toolingId, setToolingId] = useState(""), [part, setPart] = useState(""), [version, setVersion] = useState(""), [supplier, setSupplier] = useState(""), [toolCavities, setToolCavities] = useState("1");
  const [round, setRound] = useState(""), [purpose, setPurpose] = useState(""), [lots, setLots] = useState(""), [parameters, setParameters] = useState(""), [cavities, setCavities] = useState("");
  const [issues, setIssues] = useState(""), [actions, setActions] = useState(""), [preparationId, setPreparationId] = useState(""), [reason, setReason] = useState("");
  const alive = useRef(true);
  const refresh = useCallback(async () => {
    const [trials, professional] = await Promise.all([
      api<{ tooling: Tooling[]; items: TrialRow[] }>(`v1/products/${product.id}/builds/${build.id}/tool-trials`),
      api<{ preparations: Preparation[] }>(`v1/products/${product.id}/verification-professional`),
    ]);
    if (!alive.current) return;
    setTooling(trials.tooling); setItems(trials.items);
    setPreparations(professional.preparations.filter(row => row.build_id === build.id && row.is_current));
  }, [api, product.id, build.id]);
  useEffect(() => { alive.current = true; void Promise.resolve().then(() => alive.current ? refresh() : undefined).catch(failure => setError((failure as Error).message)); return () => { alive.current = false; }; }, [refresh, setError]);
  const chosen = tooling.find(row => row.id === toolingId);
  function preview() {
    void action.start(() => {
      const preparation = preparations.find(row => row.id === preparationId);
      if (!preparation) throw new Error("请选择本 Build 当前的验证准备；试模会按它带出验证请求。");
      if (!round.trim() || !purpose.trim()) throw new Error("请填写试模轮次与目的。");
      const toolingPart = chosen
        ? { tooling: { id: chosen.id, revision: chosen.revision, ...(version.trim() && version.trim() !== chosen.version ? { changes: { version: version.trim() } } : {}) } }
        : { tooling_new: { part: part.trim(), version: version.trim(), supplier_ref: supplier.trim(), cavities: Number(toolCavities) } };
      return makeCommand(product, "npi.tooltrial.create", {
        build: { id: build.id, revision: build.revision },
        ...toolingPart,
        trial: { round: round.trim(), purpose: purpose.trim(), material_lots: splitLines(lots), parameters: trialParameters(parameters), cavities: trialCavities(cavities), issues: splitLines(issues), corrective_actions: splitLines(actions) },
        verification: { request_id: crypto.randomUUID(), preparation_id: preparation.id, expected_preparation_revision: preparation.revision, preparation_sha256: preparation.sha256, reason: "试模样件的验证请求" },
        reason: reason.trim() || "登记本轮试模",
      }, reads(preparation.required_source_read_set, preparation.authority?.request_create?.required_source_read_set ?? []));
    }, "T1");
  }
  const ready = !!preparationId && (chosen ? true : !!part.trim() && !!version.trim() && !!supplier.trim());
  // After a save the next round references the tooling just used, never registers it again.
  async function saved() {
    const usedPart = chosen?.part ?? part.trim(), usedSupplier = chosen?.supplier_ref ?? supplier.trim();
    const trials = await api<{ tooling: Tooling[]; items: TrialRow[] }>(`v1/products/${product.id}/builds/${build.id}/tool-trials`);
    if (!alive.current) return;
    setTooling(trials.tooling); setItems(trials.items);
    const used = trials.tooling.find(row => row.part === usedPart && row.supplier_ref === usedSupplier);
    if (used) { setToolingId(used.id); setVersion(used.version); }
    setRound(""); setPurpose(""); setLots(""); setParameters(""); setCavities(""); setIssues(""); setActions(""); setReason("");
  }
  return <section className="min-w-0 space-y-3 rounded-lg border border-border p-3" aria-label="试模登记">
    <h3 className="flex items-center gap-2 font-semibold"><Hammer aria-hidden size={16}/>试模登记</h3>
    <p className="subtle text-xs">工程或制造具名本人一次确认：记录本轮试模，首次试模同时登记模具，并按本 Build 的验证准备带出验证请求。模具是否验收看试模样件所在测试的具名处置（接受、拒绝或尚无处置）。寿命与保养留在 ERP/MES。</p>
    {action.error && <p role="alert" className="text-sm text-destructive [overflow-wrap:anywhere]">{action.error}</p>}
    {action.notice && <p role="status" className="text-sm">{action.notice}</p>}
    {items === null ? <p className="subtle text-sm">正在读取…</p> : items.length === 0 ? <p className="subtle text-sm">本 Build 还没有试模记录。</p> : <ul className="space-y-2">{items.map(row => { const tool = tooling.find(value => value.id === row.tooling.id); return <li key={row.id} className="border-t border-border pt-2 text-sm">
      <p>{row.trial.round} · {row.trial.purpose}</p>
      <p className="subtle text-xs">模具 {row.tooling.part ? `${row.tooling.part} ${row.tooling.version ?? ""}` : tool ? tool.part : row.tooling.id.slice(0, 8)} v{row.tooling.revision} · 验证请求 {row.request_id.slice(0, 8)} · {timeText(row.recorded_at)}</p>
      {row.trial.issues.length > 0 && <p className="text-xs [overflow-wrap:anywhere]">问题：{row.trial.issues.join("；")}</p>}
    </li>; })}</ul>}
    <div className="grid gap-2 sm:grid-cols-2">
      <label className="block text-xs">模具<select value={toolingId} onChange={e => { setToolingId(e.target.value); setVersion(tooling.find(row => row.id === e.target.value)?.version ?? ""); }}><option value="">首次试模，登记新模具</option>{tooling.map(row => <option key={row.id} value={row.id}>{row.part} · {row.version} · {row.supplier_ref} · v{row.revision}</option>)}</select></label>
      {chosen ? <label className="block text-xs">模具版本（有变化时续版）<input value={version} onChange={e => setVersion(e.target.value)}/></label> : <>
        <label className="block text-xs">零件<input value={part} onChange={e => setPart(e.target.value)}/></label>
        <label className="block text-xs">模具版本<input value={version} onChange={e => setVersion(e.target.value)}/></label>
        <label className="block text-xs">供应商模具编号<input value={supplier} onChange={e => setSupplier(e.target.value)}/></label>
        <label className="block text-xs">穴数<input value={toolCavities} inputMode="numeric" onChange={e => setToolCavities(e.target.value)}/></label>
      </>}
      <label className="block text-xs">试模轮次<input value={round} placeholder="T0" onChange={e => setRound(e.target.value)}/></label>
      <label className="block text-xs">试模目的<input value={purpose} onChange={e => setPurpose(e.target.value)}/></label>
      <label className="block text-xs">材料批次（每行一个）<textarea rows={2} value={lots} onChange={e => setLots(e.target.value)}/></label>
      <label className="block text-xs">关键参数（每行“名称 = 数值 单位”）<textarea rows={2} value={parameters} onChange={e => setParameters(e.target.value)}/></label>
      <label className="block text-xs">本轮穴位（逗号分隔）<input value={cavities} onChange={e => setCavities(e.target.value)}/></label>
      <label className="block text-xs">验证准备<select value={preparationId} onChange={e => setPreparationId(e.target.value)}><option value="">选择本 Build 当前准备</option>{preparations.map(row => <option key={row.id} value={row.id}>{row.title} · v{row.revision}</option>)}</select></label>
      <label className="block text-xs">问题（每行一条）<textarea rows={2} value={issues} onChange={e => setIssues(e.target.value)}/></label>
      <label className="block text-xs">纠正措施（每行一条）<textarea rows={2} value={actions} onChange={e => setActions(e.target.value)}/></label>
      <label className="block text-xs sm:col-span-2">理由<input value={reason} onChange={e => setReason(e.target.value)}/></label>
    </div>
    {preparations.length === 0 && items !== null && <p className="subtle text-xs">本 Build 还没有当前验证准备；先在验证准备中建立，再登记试模。</p>}
    {action.prepared ? <NamedCommandReview prepared={action.prepared} busy={action.busy} onCancel={action.cancel} onConfirm={() => void action.confirm("tool_trial", "试模已登记，验证请求已建立；送样与开测仍按验证流程办理。", saved)}/> : <Button size="sm" variant="outline" disabled={action.busy || !ready} onClick={preview}>预览试模登记</Button>}
  </section>;
}
