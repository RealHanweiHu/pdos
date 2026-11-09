"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowsClockwise, CheckCircle, FileArrowUp, Info, WarningCircle, XCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { BomConfiguration, PreparationApi } from "@/lib/build-preparation-view";
import { utcText } from "@/lib/project-plan-view";
import {
  actionTitles, changeTitles, fieldTitles, importCommand, importRequest, isDiff, isReview, isRuleCard, pendingRows, quantityText, ruleItemText, ruleStatusTitles, valueText,
  type BomDiff, type BomReview, type Disposition, type ImportColumn, type ImportResult, type RuleCard, type RuleStatus,
} from "@/features/builds/lib/bom-review";

const statusTone: Record<RuleStatus, string> = { pass: "text-muted-foreground", warn: "text-primary", fail: "text-destructive", not_applicable: "text-muted-foreground" };
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function StatusIcon({ status }: { status: RuleStatus }) {
  if (status === "fail") return <XCircle aria-hidden="true" className="shrink-0 text-destructive"/>;
  if (status === "warn") return <WarningCircle aria-hidden="true" className="shrink-0 text-primary"/>;
  if (status === "pass") return <CheckCircle aria-hidden="true" className="shrink-0 text-muted-foreground"/>;
  return <Info aria-hidden="true" className="shrink-0 text-muted-foreground"/>;
}

export function RuleCardView({ card }: { card: RuleCard }) {
  return <section className="min-w-0 space-y-2" aria-label="BOM 规则卡">
    <h4 className="flex items-center gap-2 text-sm font-medium"><StatusIcon status={card.status}/>BOM 规则卡 · {ruleStatusTitles[card.status]}</h4>
    <ul className="min-w-0 space-y-2 text-sm">{card.rules.map(rule => <li key={rule.code} className="min-w-0 rounded-lg border border-border p-2">
      <p className="flex items-start gap-2"><StatusIcon status={rule.status}/><span className="min-w-0"><span className="font-medium">{rule.title}</span> <span className={statusTone[rule.status]}>· {ruleStatusTitles[rule.status]}{rule.count ? ` · ${rule.count} 处` : ""}</span></span></p>
      {rule.items.length > 0 && <ul className="mt-1 space-y-0.5 pl-6 [overflow-wrap:anywhere]">{rule.items.slice(0, 20).map((item, index) => <li key={index}>{ruleItemText(rule, item)}</li>)}{rule.items.length > 20 && <li className="subtle">另有 {rule.items.length - 20} 处，导出或分版核对。</li>}</ul>}
      {rule.status !== "pass" && rule.status !== "not_applicable" && <p className="subtle mt-1 pl-6">{rule.explanation}</p>}
    </li>)}</ul>
    <p className="subtle text-xs">{card.basis}</p>
  </section>;
}

export function BomDiffView({ diff, previousLabel }: { diff: BomDiff; previousLabel: string }) {
  const { summary } = diff;
  return <section className="min-w-0 space-y-2" aria-label="BOM 版本差异">
    <h4 className="text-sm font-medium">与{previousLabel}的差异</h4>
    <p className="text-sm">新增 {summary.added} · 删除 {summary.removed} · 修改 {summary.changed} · 未变 {summary.unchanged}</p>
    {diff.lines.length === 0 ? <p className="subtle text-sm">没有行变化。</p> : <div className="min-w-0 overflow-x-auto" role="region" aria-label="差异行" tabIndex={0}>
      <table className="w-full min-w-[520px] text-left text-sm"><thead><tr className="subtle"><th className="py-1 pr-3 font-normal">行标识</th><th className="py-1 pr-3 font-normal">变化</th><th className="py-1 pr-3 font-normal">物料</th><th className="py-1 font-normal">内容</th></tr></thead>
        <tbody>{diff.lines.map(line => <tr key={line.key} className="border-t border-border align-top">
          <td className="py-1.5 pr-3 font-mono [overflow-wrap:anywhere]">{line.key}</td>
          <td className={`py-1.5 pr-3 ${line.change === "removed" ? "text-destructive" : line.change === "added" ? "text-primary" : ""}`}>{changeTitles[line.change]}</td>
          <td className="py-1.5 pr-3 [overflow-wrap:anywhere]">{(line.after ?? line.before)?.part}</td>
          <td className="py-1.5 [overflow-wrap:anywhere]">{line.change === "changed" ? <ul className="space-y-0.5">{line.fields.map(field => <li key={field}>
            {field === "reference_designators" && line.designators ? <>位号{line.designators.added.length > 0 && <> +{line.designators.added.join("、")}</>}{line.designators.removed.length > 0 && <> −{line.designators.removed.join("、")}</>}</>
              : <>{fieldTitles[field] ?? field}：{valueText(field, line.before)} → {valueText(field, line.after)}</>}
          </li>)}</ul> : <>{quantityText(line.after ?? line.before)}{(line.after ?? line.before)?.reference_designators.length ? ` · 位号 ${(line.after ?? line.before)?.reference_designators.join("、")}` : ""}</>}</td>
        </tr>)}</tbody></table></div>}
  </section>;
}

