"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { rows, text, type Row } from "@/components/quality/fmea-sources";
import { noticeCall, NoticeApplicationReceipt } from "./supplier-notice-applications";
import { SupplierNoticeReviews } from "./supplier-notice-reviews";

export function SupplierNoticeLinks({ projectId, targetKind, targetId }: { projectId: string; targetKind: "issue" | "ecr"; targetId: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function load(more = false) { setBusy(true); setError(""); try { const value = await noticeCall(`/api/projects/${projectId}/npi/supplier-notices/links?target_kind=${targetKind}&target_id=${targetId}${more && data?.next_before_id ? `&before_id=${data.next_before_id}` : ""}`); setData(old => more && old ? { ...value, items: [...rows(old.items), ...rows(value.items)] } : value); } catch (e) { setError(e instanceof Error ? e.message : "通告来源暂不可读取"); } finally { setBusy(false); } }
  return <details className="my-2 space-y-2 rounded-md border p-2 text-sm" onToggle={e => { if (e.currentTarget.open && !data && !busy) void load(); }}><summary className="cursor-pointer">通告来源与具名审阅</summary>{error && <p role="alert" className="text-destructive">{error}</p>}<Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>读取通告关联</Button>{data && rows(data.items).length===0 && <p className="text-xs">暂无当前可读取的通告关联。</p>}{rows(data?.items).map(item => <div className="space-y-2" key={text(item.id)}><NoticeApplicationReceipt projectId={projectId} value={item}/>{item.content_available!==false && <SupplierNoticeReviews projectId={projectId} candidateId={text(item.candidate_id)}/>}</div>)}{!!data?.next_before_id && <Button size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>更早20项关联</Button>}</details>;
}
