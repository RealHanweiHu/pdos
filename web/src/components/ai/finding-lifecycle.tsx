"use client";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

async function read(path: string): Promise<Record<string, unknown>> {
  const response = await fetch(`/api/ai/findings/${path}`, { cache: "no-store" });
  const value: unknown = await response.json();
  if (!response.ok || !isRecord(value)) throw new Error("当前无法读取归档规则或办理历史");
  return value;
}
export function FindingArchivePolicy() {
  const [policy, setPolicy] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  async function load() { setError(""); try { setPolicy(await read("archive-policy")); } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } }
  useEffect(() => { let active = true; void read("archive-policy").then(value => { if (active) setPolicy(value); }, () => { if (active) setError("归档规则暂不可用"); }); return () => { active = false; }; }, []);
  return <div className="mt-2 text-xs text-muted-foreground">{policy ? <p>自动归档配置：{policy.automatic_enabled === true ? "开启" : "关闭"}。定时扫描处理超过 {String(policy.ttl_days)} 天未裁决的建议；恢复后重新获得 {String(policy.ttl_days)} 天处理期。已接受待应用的建议保留。每次扫描最多 {String(policy.batch_size)} 条，其余由后续扫描继续处理，实际处理时间见建议历史。</p> : <p>正在读取归档规则…</p>}{error && <p role="alert">{error}<Button size="sm" variant="ghost" onClick={() => void load()}>重读规则</Button></p>}</div>;
}
const labels: Record<string, string> = { review_undone: "撤销裁决", created: "建立建议", accepted: "接受", rejected: "拒绝", applied: "独立应用", archived: "归档", restored: "恢复待审", pending_review: "待审" };
export function FindingLifecycle({ findingId }: { findingId: string }) {
  const [items, setItems] = useState<Record<string, unknown>[]>([]), [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [next, setNext] = useState<Record<string, unknown> | null>(null);
  async function load(more = false) {
    setLoaded(true); setBusy(true); setError("");
    try {
      const query = more && next ? `?before_at=${encodeURIComponent(String(next.before_at))}&before_id=${encodeURIComponent(String(next.before_id))}` : "";
      const result = await read(`${findingId}/lifecycle${query}`);
      if (!Array.isArray(result.items)) throw new Error("办理历史格式不完整");
      const page = result.items.filter(isRecord);
      setItems(old => more ? [...old, ...page.filter(row => !old.some(previous => previous.id === row.id))] : page); setNext(isRecord(result.next) ? result.next : null);
    } catch (e) { setError(e instanceof Error ? e.message : "读取历史失败"); }
    finally { setBusy(false); }
  }
  return <details className="w-full rounded-md border p-3 text-xs" onToggle={event => { if (event.currentTarget.open && !loaded && !busy) void load(); }}><summary className="cursor-pointer">归档、恢复与办理历史</summary><Button size="sm" variant="ghost" disabled={busy} onClick={() => void load()}>刷新历史</Button>{error && <p role="alert" className="text-destructive">{error}</p>}{loaded && !busy && !error && !items.length && <p>暂无记录。</p>}{items.map(item => { const detail = isRecord(item.detail) ? item.detail : {}; return <div key={String(item.id)} className="mt-2 space-y-1 rounded-md border p-2"><p>{labels[String(item.action)] ?? String(item.action)} · {detail.automatic === true ? "系统按到期规则处理" : String(item.actor_name ?? "服务记录")} · {new Date(String(item.created_at)).toLocaleString("zh-CN")}</p><p>{labels[String(item.from_status)] ?? String(item.from_status ?? "未建立")} → {labels[String(item.to_status)] ?? String(item.to_status)}</p>{item.action === "archived" && <p>{String(detail.ttl_days ?? 14)} 天未裁决{detail.inactive_since ? `，本轮起算 ${new Date(String(detail.inactive_since)).toLocaleString("zh-CN")}` : ""}</p>}{item.action === "restored" && <p>重新进入待审队列；审阅和应用仍需核对当前依据。</p>}{item.action === "review_undone" && <details><summary>查看撤销前的裁决与人工稿</summary><p>原裁决时间：{String(detail.reviewed_at ?? "未记录")}；窗口 {String(detail.window_seconds ?? 5)} 秒。</p><p>{String(detail.review_comment ?? "未填写原裁决说明")}</p>{isRecord(detail.accepted_payload) && <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded border p-2">{JSON.stringify(detail.accepted_payload, null, 2)}</pre>}</details>}{typeof detail.comment === "string" && <p className="whitespace-pre-wrap">{detail.comment}</p>}</div>; })}{next && <Button size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>更早记录</Button>}</details>;
}
