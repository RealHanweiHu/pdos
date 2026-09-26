"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { BUILD_PURPOSE_LABELS, createBuild, fetchBuildOptions, type BuildPurpose } from "./project-npi-api";

const input = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
export function ProjectBuildCreate({ projectId, busy, onCreated }: {
  projectId: string; busy: boolean; onCreated: () => Promise<void>;
}) {
  const [stages, setStages] = useState<Awaited<ReturnType<typeof fetchBuildOptions>>["stages"] | null>(null);
  const [stageId, setStageId] = useState(""), [purpose, setPurpose] = useState<BuildPurpose>("engineering_build");
  const [code, setCode] = useState(""), [quantity, setQuantity] = useState(""), [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false), [error, setError] = useState<string | null>(null), [receipt, setReceipt] = useState<string | null>(null);
  const blocked = busy || loading;
  const stage = stages?.find(s => s.id === stageId);
  async function load() {
    setLoading(true); setError(null);
    try { const result = await fetchBuildOptions(projectId); setStages(result.stages); }
    catch (e) { setError(e instanceof Error ? e.message : "项目阶段暂不可用"); }
    finally { setLoading(false); }
  }
  return <details className="rounded-md border p-3">
    <summary className="cursor-pointer text-sm font-medium">登记试制批次</summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs text-muted-foreground">按真实批次编号、项目阶段及用途登记，保存后可建立样机档案。</p>
      {!stages && <Button type="button" size="sm" variant="outline" disabled={blocked} onClick={() => void load()}>读取项目阶段</Button>}
      {stages && stages.length === 0 && <p className="text-sm">项目尚无 EVT、DVT 或 PVT 阶段，请先完成项目流程配置。</p>}
      {stages && stages.length > 0 && <form className="space-y-3" onSubmit={async event => {
        event.preventDefault(); if (!stage || blocked) return;
        setLoading(true); setError(null); setReceipt(null);
        try {
          const result = await createBuild(projectId, { stage_id: stage.id, phase: stage.code, purpose, code: code.trim(), planned_quantity: Number(quantity), notes: notes.trim() || null });
          if (!isRecord(result) || typeof result.id !== "string" || typeof result.code !== "string") throw new Error("未取得完整回执，请先刷新批次列表核对");
          setReceipt(`已登记批次 ${result.code}，可在列表中建立样机。`);
          setCode(""); setQuantity(""); setNotes("");
          await onCreated();
        } catch (e) { setError(`${e instanceof Error ? e.message : "登记未完成"}。输入已保留；如未收到回执，请先刷新批次列表核对。`); }
        finally { setLoading(false); }
      }}>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs">真实批次编号<input required maxLength={64} className={input} value={code} disabled={blocked} onChange={e => setCode(e.target.value)} /></label>
          <label className="text-xs">所属阶段<select required className={input} value={stageId} disabled={blocked} onChange={e => setStageId(e.target.value)}><option value="">请选择项目阶段</option>{stages.map(s => <option key={s.id} value={s.id}>{s.code.toUpperCase()} · {s.name}</option>)}</select></label>
          <label className="text-xs">批次用途<select className={input} value={purpose} disabled={blocked} onChange={e => setPurpose(e.target.value as BuildPurpose)}>{Object.entries(BUILD_PURPOSE_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label className="text-xs">计划数量（台）<input required type="number" min={1} max={2147483647} step={1} className={input} value={quantity} disabled={blocked} onChange={e => setQuantity(e.target.value)} /></label>
        </div>
        <label className="block text-xs">备注<textarea maxLength={20000} className={input} value={notes} disabled={blocked} onChange={e => setNotes(e.target.value)} /></label>
        <Button type="submit" size="sm" disabled={blocked || !stage || !code.trim() || !Number.isSafeInteger(Number(quantity)) || Number(quantity) < 1}>登记批次</Button>
      </form>}
      <Button type="button" size="sm" variant="outline" disabled={blocked} onClick={async () => { setLoading(true); try { await onCreated(); } finally { setLoading(false); } }}>刷新批次列表</Button>
      {receipt && <p role="status" className="text-sm">{receipt}</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
  </details>;
}
