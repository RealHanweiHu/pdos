"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import type { AiFinding } from "./ai-types";
import { FindingBatchError, requestFindingBatch, type FindingBatchRequest, type FindingBatchResult } from "./ai-api";

export function FindingReviewUndo({ items, onRecorded }: { items: AiFinding[]; onRecorded: (result: FindingBatchResult) => void }) {
  const [clock, setClock] = useState(() => Date.now()), [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null), [pending, setPending] = useState<FindingBatchRequest | null>(null);
  const [finished, setFinished] = useState(false);
  const eligible = items.length > 0 && items.every(item => ["accepted", "rejected"].includes(item.status) && item.review_undo_until && !item.superseded_by);
  const deadline = eligible ? Math.min(...items.map(item => Date.parse(item.review_undo_until!))) : 0;
  useEffect(() => {
    if (!deadline) return;
    const timer = window.setInterval(() => { const now = Date.now(); setClock(now); if (now >= deadline) window.clearInterval(timer); }, 200);
    return () => window.clearInterval(timer);
  }, [deadline]);
  async function perform(request: FindingBatchRequest, readOnly = false) {
    setBusy(true); setError(null); setPending(request);
    try {
      const result = await requestFindingBatch(readOnly ? request.request_id : request);
      setPending(null); setFinished(true); onRecorded(result);
    } catch (failure) {
      if (!readOnly && failure instanceof FindingBatchError && [400, 403, 404, 409, 422].includes(failure.status)) { setPending(null); setFinished(true); }
      setError(failure instanceof Error ? failure.message : "撤销结果未确认，请核对原请求回执。");
    } finally { setBusy(false); }
  }
  if ((!eligible || deadline <= clock || finished) && !pending && !error) return null;
  return <div className="fixed bottom-4 left-4 right-4 z-50 space-y-2 rounded-lg border bg-background p-4 text-xs shadow-lg sm:left-auto sm:max-w-md" role="status">
    <p className="truncate font-semibold">{items[0]?.title}{items.length > 1 ? ` 等${items.length}条` : ""}</p>
    <p>本人裁决后5秒内可撤销{items.length > 1 ? `本组 ${items.length} 条` : "本次裁决"}，恢复待审；原裁决、人工稿和理由留在历史。已应用或有新修订时不能撤销。</p>
    {!pending && !finished && deadline > clock ? <Button size="sm" variant="outline" disabled={busy} onClick={() => void perform({ request_id: crypto.randomUUID(), action: "review_undone", comment: "撤销本人刚才的裁决，恢复待审", items: items.map(item => ({ finding_id: item.id, expected_updated_at: item.updated_at })) })}>撤销{items.length > 1 ? "本组裁决" : "本次裁决"}（{Math.ceil((deadline - clock) / 1000)}秒）</Button> : !pending && !finished ? <p>5秒撤销窗口已结束；请在原记录查看当前状态和后续办理。</p> : null}
    {error && <><p role="alert" className="text-destructive">{error}</p>{!pending && <Button size="sm" variant="ghost" onClick={() => { setError(null); setFinished(true); }}>知道了</Button>}</>}
    {pending && <><p className="break-all">原撤销请求：{pending.request_id}。结果未确认时保留此编号；重试复用原结果，不重新撤销新裁决。</p><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void perform(pending, true)}>读取撤销回执</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => void perform(pending)}>重试原撤销请求</Button></div></>}
  </div>;
}
