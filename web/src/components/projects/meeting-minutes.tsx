"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { AiMeetingEventHistory } from "./ai-meeting-event-history";
import { AiMeetingDrafts } from "./ai-meeting-drafts";
import { isRecord, responseBody } from "@/components/workspace-api";

const input = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
function text(value: unknown): string { if (typeof value !== "string") throw new Error("纪要资料不完整"); return value; }
function id(value: unknown): string { const result = text(value); if (!/^[0-9a-f-]{36}$/.test(result)) throw new Error("纪要来源标识不完整"); return result; }
function number(value: unknown): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("纪要版本不完整"); return value; }
function list(value: unknown): unknown[] { if (!Array.isArray(value)) throw new Error("纪要清单不完整"); return value; }
type Citation = { transcript_id: string; segment_id: string; expected_digest: string; exact_quote: string; sequence: number };
function citationKey(value: Citation): string { return JSON.stringify([value.segment_id, value.exact_quote]); }
function citation(value: unknown): Citation {
  if (!isRecord(value)) throw new Error("纪要原句引用不完整");
  return { transcript_id: id(value.transcript_id), segment_id: id(value.segment_id), expected_digest: text(value.source_digest), exact_quote: text(value.exact_quote), sequence: number(value.sequence) };
}
function parse(value: unknown) {
  if (!isRecord(value) || typeof value.editable !== "boolean") throw new Error("正式纪要资料不完整");
  return { current: number(value.current_version), next: value.next_before === null ? null : number(value.next_before), editable: value.editable,
    sources: list(value.sources).map(row => { if (!isRecord(row)) throw new Error("转写来源不完整"); return { id: id(row.id), time: text(row.uploaded_at), count: number(row.segment_count), superseded: row.superseded_at !== null }; }),
    items: list(value.items).map(row => {
      if (!isRecord(row) || typeof row.source_current !== "boolean") throw new Error("纪要版本资料不完整");
      return { findingId: row.source_finding_id === null ? null : id(row.source_finding_id), id: id(row.id), version: number(row.version_no), body: text(row.body), unresolved: text(row.unresolved_points), reason: text(row.reason), name: text(row.confirmed_by), time: text(row.confirmed_at), current: row.source_current, citations: list(row.citations).map(citation) };
    }),
  };
}
type Data = ReturnType<typeof parse>;
type Draft = { expected: number; body: string; unresolved: string; reason: string; citations: Citation[] };
function parseSource(value: unknown) {
  if (!isRecord(value) || typeof value.source_complete !== "boolean") throw new Error("原句片段资料不完整");
  return { digest: text(value.digest), usable: value.source_complete && value.superseded === false,
    segments: list(value.segments).map(row => {
      if (!isRecord(row)) throw new Error("片段不完整");
      return { id: id(row.id), sequence: number(row.sequence), content: text(row.content), label: row.speaker_label === null ? "标签不明" : text(row.speaker_label), user: row.speaker_user_id === null ? null : id(row.speaker_user_id) };
    }),
    members: list(value.members).map(row => { if (!isRecord(row)) throw new Error("归属记录不完整"); return { id: id(row.id), name: text(row.display_name) }; }),
  };
}
type Source = ReturnType<typeof parseSource> & { id: string };
async function request(path: string, body?: object): Promise<unknown> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "纪要办理暂不可用，请刷新核对结果");
  return value;
}
function subscribeLocation(update: () => void) {
  window.addEventListener("popstate", update);
  return () => window.removeEventListener("popstate", update);
}

