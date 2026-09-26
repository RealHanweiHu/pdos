"use client";

import { isRecord } from "@/components/workspace-api";
import { Button } from "@/components/ui/button";

function value(source: Record<string, unknown>, key: string): string { return typeof source[key] === "string" ? source[key] : ""; }
export function minutesProposalReady(payload: Record<string, unknown>): boolean {
  return ["title", "body", "unresolved_points"].every(key => value(payload, key).trim())
    && isRecord(payload.base_snapshot) && typeof payload.base_version === "number"
    && Array.isArray(payload.citations) && payload.citations.length > 0;
}
export function MeetingMinutesProposalView({ projectId, payload, onChange }: {
  projectId: string; payload: Record<string, unknown>; onChange?: (next: Record<string, unknown>) => void;
}) {
  const base = isRecord(payload.base_snapshot) ? payload.base_snapshot : {};
  const citations = Array.isArray(payload.citations) ? payload.citations.filter(isRecord) : [];
  const meetingId = value(payload, "meeting_id");
  const fields = [{ key: "body", label: "纪要正文", limit: 20000 }, { key: "unresolved_points", label: "未决事项", limit: 5000 }];
  return <div className="space-y-4 p-4 text-sm">
    <p className="text-xs text-muted-foreground">将基于第 {String(payload.base_version ?? "未知")} 版生成正式纪要新版本。接受建议与应用分别办理；决定、行动及其他业务对象不随纪要应用自动创建或批准。</p>
    {onChange ? <label className="block text-xs">候选标题<input className="mt-1 w-full rounded-md border bg-background p-2 text-sm" maxLength={512} value={value(payload, "title")} onChange={event => onChange({ ...payload, title: event.target.value })} /></label> : <h4 className="font-medium">{value(payload, "title")}</h4>}
    {fields.map(field => <section key={field.key} className="space-y-2"><h4 className="text-xs font-medium">{field.label}</h4><div className="grid gap-3 sm:grid-cols-2"><div className="rounded-lg bg-muted/40 p-3"><p className="mb-2 text-xs text-muted-foreground">当前已确认版本</p><p className="whitespace-pre-wrap break-words">{value(base, field.key) || "尚无已确认内容"}</p></div><div className="rounded-lg border p-3"><p className="mb-2 text-xs text-muted-foreground">本次建议</p>{onChange ? <textarea aria-label={`修改${field.label}`} className="min-h-32 w-full rounded-md border bg-background p-2 text-sm" maxLength={field.limit} value={value(payload, field.key)} onChange={event => onChange({ ...payload, [field.key]: event.target.value })} /> : <p className="whitespace-pre-wrap break-words">{value(payload, field.key)}</p>}</div></div></section>)}
    <section className="space-y-2"><h4 className="text-xs font-medium">本稿原句引用 · {citations.length} 处</h4>{citations.map((quote, index) => <blockquote key={`${value(quote, "segment_id")}:${index}`} className="space-y-2 border-l-2 pl-3"><p className="whitespace-pre-wrap break-words text-xs">{value(quote, "exact_quote")}</p>{onChange && <Button size="sm" type="button" variant="outline" disabled={citations.length <= 1} onClick={() => onChange({ ...payload, citations: citations.filter((_, position) => position !== index) })}>移除此引用</Button>}</blockquote>)}
      {/^[0-9a-f-]{36}$/.test(meetingId) && <a className="text-xs text-primary underline" href={`/projects?project=${projectId}&tab=decisions&meeting=${meetingId}`}>打开会议，核对原文、说话人和正式纪要</a>}
    </section>
    {!minutesProposalReady(payload) && <p className="text-xs text-destructive">正文、未决事项、版本或原句引用不完整，请补齐再接受。</p>}
  </div>;
}
