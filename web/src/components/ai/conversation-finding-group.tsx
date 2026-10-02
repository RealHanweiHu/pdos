"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { requestFinding } from "./ai-api";
import type { AiFinding } from "./ai-types";
import { ConversationFinding } from "./conversation-finding";

const labels = { pending_review: "待审阅", accepted: "待独立应用", applied: "已应用", rejected: "已拒绝", archived: "已归档" };

export function ConversationFindingGroup({ findingIds }: { findingIds: string[] }) {
  const ids = [...new Set(findingIds)];
  return ids.length ? <FindingGroup key={JSON.stringify(ids)} ids={ids}/> : null;
}

function FindingGroup({ ids }: { ids: string[] }) {
  const [items, setItems] = useState<Record<string, AiFinding>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [uncertain, setUncertain] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false);
  const active = useRef(true), running = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function load(targets: string[]) {
    if (running.current) return;
    running.current = true; setBusy(true);
    const results = await Promise.allSettled(targets.map(id => requestFinding(id)));
    if (!active.current) return;
    setItems(old => { const next = { ...old }; results.forEach((r, i) => { if (r.status === "fulfilled") next[targets[i]] = r.value; }); return next; });
    setErrors(old => { const next = { ...old }; results.forEach((r, i) => { if (r.status === "rejected") next[targets[i]] = r.reason instanceof Error ? r.reason.message : "暂时无法读取"; else delete next[targets[i]]; }); return next; });
    setLoaded(true); setBusy(false); running.current = false;
  }
  function update(item: AiFinding) { setItems(old => ({ ...old, [item.id]: item })); setUncertain(old => old.filter(id => id !== item.id)); }
  const known = Object.values(items).filter(item => !uncertain.includes(item.id));
  const pending = known.filter(item => !item.superseded_by && ["pending_review", "accepted"].includes(item.status)).length;
  const applied = known.filter(item => item.status === "applied").length;
  const other = known.length - pending - applied;
  return <details className="space-y-3 rounded-lg border p-3" onToggle={e => { if (e.target === e.currentTarget && e.currentTarget.open && !loaded) void load(ids); }}>
    <summary className="cursor-pointer text-sm font-medium">本条消息的 {ids.length} 项候选与办理回执</summary>
    <p className="text-xs">各项独立接受和应用；某项失败不撤销其他项的实际结果。以下为最近核对的回执；展开候选可刷新当前裁决。已应用表示已登记业务对象，后续完成与验收仍以原对象为准。</p>
    {loaded && <p role="status" className="text-sm">待办理 {pending} · 已应用 {applied} · 已拒绝／归档／被替代 {other} · 状态未确认 {ids.length - known.length}</p>}
    {busy && <p role="status" className="text-xs">正在核对逐项回执…</p>}
    {Object.keys(errors).length > 0 && <Button size="sm" variant="outline" disabled={busy} onClick={() => void load(Object.keys(errors))}>重试未读到的回执</Button>}
    {ids.map((id, index) => {
      const item = items[id];
      return <div key={id} className="space-y-2 border-t pt-2">
        <p className="text-xs">候选 {index + 1} · {item && !uncertain.includes(id) ? item.superseded_by && item.status !== "applied" ? "已有新修订，保留原回执" : labels[item.status] : "状态未确认"}</p>
        {errors[id] && <p role="alert" className="text-xs text-destructive">{errors[id]}。其他候选可继续办理。</p>}
        {item && <ConversationFinding findingId={id} initialFinding={item} onLoaded={update} onRecorded={update} onUnconfirmed={() => setUncertain(old => [...new Set([...old, id])])}/>}
      </div>;
    })}
  </details>;
}
