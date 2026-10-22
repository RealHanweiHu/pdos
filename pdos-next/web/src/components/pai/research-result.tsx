type Row = { row_id: string; snapshot_id: string; brand?: string; model?: string; value?: unknown; unit?: string; condition?: string; quote: string; locator: string; status: string };
type Source = { id: string; title: string; final_url: string; retrieved_at: string; status: string };
type Coverage = { task_key: string; searches: unknown[]; reads: { error?: unknown }[]; unread_urls: string[]; unread_locations: unknown[]; accepted_rows: number; rejected_rows: number };
type Failure = { message: string; reason: string; stage?: string; url?: string };
type Job = { status: string; snapshots: Source[]; ledger: Row[]; coverage: Coverage[]; failures: Failure[] };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
function href(value: unknown): string | undefined {
  if (typeof value !== "string") return;
  try { const url = new URL(value); if (["https:", "http:"].includes(url.protocol) && !url.username && !url.password) return url.href; } catch { /* A malformed source is displayed as text. */ }
}
const labels: Record<string, string> = { completed: "已核对", partial: "部分完成", unavailable: "未能完成", ok: "已读取" };
function validJob(value: unknown): value is Job {
  if (!record(value) || !Array.isArray(value.snapshots) || !Array.isArray(value.ledger) || !Array.isArray(value.coverage) || !Array.isArray(value.failures)) return false;
  return value.snapshots.every(source => record(source) && [source.id, source.title, source.final_url, source.retrieved_at, source.status].every(field => typeof field === "string"))
    && value.ledger.every(row => record(row) && [row.row_id, row.snapshot_id, row.quote, row.locator, row.status].every(field => typeof field === "string"))
    && value.coverage.every(row => record(row) && typeof row.task_key === "string" && [row.searches, row.reads, row.unread_urls, row.unread_locations].every(Array.isArray) && (row.reads as unknown[]).every(record) && [row.accepted_rows, row.rejected_rows].every(count => Number.isInteger(count) && Number(count) >= 0))
    && value.failures.every(row => record(row) && typeof row.message === "string" && typeof row.reason === "string");
}

/** This reserved result is filled by the server from the actual research ledger. */
export function ResearchResult({ value }: { value: unknown }) {
  if (value === undefined || value === null) return null;
  if (!record(value) || value.version !== 1 || !Array.isArray(value.jobs) || !value.jobs.every(validJob)) return <p role="alert">研究记录格式暂不可核对，请刷新实际结果。</p>;
  const jobs = value.jobs as Job[];
  const sources = [...new Map(jobs.flatMap(job => job.snapshots).map(source => [source.id, source])).values()];
  const rows = [...new Map(jobs.flatMap(job => job.ledger).map(row => [row.row_id, row])).values()];
  if (sources.length !== value.source_count || rows.length !== value.row_count) return <p role="alert">研究来源或台账数量尚未核对，请刷新实际结果。</p>;
  return <section className="min-w-0 space-y-3 rounded-lg border p-3" aria-label="研究来源与覆盖">
    <div><h4 className="font-medium">研究来源与覆盖</h4><p className="subtle">{sources.length} 份实际来源 · {rows.length} 条核对记录</p></div>
    {sources.length === 0 && <p className="text-sm">尚未读到可引用来源，请查看下方未完成说明。</p>}
    <ul className="space-y-2">{sources.map(source => <li key={source.id} className="min-w-0 break-words text-sm">
      {href(source.final_url) ? <a href={href(source.final_url)} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">{source.title || source.final_url}</a> : <span>{source.title || "来源地址暂不可核对"}</span>}
      <p className="subtle">{labels[source.status] ?? "状态待核对"} · 读取于 <time dateTime={source.retrieved_at}>{source.retrieved_at.replace("T", " ").replace("+00:00", " UTC")}</time></p>
    </li>)}</ul>
    {rows.length > 0 && <details><summary className="cursor-pointer text-sm">查看逐字核对片段</summary><ul className="mt-3 space-y-3">{rows.map(row => <li key={row.row_id} className="min-w-0 text-sm">
      <p className="break-words font-medium">{[row.brand, row.model].filter(Boolean).join(" · ") || "未确定品牌 / 型号"}{row.value != null && ` · ${String(row.value)} ${row.unit ?? ""}`}</p>
      {row.condition && <p className="subtle">工况：{row.condition}</p>}<blockquote className="my-1 break-words border-l-2 pl-3">{row.quote}</blockquote><p className="subtle">来源：{sources.find(source => source.id === row.snapshot_id)?.title ?? "来源待核对"} · 原文定位：{row.locator}{row.status === "partial" && " · 信息仍有缺项"}</p>
    </li>)}</ul></details>}
    {jobs.map((job, index) => <div key={index} className="min-w-0 border-t pt-3 text-sm">
      <p className="font-medium">研究任务 {index + 1} · {labels[job.status] ?? "状态待核对"}</p>
      {job.coverage.map((coverage, task) => <p key={task} className="mt-1 break-words text-muted-foreground">{coverage.task_key}：{coverage.searches.length} 次查询，{coverage.reads.filter(read => !read.error).length} 页读取；采纳 {coverage.accepted_rows} 条，未采纳 {coverage.rejected_rows} 条。尚未读取 {coverage.unread_urls.length} 个网址、{coverage.unread_locations.length} 段原文。</p>)}
      {job.failures.length > 0 && <ul className="mt-2 space-y-1">{job.failures.map((failure, failureIndex) => <li key={failureIndex} className="break-words">未完成：{failure.message}<span className="subtle">（{failure.reason}）</span></li>)}</ul>}
    </div>)}
    <p className="subtle">以上来源、片段、覆盖和失败记录由实际研究台账提供。来源登记与后续采用请另行确认。</p>
  </section>;
}
