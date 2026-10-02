"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowClockwiseIcon } from "@phosphor-icons/react";
import { isRecord } from "@/components/workspace-api";

type CurrentCheck = {
  projects: { id: string; code: string; name: string }[];
  selected_project_id: string;
  check: {
    state: "current" | "blocked" | "unavailable";
    checked_at: string;
    protocol_id: string | null;
    reasons: { code: string; message: string }[];
    fresh_check: { raw_total: number; verified_total: number; unverified_total: number } | null;
  };
};
const button = "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-md border bg-background px-3 text-xs outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
function parse(value: unknown): CurrentCheck {
  if (!isRecord(value) || !Array.isArray(value.projects) || !isRecord(value.check)) throw new Error("当前核对资料不完整，请重新读取。");
  const check = value.check;
  if (!["current", "blocked", "unavailable"].includes(String(check.state)) || check.qualification_granted !== false || typeof check.checked_at !== "string" || !Number.isFinite(Date.parse(check.checked_at)) || (check.protocol_id !== null && typeof check.protocol_id !== "string") || !Array.isArray(check.reasons)) throw new Error("当前核对结果不完整，请重新读取。");
  const projects = value.projects.map(item => {
    if (!isRecord(item) || typeof item.id !== "string" || typeof item.code !== "string" || typeof item.name !== "string") throw new Error("项目范围不完整，请重新读取。");
    return { id: item.id, code: item.code, name: item.name };
  });
  if (typeof value.selected_project_id !== "string" || !projects.some(project => project.id === value.selected_project_id)) throw new Error("当前核对项目不完整，请重新读取。");
  const reasons = check.reasons.map(item => {
    if (!isRecord(item) || typeof item.code !== "string" || typeof item.message !== "string") throw new Error("核对条件不完整，请重新读取。");
    return { code: item.code, message: item.message };
  });
  let fresh: CurrentCheck["check"]["fresh_check"] = null;
  if (check.fresh_check !== null) {
    const item = check.fresh_check;
    if (!isRecord(item) || ![item.raw_total, item.verified_total, item.unverified_total].every(number => typeof number === "number" && Number.isSafeInteger(number) && number >= 0)) throw new Error("当前原稿统计不完整，请重新读取。");
    fresh = { raw_total: item.raw_total as number, verified_total: item.verified_total as number, unverified_total: item.unverified_total as number };
  }
  return { projects, selected_project_id: value.selected_project_id, check: { state: check.state as CurrentCheck["check"]["state"], checked_at: check.checked_at, protocol_id: check.protocol_id, reasons, fresh_check: fresh } };
}

export function AiWriteTrialCurrent({ protocolId }: { protocolId: string }) {
  const [result, setResult] = useState<CurrentCheck | null>(null);
  const [projects, setProjects] = useState<CurrentCheck["projects"]>([]);
  const [project, setProject] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, [protocolId]);
  async function load(projectId = project) {
    const current = ++generation.current;
    setLoading(true); setResult(null); setError(null);
    try {
      const response = await fetch(`/api/ai/governance/write-policy/trials/${encodeURIComponent(protocolId)}/current-check${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`, { cache: "no-store", credentials: "same-origin" });
      if (!response.ok) {
        if ([401, 403].includes(response.status) && current === generation.current) { setProjects([]); setProject(""); }
        throw new Error(response.status === 403 ? "当前账号无权核对该范围。" : response.status === 401 ? "登录已失效，请重新登录。" : "当前材料核对未完成，请重试。");
      }
      const next = parse(await response.json());
      if (current === generation.current) { setResult(next); setProjects(next.projects); setProject(next.selected_project_id); }
    } catch (error) {
      if (current === generation.current) setError(error instanceof Error ? error.message : "当前材料核对未完成，请重试。");
    } finally { if (current === generation.current) setLoading(false); }
  }
  return <section aria-label="当前资格材料核对" className="rounded-lg border bg-muted/15 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><h5 className="text-xs font-medium">当前材料</h5><button type="button" className={button} disabled={loading} onClick={() => void load()}><ArrowClockwiseIcon aria-hidden="true" size={14} />{loading ? "正在核对…" : "核对当前材料"}</button></div>
    <p className="mt-2 text-xs leading-5 text-muted-foreground">按指定模型和项目重新读取后续办理及最新采集。只核对材料，不启用自动写入，原回执保持不变。</p>
    {projects.length > 1 && <label className="mt-3 block text-xs">核对项目<select value={project} disabled={loading} onChange={event => { setProject(event.target.value); void load(event.target.value); }} className="mt-1 min-h-9 w-full min-w-0 rounded-md border bg-background px-2.5 outline-none focus-visible:ring-2 focus-visible:ring-ring">{projects.map(item => <option key={item.id} value={item.id}>{item.name} · {item.code}</option>)}</select></label>}
    {loading && <p role="status" className="mt-3 text-xs text-muted-foreground">正在重新核对当前原稿与评测版本…</p>}
    {error && <p role="alert" className="mt-3 text-xs text-destructive">{error}</p>}
    {result && <div className="mt-3 space-y-2 text-xs leading-5">
      <p className="font-medium">{result.check.state === "current" ? "当前材料满足候选条件；本次核对不启用自动写入" : result.check.state === "unavailable" ? "当前材料暂时无法完整核实" : "当前材料仍有待满足条件"}</p>
      <p className="text-muted-foreground">{result.projects.find(item => item.id === result.selected_project_id)?.name} · 核对于 {new Date(result.check.checked_at).toLocaleString("zh-CN")}</p>
      {result.check.protocol_id && result.check.protocol_id !== protocolId && <p className="text-primary">已采用同项目、同模型版本的后续试运行材料；本页原回执仍保留。</p>}
      {result.check.fresh_check && <p>当前窗口内原稿 {result.check.fresh_check.raw_total} 份 · 来源已核实 {result.check.fresh_check.verified_total} 份 · 待核实 {result.check.fresh_check.unverified_total} 份</p>}
      {result.check.reasons.length > 0 && <ul aria-label="当前材料待满足条件" className="space-y-1 text-muted-foreground">{result.check.reasons.map(reason => <li key={reason.code}>· {reason.message}</li>)}</ul>}
    </div>}
  </section>;
}
