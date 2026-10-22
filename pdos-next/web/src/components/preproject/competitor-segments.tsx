"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import { canonical, clearSegmentJournal, competitorAssignmentPath, isCompetitorAssignment, persistSegmentJournal, readSegmentJournal, segmentCommand, segmentJournalKey, segmentKey, validSegmentPreview, validSegmentReceipt, type CompetitorAssignment, type FixedSegment, type SegmentCommand, type SegmentPreview, type SegmentReceipt } from "@/lib/competitor-segments";
import { ProposalSourceInspector } from "./proposal-source-inspector";
import styles from "./competitor-segments.module.css";

type Props = { categoryId: string; entryId: string; api: typeof browserApi; onSaved: () => void | Promise<void>; onClose: () => void };
export function CompetitorSegments(props: Props) {
  return <AssignmentReader key={`${props.categoryId}:${props.entryId}`} {...props}/>;
}
function AssignmentReader(props: Props) {
  const { api, categoryId, entryId } = props;
  const [loaded, setLoaded] = useState<{ api: typeof browserApi; value: CompetitorAssignment } | null>(null), [failure, setFailure] = useState<{ api: typeof browserApi; message: string } | null>(null), [attempt, setAttempt] = useState(0);
  const data = loaded?.api === api ? loaded.value : null, error = failure?.api === api ? failure.message : "";
  useEffect(() => {
    let active = true;
    void api<unknown>(competitorAssignmentPath(categoryId, entryId)).then(value => {
      if (!active) return;
      if (!isCompetitorAssignment(value, categoryId, entryId)) throw new Error("细分维护资料与当前品类、竞品不一致，或内容不完整。");
      setLoaded({ api, value }); setFailure(null);
    }).catch(failure => { if (active) { setLoaded(null); setFailure({ api, message: (failure as Error).message }); } });
    return () => { active = false; };
  }, [api, categoryId, entryId, attempt]);
  return <section className={styles.editor} aria-label="维护竞品细分">
    <header className={styles.header}><h3>维护竞品细分</h3><Button type="button" variant="ghost" size="xs" onClick={props.onClose}>关闭细分维护</Button></header>
    {data ? <SegmentEditor key={`${data.category_id}:${data.competitor.id}:${data.principal_id}`} {...props} initial={data}/> : error ? <div className={styles.notice} role="alert"><p>{error}</p><Button type="button" size="xs" variant="outline" onClick={() => { setFailure(null); setAttempt(v => v + 1); }}>重新读取细分维护资料</Button></div> : <p className={styles.notice} role="status">正在读取竞品固定版本与可选细分…</p>}
  </section>;
}
function SegmentEditor({ initial, api, categoryId, onSaved, onClose }: Props & { initial: CompetitorAssignment }) {
  const principalId = initial.principal_id, lineageId = initial.competitor.lineage_id;
  const [data, setData] = useState<CompetitorAssignment | null>(initial), [selected, setSelected] = useState<FixedSegment[]>(initial.selected_segments);
  const [prepared, setPrepared] = useState<SegmentPreview | null>(null), [previewRequest, setPreviewRequest] = useState<SegmentCommand | null>(null), [pending, setPending] = useState<SegmentCommand | null>(null);
  const [checked, setChecked] = useState(false), [blocked, setBlocked] = useState(false), [rejected, setRejected] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(""), [receipt, setReceipt] = useState<SegmentReceipt | null>(null);
  const live = useRef(false), active = useRef(false), generation = useRef(0);
  const valid = (own: number) => live.current && generation.current === own;
  useEffect(() => {
    live.current = true;
    const own = ++generation.current;
    void Promise.resolve().then(() => {
      if (!live.current || generation.current !== own) return;
      try {
        const raw = window.sessionStorage.getItem(segmentJournalKey(principalId, categoryId, lineageId));
        if (raw) { setPending(readSegmentJournal(raw, principalId, categoryId, lineageId)); setError("找到待核对的原保存请求；不会自动发送，请本人核对原请求取得回执。"); }
      } catch (failure) { setBlocked(true); setError((failure as Error).message); }
      setChecked(true);
    });
    const epoch = generation;
    return () => { live.current = false; epoch.current++; };
  }, [principalId, categoryId, lineageId]);

  function failure(failed: unknown) {
    const value = failed as Error & { status?: number; code?: string };
    setError(value.message);
    if (value.status === 401 || value.status === 403 || ["SOURCE_UNAVAILABLE", "SOURCE_STALE"].includes(value.code ?? "")) { setData(null); setSelected([]); setPrepared(null); setPreviewRequest(null); }
  }
  async function readCurrent(entryId: string, own: number) {
    setData(null); setSelected([]); setPrepared(null); setPreviewRequest(null);
    const value = await api<unknown>(competitorAssignmentPath(categoryId, entryId));
    if (!valid(own)) return;
    if (!isCompetitorAssignment(value, categoryId, entryId) || value.principal_id !== principalId || value.competitor.lineage_id !== lineageId) throw new Error("返回资料与本次本人身份或竞品谱系不一致，请关闭后重新打开。");
    setData(value); setSelected(value.selected_segments);
  }
  async function refresh() {
    if (active.current) return;
    active.current = true; setBusy(true); setError("");
    const own = ++generation.current;
    try { await readCurrent(receipt?.result.entry_id ?? data?.competitor.id ?? initial.competitor.id, own); }
    catch (value) { if (valid(own)) failure(value); }
    finally { if (valid(own)) { active.current = false; setBusy(false); } }
  }
  async function preview(command: SegmentCommand) {
    if (active.current || pending || blocked || !checked || !data?.can_edit) return;
    active.current = true; setBusy(true); setError(""); setPreviewRequest(command);
    const own = generation.current;
    try {
      const value = await api<unknown>(`v1/categories/${categoryId}/commands/preview`, command);
      if (!valid(own)) return;
      if (!validSegmentPreview(value, command)) throw new Error("返回预览与本次固定细分、完整竞品内容不一致，请重试原预览。");
      setPrepared(value); setPreviewRequest(null);
    } catch (value) { if (valid(own)) failure(value); }
    finally { if (valid(own)) { active.current = false; setBusy(false); } }
  }
  async function save(command: SegmentCommand) {
    if (active.current || blocked || !checked || (pending ? !data : !data?.can_edit) || rejected) return;
    active.current = true; setBusy(true); setError("");
    const own = generation.current;
    try {
      // Session storage is only a sealed request journal, never a saved business fact.
      // Persistence must succeed before the first POST, including an explicit retry.
      persistSegmentJournal(window.sessionStorage, command, principalId);
      setPending(command); setPrepared(null); setPreviewRequest(null);
      const value = await api<unknown>(`v1/categories/${categoryId}/commands`, command);
      if (!valid(own)) return;
      if (!validSegmentReceipt(value, command)) throw new Error("尚未取得与原请求一致的保存回执，请核对原保存请求。");
      setReceipt(value); setRejected(false);
      try { clearSegmentJournal(window.sessionStorage, command, principalId); setPending(null); }
      catch (err) { setError(`保存已成功；${(err as Error).message}`); }
      const parentFinished = Promise.resolve().then(onSaved).catch(() => { if (valid(own)) setError("保存已成功；竞品列表或矩阵刷新失败，请刷新品类资料。"); });
      try { await readCurrent(value.result.entry_id, own); }
      catch (err) { if (valid(own)) { failure(err); setError(`保存已成功；最新竞品资料读取失败：${(err as Error).message}`); } }
      await parentFinished;
    } catch (err) {
      if (valid(own)) {
        failure(err);
        const failed = err as Error & { status?: number; code?: string; detail?: { reason?: string } };
        const reason = failed.detail?.reason;
        // These exact host errors occur after both original receipt indexes are checked.
        if (failed.status === 409 && ((failed.code === "CONFIRMATION_REQUIRED" && ["CONFIRMATION_REQUIRED", "CONFIRMATION_SCOPE_CHANGED"].includes(reason ?? "")) || (failed.code === "VERSION_CONFLICT" && reason === "material_version_moved"))) { setRejected(true); setPrepared(null); setPreviewRequest(null); }
      }
    } finally { if (valid(own)) { active.current = false; setBusy(false); } }
  }
  async function endRejected() {
    if (active.current || !pending || !rejected) return;
    active.current = true; setBusy(true); setError("");
    try { clearSegmentJournal(window.sessionStorage, pending, principalId); await onSaved(); if (live.current) onClose(); }
    catch (err) { if (live.current) failure(err); }
    finally { if (live.current) { active.current = false; setBusy(false); } }
  }
  const choices = [...new Map([...(data?.selected_segments ?? []), ...(data?.segments ?? [])].map(item => [segmentKey(item), item])).values()];
  const previewRefs = (prepared?.command.payload.content.segment_refs ?? []) as { entry_id: string; version: number }[];
  const locked = !checked || blocked || busy || !!pending || !!prepared;
  const changed = canonical(selected.map(({ entry_id, version }) => ({ entry_id, version })).sort((a, b) => segmentKey(a).localeCompare(segmentKey(b)))) !== canonical((data?.selected_segments ?? []).map(({ entry_id, version }) => ({ entry_id, version })).sort((a, b) => segmentKey(a).localeCompare(segmentKey(b))));
  return <div className={styles.body}>
    {receipt && <p className={styles.success} role="status">人工续版已保存 · v{receipt.result.version} · 回执 {receipt.id}。旧版本与原作者记录保留。</p>}
    {error && <p className={styles.notice} role="alert">{error}</p>}
    {pending && <div className={styles.recovery}><p>{rejected ? "服务器已明确拒绝原保存请求，未取得成功回执。" : "原保存结果待核对；新编辑已暂停。"} 固定基版 v{pending.expected_revision}。</p><p className={styles.ids}>请求 {pending.command_id}</p>{rejected ? <Button type="button" variant="outline" size="xs" disabled={busy} onClick={() => void endRejected()}>结束已拒绝请求并刷新列表</Button> : <Button type="button" variant="outline" size="xs" disabled={busy || !data || blocked} onClick={() => void save(pending)}>核对原保存请求</Button>}<small>核对沿用原请求与幂等标识，不生成新保存请求。</small></div>}
    {!data ? <div className={styles.notice}><p>当前竞品正文未展示，请重新读取当前权限与来源。</p><Button type="button" variant="outline" size="xs" disabled={busy} onClick={() => void refresh()}>重新读取当前竞品</Button></div> : <>
      <div className={styles.identity}><strong>{typeof data.competitor.content?.brand === "string" ? data.competitor.content.brand : "竞品正文不可读"} {typeof data.competitor.content?.model === "string" ? data.competitor.content.model : ""}</strong><span>当前读取 v{data.competitor.version} · {data.competitor.origin === "ai_draft" ? "AI 草稿" : data.competitor.origin === "human" ? "人工" : data.competitor.origin}</span></div>
      {!data.can_edit && <div className={styles.notice}><p>当前仅可查看，不能保存。</p>{data.blockers.map((item, index) => <p key={index}>{item.message}</p>)}</div>}
      <fieldset className={styles.choices} disabled={locked || !data.can_edit}><legend>选择固定细分版本</legend>{choices.map(item => {
        const selectedItem = selected.some(value => segmentKey(value) === segmentKey(item)), unavailable = item.status === "unavailable";
        return <div className={styles.choice} key={segmentKey(item)}><label><input type="checkbox" checked={selectedItem} disabled={unavailable && !selectedItem} onChange={event => { setSelected(previous => event.target.checked ? [...previous, item] : previous.filter(value => segmentKey(value) !== segmentKey(item))); setPreviewRequest(null); setError(""); }}/><span>{item.label ?? "固定细分不可读"} · v{item.version}{unavailable ? " · 可显式移除" : data.selected_segments.some(value => segmentKey(value) === segmentKey(item)) ? " · 原固定引用" : " · 可选版本"}</span></label><details><summary>固定引用与来源</summary><p className={styles.ids}>{item.entry_id} · v{item.version}</p>{item.source_refs.length > 0 && <ProposalSourceInspector sources={item.source_refs} label="细分来源"/>}</details></div>;
      })}{choices.length === 0 && <p>当前没有可读细分版本。</p>}</fieldset>
      <p className={styles.note}>历史引用不会自动换成 Current；移除或替换后须预览并本人确认。{data.unavailable_segment_count > 0 && `另有 ${data.unavailable_segment_count} 个细分不可读。`}</p>
      {data.competitor.content && <details className={styles.source}><summary>沿用的竞品内容与原作者</summary><p>本次仅更新细分引用；品牌型号、原价格、规格与来源完整沿用，不代表新实测。保存追加人工版本，旧版 AI 作者和原版本仍保留。</p><pre>{JSON.stringify(data.competitor.content, null, 2)}</pre><dl><dt>原作者</dt><dd>{data.competitor.writer_id ?? "未记录"}</dd><dt>原 Run</dt><dd>{data.competitor.run_id ?? "未记录"}</dd><dt>原确认人</dt><dd>{data.competitor.confirmed_by ?? "未记录"}</dd><dt>地区</dt><dd>{data.competitor.regions.join("、") || "未登记"}</dd></dl><ProposalSourceInspector sources={data.competitor.source_refs} label="竞品来源"/></details>}
      {prepared ? <div className={styles.preview}>
        <h4>人工续版预览</h4><p><strong>{String(prepared.command.payload.content.brand)} {String(prepared.command.payload.content.model)}</strong></p>
        <p>基版 v{prepared.command.expected_revision} → 人工新版本（保存后生效）。</p>
        <p>固定细分：</p>{previewRefs.length ? <ul>{previewRefs.map(ref => <li key={segmentKey(ref)}>{choices.find(item => segmentKey(item) === segmentKey(ref))?.label ?? "固定细分名称不可读"} · 固定 v{ref.version}</li>)}</ul> : <p>无细分关联（本次明确清空）。</p>}
        <p>原价格、规格和来源完整沿用；本次仅修改固定细分，不代表新实测。</p>
        <details className={styles.source}><summary>核对完整竞品内容、地区与来源</summary><pre>{JSON.stringify(prepared.command.payload.content, null, 2)}</pre><p>地区：{prepared.command.payload.regions.join("、") || "未登记"}</p><ProposalSourceInspector sources={prepared.command.payload.source_refs} label="沿用来源"/></details>
        <div className={styles.actions}><Button type="button" size="sm" disabled={busy} onClick={() => void save(prepared.command)}>本人确认保存细分</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => { setPrepared(null); setPreviewRequest(null); }}>返回调整细分</Button></div>
      </div> : data.can_edit && !pending && !blocked && <div className={styles.actions}>{previewRequest ? <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void preview(previewRequest)}>重试原细分预览</Button> : <Button type="button" size="sm" disabled={locked || !changed} onClick={() => { try { void preview(segmentCommand(data, selected)); } catch (err) { failure(err); } }}>预览细分续版</Button>}</div>}
    </>}
  </div>;
}