/** One saved version: its difference to the fixed predecessor and the rule card (D282). */
export function BomVersionReview({ api, productId, bomId }: { api: PreparationApi; productId: string; bomId: string }) {
  const [open, setOpen] = useState(false), [review, setReview] = useState<BomReview | null>(null), [error, setError] = useState(""), [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    api<unknown>(`v1/products/${productId}/configurations/boms/${bomId}/review`).then(value => {
      if (!alive) return;
      if (!isReview(value)) throw new Error("差异与规则卡内容不完整，请刷新。");
      setReview(value); setError("");
    }).catch(failure => { if (alive) setError((failure as Error).message); });
    return () => { alive = false; };
  }, [api, productId, bomId, open, attempt]);
  return <details className="min-w-0 rounded-lg border border-border p-3" onToggle={event => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
    <summary className="cursor-pointer text-sm font-medium">版本差异与规则卡</summary>
    <div className="mt-3 min-w-0 space-y-4">
      {error && <p role="alert" className="text-sm text-destructive">{error} <Button type="button" size="xs" variant="ghost" onClick={() => setAttempt(n => n + 1)}><ArrowsClockwise/>重试</Button></p>}
      {!review && !error && open && <p className="subtle text-sm" role="status">正在读取差异与规则卡…</p>}
      {review && <>
        <BomDiffView diff={review.diff} previousLabel={review.previous ? `上一版 v${review.previous.revision}` : "空 BOM（首版）"}/>
        <RuleCardView card={review.rules}/>
        {review.import_basis && <p className="subtle text-xs [overflow-wrap:anywhere]">本版由原件导入：{review.import_basis.format === "xlsx" ? `工作表「${review.import_basis.sheet}」` : "CSV"}，表头第 {review.import_basis.header_row} 行，导入 {Object.keys(review.import_basis.rows).length} 行，跳过 {review.import_basis.skipped.length} 行{review.import_basis.unmapped_columns.length ? `，未导入的列：${review.import_basis.unmapped_columns.map(c => c.header ?? `第 ${c.column} 列`).join("、")}` : ""}。</p>}
      </>}
    </div>
  </details>;
}

type Original = { id: string; title: string; filename: string; media_type: string; status: string; artifact_id: string | null };
type Workspace = { originals?: Original[]; sources?: { id: string; revision: number; status: string }[] };
type Preview = { command: { payload: Record<string, unknown> } & Record<string, unknown>; confirmation_token: string; expires_at: string; review: Record<string, unknown> & { effect: string } };

const isCurrent = (bom: BomConfiguration, boms: BomConfiguration[]) => !bom.series_id || !boms.some(other => other.series_id === bom.series_id && other.revision > bom.revision);

