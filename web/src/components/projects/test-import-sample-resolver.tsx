"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ProjectBuildCreate } from "./project-build-create";
import { isRecord } from "@/components/workspace-api";

const input = "mt-1 w-full rounded-md border bg-background p-2 text-xs";
type Row = Record<string, unknown>;
const text = (v: unknown) => v === null || v === undefined ? "未知" : String(v);
const status: Record<string, string> = { planned: "计划中", in_progress: "进行中", completed: "已完成", cancelled: "已取消", built: "已装机", testing: "测试中", accepted: "已接收", scrapped: "已报废" };
export function TestImportSampleResolver({ projectId, suggestedBuildCode, onBuildCreated, runIds, suggestedSerial, busy, loadOptions, onResolve, digest }: { projectId: string; suggestedBuildCode: string; onBuildCreated: () => Promise<void>; runIds: string[]; suggestedSerial: string; busy: boolean; loadOptions: (search: string) => Promise<unknown>; onResolve: (body: object) => Promise<void>; digest: string }) {
  const [data, setData] = useState<{ samples: Row[]; builds: Row[]; boms: Row[]; more: boolean; allowed: boolean } | null>(null);
  const [loading, setLoading] = useState(false), [error, setError] = useState<string | null>(null), [search, setSearch] = useState(suggestedSerial);
  const [mode, setMode] = useState("reuse"), [sampleId, setSampleId] = useState(""), [buildId, setBuildId] = useState("");
  const [serial, setSerial] = useState(suggestedSerial), [builtDate, setBuiltDate] = useState(""), [bomId, setBomId] = useState(""), [parentId, setParentId] = useState("");
  const [reason, setReason] = useState(""), [notes, setNotes] = useState(""), [ack, setAck] = useState(false);
  const request = useRef<{ signature: string; id: string } | null>(null);
  async function load() { setLoading(true); setError(null); try { const result = await loadOptions(search); if (!isRecord(result) || !Array.isArray(result.samples) || !Array.isArray(result.builds) || !Array.isArray(result.prototype_boms)) throw new Error("样机与批次资料不完整"); setData({ samples: result.samples.filter(isRecord), builds: result.builds.filter(isRecord), boms: result.prototype_boms.filter(isRecord), more: result.more_samples === true, allowed: result.can_resolve === true }); setSampleId(""); setParentId(""); setAck(false);
    const matches = result.builds.filter(isRecord).filter(b => b.code === suggestedBuildCode);
    setBuildId(matches.length === 1 && ["planned", "in_progress"].includes(String(matches[0].status)) && Number(matches[0].registered_samples) < Number(matches[0].planned_quantity) ? String(matches[0].id) : ""); } catch (e) { setError(e instanceof Error ? e.message : "样机资料暂不可用"); } finally { setLoading(false); } }
  const blocked = busy || loading;
  const chosen = data?.samples.find(s => String(s.id) === sampleId);
  return <div className="space-y-3 rounded-md border bg-muted/30 p-3 text-xs"><p className="font-medium">为选中的 {runIds.length} 条测试记录补齐实际样机</p>
    <p>核对原编号后复用已有记录；确需新建时，确认真实所属批次和装机日期。新建沿原批次状态与数量限制执行，计划BOM和报告中的当次配置分别保留。</p>
    <div className="flex items-end gap-2"><label className="flex-1">按样机编号查找<input className={input} value={search} maxLength={128} disabled={blocked} onChange={e => setSearch(e.target.value)} /></label><Button type="button" size="sm" variant="outline" disabled={blocked} onClick={() => void load()}>查询样机及批次</Button></div>
    {data?.more && <p>匹配结果超过200条，请缩小编号查询范围。</p>}
    {data?.allowed && <><label className="block">办理方式<select className={input} value={mode} disabled={blocked} onChange={e => { setMode(e.target.value); setAck(false); }}><option value="reuse">复用已有样机</option><option value="create">确认新建样机并绑定</option></select></label>
      {suggestedBuildCode && <p>选中记录的报告批次原值：{suggestedBuildCode}。仅唯一且可建档的同编号批次预选，仍需核对确认。</p>}
      {mode === "reuse" ? <><label className="block">实际样机<select className={input} value={sampleId} disabled={blocked} onChange={e => { setSampleId(e.target.value); setAck(false); }}><option value="">请选择</option>{data.samples.map(s => <option key={String(s.id)} value={String(s.id)}>{text(s.serial_number)} · {status[text(s.status)] ?? text(s.status)}</option>)}</select></label>
        {chosen && <p>所属批次：{text(data.builds.find(b => b.id === chosen.build_batch_id)?.code)} · {chosen.built_at_precision === "day" ? `装机日期 ${text(chosen.built_at).slice(0, 10)}` : chosen.built_at_precision === "instant" ? `装机时间 ${text(chosen.built_at)}` : "历史装机日期精度未知"}</p>}</> : <>
        <div className="grid gap-3 sm:grid-cols-2"><label>真实样机编号<input className={input} value={serial} maxLength={128} disabled={blocked} onChange={e => { setSerial(e.target.value); setAck(false); }} /></label><label>实际装机日期（日期精度）<input className={input} type="date" value={builtDate} disabled={blocked} onChange={e => { setBuiltDate(e.target.value); setAck(false); }} /></label></div>
        <ProjectBuildCreate projectId={projectId} busy={blocked} onCreated={async () => { await onBuildCreated(); await load(); }} />
        <label className="block">所属现有批次<select className={input} value={buildId} disabled={blocked} onChange={e => { setBuildId(e.target.value); setAck(false); }}><option value="">请选择真实批次</option>{data.builds.map(b => <option key={String(b.id)} value={String(b.id)} disabled={!["planned", "in_progress"].includes(String(b.status)) || Number(b.registered_samples) >= Number(b.planned_quantity)}>{text(b.code)} · {text(b.phase).toUpperCase()} · {status[text(b.status)] ?? text(b.status)} · 已建档{text(b.registered_samples)}/{text(b.planned_quantity)}</option>)}</select></label>
        <p className="text-muted-foreground">已完成、已取消或数量已满的批次不能直接补建，请沿原批次流程调整。缺少真实批次时，可先登记，再重新核对样机归属。</p>
        <div className="grid gap-3 sm:grid-cols-2"><label>计划样机BOM（可选）<select className={input} value={bomId} disabled={blocked} onChange={e => { setBomId(e.target.value); setAck(false); }}><option value="">未知，暂不绑定</option>{data.boms.map(b => <option key={String(b.id)} value={String(b.id)}>{text(b.code)} · 版本{text(b.version)}</option>)}</select></label><label>母样机（可选，来自当前查询）<select className={input} value={parentId} disabled={blocked} onChange={e => { setParentId(e.target.value); setAck(false); }}><option value="">无或未知</option>{data.samples.map(s => <option key={String(s.id)} value={String(s.id)}>{text(s.serial_number)}</option>)}</select></label></div>
        <label className="block">建档备注<textarea className={input} value={notes} maxLength={20000} disabled={blocked} onChange={e => setNotes(e.target.value)} /></label>
      </>}
      <label className="block">绑定依据及编号差异说明<textarea className={input} value={reason} maxLength={2000} disabled={blocked} onChange={e => { setReason(e.target.value); setAck(false); }} /></label>
      <label className="flex gap-2"><input type="checkbox" checked={ack} disabled={blocked} onChange={e => setAck(e.target.checked)} />已核对选中的全部记录均属于上述实际样机，并确认{mode === "create" ? "新建样机档案及" : ""}绑定；报告结果仍需单独确认。</label>
      <Button type="button" size="sm" disabled={blocked || !ack || !reason.trim() || (mode === "reuse" ? !sampleId : !serial.trim() || !builtDate || !buildId)} onClick={async () => {
        setLoading(true); setError(null);
        try {
          const value = { expected_digest: digest, run_ids: runIds, reason: reason.trim(), sample_id: mode === "reuse" ? sampleId : null, new_sample: mode === "create" ? { serial_number: serial.trim(), build_id: buildId, built_date: builtDate, prototype_bom_id: bomId || null, parent_sample_id: parentId || null, notes: notes.trim() || null } : null };
          const signature = JSON.stringify(value);
          if (request.current?.signature !== signature) request.current = { signature, id: crypto.randomUUID() };
          await onResolve({ ...value, request_id: request.current.id });
        } catch (e) { setError(e instanceof Error ? e.message : "样机办理未完成，请重试原请求"); } finally { setLoading(false); }
      }}>{mode === "create" ? "确认新建并绑定样机" : "确认复用并绑定样机"}</Button>
    </>}
    {data && !data.allowed && <p>当前批次已停止补缺，请刷新查看后续版本或确认回执。</p>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </div>;
}
