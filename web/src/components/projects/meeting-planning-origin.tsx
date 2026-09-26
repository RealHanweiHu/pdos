"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { MeetingPlanningReview } from "./meeting-planning-review";

export function MeetingPlanningOrigin({ projectId, meetingId }: { projectId: string; meetingId: string }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null), [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  async function load() {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/meetings/${meetingId}/planning-origin`, { cache: "no-store" });
      const value: unknown = await responseBody(response).catch(() => null);
      if (!response.ok || !isRecord(value) || !(value.origin === null || isRecord(value.origin))) throw new Error("创建来源暂不可读，请重试");
      setData(isRecord(value.origin) ? value.origin : null); setLoaded(true);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); }
  }
  return <details className="rounded-md border p-3 text-xs" onToggle={e => { if (e.currentTarget.open && !loaded && !busy) void load(); }}><summary className="cursor-pointer">会议草案创建来源</summary><div className="mt-2 space-y-2">{busy && <p>正在读取创建回执…</p>}{loaded && !data && <p>此会议没有临时 AI 草案创建回执。</p>}{data && <><p>{String(data.creator_name)} 于 {String(data.reviewed_at)} 接受人工稿，{String(data.applied_at)} 独立创建本会议。当前会议后续安排以实际会议记录为准。</p>{typeof data.own_finding_id === "string" && <MeetingPlanningReview projectId={projectId} findingId={data.own_finding_id}/>}</>}{error && <><p role="alert" className="text-destructive">{error}</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>重读创建来源</Button></>}</div></details>;
}