/** Import an XLSX/CSV original as one new BOM version: convert by code, decide rows, confirm once (P79 D98). */
export function BomImport({ api, product, boms, disabled, onSaved }: { api: PreparationApi; product: { id: string; revision: number }; boms: BomConfiguration[]; disabled?: boolean; onSaved: (bomId: string) => void | Promise<void> }) {
  const [originals, setOriginals] = useState<(Original & { revision: number })[]>([]), [loaded, setLoaded] = useState(false);
  const [originalId, setOriginalId] = useState(""), [previousId, setPreviousId] = useState(""), [visibility, setVisibility] = useState("private");
  const [name, setName] = useState(""), [reason, setReason] = useState(""), [sheet, setSheet] = useState<string | null>(null), [headerRow, setHeaderRow] = useState<number | null>(null);
  const [columns, setColumns] = useState<ImportColumn[] | null>(null), [dispositions, setDispositions] = useState<Record<number, Disposition>>({});
  const [result, setResult] = useState<ImportResult | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const original = originals.find(item => item.id === originalId), previous = boms.find(item => item.id === previousId) ?? null;

  async function loadOriginals() {
    setError("");
    try {
      const workspace = await api<Workspace>(`v1/products/${product.id}/workspace`);
      const revisions = new Map((workspace.sources ?? []).filter(source => source.status === "active").map(source => [source.id, source.revision]));
      setOriginals((workspace.originals ?? []).filter(item => item.status === "parsed" && item.artifact_id && revisions.has(item.artifact_id) && (item.media_type === XLSX || item.filename.toLowerCase().endsWith(".csv")))
        .map(item => ({ ...item, revision: revisions.get(item.artifact_id as string) as number })));
      setLoaded(true);
    } catch (failure) { setError((failure as Error).message); }
  }
  function reset(next: Partial<{ originalId: string; previousId: string; visibility: string }>) {
    if (next.originalId !== undefined) { setOriginalId(next.originalId); setSheet(null); setHeaderRow(null); setColumns(null); }
    if (next.previousId !== undefined) setPreviousId(next.previousId);
    if (next.visibility !== undefined) setVisibility(next.visibility);
    setDispositions({}); setResult(null); setNotice("");
  }
  async function convert(overrides: Partial<{ sheet: string | null; headerRow: number | null; columns: ImportColumn[] | null }> = {}) {
    if (!original?.artifact_id) { setError("请先选择已解析的 XLSX 或 CSV 原件。"); return; }
    setBusy(true); setError(""); setNotice("");
    const chosen = { sheet, headerRow, columns, ...overrides };
    try {
      const value = await api<ImportResult>(`v1/products/${product.id}/configurations/bom-import/inputs`, importRequest({
        artifactId: original.artifact_id, revision: original.revision, sheet: chosen.sheet, headerRow: chosen.headerRow, columns: chosen.columns,
        dispositions: Object.values(dispositions), previous: previous ? { id: previous.id, revision: previous.revision } : null, visibility,
      }));
      if (!value || typeof value.complete !== "boolean" || !Array.isArray(value.headers)) throw new Error("转换结果不完整，请重试。");
      if (value.rules && !isRuleCard(value.rules)) throw new Error("规则卡内容不完整，请重试。");
      if (value.diff && !isDiff(value.diff)) throw new Error("差异内容不完整，请重试。");
      setResult(value); setSheet(value.sheet); setHeaderRow(value.header_row); setColumns(value.columns.map(c => ({ field: c.field, column: c.column })));
      if (!name && original) setName(original.title.replace(/\.(xlsx|csv)$/i, "").slice(0, 200));
    } catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  }
  function mapColumn(column: number, field: string) {
    const next = (columns ?? []).filter(entry => entry.column !== column && entry.field !== field);
    setColumns(field ? [...next, { field, column }].sort((a, b) => a.column - b.column) : next);
    setResult(null);
  }
  function decide(row: number, value: Disposition | null) {
    setDispositions(current => { const next = { ...current }; if (value) next[row] = value; else delete next[row]; return next; });
  }
  async function review() {
    setError("");
    try {
      if (!result) throw new Error("请先转换。");
      const command = importCommand({ productId: product.id, productRevision: product.revision, name, reason, visibility, previous: previous ? { id: previous.id, revision: previous.revision, required_source_read_set: previous.required_source_read_set } : null, result });
      setBusy(true);
      const value = await api<Preview>("v1/commands/preview", command);
      if (!value?.confirmation_token || !value.review?.effect || value.command?.command_id !== command.command_id) throw new Error("预览内容尚未确认，请重新核对。");
      setPreview(value); dialog.current?.showModal?.();
    } catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  }
  async function confirm() {
    if (!preview) return;
    setBusy(true); setError("");
    try {
      const receipt = await api<{ id: string; subject_id: string; subject_type: string }>("v1/commands", preview.command);
      if (!receipt?.subject_id || receipt.subject_type !== "bom_revision") throw new Error("保存回执尚未确认，请按原请求重试。");
      dialog.current?.close(); setPreview(null); setResult(null); setDispositions({}); setReason("");
      setNotice("已保存为新的 BOM 草稿版本；原件、映射与逐行处置随版本保留。尚未发布或批准。");
      await onSaved(receipt.subject_id);
    } catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  }

  const pending = pendingRows(result), fields = result?.fields ?? [];
  const reviewDiff = preview && isDiff(preview.review.diff) ? preview.review.diff : null, reviewRules = preview && isRuleCard(preview.review.rules) ? preview.review.rules : null;
  return <details className="mb-4 min-w-0 rounded-lg border border-border p-3" onToggle={event => { if ((event.currentTarget as HTMLDetailsElement).open && !loaded) void loadOriginals(); }}>
    <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium"><FileArrowUp aria-hidden="true"/>从 Excel / CSV 导入整版 BOM</summary>
    <fieldset className="mt-3 min-w-0 space-y-3" disabled={disabled || busy}>
      <p className="subtle text-sm">先在“原件”中上传 XLSX 或 CSV 并完成扫描与解析。转换由代码按表头完成，不经模型；无法照原样导入的行逐条处置，整版一次确认后与前版比对。</p>
      {error && <p role="alert" className="rounded-lg border border-destructive p-2 text-sm text-destructive [overflow-wrap:anywhere]">{error}</p>}
      {notice && <p role="status" className="rounded-lg border border-border p-2 text-sm">{notice}</p>}
      <div className="grid min-w-0 gap-x-3 sm:grid-cols-2">
        <label>原件<select value={originalId} onChange={event => reset({ originalId: event.target.value })}><option value="">{loaded ? originals.length ? "选择已解析的原件" : "暂无已解析的 XLSX / CSV" : "正在读取原件…"}</option>{originals.map(item => <option key={item.id} value={item.id}>{item.title} · {item.filename}</option>)}</select></label>
        <label>续接前版<select value={previousId} onChange={event => reset({ previousId: event.target.value })}><option value="">新建首版</option>{boms.map(bom => <option key={bom.id} value={bom.id} disabled={!isCurrent(bom, boms) || bom.source_status === "needs_recheck"}>{bom.name} · v{bom.revision}{isCurrent(bom, boms) ? "" : " · 历史版"}</option>)}</select></label>
        <label>可见范围<select value={visibility} onChange={event => reset({ visibility: event.target.value })}><option value="private">仅本人</option><option value="category">品类授权成员</option></select></label>
        <label>BOM 名称<input maxLength={200} value={name} onChange={event => setName(event.target.value)}/></label>
      </div>
      <label>导入原因<textarea maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} placeholder="例如：按供应商回传的 BOM v3 建立 EVT 版本"/></label>
      <Button type="button" variant="outline" disabled={!original} onClick={() => void convert()}><ArrowsClockwise/>{result ? "按当前映射与处置重新转换" : "转换并核对"}</Button>
      {result && <div className="min-w-0 space-y-4">
        <div className="grid min-w-0 gap-x-3 sm:grid-cols-2">
          {result.format === "xlsx" && <label>工作表<select value={sheet ?? ""} onChange={event => { setSheet(event.target.value); setHeaderRow(null); setColumns(null); void convert({ sheet: event.target.value, headerRow: null, columns: null }); }}>{result.sheets.map(item => <option key={item} value={item}>{item}</option>)}</select></label>}
          <label>表头所在行<input inputMode="numeric" value={headerRow ?? ""} onChange={event => { const n = Number(event.target.value); setHeaderRow(Number.isInteger(n) && n > 0 ? n : null); setColumns(null); setResult(null); }}/></label>
        </div>
        <details className="min-w-0" open={!result.complete}><summary className="cursor-pointer text-sm font-medium">列映射{result.suggested ? "（按表头同义词建议，可改）" : ""}</summary>
          <div className="mt-2 grid min-w-0 gap-x-3 sm:grid-cols-2">{result.headers.map(header => <label key={header.column} className="min-w-0">第 {header.column} 列 · <span className="[overflow-wrap:anywhere]">{header.text}</span>
            <select value={(columns ?? []).find(c => c.column === header.column)?.field ?? ""} onChange={event => mapColumn(header.column, event.target.value)}><option value="">不导入</option>{fields.map(field => <option key={field.field} value={field.field}>{field.title}</option>)}</select></label>)}</div>
          {result.basis_error && <p role="alert" className="text-sm text-destructive">{result.basis_error}</p>}
        </details>
        {result.counts && <p className="text-sm">可导入 {result.counts.ready} 行 · 待处置 {result.counts.needs_disposition} 行 · 已跳过 {result.counts.skipped} 行 · 空行 {result.counts.ignored} 行{result.unmapped_columns?.length ? ` · 未导入的列：${result.unmapped_columns.map(c => c.header ?? `第 ${c.column} 列`).join("、")}` : ""}</p>}
        {(result.issues ?? []).map((issue, index) => <p key={index} role="alert" className="text-sm text-destructive">{issue.message}</p>)}
        {pending.length > 0 && <section className="min-w-0 space-y-2" aria-label="逐行处置"><h4 className="text-sm font-medium">逐行处置 · {pending.length} 行</h4>
          <ul className="space-y-2">{pending.map(row => { const chosen = dispositions[row.row]; return <li key={row.row} className="min-w-0 rounded-lg border border-border p-2 text-sm">
            <p className="font-medium [overflow-wrap:anywhere]">原件第 {row.row} 行{row.part ? ` · ${row.part}` : ""}</p>
            {row.issues.map((issue, index) => <p key={index} className="text-destructive">{issue.message}</p>)}{row.reason && !row.issues.length && <p className="subtle">{row.reason}</p>}
            <div className="mt-1 grid min-w-0 gap-x-3 sm:grid-cols-2">
              <label>处置<select value={chosen ? chosen.action === "reuse" ? `reuse:${chosen.part_id}` : chosen.action : ""} onChange={event => { const value = event.target.value; if (!value) { decide(row.row, null); return; } if (value.startsWith("reuse:")) { const hint = row.hints.find(h => h.part_id === value.slice(6)); decide(row.row, { row: row.row, action: "reuse", part_id: hint?.part_id, expected_part_revision: hint?.revision }); return; } decide(row.row, { row: row.row, action: value as Disposition["action"], reason: chosen?.reason ?? null }); }}>
                <option value="">请选择</option>{row.allowed.filter(action => action !== "reuse").map(action => <option key={action} value={action}>{actionTitles[action]}</option>)}{row.allowed.includes("reuse") && row.hints.map(hint => <option key={hint.part_id} value={`reuse:${hint.part_id}`}>关联已有物料：{hint.label} · v{hint.revision}</option>)}
              </select></label>
              {chosen?.action === "skip" && <label>跳过原因（可选）<input maxLength={500} value={chosen.reason ?? ""} onChange={event => decide(row.row, { ...chosen, reason: event.target.value })}/></label>}
            </div>
          </li>; })}</ul>
          <Button type="button" size="sm" variant="outline" onClick={() => void convert()}><ArrowsClockwise/>按处置重新转换</Button>
        </section>}
        {result.diff && <BomDiffView diff={result.diff} previousLabel={result.previous ? `前版 v${result.previous.revision}` : "空 BOM（首版）"}/>}
        {result.rules && <RuleCardView card={result.rules}/>}
        <Button type="button" disabled={!result.complete} onClick={() => void review()}>核对并一次确认整版</Button>
        {!result.complete && <p className="subtle text-sm">全部行处置完毕、映射有效后才能确认。</p>}
      </div>}
    </fieldset>
    <dialog ref={dialog} className="!w-[min(760px,calc(100vw-32px))] max-h-[90vh] overflow-auto" onCancel={event => { event.preventDefault(); if (!busy) { dialog.current?.close(); setPreview(null); } }}>{preview && <div className="min-w-0 space-y-4">
      <h2 className="text-lg font-semibold">一次确认：导入 BOM 新版本</h2>
      <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{preview.review.effect}</p>
      <p className="text-sm">名称：{name} · 可见范围：{visibility === "category" ? "品类授权成员" : "仅本人"} · {previous ? `续接 ${previous.name} v${previous.revision}` : "新建首版"}</p>
      {reviewDiff && <BomDiffView diff={reviewDiff} previousLabel={previous ? `前版 v${previous.revision}` : "空 BOM（首版）"}/>}
      {reviewRules && <RuleCardView card={reviewRules}/>}
      <p className="subtle text-sm">规则卡只提示，不阻止保存。本次确认在 {utcText(preview.expires_at)} 前有效；保存不发布、不批准，也不改变齐套与替代料批准。</p>
      <div className="flex flex-wrap justify-end gap-2"><Button type="button" variant="outline" disabled={busy} onClick={() => { dialog.current?.close(); setPreview(null); }}>返回修改</Button><Button type="button" disabled={busy} onClick={() => void confirm()}>确认保存此版本</Button></div>
    </div>}</dialog>
  </details>;
}
