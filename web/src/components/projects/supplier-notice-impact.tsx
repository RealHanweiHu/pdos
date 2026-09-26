"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { noticeCall } from "./supplier-notice-applications";

export type NoticeAssessment = { conclusion: string; basis: string; next_action: string | null };
export type NoticeImpactDraft = { expected_basis_digest: string; source_responses: Record<string, NoticeAssessment>; assessments: Record<string, NoticeAssessment> };
export function useNoticeImpact(projectId: string, ecrId: string) {
  const [data, setData] = useState<Row | null>(null), [error, setError] = useState<string | null>(null), [loading, setLoading] = useState(true);
  const url = `/api/projects/${projectId}/npi/supplier-notices/ecrs/${ecrId}/impact`;
  useEffect(() => { let active = true; void noticeCall(url).then(value => { if (active) { setData(value); setError(null); } }).catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : "通告依据暂不可读取"); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [url]);
  const reload = useCallback(async () => { setLoading(true); setError(null); try { setData(await noticeCall(url)); } catch (e) { setData(null); setError(e instanceof Error ? e.message : "通告依据暂不可读取"); } finally { setLoading(false); } }, [url]);
  return { data, error, loading, reload };
}
export function NoticeImpactFields({ data, error, loading, reload, responses, onChange, busy }: { data: Row | null; error: string | null; loading: boolean; reload: () => Promise<void>; responses: Record<string, NoticeAssessment>; onChange: (value: Record<string, NoticeAssessment>) => void; busy: boolean }) {
  const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
  return <section className="space-y-2 rounded-md border p-3"><h5 className="text-sm font-medium">厂商通告影响依据</h5>{error && <p role="alert" className="text-destructive">{error}</p>}<Button type="button" size="sm" variant="outline" disabled={busy || loading} onClick={() => void reload()}>{loading ? "正在读取已关联通告…" : "重新读取当前通告依据"}</Button>
    {data && rows(data.sources).length===0 && <p className="text-xs text-muted-foreground">此变更尚无通告关联，沿原影响分析办理。</p>}
    {rows(data?.sources).map(source => { const id = text(source.application_id), notice = obj(source.notice), response = responses[id] || { conclusion: "", basis: "", next_action: "" }; const update = (patch: Partial<NoticeAssessment>) => onChange({ ...responses, [id]: { ...response, ...patch } }); return <fieldset className="space-y-2 rounded-md border p-3 text-xs" key={id}><legend>{text(notice.notice_identifier) || "通告来源"} · 人审 v{text(source.review_version)}</legend>{source.ready!==true ? <p>{text(source.error)}</p> : <><p>{text(notice.manufacturer)} / {text(notice.manufacturer_part_number)} · BOM {text(source.bom_code)} v{text(source.bom_version)}</p><p className="whitespace-pre-wrap">人审适用范围：{text(notice.applicable_scope)}</p><p className="whitespace-pre-wrap">人审影响：{text(notice.impact)}</p><p className="whitespace-pre-wrap">后续要求：{text(notice.follow_up)}</p>{rows(notice.dates).map(d => <p key={text(d.kind)}>{{ announced: "发布", effective: "生效", last_order: "最后下单", last_delivery: "最后交付" }[text(d.kind)] || text(d.kind)}：{text(d.value) || "未知／不适用"}；{text(d.basis)}</p>)}<p className="whitespace-pre-wrap">原应用依据：{text(source.reason)}</p>{source.revised_since_application===true && <p>人审在原应用后已有修订。本次分析采用当前已接受版本，原应用记录保留。</p>}
      <label className="block">本通告对在用件的影响<select required disabled={busy} className={field} value={response.conclusion} onChange={e => update({ conclusion: e.target.value })}><option value="">请选择</option><option value="affected">受影响，纳入实际BOM</option><option value="unaffected">无影响，有依据</option><option value="unknown">尚未明确</option></select></label><label className="block">分析判断及范围依据<textarea required maxLength={2048} disabled={busy} className={field} value={response.basis} onChange={e => update({ basis: e.target.value })}/></label><label className="block">后续处理{response.conclusion==="unaffected" ? "（可留空）" : "（必填）"}<textarea required={response.conclusion!=="unaffected"} maxLength={2048} disabled={busy} className={field} value={response.next_action ?? ""} onChange={e => update({ next_action: e.target.value })}/></label>
    </>}</fieldset>; })}
    {!!rows(data?.sources).length && <p className="text-xs text-muted-foreground">逐条回应后，继续完成下方九类影响分析及实际BOM选择。未知影响可提交待核对，批准前须明确。</p>}
  </section>;
}