export function MeetingMinutes({ projectId, meetingId, canManage, isCompleted }: { projectId: string; meetingId: string; canManage: boolean; isCompleted: boolean }) {
  const minutesFocus = useSyncExternalStore(subscribeLocation, () => {
    const params = new URLSearchParams(window.location.search);
    const wanted = params.get("minutes");
    return params.get("meeting") === meetingId && wanted && (wanted === "all" || /^[0-9a-f-]{36}$/.test(wanted)) ? wanted : null;
  }, () => null);
  const focusedId = minutesFocus === "all" ? null : minutesFocus;
  const [data, setData] = useState<Data | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [segmentId, setSegmentId] = useState("");
  const [quote, setQuote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const draftPanels = useRef<HTMLDivElement>(null);
  const retry = useRef<{ signature: string; id: string } | null>(null);
  const path = `/api/projects/${projectId}/meetings/${meetingId}`;
  const readPath = `${path}/minutes${focusedId ? `?record_id=${focusedId}` : ""}`;
  useEffect(() => {
    if (!minutesFocus) return;
    let current = true;
    async function loadLinkedVersion() {
      try {
        const next = parse(await request(readPath));
        if (current) { setData(next); setError(null); }
      } catch (failure) {
        if (current) { setData(null); setError(failure instanceof Error ? failure.message : "指定纪要读取失败"); }
      }
    }
    void loadLinkedVersion();
    return () => { current = false; };
  }, [minutesFocus, readPath]);
  async function load() { setData(parse(await request(readPath))); }
  async function older() {
    if (!data?.next) return;
    const next = parse(await request(`${path}/minutes?before_version=${data.next}`));
    if (next.current !== data.current) throw new Error("正式纪要已有更新，请刷新后查看完整版本");
    setData({ ...data, next: next.next, items: [...data.items, ...next.items.filter(row => !data.items.some(item => item.id === row.id))] });
  }
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await work(); } catch (error) { setError(error instanceof Error ? error.message : "纪要办理未完成"); } finally { setBusy(false); }
  }
  async function loadSource(value: string) {
    if (!value) { setSource(null); setSegmentId(""); setQuote(""); return; }
    const loaded = parseSource(await request(`${path}/transcripts/${value}`));
    setSource({ ...loaded, id: value }); setSegmentId(""); setQuote("");
  }
  function begin() {
    if (!data) return;
    const latest = data.items.find(item => item.version === data.current);
    setDraft({ expected: data.current, body: latest?.body ?? "", unresolved: latest?.unresolved ?? "", reason: "", citations: latest?.citations ?? [] });
    setSource(null); setSegmentId(""); setQuote(""); setNotice(null);
  }
  async function confirm() {
    if (!draft) return;
    const body = { expected_version: draft.expected, body: draft.body, unresolved_points: draft.unresolved, reason: draft.reason,
      citations: draft.citations.map(({ sequence, ...entry }) => { void sequence; return entry; }) };
    const signature = JSON.stringify(body);
    if (retry.current?.signature !== signature) retry.current = { signature, id: crypto.randomUUID() };
    const result = await request(`${path}/minutes`, { ...body, request_id: retry.current.id });
    if (!isRecord(result)) throw new Error("纪要确认回执不完整，请刷新核对");
    setNotice(`第 ${number(result.version)} 版正式纪要已确认。决定、行动及其他业务记录仍需各自办理。`);
    setDraft(null); await load();
  }
  const segment = source?.segments.find(item => item.id === segmentId);
  const editable = canManage && isCompleted && data?.editable && !busy && !focusedId;
  return <><AiMeetingEventHistory projectId={projectId} meetingId={meetingId} onOpenDrafts={kind => {
    const panel = draftPanels.current?.querySelector<HTMLDetailsElement>(`[data-draft-kind="${kind}"] details`);
    if (panel) { panel.open = true; panel.scrollIntoView?.({ behavior: "smooth", block: "nearest" }); }
  }} /><div ref={draftPanels} className="contents"><div className="contents" data-draft-kind="minutes"><AiMeetingDrafts key={`${projectId}:${meetingId}`} projectId={projectId} meetingId={meetingId} onPublished={async () => { await load(); }} /></div><div className="contents" data-draft-kind="actions"><AiMeetingDrafts key={`${projectId}:${meetingId}:actions`} kind="actions" projectId={projectId} meetingId={meetingId} onPublished={async () => { await load(); }} /></div><div className="contents" data-draft-kind="decisions"><AiMeetingDrafts key={`${projectId}:${meetingId}:decisions`} kind="decisions" projectId={projectId} meetingId={meetingId} onPublished={async () => { await load(); }} /></div></div><details open={minutesFocus ? true : undefined} className="rounded-lg border p-2 sm:p-3" onToggle={event => { if (event.currentTarget.open && !data && !busy && !minutesFocus) void act(load); }}>
    <summary className="cursor-pointer text-sm font-medium">正式纪要与确认版本</summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs text-muted-foreground">手工编写会议讨论、结论及未决事项，选取对应转写原句后具名确认。每次修订保留旧版，纪要确认不会替代决定批准或行动分派。</p>
      {focusedId && <p className="text-xs text-muted-foreground">正在回查链接指定的正式纪要，刷新保留原版本。<a className="ml-2 text-primary underline" href={`/projects?project=${projectId}&tab=decisions&meeting=${meetingId}&minutes=all`}>查看全部纪要版本</a></p>}
      <div className="flex gap-2"><Button size="sm" variant="outline" disabled={busy || !!draft} onClick={() => void act(load)}>刷新正式纪要</Button>{editable && !draft && <Button size="sm" onClick={begin}>{data.current ? "基于当前版本修订" : "编写正式纪要"}</Button>}</div>
      {!isCompleted && <p className="text-xs text-muted-foreground">会议结束且未归档时可确认正式纪要。</p>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}{notice && <p role="status" className="text-xs">{notice}</p>}
      {draft && <form className="space-y-3 rounded-lg border p-3" onSubmit={event => { event.preventDefault(); void act(confirm); }}>
        <p className="text-xs">基于第 {draft.expected} 版编写；保存后形成第 {draft.expected + 1} 版。</p>
        <label className="block text-sm">讨论与结论<textarea required className={`${input} min-h-48`} maxLength={20000} disabled={!editable} value={draft.body} onChange={event => setDraft({ ...draft, body: event.target.value })} /></label>
        <label className="block text-sm">未决事项与待补证内容（如无，请明确写明）<textarea required className={input} maxLength={5000} disabled={!editable} value={draft.unresolved} onChange={event => setDraft({ ...draft, unresolved: event.target.value })} /></label>
        <section className="space-y-3 rounded-md bg-muted/30 p-3"><h4 className="text-sm font-medium">选取原句依据</h4>
          <select aria-label="选择纪要转写来源" className={input} disabled={!editable} value={source?.id ?? ""} onChange={event => void act(() => loadSource(event.target.value))}><option value="">选择本次会议转写</option>{data?.sources.filter(item => !item.superseded).map(item => <option key={item.id} value={item.id}>{new Date(item.time).toLocaleString("zh-CN")} · {item.count} 个片段</option>)}</select>
          {source && !source.usable && <p className="text-xs text-destructive">该转写原文或片段尚不完整，不能用于确认。</p>}
          {source?.usable && <>
            <select aria-label="选择引用片段" className={input} disabled={!editable} value={segmentId} onChange={event => { setSegmentId(event.target.value); setQuote(Array.from(source.segments.find(item => item.id === event.target.value)?.content ?? "").slice(0, 2000).join("")); }}><option value="">选择片段</option>{source.segments.map(item => <option key={item.id} value={item.id}>片段 {item.sequence} · {item.label}</option>)}</select>
            {segment && <><p className="text-xs">当前发言人：{segment.label} · {segment.user ? source.members.find(item => item.id === segment.user)?.name ?? "历史项目成员" : "身份未绑定"}</p><blockquote className="max-h-48 overflow-auto whitespace-pre-wrap break-words border-l-2 pl-3 text-sm">{segment.content}</blockquote><label className="block text-xs">用于纪要的原句摘录<textarea className={input} maxLength={2000} disabled={!editable} value={quote} onChange={event => setQuote(event.target.value)} /></label>
              <Button type="button" size="sm" variant="outline" disabled={!editable || !quote.trim() || !segment.content.includes(quote) || draft.citations.length >= 100 || draft.citations.some(item => item.segment_id === segment.id && item.exact_quote === quote)} onClick={() => setDraft({ ...draft, citations: [...draft.citations, { transcript_id: source.id, segment_id: segment.id, expected_digest: source.digest, exact_quote: quote, sequence: segment.sequence }] })}>将本句列为依据</Button></>}
          </>}
        </section>
        <div className="space-y-2"><h4 className="text-sm font-medium">本版引用 · {draft.citations.length} 处</h4>{draft.citations.map(entry => {
          const currentSegment = source?.id === entry.transcript_id ? source.segments.find(item => item.id === entry.segment_id) : null;
          const changed = source?.id === entry.transcript_id && source.digest !== entry.expected_digest;
          return <div key={citationKey(entry)} className="space-y-2 rounded-md border p-2"><p className="whitespace-pre-wrap text-xs">片段 {entry.sequence}：{entry.exact_quote}</p>
            {changed && <p className="text-xs text-destructive">该转写或说话人校正已有变化，请复查后重新确认本句依据。</p>}
            {currentSegment && <p className="text-xs text-muted-foreground">当前标签：{currentSegment.label} · {currentSegment.user ? source?.members.find(member => member.id === currentSegment.user)?.name ?? "历史项目成员" : "身份未绑定"}</p>}
            <div className="flex gap-2">{changed && source?.usable && currentSegment?.content.includes(entry.exact_quote) && <Button type="button" size="sm" variant="outline" disabled={!editable} onClick={() => setDraft({ ...draft, citations: draft.citations.map(item => citationKey(item) === citationKey(entry) ? { ...item, expected_digest: source.digest } : item) })}>已核对本句及说话人</Button>}<Button type="button" size="sm" variant="outline" disabled={!editable} onClick={() => setDraft({ ...draft, citations: draft.citations.filter(item => citationKey(item) !== citationKey(entry)) })}>移除此引用</Button></div>
          </div>;
        })}</div>
        <label className="block text-sm">确认或修订理由<textarea required className={input} maxLength={3000} disabled={!editable} value={draft.reason} onChange={event => setDraft({ ...draft, reason: event.target.value })} /></label>
        <div className="flex gap-2"><Button size="sm" disabled={!editable || !draft.body.trim() || !draft.unresolved.trim() || !draft.reason.trim() || !draft.citations.length}>确认本版正式纪要</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setDraft(null)}>放弃本次编辑</Button></div>
      </form>}
      {!draft && source && segment && <section className="space-y-2 rounded-md bg-muted/30 p-3"><h4 className="text-sm font-medium">当前引用原文 · 片段 {segment.sequence}</h4><p className="text-xs">当前标签：{segment.label} · {segment.user ? source.members.find(member => member.id === segment.user)?.name ?? "历史项目成员" : "身份未绑定"}</p><blockquote className="max-h-64 overflow-auto whitespace-pre-wrap break-words border-l-2 pl-3 text-sm">{segment.content}</blockquote>{(!source.usable || !segment.content.includes(quote)) && <p className="text-xs text-destructive">当前来源不可用于新确认，或本版引用已无法与原句对应。</p>}<p className="text-xs text-muted-foreground">这里展示当前来源；各纪要版本中的原句摘录保持原确认记录。</p></section>}
      {data?.items.length === 0 && <p className="text-xs text-muted-foreground">尚无已确认的正式纪要。</p>}
      {data?.items.map(entry => <details key={entry.id} open={entry.id === focusedId ? true : undefined} className="rounded-lg border p-2 sm:p-3"><summary className="cursor-pointer text-sm">第 {entry.version} 版{entry.version === data.current ? " · 当前版本" : " · 历史版本"} · {entry.name} · {new Date(entry.time).toLocaleString("zh-CN")}</summary><div className="mt-3 space-y-3">
        {!entry.current && <p className="text-xs text-destructive">本版引用的来源已变化或失效。原确认历史保留；继续使用前请复核并修订。</p>}
        {entry.findingId && <a className="text-xs text-primary underline" href={`/ai-review?finding=${entry.findingId}`}>查看模型建议、独立接受与应用回执</a>}<p className="whitespace-pre-wrap text-sm">{entry.body}</p><div className="text-sm"><h4 className="font-medium">未决事项</h4><p className="whitespace-pre-wrap">{entry.unresolved}</p></div><p className="whitespace-pre-wrap text-xs text-muted-foreground">确认依据：{entry.reason}</p>
        <details className="rounded-md bg-muted/30 p-2"><summary className="cursor-pointer text-xs">本版引用的原句 · {entry.citations.length} 处</summary><ul className="mt-2 space-y-2 text-xs">{entry.citations.map(item => <li key={citationKey(item)} className="space-y-1"><p className="whitespace-pre-wrap">片段 {item.sequence}：{item.exact_quote}</p><Button size="sm" variant="outline" disabled={busy || !!draft} onClick={() => void act(async () => { await loadSource(item.transcript_id); setSegmentId(item.segment_id); setQuote(item.exact_quote); })}>核对当前完整原句</Button></li>)}</ul></details>
      </div></details>)}
      {data?.next && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(older)}>查看更多历史版本</Button>}
    </div>
  </details></>;
}
